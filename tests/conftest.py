"""Shared test fixtures.

One fixture exists for a reason worth stating. On this machine ffmpeg is the
confined snap build, and snap's interface policy lets it read and write the
user's home but **not** ``/tmp``. pytest's default ``--basetemp`` lives under
``/tmp``, so any test that asks ffmpeg to write a file fails with
``Could not open file`` — not because ffmpeg is broken, but because it is not
allowed to see that path.

``tmp_path`` is therefore redirected into a scratch directory beside the repo,
which is both writable by the snap and cleaned up on exit. Tests that shell out
to ffmpeg stay honest: they run against the same build a user would.

Six capability markers live here, and they are independent on purpose:

``needs_render``
    ffmpeg and rsvg-convert are installed. Absent in the lean CI job.

``needs_sandbox``
    a command declared ``backend: bubblewrap`` will actually run confined. This
    is *probed*, not looked up, because an installed ``bwrap`` that the kernel
    refuses is not a sandbox — see ``vidkit.exec.bwrap_available``.

``needs_docker``
    a container can actually *run* here, which is a stricter question than
    whether ``docker(1)`` is on ``PATH``. Probed by running one, for the reason
    above and for the reason ``exec-guide.md`` gives: Docker's "available" has
    three meanings and only the third one is the one a spec means.

``needs_playwright``
    Playwright is importable *and* a browser binary has been downloaded. Both
    halves matter: the Python package installs in a second, the ~170 MB browser
    download does not, and a test that says "drive a browser" fails on an
    un-downloaded Chromium with an error that reads like an engine bug.

``needs_mcp``
    the ``mcp`` package imports, so the server can be driven over its own
    transport. It is a declared extra, but not one ``.[dev]`` pulls in, so the
    lean job does not have it.

``needs_pre_312_python``
    an interpreter below 3.12 is present *and was proved by compiling* to reject
    a PEP 701 f-string while accepting legal ones. The rule lives in the
    tokenizer, so no 3.12+ interpreter can see it, and ``PATH`` is deliberately
    narrowed in the lean job — hence the probe compiles rather than looks up.

The six are applied independently and must stay that way. An earlier version
of this file returned early once the render tools were present, which silently
disabled the sandbox marker on exactly the machines where it mattered least —
the CI runner has ffmpeg and no usable bwrap. That is defect G one layer up;
capability markers do not compose by implication.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

_SCRATCH = Path(__file__).resolve().parent.parent / ".pytest-tmp"


def arun(awaitable_or_fn, *args, **kwargs):
    """Drive a coroutine (or coroutine function) to completion, with no extra dependency.

    A tool whose body hops off the event loop is an ``async def``, and a coroutine
    called from a sync test is a coroutine object, not an answer — so the test
    "passes" an assertion about an exception that was never raised. Awaiting it is
    what makes the test a test (defect 57 / D57).

    ``anyio`` would do this too, but it is not a declared dependency of anything
    vidkit installs: it arrives with ``mcp``, and the lean core installs neither.
    The suite therefore cannot import it, and four modules did, so the ``pytest``
    CI jobs died at *collection* on a missing module rather than on an assertion —
    the tests were green locally purely because ``mcp`` happened to be present.
    ``asyncio.run`` is stdlib and drives the same callables: ``_loop.offload``
    fast-paths through when there is no loop, and anyio's own default backend is
    asyncio, so the ``mcp`` memory transport runs under it unchanged.
    """
    call = awaitable_or_fn if inspect.isawaitable(awaitable_or_fn) else None
    if call is None:
        coro = awaitable_or_fn(*args, **kwargs)
    else:
        coro = awaitable_or_fn
    if not inspect.isawaitable(coro):
        return coro
    return asyncio.run(coro)


def mcp_sdk():
    """The MCP app class, whichever name this version of ``mcp`` gives it.

    ``FastMCP`` in 1.x, ``MCPServer`` in 2.x. Imported lazily so a lean install
    without ``mcp`` can still import this module.
    """
    from vidkit.mcp_server import _server_class

    return _server_class()


def _low_level(server):
    """The low-level ``Server`` inside the SDK's app, whichever version this is.

    Both spellings are *private*, which is the seam defect 27 was caught on. It
    is confined to this one function so the exit proof itself uses only stable
    API: ``Server.run`` and ``create_client_server_memory_streams`` have the same
    signature in 1.27.2 and 2.3.0, while the attribute that reaches the server
    from the app does not.
    """
    for attr in ("_mcp_server", "_lowlevel_server"):   # mcp 1.x, then 2.x
        got = getattr(server, attr, None)
        if got is not None:
            return got
    raise RuntimeError(f"no low-level MCP server on {type(server).__name__} "
                       f"(mcp {__import__('importlib.metadata', fromlist=['x']).version('mcp')})")


def mcp_is_error(answered) -> bool:
    """``CallToolResult.isError``, under either spelling (2.x renamed it)."""
    return bool(getattr(answered, "isError", getattr(answered, "is_error", False)))


def mcp_text(answered) -> str:
    """The first text block of a tool result, both versions alike."""
    return answered.content[0].text


def mcp_tool_text(out) -> str:
    """The text of an in-process ``server.call_tool(...)`` result, both SDK majors.

    These two return *different shapes*, which is why the tests cannot index the
    result directly: ``mcp`` 1.x hands back ``list[ContentBlock]``, while 2.x wraps
    it in a ``CallToolResult``. Only the wrapper differs; the first block is text
    in both.
    """
    if hasattr(out, "content"):        # mcp 2.x: CallToolResult
        out = out.content
    return out[0].text


def mcp_resource_text(out) -> str:
    """The text of an in-process ``server.read_resource(...)`` result, both majors.

    1.x returns a bare sequence of ``ReadResourceContents``; 2.x wraps it in a
    ``ReadResourceResult``. The *element* shape is the same in both, so unwrapping
    the sequence is the whole job.
    """
    parts = list(out.contents) if hasattr(out, "contents") else list(out)
    part = parts[0]
    return getattr(part, "content", None) or part.text


def mcp_resource_template_uri(template) -> str:
    """``ResourceTemplate.uriTemplate``, under either spelling (2.x renamed it)."""
    return getattr(template, "uriTemplate", None) or template.uri_template


def mcp_session(server):
    """A client session wired to ``server`` over the in-memory transport.

    ``mcp.shared.memory.create_connected_server_and_client_session`` used to do
    this, and the exit proof used it — but it was removed in ``mcp`` 2.x, and the
    extra declares ``mcp>=1.20``, so CI (which resolved 2.3.0) failed while every
    local run passed on 1.27.2. Two facts made that the wrong dependency:

    * ``server.call_tool`` is **in-process** — it goes straight to the tool
      manager and never touches the wire — so proving the tools work *over MCP*
      needs a session, not a shortcut;
    * only the *private* attribute that reaches the low-level ``Server`` from the
      app changed between versions (``_mcp_server`` → ``_lowlevel_server``).
      ``Server.run``, ``create_client_server_memory_streams`` and
      ``ClientSession`` are all present and identically shaped in both.

    So this rebuilds the helper on the stable pieces and keeps the one private
    lookup in ``_low_level``. It is an async context manager, to be driven by
    ``arun`` from a sync test.
    """
    import contextlib

    @contextlib.asynccontextmanager
    async def _session():
        import anyio
        from mcp.client.session import ClientSession
        from mcp.shared.memory import create_client_server_memory_streams

        async with create_client_server_memory_streams() as (client_side, server_side):
            client_read, client_write = client_side
            server_read, server_write = server_side
            raw = _low_level(server)
            async with anyio.create_task_group() as tg:
                tg.start_soon(lambda: raw.run(server_read, server_write,
                                              raw.create_initialization_options()))
                try:
                    client = ClientSession(read_stream=client_read,
                                           write_stream=client_write)
                    async with client:
                        await client.initialize()
                        yield client
                finally:
                    tg.cancel_scope.cancel()

    return _session()

#: The external tools a *render* needs. The lean ``pytest`` CI job installs none
#: of them — it checks Python logic, which is fast and always available — while
#: the ``build hello-world end to end`` job installs exactly these and renders
#: for real. A test that reaches the pipeline says so with ``needs_render``, or
#: it fails in CI for a reason that has nothing to do with the code under test.
RENDER_TOOLS = ("ffmpeg", "rsvg-convert")

_HAVE_RENDER = all(shutil.which(t) for t in RENDER_TOOLS)

#: The sandbox a spec gets when it does not say otherwise. Unlike the render
#: tools, this one is deliberately **probed rather than looked up**: an
#: installed ``bwrap`` that the kernel refuses is not an available sandbox, and
#: on Ubuntu 24.04 that is the normal state of affairs. A test that builds a
#: spec which declares ``backend: bubblewrap`` — the default — needs the sandbox
#: to be genuinely usable, not merely present on ``PATH``.
def _probe_sandbox() -> bool:
    try:
        from vidkit.exec import bwrap_available
    except Exception:  # pragma: no cover - an unimportable engine is its own failure
        return False
    ok, _ = bwrap_available()
    return ok


_HAVE_SANDBOX = _probe_sandbox()


#: Whether a container can actually run here. Probed, never looked up: on a
#: machine with the client installed and the daemon down, ``which docker`` says
#: yes and every declared command fails — the same lie ``bwrap_available`` was
#: rewritten to stop telling.
def _probe_docker() -> bool:
    try:
        from vidkit.exec import docker_available
    except Exception:  # pragma: no cover
        return False
    ok, _ = docker_available()
    return ok


_HAVE_DOCKER = _probe_docker()


#: Whether a *browser* can actually be driven here. Two facts, not one: the
#: Playwright Python package imports, and a Chromium has been downloaded. The
#: package installs from a wheel in a second; the browser is a ~170 MB fetch
#: that a fresh checkout does not have, and the test that discovers this is the
#: *first* one that drives a browser, with a message that reads like a bug in us.
def _probe_playwright() -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:  # pragma: no cover - not installed is the normal lean case
        return False
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            browser.close()
        return True
    except Exception:
        return False


_HAVE_PLAYWRIGHT = _probe_playwright()


#: The MCP package imports, so a test can speak to the server over its own transport.
#: It is a *declared* extra (``.[mcp]``), but it is not part of ``.[dev]``, and the
#: lean `pytest` job installs only ``.[dev]``. Without this probe those tests die at
#: *import* — a collection error, not a failure — on a machine where the engine is
#: entirely healthy. That is the same shape of blindness as ``needs_playwright``, so
#: it gets the same treatment rather than an accidental dependency on a developer's
#: machine having installed the extra.
def _probe_mcp() -> bool:
    import importlib.util

    return importlib.util.find_spec("mcp") is not None


_HAVE_MCP = _probe_mcp()


#: Raw source text that is legal in every language version and illegal before 3.12,
#: established by compiling each case. The point is the tokens an *old* tokenizer
#: has to reject, so do not "tidy" these into f-strings.
_PEP701_ILLEGAL = (
    'x = f"{f"{1}"}"\n',            # nested literal reuses the outer quote
    "d = {}\nx = f'{d['k']}'\n",    # subscript key reuses the outer quote
)
_PEP701_LEGAL = (
    """x = f"{f' at {1!r}'}"\n""",    # nested f-string, *different* quote
    'a = 0\nx = f"{a:02d}"\n',      # the shape a bad scan flagged as illegal
    'a = b = c = 0\nx = f"{a}-{b:02d}-{c:02d}"\n',
    'a = None\nx = f"{a!r}"\n',
    'd = {}\nx = f"""{d["k"]}"""\n',  # same quote, but triple-delimited
)


def _candidate_interpreters() -> list[str]:
    """Every plausible pre-3.12 interpreter path, without trusting ``PATH``.

    ``shutil.which`` consults ``PATH`` alone, and the lean CI job narrows ``PATH``
    to the handful of tools the engine shells out to — so a probe built on ``which``
    reports "no old interpreter here" on a host that has one, and the guard against
    PEP 701 silently stops guarding. Absolute well-known locations are checked too,
    which is what makes the lean run measure the *host* rather than the ``PATH``.
    """
    names = ("python3.10", "python3.11")
    found: list[str] = []
    for name in names:
        which = shutil.which(name)
        if which:
            found.append(which)
        for base in ("/usr/bin", "/usr/local/bin", "/bin", os.path.expanduser("~/.local/bin")):
            path = os.path.join(base, name)
            if os.path.isfile(path) and os.access(path, os.X_OK):
                found.append(path)
    seen: set[str] = set()
    unique = []
    for path in found:
        real = os.path.realpath(path)
        if real not in seen:
            seen.add(real)
            unique.append(path)
    return unique


@functools.lru_cache(maxsize=1)
def _find_pre_312_interpreter() -> str:
    """A pre-3.12 interpreter this host can really run, or ``""``.

    "Found on disk" is not the question — a name can point at a broken symlink, a
    wrapper for a managed toolchain that refuses, or a real interpreter that cannot
    import its own stdlib. The candidate has to *detect the defect* to count, so
    each one is asked to compile the illegal shape and accept the legal one. A path
    that cannot answer is not evidence, and a check that cannot fail is worse than
    no check — the same rule the markers were built on.
    """
    for exe in _candidate_interpreters():
        try:
            if _compiles_with(exe, _PEP701_ILLEGAL[0]):
                continue  # accepts the illegal shape, so it cannot detect the defect
            if not all(_compiles_with(exe, src) for src in _PEP701_LEGAL):
                continue  # rejects legal code, so it would cry wolf
        except OSError:  # pragma: no cover - candidate that cannot be executed
            continue
        return exe
    return ""


def _compiles_with(exe: str, source: str) -> bool:
    """Whether ``exe``'s compiler accepts ``source``. False on any failure to run."""
    handle = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False)
    try:
        with handle:
            handle.write(source)
        proc = subprocess.run([exe, "-m", "py_compile", handle.name],
                              capture_output=True, text=True)
        return proc.returncode == 0
    except OSError:  # pragma: no cover - candidate vanished between probe and use
        return False
    finally:
        try:
            os.unlink(handle.name)
        except OSError:  # pragma: no cover
            pass


