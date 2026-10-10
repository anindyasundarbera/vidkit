"""vidkit as an MCP server.

Exposes vidkit's capabilities as MCP tools and resources so an agent (in an IDE or a chat
client) can plan, build, inspect, and verify videos directly.

Design
------
* **The work lives in plain functions** (`tool_*`) that take and return JSON-able data.
  They never print and never exit, so they are easy to test and to reuse.
* **`build_server()`** wraps each function as an MCP tool with a JSON-Schema input, and
  registers two resources (the documentation index and the spec reference).
* **Transports:** stdio (default — what IDE clients launch) or
  ``--transport streamable-http|sse`` (for a long-lived HTTP server).

Every ``tool_*`` raises :class:`ToolError` for expected failures (bad spec, failed build,
downstream service), which the MCP layer turns into an error result. The tool functions
are unit-tested in ``tests/test_mcp.py``.

Run::

    python -m vidkit.mcp_server            # stdio
    python -m vidkit.mcp_server --transport streamable-http --port 8765
"""

from __future__ import annotations

import contextlib
import io
import ipaddress
import json
import os
import signal
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator

if TYPE_CHECKING:
    from . import studio

from .errors import ToolError, VidkitError
from .provenance import Provenance
from .reports import doctor_report, plan_report

try:  # pragma: no cover - the MCP extra is optional
    from mcp.server.fastmcp import Context
except ImportError:  # pragma: no cover
    try:
        # mcp 2.x renamed FastMCP to MCPServer and moved the class with it.
        from mcp.server.mcpserver import Context
    except ImportError:
        # A placeholder so the module still imports, and so the annotations that mention
        # it still evaluate, when the optional extra is absent. The SDK matches the real
        # class by subclass, so this can only ever be a stand-in for a server that does
        # not exist anyway.
        Context = Any  # type: ignore[assignment,misc]


#: The SDK renamed ``FastMCP`` to ``MCPServer`` in 2.0. ``mcp>=1.20`` is what the
#: extra declares, so both spellings are live and neither may be assumed.
_SERVER_CLASSES = (
    ("mcp.server.fastmcp", "FastMCP"),
    ("mcp.server.mcpserver", "MCPServer"),
)


def _server_class():
    """Return the SDK's app class, whichever name this version of ``mcp`` uses.

    Raises the same ``ImportError`` that importing the SDK would, so the caller
    can tell "no mcp installed" from "mcp installed but unrecognised".
    """
    import importlib

    errors = []
    for module_name, attr in _SERVER_CLASSES:
        try:
            return getattr(importlib.import_module(module_name), attr)
        except (ImportError, AttributeError) as exc:
            errors.append(exc)
    raise ImportError(
        "no MCP app class found — this version of 'mcp' is newer than vidkit knows "
        f"(looked for {', '.join(f'{m}.{a}' for m, a in _SERVER_CLASSES)})"
    ) from errors[0]


# --------------------------------------------------------------------------- #
# stdout protection
# --------------------------------------------------------------------------- #
class _ToStderr(io.TextIOBase):
    """A stdout stand-in that writes to stderr instead.

    The pipeline is chatty (``print()`` progress lines). Over the MCP stdio
    transport stdout carries JSON-RPC, so *any* stray write corrupts the channel.
    Because stderr is safe, tools run with Python-level stdout redirected here.
    ``fileno`` deliberately remains unimplemented so accidental C-level writes
    fail loudly rather than leaking onto the wire.
    """

    def __init__(self, target: io.TextIOBase) -> None:
        self._target = target

    def write(self, s: str) -> int:  # type: ignore[override]
        return self._target.write(s)

    def flush(self) -> None:  # type: ignore[override]
        self._target.flush()

    def writable(self) -> bool:  # type: ignore[override]
        return True

    def isatty(self) -> bool:  # type: ignore[override]
        return False


@contextlib.contextmanager
def stdout_to_stderr() -> Iterator[None]:
    """Redirect Python-level stdout to stderr for the duration of the block."""
    original = sys.stdout
    sys.stdout = _ToStderr(sys.stderr)
    try:
        yield
    finally:
        sys.stdout = original

# --------------------------------------------------------------------------- #
# Default spec: a spec named video.yaml/spec.yaml, preferring examples, then rglob.
# --------------------------------------------------------------------------- #
def default_spec() -> str | None:
    """A best-effort default spec path, so tools can be called with no argument."""
    import glob

    # 1. common explicit locations
    for rel in ("video.yaml", "video.yml", "spec.yaml", "spec.yml"):
        p = Path(rel)
        if p.exists():
            return str(p.resolve())

    # 2. the first spec under examples/
    for pattern in ("examples/*/video.y*ml", "examples/*/spec.y*ml",
                    "vidkit/examples/*/video.y*ml"):
        hits = sorted(glob.glob(pattern))
        if hits:
            return str(Path(hits[0]).resolve())

    # 3. any file under the CWD that looks like a vidkit spec
    for pattern in ("*.y*ml", "*.json", "**/video.y*ml", "**/spec.y*ml"):
        for p in sorted(Path.cwd().rglob(pattern)):
            try:
                head = p.read_text(encoding="utf-8")[:400]
            except OSError:
                continue
            if "project:" in head or '"project"' in head:
                return str(p.resolve())
    return None


def resolve_spec(spec: str | None) -> Path:
    """Resolve an explicit spec or the default; raise if neither exists."""
    if spec:
        p = Path(spec).expanduser()
        if not p.exists():
            raise ToolError(f"spec not found: {p}")
        return p.resolve()
    d = default_spec()
    if d is None:
        raise ToolError("no spec given and no spec found under the current directory")
    return Path(d)


def _assets_summary(assets) -> dict[str, Any]:
    clips = sorted(str(p) for p in assets.stills.values() if str(p).endswith(".mp4"))
    return {
        "output": str(assets.output) if assets.output else None,
        "srt": str(assets.srt) if assets.srt else None,
        "clip_count": len(clips),
        "report": assets.report.to_dict() if assets.report else None,
    }


# --------------------------------------------------------------------------- #
# Studio sessions
# --------------------------------------------------------------------------- #
# A session is what turns a dozen verbs into one sitting: open the set, bring the
# environment up, capture, look at it, capture again, keep the good one, render,
# read the report. The *state* lives in `studio.py`; what lives here is only the
# translation from a tool's arguments to a call on it, plus the one thing a tool
# has that a module does not — a place to report progress to.
#
# Every function below is deliberately thin. If one of them ever computes a fact
# rather than reading it, the fact has two sources and the session stops being
# checkable.
# --------------------------------------------------------------------------- #
_PROJECT: Path | None = None


def _session(session: str, out: str | None) -> "studio.Session":
    """The session with this id — the one this process is holding, if it is.

    The live copy wins over the record on disk, and that is the whole point. A
    sitting holds things that cannot be written down: an open page, a running
    container, a `Context`. The record is a *transcript* of a sitting, not the
    sitting itself, so a tool that read the transcript back on every call would
    get a fresh `Session` with nothing attached to it — and `browser_shot` would
    have no browser to photograph. Ask for the live one first; fall back to disk
    for a session this process never opened, or one whose record it is being asked
    about after the fact.
    """
    from . import studio

    session_id = (session or "").strip()
    if not session_id:
        raise ToolError(
            "a session id is required — `session_open` returns one, and "
            "`session_list` shows the sessions in an output directory")
    live = studio.held(session_id, out) if out else studio.held(session_id)
    if live is not None:
        return live
    return studio.Registry(_implicit_project() if not out else out).load(session_id)


async def _driver(session: str, out: str | None, fn, /, *args, **kwargs):
    """Run ``fn`` for a session on the thread that owns its browser, and await it.

    Playwright's page belongs to the thread that made it, so the call has to go
    there — and because this is an ``async`` tool body the server's loop is free
    while it does. A missing session is resolved *before* the worker is asked, so
    the error is a plain ``no session`` rather than whatever the worker would have
    made of a `None`.
    """
    from . import _loop

    sess = _session(session, out)
    return await _loop.offload(_loop.session, sess, fn, *args, **kwargs)


