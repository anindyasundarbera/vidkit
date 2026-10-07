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
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

_SCRATCH = Path(__file__).resolve().parent.parent / ".pytest-tmp"

#: The external tools a *render* needs. The lean ``pytest`` CI job installs none
#: of them — it checks Python logic, which is fast and always available — while
#: the ``build hello-world end to end`` job installs exactly these and renders
#: for real. A test that reaches the pipeline says so with ``needs_render``, or
#: it fails in CI for a reason that has nothing to do with the code under test.
RENDER_TOOLS = ("ffmpeg", "rsvg-convert")

_HAVE_RENDER = all(shutil.which(t) for t in RENDER_TOOLS)


def pytest_configure(config) -> None:
    _SCRATCH.mkdir(exist_ok=True)
    config.option.basetemp = str(_SCRATCH)
    config.addinivalue_line(
        "markers",
        "needs_render: reaches the pipeline, so it needs ffmpeg and rsvg-convert")


def pytest_collection_modifyitems(config, items) -> None:
    if _HAVE_RENDER:
        return
    skip = pytest.mark.skip(reason="render toolchain not installed (ffmpeg + rsvg-convert)")
    for item in items:
        if "needs_render" in item.keywords:
            item.add_marker(skip)


def pytest_unconfigure(config) -> None:
    shutil.rmtree(_SCRATCH, ignore_errors=True)


@pytest.fixture(scope="session")
def scratch() -> Path:
    """A directory ffmpeg may write to, unlike the system temp dir."""
    _SCRATCH.mkdir(exist_ok=True)
    return _SCRATCH