_PRE_312_PYTHON = _find_pre_312_interpreter()

#: Whether a pre-3.12 interpreter is available. Exported so ``tests/test_hygiene.py``
#: can skip *and say so* instead of asserting: a host with only 3.12+ cannot detect
#: PEP 701 at all, and the honest response is to skip the claim, not to fake it.
HAVE_PRE_312_PYTHON = bool(_PRE_312_PYTHON)


def pytest_configure(config) -> None:
    _SCRATCH.mkdir(exist_ok=True)
    config.option.basetemp = str(_SCRATCH)
    config.addinivalue_line(
        "markers",
        "needs_render: reaches the pipeline, so it needs ffmpeg and rsvg-convert")
    config.addinivalue_line(
        "markers",
        "needs_sandbox: declares `backend: bubblewrap`, so it needs a sandbox "
        "that can actually run (probing bwrap, not merely finding it on PATH)")
    config.addinivalue_line(
        "markers",
        "needs_docker: declares an `environment:` and `backend: docker`, so it "
        "needs a container to actually run (probing with `docker run`, not "
        "merely finding docker on PATH)")
    config.addinivalue_line(
        "markers",
        "needs_playwright: drives a real browser, so it needs the Playwright "
        "package *and* a downloaded Chromium (probing with launch(), not "
        "merely finding the package)")
    config.addinivalue_line(
        "markers",
        "needs_mcp: speaks MCP to the server over its own transport, so it "
        "needs the `mcp` extra installed (a declared extra, but not one of "
        "the ones `.[dev]` pulls in)")
    config.addinivalue_line(
        "markers",
        "needs_pre_312_python: compiles source with an interpreter below 3.12, "
        "because the PEP 701 f-string quoting rule lives in the tokenizer and "
        "cannot be seen from 3.12+ (probed by compiling, not by finding a name)")


