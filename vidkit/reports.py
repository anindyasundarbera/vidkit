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
    """Sandbox capability with no spec in hand — a fact about this host."""
    from .exec import bwrap_available

    ok, detail = bwrap_available()
    return {"ok": ok, "declared": ["bubblewrap"], "available": ok,
            "detail": "bubblewrap can start a sandbox on this host" if ok else detail}


def _sandbox_needs(spec) -> dict[str, Any]:
    """Whether the spec's declared sandbox will actually work on this host (defect G).

    ``doctor`` has to answer "can this machine run this story", and a spec whose
    commands declare ``backend: bubblewrap`` on a host that cannot start a
    namespace is a story this machine cannot run. Saying so here is the whole
    point: otherwise the failure arrives as a ``SpecError`` in the middle of a
    build, or — worse — never arrives, and the recording quietly documents a
    sandbox that was not there.

    ``available`` always answers the *host* question ("can bwrap start?"), never
    the narrower "does this spec need it?", so a reader can tell a machine that
    cannot sandbox from a spec that does not ask it to.
    """
    from .exec import bwrap_available

    declared = sorted({step.backend for step in spec.exec})
    ok, detail = bwrap_available()
    needs_it = "bubblewrap" in declared
    if not declared:
        how = "no exec steps declared; bubblewrap is usable" if ok else (
            f"no exec steps declared, but {detail}")
    elif ok:
        how = f"{', '.join(declared)} will run as declared"
    elif needs_it:
        how = f"declared {', '.join(declared)} cannot run: {detail}"
    else:
        how = f"declared {', '.join(declared)} run unconfined on this host"
    return {
        "ok": ok or not needs_it,
        "declared": declared,
        "available": ok,
        "detail": how,
    }


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
            "shots": [f"{s.kind}:{s.ref}({s.effect})" for s in sc.shots],
        })

    est_total = total_words / WORDS_PER_SECOND if total_words else 0.0
    return {
        "title": spec.project.title,
        "slug": spec.project.slug,
        "output": spec.project.output,
        "size": list(spec.project.size),
        "fps": spec.project.fps,
        "window": [spec.project.min_seconds, spec.project.max_seconds],
        "scenes": scenes,
        "narration_words": total_words,
        "est_seconds": round(est_total, 1),
        "est_minutes": round(est_total / 60, 2),
        "within_window": bool(
            spec.project.min_seconds <= est_total <= spec.project.max_seconds
        ) if est_total else None,
        "banned": list(spec.guard.banned),
        "required": list(spec.guard.required),
        "require_live_mode": spec.guard.require_live_mode,
        "story": spec.story.to_dict() if spec.story else None,
        "timeframe": spec.timeframe.to_dict() if spec.timeframe else None,
    }


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
            f"    {s['n']:2d}. {s['title'] or '(untitled)':38s} {s['est_seconds']:5.1f}s  "
            f"{', '.join(s['shots'])}"
        )
    lines.append(f"  narration words: {report['narration_words']}  |  "
                 f"est. runtime ~{report['est_minutes']:.2f} min")
    if report["within_window"] is False:
        lines.append("  WARNING: estimated runtime outside the project window")
    lines.append(f"  banned phrases: {len(report['banned'])}")
    for b in report["banned"]:
        lines.append(f"    - {b}")
    lines.append(f"  required phrases: {len(report['required'])}")
    for r in report["required"]:
        lines.append(f"    - {r}")
    return "\n".join(lines)
