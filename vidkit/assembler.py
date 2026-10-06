"""The pipeline: spec + provider -> finished, captioned video.

Stages run in order and can be limited with ``only``:

``data``      provider datasets -> JSON in ``_build/data``
``panels``    chart definitions -> SVG -> PNG stills
``stills``    static SVG/PNG assets referenced by scenes -> PNG stills
``capture``   Playwright screen recordings -> PNG stills
``narration`` TTS per scene -> WAVs (+ measured scene durations)
``clips``     stills -> timed video clips
``concat``    clips -> one video track; WAVs -> one audio track
``render``    mux video + audio + burned-in captions -> final mp4
``verify``    run the guard checks and write a report
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from . import capture as _capture
from . import panels as _panels
from . import provider as _provider
from . import tts as _tts
from .context import Context
from .errors import SpecError
from .narration import build_srt, parse_scene_script, word_count
from .spec import Spec, load_spec
from .svg import PanelDoc, document
from .verify import Report, verify_output

STAGES = ["data", "panels", "stills", "capture", "narration", "clips", "concat",
          "render", "verify"]


@dataclass
class Assets:
    stills: dict[str, Path] = field(default_factory=dict)      # name -> png
    panel_stills: dict[str, Path] = field(default_factory=dict)
    capture_stills: dict[str, Path] = field(default_factory=dict)
    scene_audio: list[_tts.SceneAudio] = field(default_factory=list)
    video_track: Path | None = None
    audio_track: Path | None = None
    srt: Path | None = None
    output: Path | None = None
    report: Report | None = None


# --------------------------------------------------------------------------- #
def make_context(spec_path: Path | str, out_dir: Path | None = None) -> Context:
    spec_path = Path(spec_path).resolve()
    spec = load_spec(spec_path)
    root = spec_path.parent
    out = Path(out_dir).resolve() if out_dir else root
    ctx = Context(spec=spec, root=root, out_dir=out)
    ctx.ensure_dirs()
    return ctx


def _stage_set(only: Iterable[str] | None) -> set[str]:
    if not only:
        return set(STAGES)
    chosen = set(only)
    unknown = chosen - set(STAGES)
    if unknown:
        raise SpecError(f"unknown stage(s): {', '.join(sorted(unknown))}")
    return chosen


# --------------------------------------------------------------------------- #
def run(spec_path: Path | str, *, only: Iterable[str] | None = None,
        out_dir: Path | None = None) -> Assets:
    ctx = make_context(spec_path, out_dir)
    spec = ctx.spec
    stages = _stage_set(only)
    assets = Assets()

    # -- provider ---------------------------------------------------------- #
    module = None
    if spec.provider:
        module, _ = _provider.load_provider(spec.provider, ctx.root)
        reg = getattr(module, "register", None)
        if callable(reg):
            reg()
        ctx.info(f"provider: {spec.provider}")

    # -- data -------------------------------------------------------------- #
    datasets: dict = {}
    if "data" in stages:
        datasets = _provider.collect_datasets(module, ctx)
        for key, value in datasets.items():
            (ctx.data_dir / f"{key}.json").write_text(
                json.dumps(value, indent=1, default=str), encoding="utf-8")
        ctx.info(f"datasets: {', '.join(sorted(datasets)) or '(none)'}")

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
            # reload persisted datasets so panels can render on their own
            for f in ctx.data_dir.glob("*.json"):
                datasets[f.stem] = json.loads(f.read_text(encoding="utf-8"))
        for name, (kind, dataset, options) in panel_defs.items():
            data = datasets.get(dataset)
            if data is None and dataset in spec.__dict__:
                data = spec.__dict__[dataset]
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