def pytest_collection_modifyitems(config, items) -> None:
    render_skip = pytest.mark.skip(
        reason="render toolchain not installed (ffmpeg + rsvg-convert)")
    sandbox_skip = pytest.mark.skip(
        reason="no usable sandbox on this host (bwrap missing or blocked)")
    docker_skip = pytest.mark.skip(
        reason="no usable docker on this host (client, daemon or runtime)")
    playwright_skip = pytest.mark.skip(
        reason="no usable Playwright on this host (package or Chromium missing)")
    mcp_skip = pytest.mark.skip(
        reason="mcp extra not installed (needed to drive the server's transport)")
    pre_312_skip = pytest.mark.skip(
        reason="no interpreter below 3.12 on this host (PEP 701 is undetectable here)")
    for item in items:
        # six independent conditions, six independent skips: each is a separate
        # fact about the host and none implies another
        if not _HAVE_RENDER and "needs_render" in item.keywords:
            item.add_marker(render_skip)
        if not _HAVE_SANDBOX and "needs_sandbox" in item.keywords:
            item.add_marker(sandbox_skip)
        if not _HAVE_DOCKER and "needs_docker" in item.keywords:
            item.add_marker(docker_skip)
        if not _HAVE_PLAYWRIGHT and "needs_playwright" in item.keywords:
            item.add_marker(playwright_skip)
        if not _HAVE_MCP and "needs_mcp" in item.keywords:
            item.add_marker(mcp_skip)
        if not HAVE_PRE_312_PYTHON and "needs_pre_312_python" in item.keywords:
            item.add_marker(pre_312_skip)


def pytest_unconfigure(config) -> None:
    shutil.rmtree(_SCRATCH, ignore_errors=True)


@pytest.fixture(scope="session")
def scratch() -> Path:
    """A directory ffmpeg may write to, unlike the system temp dir."""
    _SCRATCH.mkdir(exist_ok=True)
    return _SCRATCH