async def _offloop(fn, /, *args, **kwargs):
    """Await any blocking engine call without sitting on the server's loop."""
    from . import _loop

    return await _loop.offload(fn, *args, **kwargs)


def _implicit_project() -> Path:
    """The project this server, running with no argument, is about.

    A session's record is a file, and a resource URI names only the session — so a
    server that is asked for ``vidkit://sessions/<id>/status`` has to know which
    project to look in. It resolves it the same way a bare tool call does: the
    directory the server was told to serve (``--project``), else the directory of
    the default spec, else the working directory. ``set_project`` pins the first.
    """
    if _PROJECT is not None:
        return _PROJECT
    from . import studio

    d = default_spec()
    return studio.default_out_dir(d) if d else Path.cwd()


def set_project(path: str | Path | None) -> None:
    """Tell the server which project its sessions belong to.

    Without this a resource read resolves the project from the working directory,
    which is right for an IDE started in the story folder and wrong for anything
    else. A resource URI cannot carry it — the URI template's parameters must match
    the handler's exactly — so the server is configured once instead.
    """
    global _PROJECT
    _PROJECT = None if path is None else Path(path).expanduser().resolve()


def _project_dir(spec: str | None, out: str | None) -> Path:
    """Where a session's state belongs: the output directory, or beside the spec."""
    from . import studio

    if out:
        return Path(out).expanduser().resolve()
    if spec:
        return studio.default_out_dir(resolve_spec(spec))
    return _implicit_project()


def tool_session_open(spec: str | None = None, out: str | None = None,
                      story: str | None = None, title: str | None = None,
                      session_id: str | None = None, max_seconds: float = 0.0,
                      max_containers: int = 0, max_tokens: int = 0) -> dict[str, Any]:
    """Open a studio session and return its record.

    A session is a *sitting*: everything a director does between "open the set" and
    "show me the film". It is durable — the record is a JSON file under
    ``<out>/.vidkit/sessions/`` — so a client that comes back after a restart, or
    after its own context was compacted, can call ``session_status`` and find out
    exactly where it was.

    ``max_seconds``, ``max_containers`` and ``max_tokens`` are the budget the sitting
    declares. Wall-clock and container counts are measured against what the work
    actually did and refuse when exhausted; the token budget is *recorded* but not
    enforced, because vidkit cannot see a client's token meter.
    """
    from . import studio

    spec_path = str(resolve_spec(spec)) if spec else (default_spec() or "")
    out_dir = _project_dir(spec if not out else None, out)
    if not spec_path and not story:
        raise ToolError(
            "a session needs a spec or a story to be about — pass `spec`, or `story` "
            "for a folder that contains one")
    sess = studio.open_session(
        out_dir, spec=spec_path, story=story or "", title=title or "",
        session_id=session_id or "", max_seconds=max_seconds,
        max_containers=max_containers, max_tokens=max_tokens)
    return {**studio.status(sess), "out_dir": str(out_dir)}


def tool_session_list(out: str | None = None, spec: str | None = None,
                      include_closed: bool = True) -> dict[str, Any]:
    """List the studio sessions in a project, newest last."""
    from . import studio

    return studio.list_sessions(_project_dir(spec, out), include_closed=include_closed)


def tool_session_status(session: str, out: str | None = None) -> dict[str, Any]:
    """Everything known about one session: takes, environments, artifacts, next step.

    ``next`` is advice, not a command: it says what the record and the disk suggest,
    and it is derived only from those. If it disagrees with your plan, believe your
    plan.
    """
    from . import studio

    return studio.status(_session(session, out))


async def tool_session_close(session: str, out: str | None = None,
                              reason: str | None = None) -> dict[str, Any]:
    """End a sitting: stop its browser, take its containers down, write the record.

    ``problems`` lists anything that would not shut down. A container that survives
    its session is exactly the kind of thing nobody notices until it is filling a
    disk, so it is reported rather than raised.
    """
    from . import studio

    return await _driver(session, out, studio.close_session,
                         _session(session, out), reason or "")


async def tool_session_capture(session: str, out: str | None = None,
                                names: list[str] | None = None) -> dict[str, Any]:
    """Run the spec's captures inside this session, recording every take.

    Unlike a build, a refused assertion here does **not** abort: it is returned in
    the result with the reason. A build must stop (I2); a director must look at what
    came back and decide, which is the difference between a pipeline and a sitting.
    """
    from . import studio

    sess = _session(session, out)

    def run():
        with stdout_to_stderr():
            result = studio.capture_run(sess, names)
        studio.save(sess)
        return result

    return await _offloop(run)


async def tool_session_build(session: str, out: str | None = None,
                              only: list[str] | None = None,
                              from_stage: str | None = None) -> dict[str, Any]:
    """Run the pipeline inside this session, keeping everything it measured.

    The same assembly the CLI runs — there is exactly one code path that turns a
    spec into a film, because the honesty of the result (I7) is only as good as the
    claim that there is only one of them.
    """
    from . import studio

    sess = _session(session, out)
    why = sess.budgets.check()
    if why:
        raise ToolError(why)

    def run():
        with stdout_to_stderr():
            return studio.build(sess, only=only, from_stage=from_stage)

    return await _offloop(run)


def _context_or_none(sess):
    """The session's live ``Context``, or ``None`` when there is no spec to build one.

    Tolerant on purpose: a redactor is a courtesy, not a precondition, and refusing to
    show a command's output because the session has no spec yet would be a worse
    failure than showing it.
    """
    from . import studio

    try:
        return studio.session_context(sess)
    except Exception:      # noqa: BLE001 - see the docstring
        return None


async def tool_session_exec(session: str, label: str, out: str | None = None,
                             stream: bool = False) -> dict[str, Any]:
    """Run one **declared** ``exec:`` step in this session.

    If the step names an environment the session has up, it runs *inside* that
    container; otherwise it runs on the host under whatever backend the step
    declares. Either way the result is the command's real exit code and the real
    length of its output — plus, when ``stream: true``, the transcript itself.

    A step that fails is reported, not fatal, because deciding what a failure means
    is the caller's job. A step that is **refused** executed nothing at all, and says
    so in ``refused``.
    """
    from . import studio

    sess = _session(session, out)
    spec = studio.load_spec(sess)
    step = spec.exec_step(label)
    if step is None:
        declared = ", ".join(e.label for e in spec.exec) or "none"
        raise ToolError(
            f"the spec declares no exec step labelled {label!r} (declared: {declared})")
    if step.environment:
        held = studio.environment_status(sess, step.environment)["held"]
        if held is None:
            raise ToolError(
                f"exec step {label!r} declares `environment: {step.environment}`, which "
                "this session has not started — call env_up first, or the step would "
                "silently run on the host instead of where the spec says")
        if not held.get("alive", True):
            raise ToolError(
                f"environment {step.environment!r} is recorded for this session but its "
                "container is gone, so the step would run somewhere the spec did not "
                "describe — call env_up to start it again")
    why = sess.budgets.check(containers=len(studio.live_refs(sess)))
    if why:
        raise ToolError(why)

    chunks: list[bytes] = []
    # Chunks are collected only when the caller asked to watch. They are the
    # command's real output as it arrived, and they are redacted on the same path
    # the recording uses — a transcript a client is shown is a *published*
    # transcript, and a credential echoed by a failing command would otherwise be
    # published by the tool that exists to be careful (`secrets.redact_bytes`).
    record = chunks.append if stream else None

    def run():
        with stdout_to_stderr():
            if step.environment:
                got = studio.environment_exec(sess, spec, label, on_chunk=record)
            else:
                got = studio.run_step(sess, spec, label, on_chunk=record)
        studio.save(sess)
        return got

    result = await _offloop(run)

    result["streamed"] = bool(stream)
    if stream:
        result["chunks"] = [
            _redact_chunk(sess, c).decode("utf-8", "replace") for c in chunks]
    return result


