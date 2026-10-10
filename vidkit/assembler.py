"""The pipeline: spec + provider -> finished, captioned video.

Stages run in order and can be limited with ``only``:

``data``      provider datasets -> JSON in ``_build/data`` (+ ``_snapshot.json``)
``panels``    chart definitions -> SVG -> PNG stills
``stills``    static SVG/PNG assets referenced by scenes -> PNG stills
``capture``   Playwright screen recordings -> PNG stills
``exec``      declared commands run in a sandbox -> recorded casts -> PNG stills
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
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable

from . import capture as _capture
from . import card
from . import exec as _exec
from . import ffmpeg as _ffmpeg
from . import overlay as _overlay
from . import panels as _panels
from . import provider as _provider
from . import terminal as _terminal
from . import tts as _tts
from .context import Context
from .errors import SpecError
from .narration import build_srt, parse_scene_script, word_count
from .provenance import Provenance, probe_tools, spec_digest
from .snapshot import (
    SNAPSHOT_FILE,
    Snapshot,
    digest_text,
    file_digest,
    load_datasets,
    request_key,
    verify_fresh,
)
from .spec import Artifact, Scene, Shot, Spec, load_spec
from .svg import PanelDoc
from .timeframe import Timeframe, parse_timeframe
from .verify import Report, verify_output

STAGES = ["data", "panels", "stills", "capture", "exec", "narration", "clips",
          "concat", "render", "verify"]


@dataclass
class Assets:
    stills: dict[str, Path] = field(default_factory=dict)      # name -> png
    panel_stills: dict[str, Path] = field(default_factory=dict)
    capture_stills: dict[str, Path] = field(default_factory=dict)
    exec_stills: dict[str, Path] = field(default_factory=dict)
    #: label -> every frame the recording was sampled into, in time order. An
    #: ``exec`` shot is a *moment* in a recording, so the shot needs the run to
    #: pick from; `at:` chooses and the default is the last frame.
    exec_frames: dict[str, list[tuple[float, Path]]] = field(default_factory=dict)
    exec_results: dict[str, _exec.ExecResult] = field(default_factory=dict)
    exec_casts: dict[str, Path] = field(default_factory=dict)
    #: label -> the factor a recording was re-timed by when it was cut to its
    #: narration, so a sped-up screencast is stated rather than implied.
    exec_playback: dict[str, float] = field(default_factory=dict)
    # A recording that only ever showed one screen is *replayed* as a single held
    # frame, and there is no speed to report — which must not be confused with a
    # recording that was replayed at 1.0x. Recorded only when frames are carried.
    exec_take_frames: dict[str, int] = field(default_factory=dict)
    #: environment name -> what became of it. Carried out of the stage so that
    #: verify and the provenance row can report the container that was used
    #: rather than the container the spec hoped for.
    environments: dict[str, _exec.EnvState] = field(default_factory=dict)
    artifacts: dict[str, Artifact] = field(default_factory=dict)   # name -> real bytes
    scene_audio: list[_tts.SceneAudio] = field(default_factory=list)
    video_track: Path | None = None
    audio_track: Path | None = None
    #: the finished mix: narration plus the declared score, ducked against the measured
    #: narration spans. ``None`` when the spec declares no score, in which case
    #: ``audio_track`` is what gets muxed and the render is byte-identical to M8.
    mix: Path | None = None
    #: what the mix actually did — how long the bed was held down for, and whether the
    #: ducking branch ran at all. On a silent cut it did not, and saying otherwise is
    #: the kind of claim this toolkit exists to refuse.
    mix_result: _ffmpeg.MixResult | None = None
    srt: Path | None = None
    output: Path | None = None
    report: Report | None = None
    provenance: dict | None = None        # what this build was made from and by
    ctx: Context | None = None            # set by run(), so a caller knows where things went


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
        as_of: date | None = None, refresh: bool = False,
        action: str = "build", ctx: Context | None = None,
        assets: Assets | None = None) -> Assets:
    """Run the pipeline.

    ``ctx`` and ``assets`` may be handed in so that a long-lived caller (the studio
    session) can run a stage at a time against the *same* object graph — the same
    measured facts, the same opened environments. Passing nothing is the ordinary
    one-shot build, which is what the CLI and the job contract do.
    """
    started = time.time()
    if ctx is None:
        ctx = make_context(spec_path, out_dir, timeframe=timeframe, as_of=as_of)
    spec = ctx.spec
    stages = _stage_set(only, from_stage)
    if refresh:
        # `--refresh` means "go to the source even though the snapshot would do",
        # so it re-adds the stage that reaching the source requires
        stages.add("data")
    if assets is None:
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
        # Declared artwork the engine draws itself. A card's whole asset is the
        # words in the spec, so there is nothing to look up and nothing that can go
        # stale; a card *may* name a backdrop picture, which was checked to exist at
        # load time. Rendered before `clips`, like a panel, so a failure costs a build
        # rather than a half-finished film.
        for sc in spec.scenes:
            for sh in sc.shots:
                if sh.kind == "card":
                    _render_card(ctx, assets, spec, sc, sh)
                elif sh.kind == "solid":
                    _render_solid(ctx, assets, spec, sc, sh)
        ctx.info(f"stills: {len(assets.stills)}")

    # -- capture ----------------------------------------------------------- #
    if "capture" in stages and spec.captures:
        for res in _capture.capture_all(ctx):
            if res.path:
                assets.capture_stills[res.name] = res.path
                assets.stills[res.name] = res.path
            for art in res.artifacts:
                assets.artifacts[art.name] = art

    # -- exec -------------------------------------------------------------- #
    # After capture and before narration: a command's *output* is a still, and
    # narration is the master clock the still is then cut to (R-E1…R-E5).
    if "exec" in stages and spec.exec:
        _exec_stage(ctx, assets)

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

    # -- provenance (R-F8) -------------------------------------------------- #
    # Written by *every* job, verify or not: a plan or a capture still produced
    # figures, and whoever reads them later needs to know what they came from.
    # `verify.json` answers "is this honest?" and this answers "what is this?"
    assets.provenance = _write_provenance(ctx, action, sorted(stages), started,
                                          assets).to_dict()

    assets.ctx = ctx
    return assets


def _write_provenance(ctx: Context, action: str, stages: list[str],
                      started: float, assets: Assets | None = None) -> Provenance:
    spec = ctx.spec
    provider_path = None
    if spec.provider:
        module = spec.provider.module or ""
        for candidate in (ctx.root / module, ctx.root / f"{module}.py"):
            if module and candidate.is_file():
                provider_path = candidate
                break
    snapshot = Snapshot.read(ctx.data_dir)
    # Every command that actually ran, with the cast that proves what it printed.
    # A *refused* command is left out: nothing executed, so there is no fact to
    # record, and `verify` is where the refusal is reported as a failure.
    commands = [
        _exec_fact(result, assets.exec_casts.get(result.request.label),
                   assets.environments.get(_env_of(spec, result.request.label)))
        for result in (assets.exec_results.values() if assets else ())
        if not result.refused
    ]
    record = Provenance(
        action=action,
        spec=str(spec.path) if spec.path else "",
        spec_sha256=spec_digest(spec.path),
        timeframe=spec.timeframe.to_dict() if spec.timeframe else None,
        started=started, ended=time.time(),
        provider=spec.provider_name,
        provider_sha256=file_digest(provider_path),
        story=spec.story.slug if spec.story else None,
        commands=commands,
        tools=probe_tools(ctx.shell),
        stages=stages,
        datasets=dict(snapshot.datasets) if snapshot else {},
        degraded=dict(spec.degraded),
    )
    record.write(ctx.build)
    return record


# --------------------------------------------------------------------------- #
# the exec stage (R-E1…R-E5)
# --------------------------------------------------------------------------- #
def _exec_request(step, ctx: Context) -> _exec.ExecRequest:
    """Translate the spec's ``Exec`` into the runtime's ``ExecRequest``.

    Two types on purpose: ``Exec`` is the surface an author writes and carries
    what a *shot* needs (``cols``/``rows``/``at``); ``ExecRequest`` is what
    :func:`vidkit.exec.run` executes and carries nothing that cannot be honoured.
    Keeping them apart means the spec cannot reach into the runner.
    """
    return _exec.ExecRequest(
        cmd=list(step.cmd),
        cwd=step.cwd,
        shell=list(step.shell),
        env=dict(step.env),
        timeout=step.timeout,
        backend=step.backend,
        network=step.network,
        reads=list(step.reads),
        expect_exit=list(step.expect_exit),
        label=step.label,
    )


def _env_of(spec: Spec, label: str) -> str:
    """The environment a command label runs in, or ``""``. One place, one rule."""
    return spec.exec_environment(label)


def _exec_stage(ctx: Context, assets: Assets) -> None:
    """Run every declared command, record it, and draw the frames it produced.

    The recording is written *before* the frames are drawn, and both are drawn
    from the same in-memory events, so the picture and the ``.cast`` cannot tell
    different stories. Every byte is redacted as it arrives — see
    :meth:`vidkit.secrets.Secrets.redact_bytes`.

    Declared environments are started before the first command and torn down in a
    ``finally``, so the container is removed on every exit path — a successful
    build, a failed check, an interrupt, or an exception from anywhere in the
    stage (R-E6). Nothing in the loop below is trusted to remember to clean up.
    """
    started: list[_exec.EnvState] = []
    try:
        _start_environments(ctx, assets, started)
        try:
            _run_exec_steps(ctx, assets)
            _capture_environment_logs(ctx, assets)
        finally:
            _stop_environments(ctx, assets, started)
    finally:
        # Belt and braces, and not redundant. `_start_environments` appends to
        # ``started`` the moment a container exists — *before* it waits for
        # readiness — so a crash between those two points still knows what to
        # remove. Without this the very first build of this example leaked a
        # Postgres container into `docker ps`: the inner `finally` was never
        # reached, because the exception happened above it. A teardown contract
        # that only covers the happy path is not a contract.
        _stop_environments(ctx, assets, started)


def _start_environments(ctx: Context, assets: Assets,
                        started: list[_exec.EnvState]) -> None:
    """Bring up each declared environment once, for the whole exec stage.

    An environment that cannot start is not fatal to the *build*: it is recorded,
    its commands are refused, and ``verify`` says so. That separation matters,
    because the honest failure is "the database never came up", which is a fact
    about the run, not "the render crashed", which is a fact about the tool.

    ``started`` is appended to as soon as a container exists, not when the
    environment is declared ready, so that a failure during the wait is still
    cleanable.
    """
    used = {e.environment for e in ctx.spec.exec if e.environment}
    for env in ctx.spec.environments:
        if env.name not in used:
            continue        # refused at load time; belt and braces
        spec_env = _env_spec(env)
        # Registered before the container is awaited: from this point on something
        # may exist, and a crash during the wait must still be able to remove it.
        state = _exec.EnvState(spec=spec_env)
        started.append(state)
        try:
            got = _exec.environment_up(spec_env, root=ctx.root)
        except (_exec.ToolError, SpecError) as exc:
            got = _exec.EnvState(spec=spec_env, up=False, up_error=str(exc))
            ctx.warn(f"environment {env.name}: {exc}")
        else:
            if got.up:
                status = "ready" if got.ready else "up"
                ctx.info(f"environment {env.name}: {status} "
                         f"[{got.spec.image}, {got.seconds:.2f}s]")
            else:
                ctx.warn(f"environment {env.name}: did not start — "
                         f"{got.up_error}")
        state.__dict__.update(got.__dict__)
        assets.environments[env.name] = state
        if state.container_id:
            # bound per *step label*, because that is what the runner looks up
            for step in ctx.spec.exec:
                if step.environment == env.name:
                    _exec.bind_step(step.label, state)


def _env_spec(env) -> _exec.EnvSpec:
    """Translate the spec's ``Environment`` into the runtime's ``EnvSpec``.

    The same split as :func:`_exec_request`: what an author writes stays in
    ``spec.py``, and what the runtime honours stays in ``exec.py``, so the spec
    cannot reach a field the runner never reads.
    """
    return _exec.EnvSpec(
        name=env.name,
        image=env.image,
        command=list(env.command),
        env=dict(env.env),
        ports=list(env.ports),
        volumes=list(env.volumes),
        timeout=env.timeout,
        ready=list(env.ready),
        ready_timeout=env.ready_timeout,
        network=env.network,
    )


def _capture_environment_logs(ctx: Context, assets: Assets) -> None:
    """Write each environment's logs to disk as evidence, before teardown.

    ``--rm`` is withheld precisely so this is possible, and the logs are the thing
    that says a service actually started rather than merely stayed running. This is
    the *happy-path* call; :func:`_stop_environments` repeats it on every exit path,
    where a build that died mid-stage would otherwise lose the one piece of
    evidence explaining why.
    """
    for state in assets.environments.values():
        if not state.container_id:
            continue
        try:
            _exec.capture_logs(state, ctx.execs / f"env-{state.spec.name}.log")
        except _exec.ToolError as exc:
            ctx.warn(f"environment {state.spec.name}: could not read logs — {exc}")


def _stop_environments(ctx: Context, assets: Assets,
                       states: list[_exec.EnvState]) -> None:
    """Tear every environment down, whatever happened above.

    Never raises. A teardown failure is reported and recorded, because the one
    thing worse than a container that will not stop is a build that hides it.

    The logs are measured here as well as on the happy path, and *before* the
    container is stopped, because this is the last moment at which a container
    that already died still has its output to give.
    """
    for state in states:
        try:
            _exec.capture_logs(state, ctx.execs / f"env-{state.spec.name}.log")
            was_removed = state.teardown.get("removed", False)
            _exec.environment_down(state)
        except Exception as exc:                            # noqa: BLE001
            state.teardown = {"attempted": True, "stopped": False,
                              "removed": False, "detail": str(exc)}
            ctx.warn(f"environment {state.spec.name}: teardown failed — {exc}")
        else:
            if not state.teardown.get("removed"):
                ctx.warn(f"environment {state.spec.name}: still present — "
                         f"{state.teardown.get('detail', '')}")
            elif not was_removed:
                # Announced once, by whichever pass actually removed something.
                # The outer `finally` deliberately runs this a second time, and a
                # second "removed" line would read like a second container. The
                # verdict is "did this pass change anything", checked against the
                # record as it stood *before* the attempt — not "does the record
                # say it was removed", which stays true for ever afterwards.
                ctx.info(f"environment {state.spec.name}: removed "
                         f"[{state.teardown.get('detail', '')}]")
    _exec.unbind_environments()


def _run_exec_steps(ctx: Context, assets: Assets) -> None:
    """The command loop proper — one request, one recording, one set of frames."""
    for step in ctx.spec.exec:
        request = _exec_request(step, ctx)
        events: list[tuple[float, bytes]] = []
        started = time.monotonic()

        def record(chunk: bytes, *, _s=step, _e=events, _t=started) -> None:
            _e.append((time.monotonic() - _t, ctx.secrets.redact_bytes(chunk)))

        result = _exec.run(request, root=ctx.root, on_chunk=record,
                           cols=step.cols, rows=step.rows)
        # the result's own copy of the text is a *second* path to the screen, and
        # it is the one that ends up in verify.json; redact it independently
        result.stdout = ctx.secrets.redact(result.stdout)
        result.stderr = ctx.secrets.redact(result.stderr)
        assets.exec_results[step.label] = result

        if result.refused:
            # a refusal is not a run: nothing happened, so nothing is filmed and
            # nothing is recorded. Say so and keep going — a later verify check
            # (`guard.require_exec_success`) is what turns this into a failure.
            ctx.warn(f"exec {step.label}: refused — {result.refused}")
            continue

        cast = _terminal.write_cast(
            events, ctx.execs / f"{step.label}.cast", cols=step.cols, rows=step.rows,
            meta={"label": step.label, "cmd": step.cmd, "backend": result.backend,
                  "exit_code": result.exit_code, "seconds": round(result.seconds, 3),
                  "network": step.network})
        assets.exec_casts[step.label] = cast

        # Sample the run at a human cadence and keep every *distinct* screen, so
        # a shot can aim at the moment something changed rather than at an
        # arbitrary tick. The final screen is always kept. The events go straight
        # in: their timestamps are the ones the recorder measured.
        frames = _exec_frames(ctx, step, events)
        assets.exec_frames[step.label] = frames
        if frames:
            assets.exec_stills[step.label] = frames[-1][1]
            assets.stills[step.label] = frames[-1][1]

        status = "timed out" if result.timed_out else f"exit {result.exit_code}"
        extra = " (unexpected)" if not result.expected else ""
        ctx.info(f"exec {step.label}: {status}{extra} in {result.seconds:.2f}s "
                 f"[{result.backend}]{', network' if step.network else ''} "
                 f"-> {len(frames)} frame(s)")


#: How often a recording is sampled into frames. Fast enough that a state change
#: is caught within a beat, slow enough that a five-minute build does not try to
#: rasterise three hundred PNGs.
EXEC_FRAME_SECONDS = 1.0


def _exec_frames(ctx: Context, step, events: list[tuple[float, bytes]]) -> list[tuple[float, Path]]:
    """Replay the recording into PNG stills: ``(seconds, png)`` in time order.

    Deliberately *frames*, not an animation. The pipeline already knows how to
    hold a still for a measured duration, and M8's clip builder can hold each of
    these for the gap to the next one — so a recording plays back at the speed it
    actually happened, with no new stage and no video codec in the middle.

    The timestamps come from the recorder's own clock, so frame times are the
    real moments the screen changed and not a side effect of however the
    recording happened to be serialised.
    """
    screen = _terminal.replay_events(events, cols=step.cols, rows=step.rows,
                                     every=EXEC_FRAME_SECONDS)
    moments = list(screen.snapshots)
    if not moments or moments[-1][0] < events[-1][0]:
        # the replay samples on an interval, so the *final* screen — the one the
        # command left behind, and the frame most shots rest on — regularly falls
        # between two samples. Take it too, or the last thing the recording shows
        # is a screen the run had already left.
        moments.append((events[-1][0], screen))
    frames: list[tuple[float, Path]] = []
    seen: list[str] = []
    for index, (seconds, snap) in enumerate(moments):
        text = "\n".join(snap.lines())
        if text in seen and index != len(moments) - 1:
            # an unchanged screen redrawn is not a new moment; the last one is
            # kept regardless, because a frame that never lands is a still nobody
            # can point at
            continue
        seen.append(text)
        svg = ctx.stills / f"exec-{step.label}-{len(frames):02d}.svg"
        png = svg.with_suffix(".png")
        svg.write_text(_terminal.render_svg(snap, ctx.spec.size, title=step.label),
                       encoding="utf-8")
        ctx.rsvg.render(svg, png, ctx.spec.size)
        frames.append((seconds, png))
    return frames


def _exec_fact(result: _exec.ExecResult, cast: Path | None,
               state: _exec.EnvState | None = None) -> dict:
    """The audit row for one command — what ran, what it did, and where the proof is."""
    fact = {
        **result.to_dict(),
        "cast": str(cast.name) if cast else None,
        "expects": list(result.request.expect_exit),
        "argv": result.request.argv(),
    }
    if state is not None:
        # Which *container* it ran in, by name as well as by id. The image alone
        # does not identify a system: two builds of the same image are two
        # different databases, and a demo about writing a row and reading it back
        # is a claim about one of them.
        fact["container"] = state.container_name
    return fact


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
        spans.append((a.n, t, t + a.seconds))
        t += a.seconds
    return spans


def _plan_scripts(spec: Spec) -> list:
    """Per-scene spoken text for planning, read the way the narration stage reads it.

    ``_scripts_for`` needs a :class:`Context` because it resolves ``narration.source``
    against the spec *root*; a planner has only a spec, so the same lookup is done here.
    Falling back to ``narration.inline`` alone made every scene that keeps its words in
    a markdown file look like it had none: ``plan_audio`` divided 0 words by 2.5 and
    every shot planned at ``0.0s`` while the film actually built 98.8s long.
    """
    from .narration import SceneScript
    by_n: dict[int, str] = {}
    if spec.narration.source:
        src = None
        for base in (spec.root, spec.root.parent, Path.cwd()):
            p = (base / spec.narration.source)
            if p.exists():
                src = p
                break
        if src is not None:
            by_n = {s.n: s.spoken
                    for s in parse_scene_script(src.read_text(encoding="utf-8"))}
    return [SceneScript(n=sc.n,
                        spoken=spec.narration.inline.get(sc.n) or by_n.get(sc.n, ""))
            for sc in spec.scenes]


def plan_audio(spec: Spec, texts: dict[int, str] | None = None) -> list[_tts.SceneAudio]:
    """Per-scene narration lengths to plan against, without needing a Context.

    ``tts._FALLBACK_WPS`` (2.5) and not ``reports.WORDS_PER_SECOND`` (2.78): this has to
    agree with what the *audio stage* produces, and with no voice engine present that
    stage estimates every scene at ``words / _FALLBACK_WPS``. The two constants have
    disagreed since M0 and the disagreement is documented; using the estimator's own
    rate here is what keeps the plan from re-introducing it somewhere that now decides
    how long a shot is.

    ``texts`` is an override for a caller that has already parsed the narration file.
    """
    spoken = texts if texts is not None else {s.n: s.spoken for s in _plan_scripts(spec)}
    out: list[_tts.SceneAudio] = []
    for sc in spec.scenes:
        text = spoken.get(sc.n) or spec.narration.inline.get(sc.n) or ""
        out.append(_tts.SceneAudio(sc.n, None, round(word_count(text) / 2.5, 3),
                                   word_count(text)))
    return out


def plan_shots(spec: Spec, audio: list[_tts.SceneAudio]) -> list[tuple[Scene, int, Shot, float]]:
    """How long each shot will be, given the narration spans it has to cover.

    This is the *one* rule that decides a shot's length, and it is here rather than in
    ``_clip_plan`` because two callers need it and they must not disagree: the
    assembler, which renders to it, and ``reports.plan_report``, which tells the author
    what will be rendered. When the two were separate the plan said a 4s shot would be
    6.1s — the estimate from the narration wording — and the film came back 16.0s.

    A declared ``seconds:`` on a **scene** replaces its measured narration span for the
    purposes of dividing the work. A declared ``seconds:`` on a **shot** is taken out of
    the scene total *before* the remainder is split by weight, because an authored
    length is an instruction rather than another vote to average against its
    neighbours. With no ``seconds:`` anywhere this reproduces the old arithmetic
    exactly: every shot gets ``span * weight / total_weight``.
    """
    spans = _spans(audio)
    by_n = {n: (a, b) for n, a, b in spans}
    plan: list[tuple[Scene, int, Shot, float]] = []
    for sc in spec.scenes:
        if sc.n not in by_n and sc.seconds is None:
            continue
        start, end = by_n.get(sc.n, (0.0, 0.0))
        total = sc.seconds if sc.seconds is not None else (end - start)
        declared = sum(sh.seconds for sh in sc.shots if sh.seconds is not None)
        if declared > total:
            raise SpecError(
                f"scene {sc.n}: its shots declare {declared:.2f}s in total but the "
                f"scene is {total:.2f}s long — a shot would be truncated, and a "
                f"truncated take is a shot that does not exist")
        wsum = sum(s.weight for s in sc.shots if s.seconds is None) or 1
        for idx, shot in enumerate(sc.shots):
            seconds = shot.seconds if shot.seconds is not None \
                else (total - declared) * (shot.weight / wsum)
            if seconds > 0:
                plan.append((sc, idx, shot, seconds))
    return plan


def _resolve_exec_frame(ctx: Context, assets: Assets, shot) -> Path:
    """The frame an ``exec`` shot shows: the one nearest ``at``, else the last.

    A recording is a *period*, not a picture, so a shot has to say which instant
    it is about. The default — the final frame — is the honest default, because
    that is the screen the command left behind.
    """
    frames = assets.exec_frames.get(shot.ref)
    if not frames:
        single = assets.exec_stills.get(shot.ref) or (
            ctx.stills / f"exec-{shot.ref}-00.png")
        if not Path(single).exists():
            raise SpecError(
                f"no recorded frame for exec {shot.ref!r} — either the command "
                "was refused, or the `exec` stage did not run")
        return Path(single)
    if shot.at is None:
        return frames[-1][1]
    return min(frames, key=lambda item: abs(item[0] - shot.at))[1]


def _artwork_name(sc, shot) -> str:
    """The still name for a drawn shot.

    Scene-and-index rather than the shot's words: a card's text is a *sentence*,
    and a sentence is not a filename. Keying on position also means two scenes may
    carry the same title without one overwriting the other's PNG.
    """
    idx = sc.shots.index(shot) if shot in sc.shots else 0
    return f"{shot.kind}-{sc.n:02d}-{idx:02d}"


def _card_backdrop(ctx: Context, spec: Spec, sc, shot) -> Path | None:
    """Absolute path to a card's backdrop, or ``None``.

    Absolutised on purpose: the card SVG is written into ``build/stills``, and rsvg
    resolves a relative ``xlink:href`` against the *SVG's* directory — so a relative
    path would resolve to a file that is not there and the card would render over
    an empty frame without erroring.
    """
    if not shot.backdrop:
        return None
    for base in (ctx.root, ctx.root.parent, Path.cwd()):
        p = (base / shot.backdrop)
        if p.exists():
            return p.resolve()
    raise SpecError(f"scene {sc.n}: card backdrop not found: {shot.backdrop}")


def _render_card(ctx: Context, assets: Assets, spec: Spec, sc, shot) -> None:
    name = _artwork_name(sc, shot)
    svg = ctx.stills / f"{name}.svg"
    # the absolute backdrop is interpolated straight into the SVG; rsvg resolves an
    # absolute href, so a card may sit over a picture anywhere on disk
    svg.write_text(card.card_svg(shot.ref, size=spec.size, kicker=shot.kicker,
                                backdrop=_card_backdrop(ctx, spec, sc, shot)),
                   encoding="utf-8")
    png = ctx.stills / f"{name}.png"
    ctx.rsvg.render(svg, png, spec.size)
    assets.stills.setdefault(name, png)


def _render_solid(ctx: Context, assets: Assets, spec: Spec, sc, shot) -> None:
    name = _artwork_name(sc, shot)
    svg = ctx.stills / f"{name}.svg"
    svg.write_text(card.solid_svg(shot.ref, spec.size), encoding="utf-8")
    png = ctx.stills / f"{name}.png"
    ctx.rsvg.render(svg, png, spec.size)
    assets.stills.setdefault(name, png)


def _resolve_shot_still(ctx: Context, assets: Assets, sc, shot) -> Path:
    if shot.kind in ("card", "solid"):
        # the engine drew these a stage earlier, under a positional name — a card's
        # text is a sentence, and a sentence is not a filename
        p = assets.stills.get(_artwork_name(sc, shot))
        if p is not None and Path(p).exists():
            return Path(p)
    elif shot.kind == "capture":
        p = assets.capture_stills.get(shot.ref) or (
            ctx.captures / f"{shot.ref}.png")
    elif shot.kind == "exec":
        return _resolve_exec_frame(ctx, assets, shot)
    elif shot.kind == "chart":
        p = assets.panel_stills.get(shot.ref) or (ctx.stills / f"{shot.ref}.png")
    else:
        p = assets.stills.get(shot.ref) or (ctx.stills / f"{Path(shot.ref).stem}.png")
    if p is None or not Path(p).exists():
        raise SpecError(f"no still for {shot.kind} {shot.ref!r}")
    return Path(p)


def _overlay_graphic(ctx: Context, assets: Assets, sc, ov) -> tuple[Path, tuple[int, int]]:
    """The PNG to composite for a scene overlay, and the size to draw it at (R-D4).

    A ``banner`` is drawn by the engine here, from the scene's own words — it
    costs no asset and cannot go stale. An ``image`` is the author's file, drawn
    as itself; an SVG is rasterised at its *declared* size so the engine is not
    resampling a diagram it cannot read.
    """
    if ov.kind == "image":
        src = _resolve_ref(ctx, ov.src or "")
        if src is None:
            raise SpecError(f"scene {sc.n}: overlay image not found: {ov.src}")
        if src.suffix.lower() == ".svg":
            size = _overlay.svg_size(src)
            if size is None:
                raise SpecError(
                    f"scene {sc.n}: overlay SVG {src.name} does not declare a "
                    "width and height, so vidkit cannot know how large to draw it")
            png = ctx.stills / f"overlay-{sc.n:02d}.png"
            ctx.rsvg.render(src, png, size)
        else:
            png, size = src, None
        return png, size

    size = _overlay.banner_size(ctx.spec.size, ov.height)
    svg = ctx.stills / f"overlay-{sc.n:02d}.svg"
    svg.write_text(_overlay.banner_svg(ov.text or sc.title, ov.kicker, size),
                   encoding="utf-8")
    png = ctx.stills / f"overlay-{sc.n:02d}.png"
    ctx.rsvg.render(svg, png, size)
    return png, size


def _clip_plan(ctx: Context, assets: Assets):
    """Every take this build needs, in screen order: ``(scene, idx, shot, seconds)``.

    Laying the whole run out before rendering any of it is what makes a
    transition possible at all: the dissolve *overlaps* two takes, so the pair
    it joins has to share an extra ``transition_seconds`` whose removal is what
    keeps the finished runtime equal to the sum of the measured narration
    durations. That matters because narration is the master clock — a video
    track that quietly lost half a second per dissolve would drift out of sync
    with the voice, and drift is a lie about timing.

    A declared ``seconds:`` wins over the arithmetic. The rule itself lives in
    :func:`plan_shots`, which takes the spec alone, because ``reports.plan_report``
    has to show the author the same numbers this renders to and two copies of a
    timing rule is two chances to disagree.
    """
    return plan_shots(ctx.spec, assets.scene_audio)


def _exec_span(ctx: Context, assets: Assets, shot,
               seconds: float) -> tuple[list, list, float] | None:
    """The frames of a recording this shot plays, and how long each is held.

    ``None`` means "this shot is a single still", which is what a recording that
    produced fewer than two moments deserves.

    ``at:`` names the moment the shot is *about*, so the frames shown are the
    ones up to it and the last of them carries the remainder of the take.

    The interior frames keep their **measured** spans — the real gaps between the
    moments the screen changed — so a command that paused for two seconds pauses
    for two seconds' worth of the shot. The **final** frame is the one the shot
    rests on, and it takes whatever time is left of the take. That rule exists for
    a specific and common case: a command that prints its result and exits has a
    final screen whose own measured span is *zero*, and a video that showed it for
    zero seconds would end on a frame nobody could read.

    If the measured spans overrun the take, the interior is compressed to make
    room and the factor is returned so it can be *reported*. A screencast shown at
    2x is honest as long as it says it is 2x; a build that quietly claimed a
    four-second ``npm test`` took a quarter of a second would not be.
    """
    frames = assets.exec_frames.get(shot.ref) or []
    if len(frames) < 2:
        return None
    times = [at for at, _png in frames]
    wanted = shot.at if shot.at is not None else times[-1]
    keep = [i for i, at in enumerate(times) if at <= wanted] or [0]

    # each kept frame's true span is the gap to the next *kept* frame, and the
    # last one's is what remains of the window this shot is about
    measured: list[float] = []
    for j, i in enumerate(keep):
        nxt = times[keep[j + 1]] if j + 1 < len(keep) else wanted
        measured.append(max(0.0, nxt - times[i]))
    paths = [frames[i][1] for i in keep]

    floor = max(1.0 / max(ctx.spec.project.fps, 1), 0.04)
    interior = measured[:-1]
    budget = seconds - floor
    total = sum(interior)
    if total > budget > 0:
        scale = budget / total
        held = [g * scale for g in interior]
        last = floor
    else:
        held = [max(g, floor) for g in interior]
        last = max(floor, seconds - sum(held))
    speed = round(1.0 / scale, 3) if total > budget > 0 else 1.0
    if speed > 1.05:
        # Say it out loud. A recording re-timed to fit a short take is not a
        # failure — narration is the master clock and the shot is the room the
        # scene had — but a build that re-times a screencast without mentioning
        # it has quietly changed how long something took.
        ctx.warn(f"exec {shot.ref}: {total:.2f}s of recording in a {seconds:.2f}s "
                 f"shot; playing at {speed}x (declare more time or an earlier "
                 f"`at:` to show it at its real pace)")
    return paths, [*held, last], speed


def plan_transitions(spec: Spec, plan) -> list[str]:
    """What each planned take does at its own outgoing junction.

    ``""`` means "cut here". One entry per take, last one always ``""`` (there is no
    junction after the final take), so the list lines up with the take list and the
    clip list rather than with a set of junctions. This is the *one* rule that decides
    a transition, and it lives here because three callers need it and they must not
    disagree: the renderer, which pads the outgoing take and tells ffmpeg to xfade,
    and ``reports.plan_report``, which tells the author how long the film will be.
    When those were separate, `vidkit plan` promised a length the build did not make.

    A junction belongs to the **outgoing** shot: a dissolve is time the outgoing
    picture lends to the one after it, which is why the pad and the xfade have to come
    from one decision — otherwise the runtime stops matching the narration (I5).
    """
    from .spec import transition_of

    return [transition_of(plan[i][2], spec.project) if i < len(plan) - 1 else ""
            for i in range(len(plan))]


def _build_clips(ctx: Context, assets: Assets, scripts) -> None:
    spec = ctx.spec
    plan = _clip_plan(ctx, assets)
    moves = plan_transitions(spec, plan)
    overlaid = 0
    graphics: dict[int, tuple[Path | None, tuple[int, int] | None]] = {}
    for i, (sc, idx, shot, seconds) in enumerate(plan):
        # The *outgoing* take of a dissolve carries the extra time, so that the
        # incoming picture appears exactly when its own narration starts and the
        # previous picture lingers, fading, over the first beat of the new one —
        # which is what a dissolve means.
        pad = spec.project.transition_seconds if moves[i] else 0.0
        png = _resolve_shot_still(ctx, assets, sc, shot)
        frames: tuple[list, list, float] | None = None
        if shot.kind == "exec":
            span = _exec_span(ctx, assets, shot, seconds + pad)
            if span is not None:
                frame_paths, held, speed = span
                # an effect (`zoom`, a drift) is a *camera* move over one picture;
                # a recording already moves, so a moving camera over it would be
                # two motions fighting. A cut effect keeps its meaning, so only
                # `hold` is allowed to carry frames.
                if shot.effect in ("hold", "", None):
                    frames = (frame_paths, held)
                    assets.exec_playback[shot.ref] = speed
                    assets.exec_take_frames[shot.ref] = len(frame_paths)
        if sc.n not in graphics:
            graphics[sc.n] = (_overlay_graphic(ctx, assets, sc, sc.overlay)
                              if sc.overlay is not None else (None, None))
        graphic, size = graphics[sc.n]
        clip = ctx.clips / f"scene-{sc.n:02d}-{idx}.mp4"
        if graphic is None:
            target = clip
        else:
            # the pre-overlay clip goes in a subdirectory so that the
            # concatenation glob still finds exactly the finished takes —
            # which is what makes a resumed `--from concat` run correct.
            target = ctx.clips / "base" / clip.name
            target.parent.mkdir(parents=True, exist_ok=True)
        if frames is not None:
            ctx.ffmpeg.frames_to_clip(frames[0], target, frames[1], size=spec.size,
                                      fps=spec.project.fps)
        else:
            # `motion:` and `effect:` are the same idea at two ages: both are a
            # camera move over one picture. `motion:` is the fuller spelling and
            # supersedes `effect:` when both are present, so a spec can migrate
            # one shot at a time without a flag day. `still_to_clip` does the
            # precedence, so an undeclared motion leaves `effect:` in charge.
            ctx.ffmpeg.still_to_clip(png, target, seconds + pad, size=spec.size,
                                     fps=spec.project.fps, effect=shot.effect,
                                     fit=shot.fit, motion=shot.motion)
        if graphic is not None:
            ov = sc.overlay
            ctx.ffmpeg.overlay_clip(target, graphic, clip,
                                    position=ov.position,
                                    opacity=ov.opacity, fade=ov.fade,
                                    graphic_size=size)
            overlaid += 1
        assets.stills.setdefault(f"_clip_{sc.n}_{idx}", clip)
    ctx.info("clips built" + (f", {overlaid} with an overlay" if overlaid else ""))


def _concat(ctx: Context, assets: Assets) -> None:
    clips = sorted(ctx.clips.glob("scene-*.mp4"),
                   key=lambda p: tuple(int(x) for x in p.stem.split("-")[1:]))
    if not clips:
        raise SpecError("no clips to concatenate")
    assets.video_track = ctx.clips / "video-track.mp4"
    spec = ctx.spec
    if len(clips) < 2:
        ctx.ffmpeg.concat(clips, assets.video_track, ctx.clips / "video.txt")
    else:
        # junction i is the one *into* clip i; the opening clip has none. A clip
        # index is not a plan index — `plan_shots` drops zero-second takes — so the
        # kinds come from the plan, and the plan must line up with the clips one for
        # one or the transitions would attach to the wrong pairs.
        plan = _clip_plan(ctx, assets)
        moves = plan_transitions(spec, plan)
        if len(plan) != len(clips):
            raise SpecError(
                f"{len(plan)} take(s) were planned but {len(clips)} were rendered — "
                "transitions cannot be attached to pairs that do not match")
        trans = {i + 1: (moves[i], spec.project.transition_seconds)
                 for i in range(len(plan) - 1) if moves[i]}
        if not trans:
            ctx.ffmpeg.concat(clips, assets.video_track, ctx.clips / "video.txt")
        else:
            ctx.ffmpeg.concat_with_transitions(clips, assets.video_track,
                                               transitions=trans)
            named = ", ".join(sorted({k for k, _ in trans.values()}))
            ctx.info(f"{named} transitions: {len(trans)} junction(s)")
    assets.audio_track = _tts.concat_audio(ctx, assets.scene_audio)
    ctx.info(f"concat: {len(clips)} clips, audio={'yes' if assets.audio_track else 'no'}")


def _mix_score(ctx: Context, assets: Assets, total: float) -> Path | None:
    """Lay the declared score under the narration (R-G3).

    Returns ``None`` when the spec declares no score, so a spec that says nothing about
    music produces a bit-identical file to M8 — the feature is additive by construction.

    The ducking windows are the **measured** narration spans, which is why this happens
    after the audio stage rather than being threaded through it: the mix has to obey the
    same clock the pictures do (I5), and a mix built from declared estimates would drift
    against the voice the moment the voice disagreed with the estimate.
    """
    sc = ctx.spec.score
    if sc is None:
        return None
    src = Path(sc.src)
    if not src.is_absolute():
        src = ctx.spec.root / src
    src = src.resolve()
    if not src.exists():
        # the spec promised music; a missing file is a broken promise, not a silent cut.
        # A silent cut is *declared* (I6); this is not.
        raise SpecError(f"score: {sc.src!r} does not exist — looked in {src.parent}")

    narration = assets.audio_track or (ctx.build / "narration.wav")
    narration = Path(narration) if Path(narration).exists() else None
    spans = [(start, end) for _, start, end in _spans(assets.scene_audio)]

    out = ctx.build / "mix.wav"
    # The result is kept rather than discarded. The run's own account of what it mixed
    # is the only thing `verify` has to report; a report derived from the *spec* would
    # claim "ducked for 16s" about a mix that, on a silent cut, never ducked at all.
    result = ctx.ffmpeg.mix(narration, src, spans, out, duration=total,
                           volume_db=sc.volume, duck_db=sc.duck_db, ramp=sc.ramp,
                           fade_in=sc.fade_in, fade_out=sc.fade_out)
    if result.ducked:
        ctx.info(f"score: {src.name} at {sc.volume:+.1f} dB, ducked {result.seconds:.1f}s "
                 f"to {sc.duck_db:+.1f} dB -> {out.name}")
    else:
        ctx.info(f"score: {src.name} at {sc.volume:+.1f} dB, no voice to duck under "
                 f"-> {out.name}")
    assets.mix = out
    assets.mix_result = result
    return out


def _render(ctx: Context, assets: Assets, scripts) -> None:
    spec = ctx.spec
    if assets.video_track is None:
        assets.video_track = ctx.clips / "video-track.mp4"
    if assets.audio_track is None and not (ctx.build / "narration.wav").exists():
        assets.audio_track = _tts.concat_audio(ctx, assets.scene_audio)
    audio = assets.audio_track or (ctx.build / "narration.wav")
    audio = audio if Path(audio).exists() else None

    # captions retimed to the real scene spans — and the mix built from those same
    # spans, so the ducking cannot disagree with the subtitles about when someone spoke
    spans = _spans(assets.scene_audio)
    scenes_text = {s.n: s.spoken for s in scripts}
    srt_text = build_srt(scenes_text, spans)
    assets.srt = ctx.out_dir / "narration.srt"
    assets.srt.write_text(srt_text, encoding="utf-8")
    ctx.info(f"captions: {len(srt_text.splitlines())} lines -> {assets.srt.name}")

    # the film's real length: the video track, not a sum of estimates. A declared
    # `seconds:` on a shot or a scene moves this number and the score has to follow it.
    total = ctx.ffmpeg.duration(assets.video_track)
    if total <= 0:
        total = sum(a.seconds for a in assets.scene_audio)
    mixed = _mix_score(ctx, assets, total)
    if mixed is not None:
        audio = mixed

    out = ctx.out_dir / spec.project.output
    ctx.ffmpeg.mux_captioned(assets.video_track, audio, assets.srt, out,
                             size=spec.size, fps=spec.project.fps,
                             ceiling=spec.project.max_seconds)
    assets.output = out
    d = ctx.ffmpeg.duration(out)
    ctx.info(f"rendered {out.name}: {d:.2f}s ({d/60:.3f} min)")
