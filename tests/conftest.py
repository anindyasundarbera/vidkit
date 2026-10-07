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

Two capability markers live here, and they are independent on purpose:

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

The four are applied independently and must stay that way. An earlier version
of this file returned early once the render tools were present, which silently
disabled the sandbox marker on exactly the machines where it mattered least —
the CI runner has ffmpeg and no usable bwrap. That is defect G one layer up;
capability markers do not compose by implication.
"""

from __future__ import annotations

import asyncio
import inspect
import shutil
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
    for item in items:
        # five independent conditions, five independent skips: each is a
        # separate fact about the host and none implies another
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


def pytest_unconfigure(config) -> None:
    shutil.rmtree(_SCRATCH, ignore_errors=True)


@pytest.fixture(scope="session")
def scratch() -> Path:
    """A directory ffmpeg may write to, unlike the system temp dir."""
    _SCRATCH.mkdir(exist_ok=True)
    return _SCRATCH
