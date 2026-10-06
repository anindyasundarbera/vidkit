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
               only: list[str] | None = None) -> dict[str, Any]:
    """Run the pipeline and return the artifacts + verification report."""
    from .assembler import run

    spec_path = resolve_spec(spec)
    out_dir = Path(out).expanduser().resolve() if out else None
    try:
        with stdout_to_stderr():
            assets = run(spec_path, only=only or None, out_dir=out_dir)
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
                    "Stages for `only`: data, panels, stills, capture, narration, clips, "
                    "concat, render, verify.",
    )
    def vidkit_build(spec: str | None = None, out: str | None = None,
                     only: list[str] | None = None) -> dict:
        return tool_build(spec, out, only)

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
