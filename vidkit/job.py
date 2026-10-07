"""The job contract: ``{story, timeframe, out} → artifact manifest`` (R-G3).

An agent should not have to know which of a dozen commands to call, in what order,
or what the result looks like. It should be able to hand vidkit a job and read back
a manifest. That contract is what this module is.

Design
------
* **One entry point.** :func:`run_job` accepts an action plus a story, a window, and
  an output directory, and returns a JSON-able manifest — always the same shape, so a
  caller can branch on ``ok`` rather than on which command it happened to invoke.
* **Failures are data, not exceptions.** A caller that reads ``ok: false`` and a
  ``failure`` block never has to parse a sentence, and — more importantly — never
  mistakes a crash for a result. :class:`VidkitError` is caught here; anything else
  is a bug and is allowed to propagate.
* **The manifest describes the run, not the wish.** Paths are reported only when the
  file is actually on disk, the report is the real ``verify.json``, and ``timeline``
  carries the *measured* per-scene spans when they exist.
* **Two ways to watch.** :func:`run_job` takes an optional ``on_progress`` sink, and
  every manifest carries the same steps back as data. The sink is a plain callable, so
  the caller decides whether that means a terminal, a log, or nothing at all.
  ``stdout`` is left alone: whoever runs a job owns its output. A transport that needs
  a silent channel (the MCP stdio one) wraps the call itself, which is what
  ``mcp_server`` already does.
"""

from __future__ import annotations

import contextlib
import io
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterable

from . import __version__
from .errors import SpecError, ToolError, VidkitError
from .timeframe import Timeframe, parse_timeframe

#: The actions a job may ask for. Each is a verb an agent can reason about.
ACTIONS = ("plan", "build", "capture", "tts", "verify", "doctor", "init")

#: How the actions map onto pipeline stages. ``None`` means "the whole pipeline".
_STAGES: dict[str, list[str] | None] = {
    "build": None,
    "capture": ["capture"],
    "tts": ["narration"],
}

ACTION_HELP: dict[str, str] = {
    "plan": "show the scene plan and estimated runtime; renders nothing",
    "build": "run the whole pipeline and return the artifacts + verification report",
    "capture": "re-run only the screen captures",
    "tts": "re-synthesize only the narration",
    "verify": "re-run the acceptance checks against the last render",
    "doctor": "check the environment, and the story's spec if there is one",
    "init": "scaffold a new story directory (needs `story`)",
}

ProgressHook = Callable[[str], None]


@dataclass
class Progress:
    """The narration of one job: ordered steps, with durations, as data.

    A caller can stream these through ``on_progress`` while the job runs, or read
    them from the manifest afterwards. Both views describe the same run, and
    neither is invented after the fact.
    """

    steps: list[dict[str, Any]] = field(default_factory=list)
    started: float = field(default_factory=time.monotonic)
    _hook: ProgressHook | None = None

    def step(self, name: str, ok: bool, detail: str = "", seconds: float | None = None,
             *, kind: str = "stage") -> dict[str, Any]:
        entry = {
            "name": name,
            "kind": kind,
            "ok": bool(ok),
            "detail": detail,
            "seconds": round(seconds, 3) if seconds is not None else None,
        }
        self.steps.append(entry)
        if self._hook is not None:
            mark = "ok" if ok else "FAILED"
            extra = f" — {detail}" if detail else ""
            self._hook(f"{name}: {mark}{extra}")
        return entry

    def to_dict(self) -> dict[str, Any]:
        return {"steps": list(self.steps), "seconds": round(time.monotonic() - self.started, 3)}


