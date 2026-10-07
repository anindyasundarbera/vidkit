"""Structured reports shared by the CLI and the MCP server.

Each ``*_report`` function returns plain data (JSON-able); each ``format_*`` function
renders the same data as human-readable text. This keeps the terminal output and the MCP
tool output consistent, and lets an agent consume the structured form.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .errors import VidkitError
from .narration import parse_scene_script, word_count
from .panels import kinds as panel_kinds
from .spec import load_spec
from .timeframe import Timeframe, parse_timeframe

#: Words-per-second used to estimate runtime when no audio has been measured.
#: ~= piper length_scale 1.08 x 2.5 wps.
WORDS_PER_SECOND = 2.78


# --------------------------------------------------------------------------- #
def doctor_report(spec_path: Path | None = None, *,
                  timeframe: Any = None, as_of: Any = None) -> dict[str, Any]:
    """Environment + optional spec sanity, as data."""
    from .capture import _find_chrome, _playwright_available
    from .ffmpeg import Shell

    sh = Shell()
    tools: list[dict[str, Any]] = []

    def add(name: str, present: bool, note: str, required: bool, detail: str = "") -> None:
        tools.append({"name": name, "present": present, "note": note,
                      "required": required, "detail": detail})

    add("ffmpeg", sh.has("ffmpeg"), "renders and muxes video", True)
    add("ffprobe", sh.has("ffprobe"), "durations read from ffmpeg if absent", False)
    add("rsvg-convert", sh.has("rsvg-convert"), "SVG assets to PNG", True)
    add("playwright", _playwright_available(), "screen capture", False)
    chrome = _find_chrome()
    add("chrome/chromium", chrome is not None, "needed for capture", False, chrome or "")
    add("piper (TTS)", importlib.util.find_spec("piper") is not None,
        "narration audio", False)
    # Reported because it is the one tool an agent needs *before* it can reach any
    # other: if `mcp` is absent, the server cannot start and no tool is reachable —
    # yet nothing else on this list would say so. Not `required`, because a machine
    # used only for `vidkit build` is perfectly healthy without it.
    add("mcp", importlib.util.find_spec("mcp") is not None,
        "the MCP server and its tools", False)

    ok = all(t["present"] for t in tools if t["required"])
    report: dict[str, Any] = {
        "version": __version__,
        "python": sys.version.split()[0],
        "tools": tools,
        "ok": ok,
        "spec": None,
        "spec_error": None,
        "panel_kinds": panel_kinds(),
        # Always answered, spec or no spec: "can I run a confined command on this
        # machine" is a question about the machine, and it is the first thing an
        # author needs to know before writing `backend: bubblewrap` anywhere.
        "backends": _backends_line(),
    }

    if spec_path:
        try:
            spec = load_spec(spec_path, timeframe=_override(timeframe, as_of), as_of=as_of)
        except VidkitError as exc:
            report["spec_error"] = str(exc)
            report["ok"] = False
            return report
        needs, missing = _secret_needs(spec)
        if needs:
            # what a provider will ask for is part of "can this machine run this
            # story", so it is reported here rather than discovered mid-build
            add("secrets", not missing, "declared by the provider", True,
                ("not set: " + ", ".join(missing)) if missing else "all present")
            report["ok"] = report["ok"] and not missing
        report["backends"] = _sandbox_needs(spec)
        report["ok"] = report["ok"] and report["backends"]["ok"]
        report["spec"] = {
            "path": str(spec_path),
            "title": spec.project.title,
            "slug": spec.project.slug,
            "output": spec.project.output,
            "size": list(spec.project.size),
            "fps": spec.project.fps,
            "scenes": len(spec.scenes),
            "captures": len(spec.captures),
            "charts": len(spec.charts),
            "provider": spec.provider_name,
            "story": spec.story.to_dict() if spec.story else None,
            "timeframe": spec.timeframe.to_dict() if spec.timeframe else None,
            "secrets": needs,
        }
    return report


def _backends_line() -> dict[str, Any]:
    """Sandbox capability with no spec in hand — a fact about this host.

    Both sandboxes are asked, because a host can have one and not the other and
    either can be the reason a story will not run. Docker's three rungs are
    reported separately — see :func:`_docker_rungs` — since "Docker is
    unavailable" covers a missing client, a stopped daemon and a broken runtime,
    which are three different repairs.
    """
    from .exec import bwrap_available, docker_available

    ok, detail = bwrap_available()
    docker_ok, docker_detail = docker_available()
    return {
        "ok": ok,
        "declared": ["bubblewrap"],
        "available": ok,
        "detail": "bubblewrap can start a sandbox on this host" if ok else detail,
        "docker": _docker_rungs(),
        "available_backends": [name for name, works in
                               (("bubblewrap", ok), ("docker", docker_ok)) if works],
        # the one-line answer to "can a container run here at all", which is what
        # a reader of `doctor` wants before they have written a spec
        "docker_detail": docker_detail,
    }


def _docker_rungs() -> dict[str, Any]:
    """The three questions behind "is Docker available", each answered on its own.

    Kept as three rows rather than one boolean for the same reason ``bwrap`` is
    probed rather than ``which``-ed: a verdict that cannot distinguish its causes
    sends the reader to the wrong fix. It is also the honest shape — the engine
    really does run three different commands with three different costs (1 ms, 60
    ms, 450 ms) and only the third one proves a container can run.
    """
    from .exec import docker_rungs

    rungs = docker_rungs()
    client, daemon, container = rungs["client"], rungs["daemon"], rungs["container"]
    if not client["ok"]:
        detail = client["detail"]
    elif not daemon["ok"]:
        detail = daemon["detail"]
    else:
        detail = container["detail"]
    return {
        "client": client["ok"],
        "daemon": daemon["ok"],
        "container": container["ok"],
        "detail": detail,
        "rungs": rungs,
    }


def _sandbox_needs(spec) -> dict[str, Any]:
    """Whether the spec's declared sandboxes will actually work on this host (defect G).

    ``doctor`` has to answer "can this machine run this story", and a spec whose
    commands declare ``backend: bubblewrap`` on a host that cannot start a
    namespace is a story this machine cannot run. Saying so here is the whole
    point: otherwise the failure arrives as a ``SpecError`` in the middle of a
    build, or — worse — never arrives, and the recording quietly documents a
    sandbox that was not there.

    ``available`` always answers the *host* question ("can bwrap start?"), never
    the narrower "does this spec need it?", so a reader can tell a machine that
    cannot sandbox from a spec that does not ask it to.

    M8 adds Docker to the same question. A spec declaring ``backend: docker`` needs
    the host to be able to *run a container*, not merely to have installed the
    client, so the third rung is what decides it — the other two are reported
    because they are what a reader needs in order to act.
    """
    from .exec import bwrap_available, docker_available

    declared = sorted({step.backend for step in spec.exec})
    ok, detail = bwrap_available()
    needs_it = "bubblewrap" in declared
    docker_ok, docker_detail = docker_available()
    docker_rungs = _docker_rungs()
    needs_docker = "docker" in declared
    if not declared:
        how = "no exec steps declared; bubblewrap is usable" if ok else (
            f"no exec steps declared, but {detail}")
    elif ok:
        how = f"{', '.join(declared)} will run as declared"
    elif needs_it:
        how = f"declared {', '.join(declared)} cannot run: {detail}"
    else:
        how = f"declared {', '.join(declared)} run unconfined on this host"
    # Docker's verdict is separate because it has a separate repair. A spec may
    # declare both sandboxes, and failing on the one the author cannot use while
    # saying nothing about the other would be a diagnosis by omission.
    docker_problem = ""
    if needs_docker and not docker_ok:
        docker_problem = (
            f"declared backend docker cannot run: {docker_rungs['detail']}")
    elif needs_docker:
        docker_problem = (
            f"docker will run as declared against {_image_list(spec)}")
    return {
        "ok": (ok or not needs_it) and (docker_ok or not needs_docker),
        "declared": declared,
        "available": ok,
        "detail": how,
        "docker": docker_rungs,
        "available_backends": [name for name, works in
                               (("bubblewrap", ok), ("docker", docker_ok)) if works],
        "docker_ok": docker_ok or not needs_docker,
        "docker_detail": docker_problem or docker_detail,
    }


def _image_list(spec) -> str:
    """Name the images a spec will actually run, so `doctor` says what it checked."""
    images = sorted({e.image for e in getattr(spec, "environments", [])})
    if not images:
        return "no declared environment"
    return ", ".join(images)


def _secret_needs(spec) -> tuple[list[dict[str, Any]], list[str]]:
    """What a provider declares it needs, and which of those are missing.

    Never a value: :class:`~vidkit.secrets.Secrets` renders a length and a label,
    which is enough to tell a wrong token from an absent one (R-B4).
    """
    if spec.provider is None:
        return [], []
    from .provider import collect_secrets, load_provider
    from .secrets import Secrets

    declared = dict(spec.provider.secrets)
    try:
        module, _ = load_provider(spec.provider.module, spec.root)
        declared.update(collect_secrets(module))
    except VidkitError:
        # an unloadable provider is already reported by whichever check loaded it
        return [{"name": n, "required": r, "why": why, "present": False}
                for n, (r, why) in sorted(declared.items())], []

    needs = Secrets()
    needs.declare(declared, why=f"declared by provider {spec.provider.module!r}")
    needs.resolve()
    rows = [
        {"name": need.name, "required": need.required, "why": need.why,
         "label": need.label(), "present": need.name in needs.values}
        for need in needs.needs.values()
    ]
    return rows, [need.name for need in needs.missing_required()]


def format_doctor(report: dict[str, Any]) -> str:
    lines = [f"vidkit {report['version']}  (python {report['python']})"]
    for t in report["tools"]:
        status = "yes" if t["present"] else ("NO " if t["required"] else "no ")
        detail = t["detail"] or t["note"]
        lines.append(f"  [{status}] {t['name']:16s} {detail}")
    # Whether a confined command can run on this host is a question about the
    # host, so it is answered even when no spec was given: `available: false`
    # means the sandbox cannot start, not that bwrap(1) is missing (defect G).
    backends = report.get("backends")
    if backends:
        declared = backends.get("declared") or ["bubblewrap"]
        mark = "yes" if backends["available"] else "NO "
        lines.append(f"  [{mark}] {'sandbox':16s} "
                     f"confines {', '.join(declared)} — {backends['detail']}")
        # Docker gets its own row even when no step uses it, because "can a
        # container run here" is a fact about the host and an author deciding
        # whether to write `backend: docker` needs it before writing anything.
        docker = backends.get("docker") or {}
        if docker:
            rungs = docker.get("rungs", {})
            client = "yes" if docker.get("client") else "no "
            daemon = ("yes" if rungs.get("daemon", {}).get("ok") else "NO ") \
                if docker.get("client") else " - "
            runnable = "yes" if docker.get("container") else "NO "
            lines.append(
                f"  [{'yes' if docker.get('container') else 'NO '}] "
                f"{'docker':16s} client {client} · daemon {daemon} · "
                f"container {runnable} — {docker.get('detail', '')}")
    if report.get("spec_error"):
        lines.append(f"  [NO ] spec              {report['spec_error']}")
    elif report.get("spec"):
        s = report["spec"]
        lines += [
            f"  [yes] spec              {s['path']}",
            f"        project         {s['title']} ({s['slug']})",
            f"        size/fps        {s['size'][0]}x{s['size'][1]} @ {s['fps']}",
            f"        scenes          {s['scenes']}",
            f"        captures        {s['captures']}",
            f"        charts          {s['charts']}",
            f"        provider        {s['provider'] or '(none)'}",
            f"        story           {_story_line(s.get('story'))}",
            f"        timeframe       {_timeframe_line(s.get('timeframe'))}",
            f"        panel kinds     {', '.join(report['panel_kinds'])}",
        ]
    return "\n".join(lines)


def _override(timeframe: Any, as_of: Any):
    """Resolve a caller's timeframe override, tolerating ``None``."""
    if timeframe is None or isinstance(timeframe, Timeframe):
        return timeframe
    return parse_timeframe(timeframe, where="--timeframe", source="override",
                           default_as_of=as_of)


