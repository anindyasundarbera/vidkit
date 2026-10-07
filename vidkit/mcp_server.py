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
import json
import os
import signal
import sys
from pathlib import Path
from typing import Any, Iterator

from . import __version__
from .errors import ToolError, VidkitError
from .reports import doctor_report, plan_report


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
# Tool functions (pure data in, pure data out)
# --------------------------------------------------------------------------- #
#: Default wall-clock ceiling for ``vidkit_run``. A tool call has no terminal to
#: Ctrl-C and no job object to cancel, so an unbounded render is a client that
#: hangs with no way to ask what happened. Override per call, or with
#: ``VIDKIT_RUN_TIMEOUT`` (seconds; ``0`` disables the ceiling).
RUN_TIMEOUT = 1800.0
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


def tool_build(spec: str | None = None, out: str | None = None,
               only: list[str] | None = None, from_stage: str | None = None,
               refresh: bool = False, progress: bool = False) -> dict[str, Any]:
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

        return run_job("build", story=str(spec_path), out=str(out_dir) if out_dir else None,
                       only=only or None, from_stage=from_stage, refresh=refresh,
                       on_progress=_emit)
    try:
        with stdout_to_stderr():
            assets = run(spec_path, only=only or None, from_stage=from_stage,
                         out_dir=out_dir, refresh=refresh)
    except VidkitError as exc:
        raise ToolError(str(exc)) from exc
    result = _assets_summary(assets)
    result["spec"] = str(spec_path)
    return result


def tool_tts(spec: str | None = None, out: str | None = None) -> dict[str, Any]:
    """(Re)synthesize per-scene narration only."""
    from .assembler import run

    spec_path = resolve_spec(spec)
    out_dir = Path(out).expanduser().resolve() if out else None
    try:
        with stdout_to_stderr():
            assets = run(spec_path, only=["narration"], out_dir=out_dir)
    except VidkitError as exc:
        raise ToolError(str(exc)) from exc
    return {
        "spec": str(spec_path),
        "scenes": len(assets.scene_audio),
        "total_seconds": round(sum(a.seconds for a in assets.scene_audio), 2),
        "wavs": [str(a.path) for a in assets.scene_audio if a.path],
    }


def tool_capture(spec: str | None = None, out: str | None = None) -> dict[str, Any]:
    """(Re)capture the screen recordings only — real UI, with assertions."""
    from .assembler import run

    spec_path = resolve_spec(spec)
    out_dir = Path(out).expanduser().resolve() if out else None
    try:
        with stdout_to_stderr():
            assets = run(spec_path, only=["capture"], out_dir=out_dir)
    except VidkitError as exc:
        raise ToolError(str(exc)) from exc
    return {
        "spec": str(spec_path),
        "captures": {name: str(p) for name, p in assets.capture_stills.items()},
    }


def tool_verify(spec: str | None = None, out: str | None = None) -> dict[str, Any]:
    """Re-run the acceptance checks on the last render."""
    from .assembler import Assets, _scripts_for, make_context
    from .verify import verify_output

    spec_path = resolve_spec(spec)
    ctx = make_context(spec_path, Path(out).expanduser().resolve() if out else None)
    assets = Assets()
    assets.output = ctx.out_dir / ctx.spec.project.output
    assets.audio_track = ctx.build / "narration.wav"
    assets.srt = ctx.out_dir / "narration.srt"
    scripts = _scripts_for(ctx.spec, ctx)
    with stdout_to_stderr():
        assets.report = verify_output(ctx, assets, {s.n: s.spoken for s in scripts})
    return assets.report.to_dict()