class _LineTicker(io.TextIOBase):
    """Report each whole line the pipeline prints as a progress step.

    The pipeline already narrates itself with ``[vidkit] …`` lines. Rather than
    re-plumbing every stage to take a callback, a job reads that stream — so the
    progress a caller sees is the pipeline's own account of itself, not a second,
    parallel one that could drift from it.
    """

    def __init__(self, progress: Progress) -> None:
        self._progress = progress
        self._buf = ""

    def write(self, s: str) -> int:
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._line(line)
        return len(s)

    def _line(self, line: str) -> None:
        text = line.strip()
        if not text:
            return
        if text.startswith("[vidkit]"):
            text = text[len("[vidkit]"):].strip()
        # classified rather than lumped together, so a caller can show stage
        # transitions in a spinner and checks in a list without parsing the text
        kind = "log"
        if text.startswith("[PASS]") or text.startswith("[FAIL]"):
            kind = "check"
        elif text.startswith("WARN "):
            kind = "warn"
        self._progress.step(text, not text.startswith("[FAIL]"), kind=kind)

    def flush(self) -> None:
        if self._buf.strip():
            self._line(self._buf)
        self._buf = ""

    def writable(self) -> bool:  # pragma: no cover - io protocol
        return True

    def isatty(self) -> bool:  # pragma: no cover - io protocol
        return False


@contextlib.contextmanager
def reporting(progress: Progress):
    """Route the pipeline's stdout into ``progress`` for the duration of the block.

    A job owns the run, so it owns what the run says: the stream becomes data in the
    manifest, and reaches a terminal only if the caller's hook puts it there. That is
    what keeps a job safe on a transport with no stdout to spare — the MCP stdio one
    — without every stage having to know about transports. ``sys.stdout`` is restored
    unconditionally, so a failure inside the block cannot dangle it.
    """
    import sys

    sink = _LineTicker(progress)
    saved = sys.stdout
    sys.stdout = sink
    try:
        yield
    finally:
        sink.flush()
        sys.stdout = saved


# --------------------------------------------------------------------------- #
# The manifest
# --------------------------------------------------------------------------- #
def _manifest(action: str, story: Path | None, out: Path | None,
              timeframe: Any = None) -> dict[str, Any]:
    return {
        "action": action,
        "ok": False,
        "story": str(story) if story else None,
        "out": str(out) if out else None,
        "spec": None,
        "timeframe": None,
        "artifacts": {},
        "report": None,
        "timeline": [],
        "failure": None,
        "progress": None,
        "vidkit": __version__,
    }


def _artifact(path: Path | None) -> dict[str, Any] | None:
    """Describe a file, but only if it is really there and non-empty."""
    if path is None:
        return None
    p = Path(path)
    if not p.exists():
        return None
    return {
        "path": str(p),
        "bytes": p.stat().st_size,
        # a file with no bytes is not a render, whatever its name says
        "ok": p.stat().st_size > 0,
    }


def _timeline(assets) -> list[dict[str, Any]]:
    """The measured per-scene spans — start, end and duration, in seconds."""
    spans: list[dict[str, Any]] = []
    at = 0.0
    for audio in getattr(assets, "scene_audio", []) or []:
        seconds = float(getattr(audio, "seconds", 0.0) or 0.0)
        spans.append({
            "n": int(getattr(audio, "n", 0)),
            "start": round(at, 3),
            "end": round(at + seconds, 3),
            "seconds": round(seconds, 3),
            "words": int(getattr(audio, "words", 0) or 0),
        })
        at += seconds
    return spans


def _failure(exc: BaseException, action: str, story: Path | None) -> dict[str, Any]:
    """A failure an agent can act on: a kind, a message, and what to try next."""
    text = str(exc)
    kind = "error"
    if isinstance(exc, SpecError):
        kind = "spec"
    elif isinstance(exc, ToolError):
        kind = "tool"
    elif isinstance(exc, VidkitError):
        kind = "vidkit"
    return {
        "kind": kind,
        "message": text,
        "action": action,
        "story": str(story) if story else None,
        "hint": _hint(text, action),
    }


_HINTS = (
    # argument mistakes first: their advice is about the call, not about the machine
    ("unknown action", "actions are listed by `vidkit_actions`"),
    ("no story given", "pass `story`: the folder holding the story's video.yaml"),
    ("no video.yaml/spec.yaml inside", "check the folder, or `init` a new story there"),
    ("no such file", "check the path; `vidkit_doctor` will list what the spec needs"),
    ("not installed", "run `vidkit_doctor` to see which tool is missing"),
    ("is not in PATH", "run `vidkit_doctor` to see which tool is missing"),
    ("snapshot is stale", "build with refresh=true, or widen the window back"),
    ("no dataset snapshot", "drop `data` from `only`, or pass refresh=true"),
    ("missing_required", "export the named variables, then retry"),
    ("not set:", "export the named variables, then retry"),
    ("no narration", "declare `narration.source` or `narration.inline`"),
    ("did not finish within", "raise `timeout`, or run fewer stages with `only`"),
    ("has no shots", "give the scene at least one still/capture/chart"),
)