def _redact_chunk(sess, chunk: bytes) -> bytes:
    """Take the credentials out of a chunk before it is shown to anyone.

    Goes through the session's own ``Context.secrets`` — the same redactor the
    recording uses — so a transcript a client reads and a transcript the build kept
    cannot disagree about what was hidden. Falls back to the chunk unchanged when
    there is no context to redact with, which can only happen before a spec is
    loaded and therefore before there are any secrets to know about.
    """
    secrets = getattr(_context_or_none(sess), "secrets", None)
    return secrets.redact_bytes(chunk) if secrets else chunk


async def _narrate_chunks(ctx, result: dict[str, Any]) -> None:
    """Offer a command's output to the client's progress channel.

    Called only when the caller asked to watch, and only after the command has
    finished. The chunks are the transcript of the command's *own* run — narration
    never re-runs anything, because running a command twice and calling it once is
    the one thing a recording must not do.

    ``info`` and ``report_progress`` are coroutines, so this is a coroutine and the
    tool that calls it is registered ``async``. Every failure is swallowed: a
    progress channel that breaks the work it is reporting on is worse than no
    narration, and the result the caller actually needs is already in the return.
    """
    chunks = result.get("chunks") or []
    total = len(chunks)
    label = str(result.get("label", "command"))
    for i, chunk in enumerate(chunks):
        text = chunk.rstrip("\n") if isinstance(chunk, str) else ""
        if not text:
            continue
        try:
            await ctx.info(text)
            await ctx.report_progress(i + 1, total, label)
        except Exception:      # noqa: BLE001 - narration must never fail the run
            return


# --------------------------------------------------------------------------- #
# Tool functions (pure data in, pure data out)
# --------------------------------------------------------------------------- #
#: Default wall-clock ceiling for ``vidkit_run``. A tool call has no terminal to
#: Ctrl-C and no job object to cancel, so an unbounded render is a client that
#: hangs with no way to ask what happened. Override per call, or with
#: ``VIDKIT_RUN_TIMEOUT`` (seconds; ``0`` disables the ceiling).
RUN_TIMEOUT = 1800.0
async def tool_env_up(session: str, name: str, out: str | None = None) -> dict[str, Any]:
    """Start a declared environment (a container) for this session.

    ``environment_up`` never raises: it returns what became of the container, with
    ``up_error`` set when it did not come up and ``ready`` saying whether it ever
    answered. Both are carried back — a container that started and never became
    ready is the failure mode that looks like success to everything but a readiness
    probe.
    """
    from . import studio

    sess = _session(session, out)
    spec = studio.load_spec(sess)
    why = sess.budgets.check(containers=len(studio.live_refs(sess)) + 1)
    if why:
        raise ToolError(why)
    def run():
        with stdout_to_stderr():
            ref = studio.start_environment(sess, spec, name)
        studio.save(sess)
        return ref

    ref = await _offloop(run)
    return {"session": sess.id, "environment": ref.to_dict(),
            "live": [e.name for e in studio.live_refs(sess)]}


async def tool_env_down(session: str, name: str | None = None,
                         out: str | None = None) -> dict[str, Any]:
    """Stop an environment — or every environment this session holds up.

    Idempotent, and it reports what Docker said rather than what was asked for. A
    container that was already gone reads ``stopped`` with no ``removed`` record:
    the session did not remove it, and saying it did would be the kind of small
    lie that makes the rest of the record unreadable.
    """
    from . import studio

    sess = _session(session, out)

    def run():
        with stdout_to_stderr():
            gone = studio.stop_environment(sess, name or "")
        studio.save(sess)
        return gone

    stopped = await _offloop(run)
    return {"session": sess.id, "stopped": [e.to_dict() for e in stopped],
            "live": [e.name for e in studio.live_refs(sess)],
            "all_removed": all(e.teardown.get("removed") for e in stopped) if stopped
            else True}


async def tool_env_status(session: str, name: str | None = None,
                           out: str | None = None) -> dict[str, Any]:
    """What this session holds, and what the host is running.

    Two answers, deliberately separate. ``held`` is the session's record of what it
    started; ``live`` is ``docker ps``'s own answer about the whole host. Where they
    disagree — a container that died while nobody was looking — the container's
    answer wins, which is why ``alive`` is computed from the host and not from the
    record.
    """
    from . import studio

    sess = _session(session, out)
    return await _offloop(studio.environment_status, sess, name or "")


async def tool_take_list(session: str, capture: str | None = None,
                          out: str | None = None) -> dict[str, Any]:
    """The takes on disk for a session, with their hashes and sizes.

    Read from the filesystem, not from the record — so a take that exists and was
    never recorded shows up in ``unrecorded``, and a recorded take whose file has
    since been deleted does not show up at all. The disk is the register; the record
    is the commentary.
    """
    from . import studio

    sess = _session(session, out)
    return await _offloop(studio.list_takes, sess, capture or "")


async def tool_take_record(session: str, capture: str, take: int = 1,
                            note: str | None = None,
                            out: str | None = None) -> dict[str, Any]:
    """Write down that a take exists: its hash, its size, and where it came from.

    Hashing is the point. Two takes of the same screen with the same name are
    otherwise indistinguishable, and "we used the second one" becomes unfalsifiable.
    Refuses when the file is not there, because a record of a take nobody can open is
    not a record.
    """
    from . import studio

    sess = _session(session, out)

    def run():
        row = studio.record_take(sess, capture, take, note or "")
        studio.save(sess)
        return row

    return {**await _offloop(run), "session": sess.id}


async def tool_take_select(session: str, capture: str, take: int = 1,
                            out: str | None = None) -> dict[str, Any]:
    """Choose which take the film will use — and record the choice.

    Selecting copies the chosen bytes over the capture's base name, reusing the
    capture stage's own rule, so a build cannot tell a selected take from a captured
    one. It changes no picture: the bytes promoted are the bytes a real capture
    produced, and their hash is kept (I7).
    """
    from . import studio

    sess = _session(session, out)

    def run():
        row = studio.select_take(sess, capture, take)
        studio.save(sess)
        return row

    return {**await _offloop(run), "session": sess.id}


async def tool_browser_open(session: str, url: str = "", out: str | None = None,
                             viewport: list[int] | None = None,
                             storage_state: str | None = None) -> dict[str, Any]:
    """Open a real browser on a real page, and keep it open across calls.

    The page stays in this process, so the next tool call drives the page this one
    opened. That is why a browser cannot be resumed after a server restart: it never
    was a record, it is a running thing. ``browser_status`` says whether one is open
    rather than guessing.
    """
    from . import _loop, studio

    sess = _session(session, out)
    spec = studio.with_spec(sess)
    if sess._live.get("page") is not None:
        raise ToolError(
            "this session already has a browser open — call browser_close first, or "
            "use browser_act to drive the one that is open")
    vp = tuple(viewport) if viewport else None

    def run():
        with stdout_to_stderr():
            return studio.browser_open(sess, spec, url, viewport=vp,
                                        storage_state=storage_state or "")

    await _offloop(_loop.session, sess, run)
    return {"session": sess.id, "open": True, "url": url,
            "note": "the page lives in this server process — drive it with "
                    "browser_act, photograph it with browser_shot"}


async def tool_browser_act(session: str, actions: list[dict],
                            out: str | None = None) -> dict[str, Any]:
    """Perform actions on the open page, one step at a time.

    The same action language a spec's ``capture.actions`` uses — so an agent that
    can drive this can write the capture that reproduces it, and vice versa. Each
    step reports ``ok`` and what the page said back, and the run **stops at the first
    refusal**, naming the step: a driver that carried on past a failed click would
    film the wrong page and call it the demo.
    """
    from . import _loop, studio

    sess = _session(session, out)

    def run():
        with stdout_to_stderr():
            got = studio.browser_act(sess, actions)
        studio.save(sess)
        return got

    return {"session": sess.id, **await _offloop(_loop.session, sess, run)}