def tool_verify_report(spec: str | None = None, out: str | None = None) -> dict[str, Any]:
    """Read the persisted ``verify.json`` from the last build (no re-check)."""
    ctx = None
    from .assembler import make_context

    spec_path = resolve_spec(spec)
    ctx = make_context(spec_path, Path(out).expanduser().resolve() if out else None)
    path = ctx.build / "verify.json"
    if not path.exists():
        raise ToolError(f"no verify.json at {path}; run build or verify first")
    return json.loads(path.read_text(encoding="utf-8"))


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
    Playwright calls, so no interpreter-level invariant is being interrupted. Where
    it is unavailable (a non-main thread, a platform without ``setitimer``) the
    bound is silently not installed — an unbounded build is worse than no build,
    but a broken build is worse than both, and the manifest still reports what it got.
    """
    if seconds <= 0 or not hasattr(signal, "setitimer"):
        yield False
        return
    def _boom(signum, frame):  # noqa: ARG001 - signal handler signature
        raise ToolError(f"`{action}` did not finish within {seconds:g}s; "
                        "the call was stopped so the client stays responsive")
    try:
        previous = signal.signal(signal.SIGALRM, _boom)
    except ValueError:  # not the main thread - no alarm to be had
        yield False
        return
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield True
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

    try:
        with _deadline(_run_timeout(timeout), action):
            return run_job(action, story=story, out=out, timeframe=timeframe, as_of=as_of,
                           refresh=refresh, title=title, slug=slug, only=only,
                           from_stage=from_stage,
                           on_progress=(lambda line: _emit(line)) if progress else None)
    except ToolError as exc:
        # the alarm normally rings inside the job, which turns it into a refusal
        # itself; this catches the case where it rang just outside that, so the
        # caller still gets a manifest instead of an exception
        return refused(action, story=story, out=out, message=str(exc))


def _emit(line: str) -> None:
    """Report progress to stderr when the server is asked to narrate a run."""
    print(line, file=sys.stderr, flush=True)


def tool_actions() -> dict[str, Any]:
    """The job actions an agent can ask for, as data."""
    from .job import ACTIONS, ACTION_HELP, stages_for

    return {"actions": [
        {"action": a, "does": ACTION_HELP[a], "stages": stages_for(a)} for a in ACTIONS
    ]}


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
def build_server(*, host: str = "127.0.0.1", port: int = 8765,
                 streamable_http_path: str = "/mcp"):
    """Create and configure the MCP server (requires the ``mcp`` extra).

    ``host``/``port``/``streamable_http_path`` only matter for the HTTP transports;
    the stdio transport ignores them.
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise SystemExit(
            "The MCP server needs the 'mcp' package. Install it with:\n"
            "    pip install 'vidkit[mcp]'\n"
            f"(import error: {exc})"
        ) from exc

    server = FastMCP(
        name="vidkit",
        instructions=(
            "vidkit produces narrated, captioned screen-recording videos from a YAML "
            "spec plus a data provider. Typical flow: call `vidkit_plan` to preview, "
            "`vidkit_build` to render, then `vidkit_verify` to check the result. Use "
            "`vidkit_doctor` first if a build fails. `vidkit_docs` returns the full "
            "documentation (start with 'concepts', then 'spec-reference')."
        ),
        host=host,
        port=port,
        streamable_http_path=streamable_http_path,
    )

    _register_tools(server)
    _register_resources(server)
    return server


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
    def vidkit_build(spec: str | None = None, out: str | None = None,
                     only: list[str] | None = None, from_stage: str | None = None,
                     refresh: bool = False, progress: bool = False) -> dict:
        return tool_build(spec, out, only, from_stage, refresh, progress)

    @server.tool(
        name="vidkit_tts",
        title="Synthesize narration",
        description="(Re)generate per-scene narration audio and re-measure timings.",
    )
    def vidkit_tts(spec: str | None = None, out: str | None = None) -> dict:
        return tool_tts(spec, out)

    @server.tool(
        name="vidkit_capture",
        title="Capture screen recordings",
        description="(Re)run the Playwright screen captures (the real UI, with assertions).",
    )
    def vidkit_capture(spec: str | None = None, out: str | None = None) -> dict:
        return tool_capture(spec, out)

    @server.tool(
        name="vidkit_verify",
        title="Verify the last render",
        description="Re-run the acceptance checks (runtime window, banned/required phrases, "
                    "caption readability, audio, live captures) against the last output.",
    )
    def vidkit_verify(spec: str | None = None, out: str | None = None) -> dict:
        return tool_verify(spec, out)

    @server.tool(
        name="vidkit_verify_report",
        title="Read the verification report",
        description="Return the persisted verify.json from the last build without re-running checks.",
    )
    def vidkit_verify_report(spec: str | None = None, out: str | None = None) -> dict:
        return tool_verify_report(spec, out)

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
    args = parser.parse_args(argv)

    server = build_server(host=args.host, port=args.port,
                          streamable_http_path=args.path)
    if args.transport == "stdio":
        server.run("stdio")
    elif args.transport == "streamable-http":
        print(f"vidkit MCP server: http://{args.host}:{args.port}{args.path}", file=sys.stderr)
        server.run("streamable-http")
    else:  # sse
        print(f"vidkit MCP server (sse): http://{args.host}:{args.port}/sse", file=sys.stderr)
        server.run("sse")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
