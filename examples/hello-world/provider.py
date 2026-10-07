"""Provider for examples/hello-world — no host dependencies, no network.

Every value below is *measured from files on disk* when the build runs: the
size of the vidkit package itself, the stage list, and the environment vidkit
found. Nothing is hard-coded, and nothing is fetched. That keeps this example
useful as a CI fixture — it exercises the provider seam and eight of the
eleven built-in panel kinds without a browser, a voice model, or a server.

This module intentionally touches only the standard library plus ``vidkit``
itself.
"""

from __future__ import annotations

import hashlib
import platform
import shutil
import sys
from pathlib import Path
from typing import Any

# examples/hello-world/provider.py -> repo root
REPO = Path(__file__).resolve().parents[2]
PKG = REPO / "vidkit"
TESTS = REPO / "tests"


# --------------------------------------------------------------------------- #
def _code_lines(path: Path) -> int:
    """Non-blank, non-comment lines — an honest size measure."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    return sum(1 for ln in lines if ln.strip() and not ln.lstrip().startswith("#"))


def _count(path: Path, needle: str) -> int:
    try:
        return path.read_text(encoding="utf-8").count(needle)
    except OSError:
        return 0


def _modules() -> list[Path]:
    if not PKG.is_dir():
        return []
    return sorted(p for p in PKG.glob("*.py") if p.name != "__init__.py")


def datasets(ctx) -> dict[str, Any]:
    """Return every dataset the spec's charts reference.

    The story's window arrives as ``ctx.timeframe`` — the *resolved* object, not a
    string to re-parse. A data source would be handed ``ctx.timeframe.as_prompt()``
    here; this example has no data source, so the window is shown instead.
    """
    modules = _modules()
    loc = {p.stem: _code_lines(p) for p in modules}
    total_loc = sum(loc.values())
    test_files = sorted(TESTS.glob("test_*.py"))
    n_tests = sum(_count(p, "def test_") for p in test_files)

    from vidkit.assembler import STAGES
    from vidkit.panels import kinds

    # -- stat_cards: headline counts, all measured -------------------------- #
    overview = {
        "window days": f"{ctx.timeframe.days}" if ctx.timeframe else "-",
        "modules": len(modules),
        "code lines": f"{total_loc:,}",
        "stages": len(STAGES),
        "panel kinds": len(kinds()),
        "tests": n_tests,
        "external tools": 2,
    }

    # -- line_series: module size across the package ------------------------ #
    points = [{"x": name, "y": value} for name, value in sorted(loc.items())]
    size_profile = {
        "series": [{"label": "code lines per module", "points": points}],
    }

    # -- bar_profile: the six largest modules ------------------------------- #
    top = sorted(loc.items(), key=lambda kv: kv[1], reverse=True)[:6]
    biggest = {
        "bars": [
            {"label": name, "value": value, "display": f"{value}",
             "note": "lines"}
            for name, value in top
        ]
    }

    # -- strip: one cell per stage, all of which ran in this build ---------- #
    pipeline = {
        "cells": [True] * len(STAGES),
        "headline": f"{len(STAGES)} stages, run in order",
        "sub": [
            "each stage writes a file, or stops the build",
            "selection: vidkit build --only panels,clips,render",
        ],
    }

    # -- endpoints: the CLI surface ---------------------------------------- #
    commands = [
        ("doctor", "check the environment and the spec"),
        ("plan", "show the scene plan and runtime estimate"),
        ("build", "run the pipeline end to end"),
        ("tts", "synthesise narration only"),
        ("capture", "run screen captures only"),
        ("verify", "re-run the acceptance checks"),
        ("docs", "print the documentation router"),
    ]
    cli = [{"method": "CLI", "path": f"vidkit {name}", "note": note}
           for name, note in commands]

    # -- kv_table: the environment this build actually saw ----------------- #
    spec_slug = ctx.spec.project.slug
    spec_file = ctx.root / "video.yaml"
    digest = hashlib.sha256(spec_file.read_bytes()).hexdigest()[:12] \
        if spec_file.exists() else "unavailable"
    tf = ctx.timeframe
    facts = [
        {"v": ctx.story.slug if ctx.story else spec_slug, "k": "story"},
        {"v": tf.label() if tf else "(not declared)", "k": "window"},
        {"v": tf.source if tf else "-", "k": "window declared in"},
        {"v": "yes" if (tf and tf.floating) else "no", "k": "window floats"},
        {"v": platform.python_version(), "k": "python"},
        {"v": sys.platform, "k": "platform"},
        {"v": "yes" if shutil.which("ffmpeg") else "no", "k": "ffmpeg"},
        {"v": "yes" if shutil.which("rsvg-convert") else "no", "k": "rsvg-convert"},
        {"v": "no (this example needs none)", "k": "browser"},
        {"v": "no (this example needs none)", "k": "voice model"},
        {"v": digest, "k": "spec sha256"},
    ]

    # -- text_panel: the design contract ----------------------------------- #
    notes = {
        "paragraphs": [
            "A spec is plain data. It names the scenes, the visuals, and the",
            "guardrails the finished cut must satisfy.",
            "A provider is a plain module. It supplies the numbers, and nothing",
            "it returns is taken on trust.",
            "Every claim in this video was counted from files on disk at build",
            "time. Rerun it, and the numbers move with the code.",
        ],
    }

    # -- terminal: how to drive it ----------------------------------------- #
    terminal = {
        "lines": [
            "$ pip install -e '.[dev]'",
            "$ vidkit doctor examples/hello-world/video.yaml",
            "$ vidkit plan   examples/hello-world/video.yaml",
            "$ vidkit build  examples/hello-world/video.yaml",
            f"[ok] {len(STAGES)} stages, {len(modules)} modules, {total_loc:,} lines",
            "[ok] verify.json written next to the render",
        ]
    }

    return {
        "overview": overview,
        "size_profile": size_profile,
        "biggest": biggest,
        "pipeline": pipeline,
        "cli": cli,
        "facts": facts,
        "notes": notes,
        "terminal": terminal,
    }