async def tool_browser_shot(session: str, name: str, take: int = 1,
                             full_page: bool = False, note: str | None = None,
                             out: str | None = None) -> dict[str, Any]:
    """Screenshot the open page, under the capture stage's own naming rule.

    Written to ``_capture/<name>.png`` (or ``<name>.taken.png``), which is exactly
    where a build looks for a capture still — so a shot taken by hand is a shot the
    film can use, and ``take_select`` can promote. Deliberately **not** promoted on
    write: shooting three takes and choosing between them is the whole point, and a
    last-shot-wins rule would answer "which take is in the film?" by accident.
    """
    from . import _loop, studio

    sess = _session(session, out)

    def run():
        with stdout_to_stderr():
            got = studio.browser_shot(sess, name, take=take, full_page=full_page,
                                      note=note or "")
        studio.save(sess)
        return got

    return {**await _offloop(_loop.session, sess, run), "session": sess.id}


async def tool_browser_status(session: str, out: str | None = None) -> dict[str, Any]:
    """Whether this session has a live browser, and where it is.

    Asked of the live objects, not of the record: a browser is not something that can
    be written to JSON and read back, so anything else would be a guess dressed as
    state.
    """
    from . import _loop

    sess = _session(session, out)
    page = await _offloop(_loop.session, sess, lambda: sess._live.get("page"))
    return {
        "session": sess.id,
        "open": page is not None,
        "url": (page.url if page is not None else None),
        "note": ("a browser is open in this server process" if page is not None else
                 "no browser is open — browser_open starts one"),
    }


async def tool_browser_close(session: str, out: str | None = None) -> dict[str, Any]:
    """Close the session's browser, and say where it was when it stopped."""
    from . import _loop, studio

    sess = _session(session, out)

    def run():
        with stdout_to_stderr():
            got = studio.browser_close(sess)
        studio.save(sess)
        return got

    return {**await _offloop(_loop.session, sess, run), "session": sess.id}


async def tool_session_report(session: str, out: str | None = None) -> dict[str, Any]:
    """Read this session's ``verify.json``, with the failed checks pulled out.

    Read from the file rather than from memory, because the file is what a reviewer
    opens — a tool that answered from memory could disagree with the artifact sitting
    beside it. ``failed`` is the short list; ``report`` is all of it.
    """
    from . import studio

    sess = _session(session, out)
    return await _offloop(studio.read_report, sess)


def tool_doctor(spec: str | None = None) -> dict[str, Any]:
    """Check the environment (and a spec, if given)."""
    path = None
    if spec:
        p = Path(spec).expanduser()
        path = p if p.exists() else None
    return doctor_report(path)


def tool_plan(spec: str | None = None) -> dict[str, Any]:
    """Scene plan and estimated runtime — no rendering."""
    return plan_report(resolve_spec(spec))


async def tool_build(spec: str | None = None, out: str | None = None,
                      only: list[str] | None = None, from_stage: str | None = None,
                      refresh: bool = False,
                      progress: bool = False) -> dict[str, Any]:
    """Run the pipeline and return the artifacts + verification report.

    ``only`` selects stages, ``from_stage`` resumes at one and runs the rest, and
    ``refresh`` re-adds the ``data`` stage so the source is asked again. They are
    the same contract as the CLI's ``--only`` / ``--from`` / ``--refresh``: an
    agent that can select stages must also be able to say "do not trust what is
    on disk" (R-B3).
    """
    from .assembler import run

    if only and from_stage:
        raise ToolError("`only` and `from_stage` are mutually exclusive")
    spec_path = resolve_spec(spec)
    out_dir = Path(out).expanduser().resolve() if out else None
    if progress:
        # `progress: true` asks for the run to narrate itself, so it goes through
        # the job contract, which owns that narration. Without it the older, leaner
        # call is kept, so a plain build is byte-for-byte what it always was.
        from .job import run_job

        return await _offloop(
            run_job, "build", story=str(spec_path),
            out=str(out_dir) if out_dir else None,
            only=only or None, from_stage=from_stage, refresh=refresh,
            on_progress=_emit)

    def render():
        try:
            with stdout_to_stderr():
                return run(spec_path, only=only or None, from_stage=from_stage,
                           out_dir=out_dir, refresh=refresh)
        except VidkitError as exc:
            raise ToolError(str(exc)) from exc

    result = _assets_summary(await _offloop(render))
    result["spec"] = str(spec_path)
    return result


async def tool_tts(spec: str | None = None, out: str | None = None) -> dict[str, Any]:
    """(Re)synthesize per-scene narration only."""
    from .assembler import run

    spec_path = resolve_spec(spec)
    out_dir = Path(out).expanduser().resolve() if out else None

    def speak():
        try:
            with stdout_to_stderr():
                return run(spec_path, only=["narration"], out_dir=out_dir)
        except VidkitError as exc:
            raise ToolError(str(exc)) from exc

    assets = await _offloop(speak)
    return {
        "spec": str(spec_path),
        "scenes": len(assets.scene_audio),
        "total_seconds": round(sum(a.seconds for a in assets.scene_audio), 2),
        "wavs": [str(a.path) for a in assets.scene_audio if a.path],
    }


async def tool_capture(spec: str | None = None, out: str | None = None) -> dict[str, Any]:
    """(Re)capture the screen recordings only — real UI, with assertions."""
    from .assembler import run

    spec_path = resolve_spec(spec)
    out_dir = Path(out).expanduser().resolve() if out else None

    def shoot():
        try:
            with stdout_to_stderr():
                return run(spec_path, only=["capture"], out_dir=out_dir)
        except VidkitError as exc:
            raise ToolError(str(exc)) from exc

    assets = await _offloop(shoot)
    return {
        "spec": str(spec_path),
        "captures": {name: str(p) for name, p in assets.capture_stills.items()},
    }


async def tool_verify(spec: str | None = None, out: str | None = None) -> dict[str, Any]:
    """Re-run the acceptance checks on the last render."""
    from .assembler import Assets, _scripts_for, make_context
    from .verify import verify_output

    spec_path = resolve_spec(spec)
    ctx = make_context(spec_path, Path(out).expanduser().resolve() if out else None)

    def check():
        assets = Assets()
        assets.output = ctx.out_dir / ctx.spec.project.output
        assets.audio_track = ctx.build / "narration.wav"
        assets.srt = ctx.out_dir / "narration.srt"
        scripts = _scripts_for(ctx.spec, ctx)
        with stdout_to_stderr():
            assets.report = verify_output(ctx, assets, {s.n: s.spoken for s in scripts})
        return assets.report.to_dict()

    return await _offloop(check)


async def tool_verify_report(spec: str | None = None,
                             out: str | None = None) -> dict[str, Any]:
    """Read the persisted ``verify.json`` from the last build (no re-check)."""
    ctx = None
    from .assembler import make_context

    spec_path = resolve_spec(spec)
    ctx = make_context(spec_path, Path(out).expanduser().resolve() if out else None)
    path = ctx.build / "verify.json"
    if not path.exists():
        raise ToolError(f"no verify.json at {path}; run build or verify first")
    return await _offloop(lambda: json.loads(path.read_text(encoding="utf-8")))


async def tool_provenance(spec: str | None = None, out: str | None = None) -> dict[str, Any]:
    """Read ``provenance.json`` — what this build is, and what made it.

    ``verify.json`` answers "is this honest?"; this answers "which build am I looking
    at?" — the spec hash, the window, the provider hash, and the version of every tool
    that rendered it. It is written by every build, so a missing record means no build
    has happened in this output directory.
    """
    from .assembler import make_context

    spec_path = resolve_spec(spec)
    ctx = make_context(spec_path, Path(out).expanduser().resolve() if out else None)
    record = await _offloop(Provenance.read, ctx.build)
    if record is None:
        raise ToolError(f"no readable provenance.json at {ctx.build}; "
                        "run build first (verify only reads what build wrote)")
    return record