def _hint(message: str, action: str) -> str:
    low = message.lower()
    for needle, hint in _HINTS:
        if needle.lower() in low:
            return hint
    if action == "init":
        return "pass `story`, the directory the new story should be written to"
    return "run `vidkit_doctor` first; it names the missing piece"


# --------------------------------------------------------------------------- #
# Actions
# --------------------------------------------------------------------------- #
def _story_spec(story: Path | None) -> Path | None:
    """The spec inside a story folder, or ``None`` when there is no folder."""
    if story is None:
        return None
    root = Path(story)
    if root.is_file():
        return root
    for name in ("video.yaml", "video.yml", "spec.yaml", "spec.yml"):
        candidate = root / name
        if candidate.exists():
            return candidate
    return None


def needs_spec(action: str) -> bool:
    """Whether an action needs a story to exist.

    ``init`` writes one instead of reading one, and ``doctor`` is most useful when
    there is no story yet — checking the machine before a story exists is the
    reason to run it first.
    """
    return action not in ("init", "doctor")


def run_job(action: str = "plan", *, story: str | Path | None = None,
            out: str | Path | None = None, timeframe: Timeframe | str | dict | None = None,
            as_of: date | None = None, refresh: bool = False,
            title: str | None = None, slug: str | None = None,
            spec: str | Path | None = None,
            only: Iterable[str] | None = None, from_stage: str | None = None,
            on_progress: ProgressHook | None = None) -> dict[str, Any]:
    """Run one job and return its manifest.

    ``action`` is one of :data:`ACTIONS`. ``story`` is a story *folder* (its spec is
    found inside) or a spec file. ``out`` is where the run writes. ``timeframe``
    overrides the story's declared window. ``refresh`` re-asks the data source.
    ``only``/``from_stage`` narrow a rendering action's stages. ``on_progress`` is
    called with one line of the run's own log as it happens — that is the only way
    the log leaves this function, so stdout stays the caller's to use.

    The returned manifest always has the same keys, so a caller can branch on
    ``ok``. Nothing here raises for an expected failure: an agent reading a
    manifest should never have to tell "vidkit said no" apart from "vidkit crashed".
    """
    story_path = Path(story).expanduser().resolve() if story else None
    out_dir = Path(out).expanduser().resolve() if out else None
    progress = Progress(_hook=on_progress)
    manifest = _manifest(action, story_path, out_dir, timeframe)

    if timeframe is not None:
        # Record the window that was *asked* for before anything can refuse, so a
        # failed job still answers "which window was that about?". An unparseable
        # one is recorded as the caller spelled it: the point is to hand back what
        # was asked, and the real complaint arrives as `failure` a moment later.
        try:
            override = (timeframe if isinstance(timeframe, Timeframe)
                        else parse_timeframe(timeframe, where="timeframe",
                                             source="override", default_as_of=as_of))
        except SpecError as exc:
            manifest["timeframe"] = {"source": "override", "given": timeframe,
                                     "error": str(exc)}
        else:
            if override is not None:
                manifest["timeframe"] = override.to_dict()

    try:
        with reporting(progress):
            # argument checking happens in here, not before it, because "you gave me
            # no story" is an expected answer to an agent's call, not a crash
            if action not in ACTIONS:
                raise ToolError(f"unknown action {action!r}; known: {', '.join(ACTIONS)}")
            spec_path = Path(spec).expanduser().resolve() if spec else _story_spec(story_path)
            if needs_spec(action) and spec_path is None:
                raise ToolError(
                    "no story given: pass a story folder (containing video.yaml) or a spec path"
                    if story_path is None else
                    f"no video.yaml/spec.yaml inside {story_path}"
                )
            manifest["spec"] = str(spec_path) if spec_path else None
            if action == "init":
                _do_init(manifest, progress, story_path, out_dir, timeframe, as_of,
                         title, slug)
            elif action == "plan":
                _do_plan(manifest, progress, spec_path, timeframe, as_of)
            elif action == "doctor":
                _do_doctor(manifest, progress, spec_path, timeframe, as_of)
            elif action == "verify":
                _do_verify(manifest, progress, spec_path, out_dir, timeframe, as_of)
            else:
                _do_build(manifest, progress, spec_path, out_dir, timeframe, as_of,
                          refresh, action, only, from_stage)
    except VidkitError as exc:
        manifest["ok"] = False
        manifest["failure"] = _failure(exc, action, story_path)
        progress.step(f"{action} failed", False, str(exc))
    manifest["progress"] = progress.to_dict()
    return manifest


