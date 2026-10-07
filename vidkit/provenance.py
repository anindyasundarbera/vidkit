"""What was built, from what, by what — the build's own identity (R-F8).

A rendered video claims things. ``verify.json`` says the claims *hold*; this
module says what they were *made from*: the spec's bytes, the window, the
provider's source, the tools that did the rendering, and when. Without it, a
``.mp4`` found on disk a year later is an assertion with no author.

The distinction that matters: ``verify.json`` answers **"is this honest?"**, and
``provenance.json`` answers **"what is this?"**. Both are written by every build,
and neither can answer the other's question.

Everything here is measured, never assumed. A tool that is not installed is
recorded as absent rather than omitted, because "we did not check" and "it was
not there" are different facts and only the second one is useful later.
"""

from __future__ import annotations

import json
import platform
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import __version__
from .snapshot import file_digest

#: Written beside ``verify.json`` in the build directory.
PROVENANCE_FILE = "provenance.json"

#: Bumped when the *shape* changes; a reader can then refuse a file it does not
#: understand instead of silently misreading it.
SCHEMA = 1

#: The external tools a render can touch. Everything on this list is probed;
#: what is absent is recorded as absent.
TOOLS = ("ffmpeg", "ffprobe", "rsvg-convert", "pdftoppm", "gs")

#: The first line of each tool's version banner, for the tools we read a version
#: out of. `ffprobe` reports its build through the same ffmpeg banner, and `gs`
#: prints its version only to stdout.
_VERSION_ARGS: dict[str, tuple[str, ...]] = {
    "ffmpeg": ("-version",),
    "ffprobe": ("-version",),
    "rsvg-convert": ("--version",),
    "pdftoppm": ("-v",),
    "gs": ("--version",),
}
_VERSION_PATTERNS = {
    "ffmpeg": re.compile(r"^ffmpeg version (\S+)"),
    "ffprobe": re.compile(r"^ffmpeg version (\S+)"),
    "rsvg-convert": re.compile(r"version ([\d.]+)"),
    "pdftoppm": re.compile(r"version ([\d.]+)"),
    "gs": re.compile(r"([\d.]+)"),
}


@dataclass
class Tool:
    """One external program, measured rather than assumed."""

    name: str
    present: bool
    version: str | None = None
    path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "present": self.present,
                "version": self.version, "path": self.path}


@dataclass
class Provenance:
    """The identity of one build."""

    action: str
    spec: str | None
    spec_sha256: str | None
    timeframe: dict[str, Any] | None
    started: float
    ended: float
    vidkit: str = __version__
    python: str = field(default_factory=lambda: platform.python_version())
    platform: str = field(default_factory=platform.platform)
    machine: str = field(default_factory=lambda: f"{platform.system()} {platform.machine()}")
    provider: str | None = None
    provider_sha256: str | None = None
    story: str | None = None
    commands: list[dict[str, Any]] = field(default_factory=list)
    tools: list[Tool] = field(default_factory=list)
    stages: list[str] = field(default_factory=list)
    datasets: dict[str, str] = field(default_factory=dict)
    degraded: dict[str, str] = field(default_factory=dict)
    schema: int = SCHEMA

    #: The name of the file a record is written to, so callers name it once.
    FILE = PROVENANCE_FILE

    @property
    def seconds(self) -> float:
        return round(self.ended - self.started, 3)

    @property
    def built_at(self) -> str:
        """When the build *finished*, to the second, in UTC.

        Not the local time: a manifest that a reviewer in another timezone reads
        should not need the reader's offset to be interpretable.
        """
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.ended))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "vidkit": self.vidkit,
            "action": self.action,
            "story": self.story,
            "spec": self.spec,
            "spec_sha256": self.spec_sha256,
            "provider": self.provider,
            "provider_sha256": self.provider_sha256,
            "timeframe": self.timeframe,
            "commands": [dict(c) for c in self.commands],
            "runtime": {"python": self.python, "platform": self.platform,
                        "machine": self.machine},
            "tools": [t.to_dict() for t in self.tools],
            "stages": list(self.stages),
            "datasets": dict(self.datasets),
            "degraded": dict(self.degraded),
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.started)),
            "built_at": self.built_at,
            "seconds": self.seconds,
        }

    # -- writing ----------------------------------------------------------- #
    def write(self, directory: Path) -> Path:
        path = Path(directory) / PROVENANCE_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=1, sort_keys=True),
                        encoding="utf-8")
        return path

    @classmethod
    def read(cls, directory: Path) -> dict[str, Any] | None:
        """The record on disk, or ``None`` — never a half-parsed guess."""
        path = Path(directory) / PROVENANCE_FILE
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if raw.get("schema") != SCHEMA:
            return None
        return raw


# --------------------------------------------------------------------------- #
def probe_tools(shell=None) -> list[Tool]:
    """Ask each tool what it is, and record the answer.

    Uses ``Shell.which`` when a shell is supplied so that a test can substitute a
    recorder; otherwise a plain ``shutil.which``.

    Cached per ``PATH``: which tools exist and what version they are is a property
    of the machine, not of the build, and a studio that spawns five processes per
    render to re-learn a constant is wasting the user's time. Keying on ``PATH``
    keeps the cache honest when a test (or a user) changes it mid-session.
    """
    import os

    if shell is not None:
        return _probe_with(shell)
    key = os.environ.get("PATH", "")
    if key not in _TOOL_CACHE:
        _TOOL_CACHE[key] = _probe_with(None)
    # a copy, so a caller cannot corrupt the cache by editing the list
    return [Tool(t.name, t.present, t.version, t.path) for t in _TOOL_CACHE[key]]


_TOOL_CACHE: dict[str, list[Tool]] = {}


def _probe_with(shell) -> list[Tool]:
    import shutil

    tools: list[Tool] = []
    for name in TOOLS:
        path = shell.which(name) if shell is not None else shutil.which(name)
        if not path:
            tools.append(Tool(name=name, present=False))
            continue
        tools.append(Tool(name=name, present=True, version=_version_of(name, path),
                          path=path))
    return tools


def _banner(path: str, args: tuple[str, ...]) -> str:
    """The noise a tool makes when asked its version, or ``""``.

    ``gs --version`` prints to stdout and everything else to stderr, so both are
    read and joined. Bounded: a tool that hangs is not worth a build.
    """
    try:
        done = subprocess.run([path, *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    return f"{done.stdout or ''}\n{done.stderr or ''}".strip()


def _version_of(name: str, path: str) -> str | None:
    args = _VERSION_ARGS.get(name)
    pattern = _VERSION_PATTERNS.get(name)
    if not args or pattern is None:
        return None
    for line in _banner(path, args).splitlines():
        match = pattern.search(line.strip())
        if match:
            return match.group(1)
    return None


def spec_digest(path: Path | None) -> str | None:
    """The spec's own bytes, so a report can name the file it describes."""
    return file_digest(path)