def _run_timeout(timeout: float | None) -> float:
    """The wall-clock ceiling for one ``vidkit_run`` call (``0`` = unbounded)."""
    if timeout is not None:
        return max(0.0, float(timeout))
    try:
        return max(0.0, float(os.environ.get("VIDKIT_RUN_TIMEOUT", RUN_TIMEOUT)))
    except ValueError:
        return RUN_TIMEOUT


@contextlib.contextmanager
def _deadline(seconds: float, action: str):
    """Refuse to let one tool call run forever.

    SIGALRM is the only cancellation a synchronous tool call can offer without a
    thread pool, and it is safe here: the pipeline's own work is subprocess and
    Playwright calls, so no interpreter-level invariant is being interrupted.

    It yields a *reason string* rather than a flag, and the caller puts that in the
    manifest. A bound that could not be installed must not be reported as one that
    was — ``signal.signal`` raises off the main thread, and a platform without
    ``setitimer`` has no alarm at all. ``None`` means the ceiling is live.
    """
    if seconds <= 0:
        yield None        # asked for no ceiling, and got none
        return
    if not hasattr(signal, "setitimer"):
        yield "this platform has no `setitimer`, so no ceiling could be installed"
        return
    def _boom(signum, frame):  # noqa: ARG001 - signal handler signature
        raise ToolError(f"`{action}` did not finish within {seconds:g}s; "
                        "the call was stopped so the client stays responsive")
    try:
        previous = signal.signal(signal.SIGALRM, _boom)
    except ValueError:  # not the main thread - no alarm to be had
        yield ("this call is not on the main thread, so no ceiling could be installed")
        return
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield None
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def tool_run(action: str = "plan", story: str | None = None, out: str | None = None,
             timeframe: str | None = None, as_of: str | None = None,
             refresh: bool = False, title: str | None = None, slug: str | None = None,
             only: list[str] | None = None, from_stage: str | None = None,
             progress: bool = False, timeout: float | None = None) -> dict[str, Any]:
    """Run one job and return its manifest (R-G3).

    The whole point of the job contract: a caller that does not know vidkit can
    call this with an action and a story and read ``ok`` and ``failure`` back,
    instead of choosing among a dozen tools and guessing their order.

    ``timeout`` bounds the call in seconds (default :data:`RUN_TIMEOUT`, or
    ``VIDKIT_RUN_TIMEOUT``; ``0`` disables it). A job that overruns is refused with a
    manifest rather than left hanging — see :func:`_deadline`.
    """
    from .job import refused, run_job

    ceiling = _run_timeout(timeout)
    try:
        with _deadline(ceiling, action) as unbounded:
            manifest = run_job(action, story=story, out=out, timeframe=timeframe,
                               as_of=as_of, refresh=refresh, title=title, slug=slug,
                               only=only, from_stage=from_stage,
                               on_progress=(lambda line: _emit(line)) if progress else None)
    except ToolError as exc:
        # the alarm normally rings inside the job, which turns it into a refusal
        # itself; this catches the case where it rang just outside that, so the
        # caller still gets a manifest instead of an exception
        return refused(action, story=story, out=out, message=str(exc))
    # A run that says it was bounded must have been. This is the one place that knows,
    # so it is the one place that may say. Tri-state on purpose: `None` means no
    # ceiling was asked for, so there is nothing to report about one; `False` means one
    # was asked for and could not be installed, and `timeout_note` says why.
    manifest["timeout_enforced"] = None if ceiling <= 0 else unbounded is None
    if unbounded:
        manifest["timeout_note"] = unbounded
    return manifest


def _emit(line: str) -> None:
    """Report progress to stderr when the server is asked to narrate a run."""
    print(line, file=sys.stderr, flush=True)


def tool_actions() -> dict[str, Any]:
    """The job actions an agent can ask for, as data."""
    from .job import actions_help

    # the same list the CLI's `run --help` and a job's own discovery return, so the
    # two surfaces cannot drift apart
    return {"actions": actions_help()}


def tool_init(story: str, title: str | None = None, slug: str | None = None,
              timeframe: str | None = None, as_of: str | None = None) -> dict[str, Any]:
    """Scaffold a runnable story directory (R-G4)."""
    from .job import run_job

    return run_job("init", story=story, title=title, slug=slug,
                   timeframe=timeframe, as_of=as_of)


def tool_capture_plan(spec: str | None = None) -> dict[str, Any]:
    """What the captures will film, in order, without filming any of it (R-G1).

    An agent that is about to drive a browser needs to know which pages, which
    assertions and which downloads a build will depend on — before it spends a
    minute discovering one was wrong.
    """
    from .assembler import make_context

    path = resolve_spec(spec)
    with stdout_to_stderr():
        # loading a context announces the story and the window, which belongs on
        # stderr — a tool's return value must be the only thing on the wire
        ctx = make_context(path)
    captures = []
    for c in ctx.spec.captures:
        steps = []
        for a in c.actions:
            step = a.kind + (f":{a.selector}" if a.selector else "")
            if a.save_as:
                step += f" -> {a.save_as}"
            if a.assert_ is not None:
                step += "  (checked)"
            steps.append(step)
        captures.append({
            "name": c.name,
            "url": c.url,
            "artifact": c.artifact,
            "storage_state": c.storage_state,
            "films_a_login": c.allow_login,
            "takes": c.take,
            "actions": steps,
            "asserts": _describe_assert(c.assert_),
            "full_page": c.full_page,
        })
    return {
        "spec": str(path),
        "captures": captures,
        "count": len(captures),
        "needs_playwright": bool(captures),
        "order": "artifact-producing captures run last, so the file they save exists",
    }


def _describe_assert(a) -> list[str]:
    """A capture's assertion, in words, so a plan can be read without the spec."""
    if a is None:
        return []
    what = a.selector
    if a.contains is not None:
        return [f"{what} contains {a.contains!r}"]
    if a.equals is not None:
        return [f"{what} equals {a.equals!r}"]
    if a.exists:
        return [f"{what} exists"]
    return [what]


def tool_panel_kinds() -> dict[str, Any]:
    """List the built-in panel kinds a chart may use."""
    from .panels import kinds

    return {"kinds": kinds()}


def _docs_root() -> Path:
    """The ``docs/`` directory next to the package (installed or in a checkout)."""
    return Path(__file__).resolve().parent.parent / "docs"


def _load_modules() -> dict[str, Any] | None:
    """Parse ``docs/modules.yaml`` (best-effort; PyYAML is optional)."""
    path = _docs_root() / "modules.yaml"
    if not path.exists():
        return None
    try:
        import yaml
    except Exception:  # pragma: no cover - optional dependency
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _doc_routes() -> dict[str, str]:
    """Flat map of resolvable doc names -> path relative to ``docs/``.

    Built from ``modules.yaml`` when available (giving both bare stems like
    ``concepts`` and module-qualified names like ``authoring/spec-reference``),
    then augmented with every ``*.md`` under ``docs/`` keyed by stem. This is the
    "module route" that lets an agent address a doc without knowing its folder.
    """
    routes: dict[str, str] = {}
    base = _docs_root()
    mods = _load_modules()
    if mods:
        for module in mods.get("modules", []) or []:
            module_id = module.get("id", "")
            for doc in module.get("docs", []) or []:
                file = doc.get("file")
                if not file:
                    continue
                routes[Path(file).stem] = file
                if module_id:
                    routes[f"{module_id}/{Path(file).stem}"] = file
    if base.exists():
        for p in base.rglob("*.md"):
            routes.setdefault(p.stem, p.relative_to(base).as_posix())
    return routes