# --------------------------------------------------------------------------- #
def _do_init(manifest, progress: Progress, story: Path | None, out: Path | None,
             timeframe: Any, as_of: date | None, title: str | None,
             slug: str | None) -> None:
    from .scaffold import scaffold_story

    target = story or out
    if target is None:
        raise ToolError("`init` needs a story directory: pass story (or out)")

    started = time.monotonic()
    written = scaffold_story(target, title=title, slug=slug,
                             timeframe=timeframe if isinstance(timeframe, Timeframe) else None,
                             as_of=as_of)
    progress.step(f"scaffolded {target.name}", True,
                  f"{len(written)} files", time.monotonic() - started)
    manifest["story"] = str(target)
    manifest["spec"] = str(target / "video.yaml")
    manifest["artifacts"] = {
        "story": _artifact(target / "story.yaml"),
        "spec": _artifact(target / "video.yaml"),
        "provider": _artifact(target / "provider.py"),
        "narration": _artifact(target / "narration.md"),
    }
    manifest["created"] = [str(p) for p in written]
    manifest["ok"] = True


def _do_plan(manifest, progress: Progress, spec: Path, timeframe: Any,
             as_of: date | None) -> None:
    from .reports import plan_report

    started = time.monotonic()
    report = plan_report(spec, timeframe=timeframe, as_of=as_of)
    progress.step("planned", True,
                  f"{len(report['scenes'])} scenes, ~{report['est_seconds']}s",
                  time.monotonic() - started)
    manifest["timeframe"] = report.get("timeframe")
    manifest["plan"] = report
    manifest["ok"] = True


def _do_doctor(manifest, progress: Progress, spec: Path | None, timeframe: Any,
               as_of: date | None) -> None:
    from .reports import doctor_report

    started = time.monotonic()
    report = doctor_report(spec, timeframe=timeframe, as_of=as_of)
    missing = [t["name"] for t in report["tools"] if t["required"] and not t["present"]]
    progress.step("doctor", report["ok"],
                  ("missing: " + ", ".join(missing)) if missing else "all required tools present",
                  time.monotonic() - started)
    manifest["doctor"] = report
    manifest["ok"] = bool(report["ok"])
    if not manifest["ok"]:
        manifest["failure"] = {
            "kind": "tool",
            "message": (report.get("spec_error")
                        or "missing required tool(s): " + ", ".join(missing)),
            "action": "doctor",
            "story": manifest["story"],
            "hint": "install the missing tool, or ignore it if this job does not need it",
        }


def _do_verify(manifest, progress: Progress, spec: Path, out: Path | None,
               timeframe: Any, as_of: date | None) -> None:
    from .assembler import Assets, _load_or_estimate, _scripts_for, make_context
    from .verify import verify_output

    started = time.monotonic()
    ctx = make_context(spec, out, timeframe=timeframe, as_of=as_of)
    assets = Assets()
    assets.output = ctx.out_dir / ctx.spec.project.output
    wav = ctx.build / "narration.wav"
    assets.audio_track = wav if wav.exists() else None
    assets.srt = ctx.out_dir / "narration.srt"
    scripts = _scripts_for(ctx.spec, ctx)
    # per-scene spans are re-read, not assumed: a verify that reported no timeline
    # would be describing a video it never looked at, and the same helper the build
    # uses keeps the two accounts of the run identical
    assets.scene_audio = _load_or_estimate(ctx, scripts)
    assets.report = verify_output(ctx, assets, {s.n: s.spoken for s in scripts})
    failed = [c.name for c in assets.report.checks if not c.ok]
    progress.step("verification", assets.report.ok,
                  "ALL PASS" if assets.report.ok else f"{len(failed)} failed: "
                  + ", ".join(failed), time.monotonic() - started)
    manifest["timeframe"] = ctx.spec.timeframe.to_dict() if ctx.spec.timeframe else None
    manifest["report"] = assets.report.to_dict()
    manifest["artifacts"] = {"output": _artifact(assets.output), "srt": _artifact(assets.srt)}
    manifest["timeline"] = _timeline(assets)
    manifest["ok"] = bool(assets.report.ok)
    if assets.output is None or not assets.output.exists():
        # "there is nothing to verify" and "the render failed its checks" are
        # different answers, and an agent should not have to infer which it got
        manifest["ok"] = False
        manifest["failure"] = {
            "kind": "missing",
            "message": f"nothing to verify: no {ctx.spec.project.output} in {ctx.out_dir}",
            "action": "verify",
            "story": manifest["story"],
            "hint": "run a build first, or point `out` at the directory of a previous run",
        }


