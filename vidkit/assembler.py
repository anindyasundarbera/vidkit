"""The pipeline: spec + provider -> finished, captioned video.

Stages run in order and can be limited with ``only``:

``data``      provider datasets -> JSON in ``_build/data`` (+ ``_snapshot.json``)
``panels``    chart definitions -> SVG -> PNG stills
``stills``    static SVG/PNG assets referenced by scenes -> PNG stills
``capture``   Playwright screen recordings -> PNG stills
``narration`` TTS per scene -> WAVs (+ measured scene durations)
``clips``     stills -> timed video clips
``concat``    clips -> one video track; WAVs -> one audio track
``render``    mux video + audio + burned-in captions -> final mp4
``verify``    run the guard checks and write a report

``only=[...]`` selects stages by name; ``from_stage`` selects a suffix. Either way
a skipped input is *proved* to be present — and datasets are proved to have been
computed for this same provider and window — rather than assumed (R-B3).
``refresh`` puts the ``data`` stage back into such a plan, so the source is asked
again even though a snapshot would have been acceptable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable

from . import capture as _capture
from . import panels as _panels
from . import provider as _provider
from . import tts as _tts
from .context import Context
from .errors import SpecError
from .narration import build_srt, parse_scene_script, word_count
from .snapshot import (SNAPSHOT_FILE, Snapshot, digest_text, load_datasets,
                       request_key, verify_fresh)
from .spec import Artifact, Spec, load_spec
from .timeframe import Timeframe, parse_timeframe
from .svg import PanelDoc, document
from .verify import Report, verify_output

STAGES = ["data", "panels", "stills", "capture", "narration", "clips", "concat",
          "render", "verify"]


@dataclass
class Assets:
    stills: dict[str, Path] = field(default_factory=dict)      # name -> png
    panel_stills: dict[str, Path] = field(default_factory=dict)
    capture_stills: dict[str, Path] = field(default_factory=dict)
    artifacts: dict[str, Artifact] = field(default_factory=dict)   # name -> real bytes
    scene_audio: list[_tts.SceneAudio] = field(default_factory=list)
    video_track: Path | None = None
    audio_track: Path | None = None
    srt: Path | None = None
    output: Path | None = None
    report: Report | None = None


# --------------------------------------------------------------------------- #
def make_context(spec_path: Path | str, out_dir: Path | None = None, *,
                 timeframe: Timeframe | str | dict | None = None,
                 as_of: date | None = None) -> Context:
    """Build the runtime context: load the spec, resolve the window, make dirs.

    ``timeframe`` overrides whatever the spec or the story manifest declared; it
    is how ``--timeframe``/``--days`` and the MCP job contract reach the pipeline.
    """
    spec_path = Path(spec_path).resolve()
    override = (timeframe if isinstance(timeframe, Timeframe)
                else parse_timeframe(timeframe, where="--timeframe",
                                     source="override", default_as_of=as_of))
    spec = load_spec(spec_path, timeframe=override, as_of=as_of)
    root = spec_path.parent
    out = Path(out_dir).resolve() if out_dir else root
    ctx = Context(spec=spec, root=root, out_dir=out)
    ctx.ensure_dirs()
    _announce(ctx)
    return ctx


def _announce(ctx: Context) -> None:
    story = ctx.spec.story
    if story is not None:
        ctx.info(f"story: {story.slug}"
                 + ("" if story.declared else " (folder convention)"))
    tf = ctx.spec.timeframe
    ctx.info(f"timeframe: {tf.label()} [{tf.source}]" if tf else "timeframe: (not declared)")


def _stage_set(only: Iterable[str] | None, from_stage: str | None = None) -> set[str]:
    """Which stages to run. ``from_stage`` wins over ``only`` when both are given."""
    if from_stage:
        if from_stage not in STAGES:
            raise SpecError(f"unknown stage {from_stage!r}; known: {', '.join(STAGES)}")
        return set(STAGES[STAGES.index(from_stage):])
    if not only:
        return set(STAGES)
    chosen = set(only)
    unknown = chosen - set(STAGES)
    if unknown:
        raise SpecError(f"unknown stage(s): {', '.join(sorted(unknown))}")
    return chosen


# --------------------------------------------------------------------------- #
def run(spec_path: Path | str, *, only: Iterable[str] | None = None,
        from_stage: str | None = None,
        out_dir: Path | None = None, timeframe: Timeframe | str | dict | None = None,
        as_of: date | None = None, refresh: bool = False) -> Assets:
    ctx = make_context(spec_path, out_dir, timeframe=timeframe, as_of=as_of)
    spec = ctx.spec
    stages = _stage_set(only, from_stage)
    if refresh:
        # `--refresh` means "go to the source even though the snapshot would do",
        # so it re-adds the stage that reaching the source requires
        stages.add("data")
    assets = Assets()

    # -- provider ---------------------------------------------------------- #
    module = None
    if spec.provider:
        # `write_back: true` was already refused at load time (R-B4); every secret
        # is declared before the module runs, so the module can
        # only ever see values the engine is able to redact afterwards
        ctx.secrets.declare(spec.provider.secrets)
        module, _ = _provider.load_provider(spec.provider.module, ctx.root)
        reg = getattr(module, "register", None)
        if callable(reg):
            reg()
        ctx.secrets.declare(_provider.collect_secrets(module))
        ctx.secrets.resolve()
        ctx.info(f"provider: {spec.provider.module}")

    # -- data -------------------------------------------------------------- #
    datasets: dict = {}
    provider_path = (ctx.root / f"{spec.provider_name}.py") if spec.provider_name else None
    wanted = request_key(provider=spec.provider_name, provider_path=provider_path,
                         timeframe=spec.timeframe)
    ran_data = "data" in stages
    if ran_data:
        try:
            datasets = _provider.collect_datasets(module, ctx)
        except _provider.SourceUnavailable:
            # an unreachable source is only fatal when nothing was declared in
            # its place; `fallback()` raises again with an explanation if so
            raise
        recorded = dict(spec.degraded)
        hashes = {}
        for key, value in datasets.items():
            blob = json.dumps(value, indent=1, default=str)
            (ctx.data_dir / f"{key}.json").write_text(blob, encoding="utf-8")
            hashes[key] = digest_text(blob)
        Snapshot(path=ctx.data_dir / SNAPSHOT_FILE, request=wanted,
                 datasets=hashes, degraded=recorded).write()
        if recorded:
            ctx.info(f"datasets: {', '.join(sorted(datasets)) or '(none)'} "
                     f"({len(recorded)} degraded)")
        else:
            ctx.info(f"datasets: {', '.join(sorted(datasets)) or '(none)'}")

    # A skipped `data` stage must re-render from the snapshot that matches *this*
    # request — a snapshot taken for another window is the bug this refuses.
    need_data = bool(stages & {"panels", "stills", "capture"})
    if need_data and not ran_data:
        verify_fresh(Snapshot.read(ctx.data_dir), wanted, data_dir=ctx.data_dir)
        ctx.info("datasets: reusing snapshot")
        for name, why in (Snapshot.read(ctx.data_dir).degraded or {}).items():
            ctx.degrade(name, why)

    # -- panels ------------------------------------------------------------ #
    panel_defs = _provider.collect_panels(module)
    if "panels" in stages:
        # provider panels are authoritative; spec `charts:` add to them, and a
        # spec chart may override options (title/kicker/etc.) but not the kind
        # or dataset the provider already chose — that keeps live wiring intact.
        for c in spec.charts:
            if c.name in panel_defs:
                kind, dataset, opts = panel_defs[c.name]
                opts = {**opts, **c.options}
                panel_defs[c.name] = (kind, dataset, opts)
            else:
                panel_defs[c.name] = (c.kind, c.dataset, dict(c.options))
        if not datasets:
            # reload persisted datasets so panels can render on their own; the
            # freshness of these files was proved above, before this point
            datasets = load_datasets(ctx.data_dir)
        for name, (kind, dataset, options) in panel_defs.items():
            data = datasets.get(dataset)
            if data is None and dataset in spec.__dict__:
                data = spec.__dict__[dataset]
            if data is None:
                raise SpecError(
                    f"chart {name!r} needs dataset {dataset!r}, which neither the "
                    "provider produced nor the spec defines")
            doc = PanelDoc(spec.project.width, spec.project.height)
            title = options.pop("title", name)
            kicker = options.pop("kicker", "")
            doc.head(title, kicker)
            _panels.render(kind, data, options, doc)
            svg_path = ctx.panels_dir / f"{name}.svg"
            svg_path.write_text(doc.svg(), encoding="utf-8")
            png = ctx.stills / f"{name}.png"
            ctx.rsvg.render(svg_path, png, spec.size)
            assets.panel_stills[name] = png
            assets.stills[name] = png
        ctx.info(f"panels: {len(panel_defs)}")

    # -- stills ------------------------------------------------------------ #
    if "stills" in stages:
        # provider-supplied stills first (paths)
        assets.stills.update(_provider.collect_stills(module, ctx))
        # spec stils are rendered on demand in _resolve_stills below
        pending = {
            sh.ref for sc in spec.scenes for sh in sc.shots if sh.kind == "still"
        }
        for ref in sorted(pending):
            src = _resolve_ref(ctx, ref)
            if src is None:
                raise SpecError(f"still not found: {ref}")
            if src.suffix.lower() == ".svg":
                png = ctx.stills / f"{src.stem}.png"
                ctx.rsvg.render(src, png, spec.size)
                assets.stills.setdefault(ref, png)
                assets.stills.setdefault(src.stem, png)
            else:
                assets.stills.setdefault(ref, src)
        ctx.info(f"stills: {len(assets.stills)}")

    # -- capture ----------------------------------------------------------- #
    if "capture" in stages and spec.captures:
        for res in _capture.capture_all(ctx):
            if res.path:
                assets.capture_stills[res.name] = res.path
                assets.stills[res.name] = res.path
            for art in res.artifacts:
                assets.artifacts[art.name] = art

    # -- narration --------------------------------------------------------- #
    scripts = _scripts_for(spec, ctx)
    if "narration" in stages or "clips" in stages or "render" in stages:
        if not assets.scene_audio:
            assets.scene_audio = (
                _tts.synthesize(ctx, scripts) if "narration" in stages
                else _load_or_estimate(ctx, scripts)
            )

    # -- clips ------------------------------------------------------------- #
    if "clips" in stages:
        _build_clips(ctx, assets, scripts)

    # -- concat ------------------------------------------------------------ #
    if "concat" in stages:
        _concat(ctx, assets)

    # -- render ------------------------------------------------------------ #
    if "render" in stages:
        _render(ctx, assets, scripts)

    # -- verify ------------------------------------------------------------ #
    if "verify" in stages:
        scenes_text = {s.n: s.spoken for s in scripts}
        assets.report = verify_output(ctx, assets, scenes_text)
        (ctx.build / "verify.json").write_text(
            json.dumps(assets.report.to_dict(), indent=1), encoding="utf-8")
        assets.report.print()

    return assets


# --------------------------------------------------------------------------- #
def _resolve_ref(ctx: Context, ref: str) -> Path | None:
    for base in (ctx.root, ctx.root.parent, Path.cwd()):
        p = (base / ref)
        if p.exists():
            return p.resolve()
    return None


def _scripts_for(spec: Spec, ctx: Context):
    """Scene spoken text: from the narration file, plus/overriding inline text."""
    scripts = []
    if spec.narration.source:
        src = _resolve_ref(ctx, spec.narration.source)
        if src is None:
            raise SpecError(f"narration.source not found: {spec.narration.source}")
        by_n = {s.n: s for s in parse_scene_script(src.read_text(encoding="utf-8"))}
    else:
        by_n = {}
    for sc in spec.scenes:
        text = spec.narration.inline.get(sc.n)
        if text is None and sc.n in by_n:
            text = by_n[sc.n].spoken
        if text is None:
            raise SpecError(f"scene {sc.n} has no narration text")
        from .narration import SceneScript
        scripts.append(SceneScript(n=sc.n, spoken=text))
    return scripts


def _load_or_estimate(ctx: Context, scripts):
    """When narration stage is skipped, reuse WAVs if present else estimate."""
    ff = ctx.ffmpeg
    out = []
    for sc in scripts:
        wav = ctx.wavs / f"scene-{sc.n:02d}.wav"
        if wav.exists():
            out.append(_tts.SceneAudio(sc.n, wav, ff.duration(wav),
                                       word_count(sc.spoken)))
        else:
            out.append(_tts.SceneAudio(sc.n, None, round(word_count(sc.spoken) / 2.5, 3),
                                       word_count(sc.spoken)))
    return out


def _spans(audio: list[_tts.SceneAudio]) -> list[tuple[int, float, float]]:
    spans, t = [], 0.0
    for a in audio:
        spans.append((a.n, t, t + a.seconds)); t += a.seconds
    return spans


def _resolve_shot_still(ctx: Context, assets: Assets, shot) -> Path:
    if shot.kind == "capture":
        p = assets.capture_stills.get(shot.ref) or (
            ctx.captures / f"{shot.ref}.png")
    elif shot.kind == "chart":
        p = assets.panel_stills.get(shot.ref) or (ctx.stills / f"{shot.ref}.png")
    else:
        p = assets.stills.get(shot.ref) or (ctx.stills / f"{Path(shot.ref).stem}.png")
    if p is None or not Path(p).exists():
        raise SpecError(f"no still for {shot.kind} {shot.ref!r}")
    return Path(p)


def _build_clips(ctx: Context, assets: Assets, scripts) -> None:
    spec = ctx.spec
    spans = _spans(assets.scene_audio)
    by_n = {n: (a, b) for n, a, b in spans}
    for sc in spec.scenes:
        if sc.n not in by_n:
            continue
        start, end = by_n[sc.n]
        wsum = sum(s.weight for s in sc.shots) or 1
        for idx, shot in enumerate(sc.shots):
            png = _resolve_shot_still(ctx, assets, shot)
            seconds = (end - start) * (shot.weight / wsum)
            if seconds <= 0:
                continue
            clip = ctx.clips / f"scene-{sc.n:02d}-{idx}.mp4"
            ctx.ffmpeg.still_to_clip(png, clip, seconds, size=spec.size,
                                     fps=spec.project.fps, effect=shot.effect)
            assets.stills.setdefault(f"_clip_{sc.n}_{idx}", clip)
    ctx.info("clips built")


def _concat(ctx: Context, assets: Assets) -> None:
    clips = sorted(ctx.clips.glob("scene-*.mp4"),
                   key=lambda p: tuple(int(x) for x in p.stem.split("-")[1:]))
    if not clips:
        raise SpecError("no clips to concatenate")
    assets.video_track = ctx.clips / "video-track.mp4"
    ctx.ffmpeg.concat(clips, assets.video_track, ctx.clips / "video.txt")
    assets.audio_track = _tts.concat_audio(ctx, assets.scene_audio)
    ctx.info(f"concat: {len(clips)} clips, audio={'yes' if assets.audio_track else 'no'}")


def _render(ctx: Context, assets: Assets, scripts) -> None:
    spec = ctx.spec
    if assets.video_track is None:
        assets.video_track = ctx.clips / "video-track.mp4"
    if assets.audio_track is None and not (ctx.build / "narration.wav").exists():
        assets.audio_track = _tts.concat_audio(ctx, assets.scene_audio)
    audio = assets.audio_track or (ctx.build / "narration.wav")
    audio = audio if Path(audio).exists() else None

    # captions retimed to the real scene spans
    scenes_text = {s.n: s.spoken for s in scripts}
    srt_text = build_srt(scenes_text, _spans(assets.scene_audio))
    assets.srt = ctx.out_dir / "narration.srt"
    assets.srt.write_text(srt_text, encoding="utf-8")
    ctx.info(f"captions: {len(srt_text.splitlines())} lines -> {assets.srt.name}")

    out = ctx.out_dir / spec.project.output
    ctx.ffmpeg.mux_captioned(assets.video_track, audio, assets.srt, out,
                             size=spec.size, fps=spec.project.fps,
                             ceiling=spec.project.max_seconds)
    assets.output = out
    d = ctx.ffmpeg.duration(out)
    ctx.info(f"rendered {out.name}: {d:.2f}s ({d/60:.3f} min)")