def _story_line(story: dict[str, Any] | None) -> str:
    if not story:
        return "(not resolved)"
    return f"{story['slug']}" + ("" if story["declared"] else " (folder convention)")


def _timeframe_line(tf: dict[str, Any] | None) -> str:
    if not tf:
        return "(not declared)"
    return f"{tf['label']}  [{tf['source']}]"


# --------------------------------------------------------------------------- #
def format_provenance(record: dict[str, Any]) -> str:
    """The build record as a person reads it. The JSON is the same document."""
    lines = [
        f"vidkit {record.get('vidkit', '?')} built {record.get('action', '?')} "
        f"at {record.get('built_at', '?')}  ({record.get('seconds', 0):.1f}s)",
        f"  spec      {record.get('spec')}",
        f"  spec hash {record.get('spec_sha256')}",
        f"  window    {_timeframe_line(record.get('timeframe'))}",
        f"  story     {record.get('story') or '(folder convention)'}",
    ]
    provider = record.get("provider")
    lines.append(f"  provider  {provider or '(none)'}"
                 + (f"  {record.get('provider_sha256')}" if provider else ""))
    if record.get("datasets"):
        for name, digest in sorted(record["datasets"].items()):
            lines.append(f"    data    {name:16s} {digest}")
    if record.get("degraded"):
        for name, why in sorted(record["degraded"].items()):
            lines.append(f"    DEGRADED {name}: {why}")
    lines.append(f"  stages    {', '.join(record.get('stages') or []) or '(none)'}")
    for t in record.get("tools", []):
        status = "yes" if t["present"] else "NO "
        lines.append(f"  [{status}] {t['name']:16s} {t.get('version') or '(not found)'}")
    rt = record.get("runtime") or {}
    if rt:
        lines.append(f"  runtime   {rt.get('python')} on {rt.get('machine')}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
def plan_report(spec_path: Path, *, timeframe: Any = None,
                as_of: Any = None) -> dict[str, Any]:
    """The scene plan and estimated runtime, as data."""
    spec = load_spec(spec_path, timeframe=_override(timeframe, as_of), as_of=as_of)
    source: dict[int, str] = {}
    if spec.narration.source:
        p = (spec_path.parent / spec.narration.source)
        if p.exists():
            source = {s.n: s.spoken for s in parse_scene_script(p.read_text(encoding="utf-8"))}

    scenes: list[dict[str, Any]] = []
    total_words = 0
    for sc in spec.scenes:
        text = spec.narration.inline.get(sc.n) or source.get(sc.n, "")
        w = word_count(text) if text else 0
        total_words += w
        scenes.append({
            "n": sc.n,
            "title": sc.title,
            "words": w,
            "est_seconds": round(w / WORDS_PER_SECOND, 1) if w else 0.0,
            "declared_seconds": sc.seconds,
            "shots": [f"{_shot_line(s)}" for s in sc.shots],
        })

    # What will *actually* be rendered. `est_seconds` above is the narration estimate
    # and stays because it is the number the runtime window is about; this is the
    # take-by-take length, which is a different number the moment a spec declares a
    # `seconds:` or a `motion:`. Reporting only the estimate let `vidkit plan` promise
    # a 24.7s film that built as 16.0s.
    from .assembler import plan_audio, plan_shots, plan_transitions
    planned = plan_shots(spec, plan_audio(spec))
    moves = plan_transitions(spec, planned)
    takes = [{"scene": sc.n, "index": idx, "kind": sh.kind, "ref": sh.ref,
              "seconds": round(sec, 3),
              "motion": sh.motion.to_dict() if sh.motion else None,
              "declared": sh.seconds is not None,
              "from_scene": sc.seconds is not None and sh.seconds is None,
              "transition": moves[i] or "cut"}
             for i, (sc, idx, sh, sec) in enumerate(planned)]
    by_scene: dict[int, float] = {}
    for t in takes:
        by_scene[t["scene"]] = by_scene.get(t["scene"], 0.0) + t["seconds"]
    for s in scenes:
        s["planned_seconds"] = round(by_scene.get(s["n"], 0.0), 3)
    planned_total = sum(by_scene.values())
    # A dissolve does **not** shorten the film. `_build_clips` pads the outgoing take
    # by `transition_seconds` and `concat_with_transitions` then overlaps the same
    # amount, so the two cancel exactly and the picture track stays the length of the
    # narration it has to cover (I5). Subtracting the overlap again here was a
    # double-count: `vidkit plan` promised 4.8s for a film that builds as 6.0s on
    # every spec with a transition declared — the same "reported length the build
    # does not make" failure that made the plan lie in M9, one layer further in.
    planned_runtime = round(planned_total, 3)

    est_total = total_words / WORDS_PER_SECOND if total_words else 0.0
    return {
        "title": spec.project.title,
        "slug": spec.project.slug,
        "output": spec.project.output,
        "size": list(spec.project.size),
        "fps": spec.project.fps,
        "window": [spec.project.min_seconds, spec.project.max_seconds],
        "scenes": scenes,
        "takes": takes,
        "timing_source": spec.timing_source,
        "planned_seconds": planned_runtime,
        "narration_words": total_words,
        "est_seconds": round(est_total, 1),
        "est_minutes": round(est_total / 60, 2),
        # The window is a promise about the *film*, so it is the planned length that
        # gets checked against it. The narration estimate is shown, not enforced.
        "within_window": bool(
            spec.project.min_seconds <= planned_runtime <= spec.project.max_seconds
        ) if planned_total else None,
        "banned": list(spec.guard.banned),
        "required": list(spec.guard.required),
        "require_live_mode": spec.guard.require_live_mode,
        "score": spec.score.to_dict() if spec.score else None,
        "story": spec.story.to_dict() if spec.story else None,
        "timeframe": spec.timeframe.to_dict() if spec.timeframe else None,
    }


def _shot_line(shot) -> str:
    """One shot, as the author wrote it: ``kind:ref``, its move, its declared length.

    A declared ``motion:`` supersedes ``effect:``, so only the one that will actually
    be rendered is printed. Printing both said ``hold, zoom in 8%`` — two moves for one
    picture, one of which is a lie.
    """
    bits = [f"{shot.kind}:{shot.ref}"]
    if shot.motion is not None:
        bits.append(shot.motion.label())
    elif shot.effect and shot.effect != "hold":
        bits.append(shot.effect)
    if shot.seconds is not None:
        bits.append(f"{shot.seconds:g}s")
    return f"{bits[0]}({', '.join(bits[1:])})" if len(bits) > 1 else bits[0]


def format_plan(report: dict[str, Any]) -> str:
    lines = [
        f"{report['title']}  [{report['slug']}]",
        f"  output: {report['output']}  {report['size'][0]}x{report['size'][1]} "
        f"@{report['fps']}",
        f"  runtime window: {report['window'][0]:.0f}-{report['window'][1]:.0f}s",
        f"  story: {_story_line(report.get('story'))}",
        f"  timeframe: {_timeframe_line(report.get('timeframe'))}",
        "  scenes:",
    ]
    for s in report["scenes"]:
        lines.append(
            f"    {s['n']:2d}. {s['title'] or '(untitled)':38s} "
            f"{s.get('planned_seconds', s['est_seconds']):5.1f}s  "
            f"{', '.join(s['shots'])}"
        )
    src = report.get("timing_source") or "narration"
    clock = ("lengths are declared in the spec" if src == "spec"
             else "lengths follow the measured narration")
    lines.append(f"  timing: {src} — {clock}")
    lines.append(f"  planned runtime: {report.get('planned_seconds', 0.0):.1f}s "
                 f"from {len(report.get('takes') or [])} take(s)")
    moves = [t for t in (report.get("takes") or []) if t.get("transition") not in
             (None, "", "cut")]
    if moves:
        lines.append("  transitions: " + ", ".join(
            f"{t['transition']} out of scene {t['scene']}.{t['index']}"
            for t in moves))
    if report.get("score"):
        sc = report["score"]
        lines.append(f"  score: {sc['src']} at {sc['volume_db']:+.1f} dB, "
                     f"ducked {sc['duck_db']:+.1f} dB "
                     f"(fade in {sc['fade_in']:g}s / out {sc['fade_out']:g}s)")
    lines.append(f"  narration words: {report['narration_words']}  |  "
                 f"est. runtime ~{report['est_minutes']:.2f} min")
    if report["within_window"] is False:
        lines.append("  WARNING: planned runtime outside the project window")
    lines.append(f"  banned phrases: {len(report['banned'])}")
    for b in report["banned"]:
        lines.append(f"    - {b}")
    lines.append(f"  required phrases: {len(report['required'])}")
    for r in report["required"]:
        lines.append(f"    - {r}")
    return "\n".join(lines)