def _do_build(manifest, progress: Progress, spec: Path, out: Path | None,
              timeframe: Any, as_of: date | None, refresh: bool, action: str,
              only: Iterable[str] | None = None,
              from_stage: str | None = None) -> None:
    from .assembler import run

    if only and from_stage:
        raise ToolError("`only` and `from_stage` are mutually exclusive")
    started = time.monotonic()
    assets = run(spec, only=only if only is not None else _STAGES.get(action),
                 from_stage=from_stage,
                 out_dir=out, timeframe=timeframe, as_of=as_of, refresh=refresh)
    ctx = getattr(assets, "ctx", None)
    if ctx is not None:
        manifest["timeframe"] = (ctx.spec.timeframe.to_dict() if ctx.spec.timeframe else None)
        manifest["spec"] = str(ctx.spec.path or spec)
        manifest["out"] = str(ctx.out_dir)
    manifest["timeline"] = _timeline(assets)
    manifest["artifacts"] = {
        "output": _artifact(assets.output),
        "srt": _artifact(assets.srt),
        "audio": _artifact(assets.audio_track),
        "verify_json": _artifact((ctx.build / "verify.json") if ctx is not None else None),
    }
    if assets.report is not None:
        manifest["report"] = assets.report.to_dict()
    progress.step("rendered"
                  if assets.output else "built",
                  True,
                  f"{sum(s['seconds'] for s in manifest['timeline']):.2f}s"
                  if manifest["timeline"] else action,
                  time.monotonic() - started)
    manifest["ok"] = True
    if assets.report is not None and not assets.report.ok:
        failed = [c.name for c in assets.report.checks if not c.ok]
        manifest["ok"] = False
        manifest["failure"] = {
            "kind": "verification",
            "message": f"{len(failed)} acceptance check(s) failed: " + ", ".join(failed),
            "action": action,
            "story": manifest["story"],
            "hint": "read report.checks for the detail, or `vidkit docs verification`",
        }


def manifest_for(action: str, **kw: Any) -> dict[str, Any]:
    """Run a job and return its manifest — a synonym, for callers that read better."""
    return run_job(action, **kw)


def refused(action: str, *, story: str | Path | None = None,
            out: str | Path | None = None, message: str,
            kind: str = "tool", hint: str = "") -> dict[str, Any]:
    """A manifest for a call that never reached the pipeline.

    Same shape as any other manifest, so a caller's error handling does not have to
    grow a second branch for "it was stopped before it started".
    """
    manifest = _manifest(
        action,
        Path(story).expanduser().resolve() if story else None,
        Path(out).expanduser().resolve() if out else None,
    )
    manifest["failure"] = {
        "kind": kind,
        "message": message,
        "action": action,
        "story": manifest["story"],
        "hint": hint or _hint(message, action),
    }
    return manifest


def actions_help() -> list[dict[str, str]]:
    """The action list as data, so an agent can discover the contract."""
    return [{"action": a, "does": ACTION_HELP[a]} for a in ACTIONS]


def stages_for(action: str) -> Iterable[str] | None:
    """Which pipeline stages an action runs (``None`` = the whole pipeline)."""
    return _STAGES.get(action)