def _doc_path(name: str | None) -> Path | None:
    """Route a doc name to a file: ``None``/``readme`` -> index, else the route table."""
    base = _docs_root()
    if not base.exists():
        return None
    target = (name or "README").strip().lstrip("/")
    if target.endswith(".md"):
        target = target[:-3]
    if target.lower() in {"", "readme", "index"}:
        index = base / "README.md"
        return index if index.exists() else None
    for candidate in (base / target, base / f"{target}.md"):
        if candidate.is_file():
            return candidate
    rel = _doc_routes().get(target)
    if rel and (base / rel).is_file():
        return base / rel
    hits = [p for p in base.rglob(f"{target}.md") if p.is_file()]
    return hits[0] if len(hits) == 1 else None


def tool_docs(name: str | None = None) -> str:
    """Return the documentation index, or a named document's Markdown.

    Names are routed through ``docs/modules.yaml``, so a bare stem
    (``concepts``), a module-qualified name (``authoring/spec-reference``), or a
    path all resolve. No name returns the module router (``docs/README.md``).
    """
    path = _doc_path(name)
    if path is None:
        routes = sorted(_doc_routes())
        raise ToolError(
            f"no doc named {name!r}; available: {', '.join(routes) or '(none)'}"
        )
    return path.read_text(encoding="utf-8")


def tool_docs_index() -> dict[str, Any]:
    """The machine-readable module route table (``docs/modules.yaml``)."""
    mods = _load_modules()
    if mods is not None:
        return mods
    return {"version": 1, "routes": _doc_routes()}


# --------------------------------------------------------------------------- #
# Server construction
# --------------------------------------------------------------------------- #
def _is_loopback(host: str) -> bool:
    """Whether ``host`` resolves to a loopback address.

    The HTTP transports expose an agent surface that can drive a browser, execute
    sandboxed commands, and render media. That is a trust boundary: binding a
    non-loopback address with no authentication publishes the surface to the
    network. The stdio transport is unaffected because it never binds a socket.
    """
    if host.lower() in ("localhost", "::1"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        pass
    # A name, not a literal address. Every resolved address must be loopback for
    # the bind to be safe; an unresolvable name resolves to nothing, which must
    # fail closed rather than look loopback.
    try:
        resolved = _resolve_host(host)
    except OSError:
        return False
    return bool(resolved) and all(
        ipaddress.ip_address(a).is_loopback for a in resolved)


def _resolve_host(host: str) -> list[str]:
    """The addresses ``host`` resolves to, for a loopback check (best effort)."""
    try:
        import socket
    except ImportError:  # pragma: no cover - the stdlib always has it
        return []
    try:
        return sorted({i[4][0] for i in socket.getaddrinfo(host, None)})
    except OSError:
        return []


def build_server(*, host: str = "127.0.0.1", port: int = 8765,
                 streamable_http_path: str = "/mcp"):
    """Create and configure the MCP server (requires the ``mcp`` extra).

    ``host``/``port``/``streamable_http_path`` only matter for the HTTP transports;
    the stdio transport ignores them.
    """
    try:
        Server = _server_class()
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise SystemExit(
            "The MCP server needs the 'mcp' package. Install it with:\n"
            "    pip install 'vidkit[mcp]'\n"
            f"(import error: {exc})"
        ) from exc

    server = Server(
        name="vidkit",
        instructions=(
            "vidkit produces narrated, captioned screen-recording videos from a YAML "
            "spec plus a data provider. Typical flow: call `vidkit_plan` to preview, "
            "`vidkit_build` to render, then `vidkit_verify` to check the result. Use "
            "`vidkit_doctor` first if a build fails. `vidkit_docs` returns the full "
            "documentation (start with 'concepts', then 'spec-reference')."
        ),
    )
    _apply_transport_settings(server, host=host, port=port, path=streamable_http_path)

    _register_tools(server)
    _register_resources(server)
    return server


def _apply_transport_settings(server, *, host: str, port: int, path: str) -> None:
    """Carry the HTTP address, on whichever SDK this is.

    ``mcp`` 1.x keeps ``host``/``port``/``streamable_http_path`` on the server's
    ``settings``; 2.x dropped them from the app entirely and takes them as kwargs
    to ``run``. Storing them on the server when 2.x ignores them keeps one launch
    path for both — ``main`` passes them where the transport reads them.
    """
    settings = getattr(server, "settings", None)
    if settings is None:  # pragma: no cover - 2.x has settings too, just not these
        return
    for name, value in (("host", host), ("port", port),
                        ("streamable_http_path", path)):
        if hasattr(settings, name):
            setattr(settings, name, value)


def _register_tools(server) -> None:
    """Register the vidkit tools.

    Schemas are inferred by the MCP SDK from the type hints and defaults, so the
    ``tool_*`` functions' signatures are the single source of truth.
    """

    @server.tool(
        name="vidkit_run",
        title="Run a vidkit job",
        description="Run one job — `init`, `doctor`, `plan`, `build`, `capture`, `tts` "
                    "or `verify` — and return its manifest. `story` is a story folder "
                    "(its video.yaml is found inside) or a spec path; `out` is where "
                    "the run writes; `timeframe` overrides the story's window. The "
                    "manifest always has the same keys, so branch on `ok` and read "
                    "`failure` for a refusal — it never raises for one. `progress: "
                    "true` narrates the run to stderr. `timeout` bounds the call in "
                    "seconds (default 1800; 0 disables) so a long render is refused "
                    "rather than left hanging. This is the one call to use when you "
                    "do not want to choose among the individual tools.",
    )
    def vidkit_run(action: str = "plan", story: str | None = None, out: str | None = None,
                   timeframe: str | None = None, as_of: str | None = None,
                   refresh: bool = False, title: str | None = None,
                   slug: str | None = None, only: list[str] | None = None,
                   from_stage: str | None = None, progress: bool = False,
                   timeout: float | None = None) -> dict:
        return tool_run(action, story, out, timeframe, as_of, refresh, title, slug,
                        only, from_stage, progress, timeout)

    @server.tool(
        name="vidkit_actions",
        title="List the job actions",
        description="The actions `vidkit_run` accepts, what each one does, and which "
                    "pipeline stages each one runs.",
    )
    def vidkit_actions() -> dict:
        return tool_actions()

    @server.tool(
        name="vidkit_init",
        title="Scaffold a new story",
        description="Create a runnable story directory (story.yaml, video.yaml, "
                    "provider.py, narration.md) and return the manifest. Refuses to "
                    "overwrite anything already there.",
    )
    def vidkit_init(story: str, title: str | None = None, slug: str | None = None,
                    timeframe: str | None = None, as_of: str | None = None) -> dict:
        return tool_init(story, title, slug, timeframe, as_of)

    @server.tool(
        name="vidkit_capture_plan",
        title="What the captures will film",
        description="The captures a build would run — URLs, action steps, assertions, "
                    "downloads — without filming any of them. Use it to check a plan "
                    "before spending a minute on a browser.",
    )
    def vidkit_capture_plan(spec: str | None = None) -> dict:
        return tool_capture_plan(spec)

    @server.tool(
        name="vidkit_doctor",
        title="Check the vidkit environment",
        description="Verify ffmpeg/rsvg-convert/playwright/piper and, if a spec is given, "
                    "its validity. Run this first when something fails.",
    )
    def vidkit_doctor(spec: str | None = None) -> dict:
        return tool_doctor(spec)

    @server.tool(
        name="vidkit_plan",
        title="Plan a video (no render)",
        description="Show the scene plan, shots, guards, and estimated runtime for a spec.",
    )
    def vidkit_plan(spec: str | None = None) -> dict:
        return tool_plan(spec)

    @server.tool(
        name="vidkit_build",
        title="Build the video",
        description="Run the full pipeline (capture, charts, narration, render, verify). "
                    "Returns the output path, captions, and the verification report. "
                    "Stages for `only`/`from_stage`: data, panels, stills, capture, "
                    "narration, clips, concat, render, verify. `refresh: true` re-asks "
                    "the data source even when a snapshot would do. `progress: true` "
                    "returns the job manifest and narrates the run to stderr; prefer "
                    "`vidkit_run` for that.",
    )
    async def vidkit_build(spec: str | None = None, out: str | None = None,
                     only: list[str] | None = None, from_stage: str | None = None,
                     refresh: bool = False, progress: bool = False) -> dict:
        return await tool_build(spec, out, only, from_stage, refresh, progress)

    @server.tool(
        name="vidkit_tts",
        title="Synthesize narration",
        description="(Re)generate per-scene narration audio and re-measure timings.",
    )
    async def vidkit_tts(spec: str | None = None, out: str | None = None) -> dict:
        return await tool_tts(spec, out)

    @server.tool(
        name="vidkit_capture",
        title="Capture screen recordings",
        description="(Re)run the Playwright screen captures (the real UI, with assertions).",
    )
    async def vidkit_capture(spec: str | None = None, out: str | None = None) -> dict:
        return await tool_capture(spec, out)

    @server.tool(
        name="vidkit_verify",
        title="Verify the last render",
        description="Re-run the acceptance checks (runtime window, banned/required phrases, "
                    "caption readability, audio, live captures) against the last output.",
    )
    async def vidkit_verify(spec: str | None = None, out: str | None = None) -> dict:
        return await tool_verify(spec, out)

    @server.tool(
        name="vidkit_verify_report",
        title="Read the verification report",
        description="Return the persisted verify.json from the last build without re-running checks.",
    )
    async def vidkit_verify_report(spec: str | None = None, out: str | None = None) -> dict:
        return await tool_verify_report(spec, out)

    @server.tool(
        name="vidkit_provenance",
        title="Read the build provenance",
        description="Return the persisted provenance.json: spec hash, window, provider "
                    "hash, stage list, dataset hashes, and the version of every tool "
                    "that rendered it. Answers 'which build is this?', where "
                    "`verify.json` answers 'is it honest?'.",
    )
    async def vidkit_provenance(spec: str | None = None, out: str | None = None) -> dict:
        return await tool_provenance(spec, out)

    @server.tool(
        name="vidkit_panel_kinds",
        title="List panel kinds",
        description="List the built-in chart/panel kinds a spec chart may reference.",
    )
    def vidkit_panel_kinds() -> dict:
        return tool_panel_kinds()

    @server.tool(
        name="vidkit_docs",
        title="Read vidkit documentation",
        description="Return the documentation index (the module router), or a named document. "
                    "Names are module-routed, so a bare stem ('concepts', 'spec-reference'), "
                    "a module-qualified name ('authoring/spec-reference'), or a path all work.",
    )
    def vidkit_docs(name: str | None = None) -> str:
        return tool_docs(name)

    @server.tool(
        name="vidkit_docs_index",
        title="Documentation route table",
        description="Return the machine-readable module map (docs/modules.yaml): modules, "
                    "their docs, and suggested reading order. Use it to route to the right doc.",
    )
    def vidkit_docs_index() -> dict:
        return tool_docs_index()

    # ----------------------------------------------------------------- studio --
    # A session is a *sitting*, and these are its verbs. They exist because the
    # work that produces a good demo is not a pipeline — it is look, decide, do it
    # again, keep the good one. Each verb here does one step of that and writes
    # down what happened, so a client can stop, come back, and still be somewhere.
    #
    # The `context: Context` parameter lives on the closure rather than on the
    # `tool_*` function: the pure functions stay importable and testable without
    # the MCP extra, and the SDK injects the context into the *registered* callable.
    @server.tool(
        name="session_open",
        title="Open a studio session",
        description="Start a sitting against a spec or a story folder. Returns a session id "
                    "and the record's own account of where it is. `max_seconds`, "
                    "`max_containers` and `max_tokens` are the budget: wall-clock and "
                    "containers are measured and refuse when spent; tokens are recorded only.",
    )
    def session_open(spec: str | None = None, out: str | None = None,
                     story: str | None = None, title: str | None = None,
                     session_id: str | None = None, max_seconds: float = 0.0,
                     max_containers: int = 0, max_tokens: int = 0) -> dict:
        return tool_session_open(spec, out, story, title, session_id,
                                 max_seconds, max_containers, max_tokens)

    @server.tool(
        name="session_list",
        title="List studio sessions",
        description="Every session in a project's output directory, newest last, with its "
                    "state, artifact count and budget use.",
    )
    def session_list(out: str | None = None, spec: str | None = None,
                     include_closed: bool = True) -> dict:
        return tool_session_list(out, spec, include_closed)

    @server.tool(
        name="session_status",
        title="Where this session is",
        description="Everything known about one session in a single call: the record, the "
                    "takes on disk, the takes not yet recorded, what environments are "
                    "running, which artifacts exist, and one `next` sentence derived from "
                    "the record and the disk. Call this after any gap.",
    )
    def session_status(session: str, out: str | None = None) -> dict:
        return tool_session_status(session, out)

    @server.tool(
        name="session_close",
        title="Close a studio session",
        description="End the sitting: close its browser, stop its containers, write its "
                    "record. Anything that would not shut down is reported in `problems`, "
                    "not raised.",
    )
    async def session_close(session: str, out: str | None = None,
                      reason: str | None = None) -> dict:
        return await tool_session_close(session, out, reason)

    @server.tool(
        name="session_capture",
        title="Capture the spec's screens",
        description="Run this spec's captures inside the session, recording every take with "
                    "its hash and size. A refused assertion is *returned*, not fatal — a "
                    "build must stop (I2), a sitting must be able to look at what came back.",
    )
    async def session_capture(session: str, out: str | None = None,
                         names: list[str] | None = None) -> dict:
        return await tool_session_capture(session, out, names)

    @server.tool(
        name="session_build",
        title="Assemble the film in this session",
        description="Run the pipeline inside the session, keeping everything it measured. "
                    "The same assembly the CLI runs — there is exactly one code path from "
                    "spec to film. `only`/`from_stage` narrow the stages.",
    )
    async def session_build(session: str, out: str | None = None,
                      only: list[str] | None = None,
                      from_stage: str | None = None) -> dict:
        return await tool_session_build(session, out, only, from_stage)

    @server.tool(
        name="session_exec",
        title="Run a declared command in this session",
        description="Run one `exec:` step the spec declares — inside its environment when "
                    "the step names one, on the host otherwise. Returns the real exit code "
                    "and output size; `stream: true` also returns the transcript. A failed "
                    "command is reported; a refused one executed nothing.",
    )
    async def session_exec(session: str, label: str, out: str | None = None,
                           stream: bool = False,
                           context: Context | None = None) -> dict:
        result = await tool_session_exec(session, label, out, stream)
        if stream and context is not None:
            await _narrate_chunks(context, result)
        return result

    @server.tool(
        name="session_report",
        title="Read this session's verification report",
        description="Return the persisted verify.json for the session's render, with the "
                    "failed checks pulled to the front. Read from the file, so it is what "
                    "a reviewer would open.",
    )
    async def session_report(session: str, out: str | None = None) -> dict:
        return await tool_session_report(session, out)

    @server.tool(
        name="take_list",
        title="List takes",
        description="What takes exist on disk for a session's captures, with their hashes "
                    "and sizes, which one the film is currently built from, and which "
                    "exist but were never recorded.",
    )
    async def take_list(session: str, capture: str | None = None,
                  out: str | None = None) -> dict:
        return await tool_take_list(session, capture, out)

    @server.tool(
        name="take_record",
        title="Record a take",
        description="Write down that a take exists — its hash, its size, and where it came "
                    "from. Refuses when the file is not there, because a record of a take "
                    "nobody can open is not a record.",
    )
    async def take_record(session: str, capture: str, take: int = 1,
                    note: str | None = None, out: str | None = None) -> dict:
        return await tool_take_record(session, capture, take, note, out)

    @server.tool(
        name="take_select",
        title="Choose which take the film uses",
        description="Promote one take so the next build uses it, and record the choice. It "
                    "copies the chosen bytes over the capture's base name using the capture "
                    "stage's own rule, so a build cannot tell a selected take from a "
                    "captured one. It changes no picture (I7).",
    )
    async def take_select(session: str, capture: str, take: int = 1,
                    out: str | None = None) -> dict:
        return await tool_take_select(session, capture, take, out)

    @server.tool(
        name="env_up",
        title="Start an environment",
        description="Start a declared environment (a container) for this session. Returns "
                    "what became of it: `up_error` when it did not start, and `ready` when "
                    "it never answered. A container that started and was never ready is the "
                    "failure that looks like success to everything but a probe.",
    )
    async def env_up(session: str, name: str, out: str | None = None) -> dict:
        return await tool_env_up(session, name, out)

    @server.tool(
        name="env_down",
        title="Stop environments",
        description="Stop one environment, or every one this session holds, and report what "
                    "Docker actually said. Idempotent: a container that was already gone "
                    "reads as stopped with no removal recorded.",
    )
    async def env_down(session: str, name: str | None = None, out: str | None = None) -> dict:
        return await tool_env_down(session, name, out)

    @server.tool(
        name="env_status",
        title="Environment status",
        description="Two answers side by side: `held` is what this session records as "
                    "started, `live` is `docker ps`'s own answer about the host. `alive` is "
                    "computed from the host, so a container that died behind your back says so.",
    )
    async def env_status(session: str, name: str | None = None,
                   out: str | None = None) -> dict:
        return await tool_env_status(session, name, out)

    @server.tool(
        name="browser_open",
        title="Open a browser",
        description="Open a real Chromium on a real page and keep it open across calls — "
                    "the page lives in this process, so the next tool drives the page this "
                    "one opened. `url` may be empty to open a blank page.",
    )
    async def browser_open(session: str, url: str = "", out: str | None = None,
                     viewport: list[int] | None = None,
                     storage_state: str | None = None) -> dict:
        return await tool_browser_open(session, url, out, viewport, storage_state)

    @server.tool(
        name="browser_act",
        title="Act on the open page",
        description="Perform actions on the open page, one step at a time, in the same "
                    "action language a spec's `capture.actions` uses — so an agent that can "
                    "drive this can write the capture that reproduces it. The run stops at "
                    "the first refusal and names the step.",
    )
    async def browser_act(session: str, actions: list[dict],
                    out: str | None = None) -> dict:
        return await tool_browser_act(session, actions, out)

    @server.tool(
        name="browser_shot",
        title="Screenshot the open page",
        description="Photograph the open page into `_capture/<name>.png` under the capture "
                    "stage's own naming rule, so a shot taken by hand is a shot the film can "
                    "use. Deliberately not promoted on write: use take_select to choose.",
    )
    async def browser_shot(session: str, name: str, take: int = 1,
                     full_page: bool = False, note: str | None = None,
                     out: str | None = None) -> dict:
        return await tool_browser_shot(session, name, take, full_page, note, out)

    @server.tool(
        name="browser_status",
        title="Is a browser open?",
        description="Whether this session has a live browser, and the URL it is on. Asked "
                    "of the live objects: a browser cannot be written to JSON and read back, "
                    "so anything else would be a guess dressed as state.",
    )
    async def browser_status(session: str, out: str | None = None) -> dict:
        return await tool_browser_status(session, out)

    @server.tool(
        name="browser_close",
        title="Close the browser",
        description="Close the session's browser and report where it was when it stopped.",
    )
    async def browser_close(session: str, out: str | None = None) -> dict:
        return await tool_browser_close(session, out)


def _register_resources(server) -> None:
    @server.resource("vidkit://docs/index", name="vidkit docs index",
                     description="The documentation module router (table of contents).",
                     mime_type="text/markdown")
    def docs_index() -> str:
        return tool_docs(None)

    @server.resource("vidkit://docs/modules", name="vidkit docs modules",
                     description="The machine-readable module route table.",
                     mime_type="application/json")
    def docs_modules() -> str:
        return json.dumps(tool_docs_index(), indent=1)

    @server.resource("vidkit://actions", name="vidkit job actions",
                     description="The job actions vidkit_run accepts, and their stages.",
                     mime_type="application/json")
    def actions() -> str:
        return json.dumps(tool_actions(), indent=1)

    @server.resource("vidkit://docs/{name}", name="vidkit doc",
                     description="A named vidkit document as Markdown (module-routed).",
                     mime_type="text/markdown")
    def doc(name: str) -> str:
        return tool_docs(name)

    @server.resource("vidkit://sessions/{session}/status",
                     name="vidkit session status",
                     description="One studio session's whole state: record, takes, "
                                 "environments, artifacts, and the next step.",
                     mime_type="application/json")
    def session_status(session: str) -> str:
        # Not `async`: `tool_session_status` reads the record and returns, so awaiting
        # it would be awaiting a dict. A resource that reaches a *live* session has to
        # await, because the live path hops threads — this one does not, and says so.
        return json.dumps(tool_session_status(session, None), indent=1)

    @server.resource("vidkit://sessions/{session}/takes",
                     name="vidkit session takes",
                     description="The takes on disk for a session, with hashes and sizes.",
                     mime_type="application/json")
    async def session_takes(session: str) -> str:
        return json.dumps(await tool_take_list(session, None, None), indent=1)

    @server.resource("vidkit://sessions/{session}/report",
                     name="vidkit session report",
                     description="This session's persisted verify.json, failed checks first.",
                     mime_type="application/json")
    async def session_report(session: str) -> str:
        return json.dumps(await tool_session_report(session, None), indent=1)


# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="vidkit-mcp", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--transport", default="stdio",
                        choices=["stdio", "streamable-http", "sse"],
                        help="MCP transport (default: stdio, for IDE clients)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--path", default="/mcp", help="HTTP path for streamable-http")
    parser.add_argument("--expose", action="store_true",
                        help="permit binding --host to a non-loopback address over an "
                             "HTTP transport; without this, a non-loopback --host is "
                             "refused because the surface is unauthenticated")
    parser.add_argument("--project", default=None,
                        help="the folder whose studio sessions this server serves; "
                             "defaults to the directory of the default spec, so "
                             "resources and tools resolve the same project")
    args = parser.parse_args(argv)

    if args.transport != "stdio" and not args.expose and not _is_loopback(args.host):
        print(
            f"refusing to bind an unauthenticated MCP HTTP transport to "
            f"{args.host!r}: the agent surface can drive a browser and execute "
            f"commands, so non-loopback binding is disabled by default. Re-run with "
            f"--host 127.0.0.1, or pass --expose if this exposure is deliberate.",
            file=sys.stderr,
        )
        return 2

    set_project(args.project)
    server = build_server(host=args.host, port=args.port,
                          streamable_http_path=args.path)
    if args.transport == "stdio":
        server.run("stdio")
    else:
        where = (f"http://{args.host}:{args.port}{args.path}"
                 if args.transport == "streamable-http"
                 else f"http://{args.host}:{args.port}/sse")
        print(f"vidkit MCP server ({args.transport}): {where}", file=sys.stderr)
        server.run(args.transport, **_transport_kwargs(server, args))
    return 0


def _transport_kwargs(server, args) -> dict:
    """The HTTP address, passed only to the SDK that takes it as an argument.

    ``mcp`` 1.x reads it from ``server.settings`` (already set by ``build_server``)
    and its ``run`` accepts no such kwargs; 2.x takes them here and ignores the
    settings. Passing them unconditionally would be a ``TypeError`` on 1.x.
    """
    if hasattr(getattr(server, "settings", None), "host"):  # 1.x owns them
        return {}
    kwargs = {"host": args.host, "port": args.port}
    if args.transport == "streamable-http":
        kwargs["streamable_http_path"] = args.path
    return kwargs


if __name__ == "__main__":
    raise SystemExit(main())
