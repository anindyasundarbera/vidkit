"""``vidkit init`` — scaffold a runnable story.

A story is a folder. This module writes the four files that make a folder one:
a manifest (identity), a spec (the plan), a provider (the numbers), and a
narration (the words). The window is written down concretely in *both* spellings
— absolute dates in the spec, and the prose form in the narration — so a
scaffolded story passes its own timeframe check by construction rather than by
luck (R-A2, R-A4).

Templates use ``%``-formatting rather than :meth:`str.format` because the spec is
full of YAML braces.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from .errors import SpecError
from .narration import parse_scene_script
from .spec import STORY_MANIFEST, _slugify
from .timeframe import Timeframe, from_relative

#: The silent-cut speaking rate (`tts._FALLBACK_WPS`). A scaffold is silent until
#: a voice engine is configured, so its window has to be sized at that rate.
_WPS = 2.5

_STORY_TEMPLATE = """\
# The identity of this story. Everything here is optional: with no story.yaml at
# all, vidkit derives the slug and title from the folder name. Declare it
# explicitly when an agent needs a stable handle for the story (R-A1).
title: %(title)s
slug: %(slug)s
timeframe: %(timeframe)s
owner: %(owner)s
description: %(description)s
"""

_VIDEO_TEMPLATE = """\
# A vidkit spec. Run it with:
#   vidkit plan  video.yaml
#   vidkit build video.yaml
#
# Requires ffmpeg and rsvg-convert. No browser, no voice model, no network.

project:
  title: %(title)s
  slug: %(slug)s
  output: %(slug)s.mp4
  size: [1920, 1080]
  fps: 30
  min_seconds: %(min_seconds)d
  max_seconds: %(max_seconds)d

voice:
  engine: none                # a declared silent cut: no voice model needed

narration:
  source: narration.md        # "## Scene N — … · mm:ss–mm:ss", spoken lines in **bold**

provider: provider            # provider.py - supplies the numbers, measured from disk

# The window this cut is about. Everything the video claims about time has to
# agree with this, and `vidkit verify` fails the build if it does not.
timeframe: %(timeframe)s

charts:
  - {name: overview, kind: stat_cards, dataset: overview}
  - {name: facts, kind: kv_table, dataset: facts}

scenes:
  - n: 0
    title: Title
    shots:
      - {chart: overview, effect: hold}
  - n: 1
    title: What this build measured
    shots:
      - {chart: facts, effect: hold}

guard:
  banned: []
  required: []
  require_live_mode: false    # no captures in this story yet
  require_audio: false        # a declared silent cut, not an accidental one
"""

_PROVIDER_TEMPLATE = '''\
"""Provider for the %(slug)s story.

Every value returned here is measured from the context at build time. Nothing is
fetched and nothing is hard-coded, so the video moves when the data moves.
``ctx.timeframe`` is the *resolved* window - use it, and never a hard-coded day
count, or the video will disagree with its own spec.
"""

from __future__ import annotations

from typing import Any


def datasets(ctx) -> dict[str, Any]:
    """Return every dataset the spec's charts reference."""
    tf = ctx.timeframe
    return {
        "overview": {
            "stories in this repo": str(len(ctx.repo_stories)),
            "scenes": str(len(ctx.spec.scenes)),
            "window days": str(tf.days) if tf else "-",
        },
        "facts": [
            {"k": "story", "v": ctx.story.slug if ctx.story else "(none)"},
            {"k": "window declared", "v": tf.label() if tf else "(not declared)"},
            {"k": "window source", "v": tf.source if tf else "-"},
            {"k": "window floats", "v": "yes" if (tf and tf.floating) else "no"},
        ],
    }
'''

_NARRATION_TEMPLATE = """\
# %(slug)s - narration

The spoken lines are the **bold** ones. Bracketed lines are stage directions and
are never spoken or captioned. The `mm:ss` ranges are the intended timing; the
build re-times every caption from the **measured** durations, so a stale range
here can never desynchronise the render.

## Scene 0 — Title · 0:00–0:05

[Title card.]

**%(title)s.**

## Scene 1 — What this build measured · 0:05–0:20

[Two panels: headline counts, then the facts table.]

**Every number on screen was measured from this repository when the build ran. The window is %(prose)s. Rerun the build and the numbers move with the code.**
"""


def scaffold_story(target: Path | str, *, title: str | None = None,
                   slug: str | None = None, timeframe: Timeframe | None = None,
                   as_of: date | None = None, owner: str = "") -> list[Path]:
    """Write a runnable story into ``target`` and return the files created.

    Existing files are never overwritten — a scaffold must be safe to run in a
    folder that already has work in it.
    """
    target = Path(target).resolve()
    _ensure_auth_ignored(target)
    if target.exists() and not target.is_dir():
        raise SpecError(f"cannot scaffold a story into a file: {target}")
    name = target.name or "story"
    tf = timeframe or from_relative(28, as_of or date.today())
    slug = _slugify(slug or name)
    title = title or name.replace("-", " ").replace("_", " ").strip() or slug
    fields = {
        "title": title,
        "slug": slug,
        "owner": owner,
        "timeframe": "{start: %s, end: %s}" % (tf.start, tf.end),
        "description": f"Scaffolded by `vidkit init` on {date.today().isoformat()}.",
        "prose": tf.prose(),
    }
    narration = _NARRATION_TEMPLATE % fields

    # Size the runtime window to the words actually written, so the scaffold
    # passes its own runtime check rather than tripping over a guessed number.
    words = sum(len(s.spoken.split()) for s in parse_scene_script(narration))
    est = words / _WPS
    fields["min_seconds"] = max(8, int(est * 0.5))
    fields["max_seconds"] = max(30, int(est * 2.0))

    planned: list[tuple[Path, str]] = [
        (target / STORY_MANIFEST, _STORY_TEMPLATE % fields),
        (target / "video.yaml", _VIDEO_TEMPLATE % fields),
        (target / "provider.py", _PROVIDER_TEMPLATE % fields),
        (target / "narration.md", narration),
    ]

    existing = [p for p, _ in planned if p.exists()]
    if existing:
        raise SpecError("refusing to overwrite: "
                        + ", ".join(p.name for p in existing) + f" (in {target})")

    target.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for path, text in planned:
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return written


_AUTH_IGNORE = (
    "# a recorded browser session is a live credential; never commit it\n"
    "# (create one with `vidkit auth <url> --spec video.yaml`)\n"
    ".auth/\n"
)


def _ensure_auth_ignored(target: Path) -> None:
    """Make sure a recorded session can never be committed by accident."""
    ignore = target / ".gitignore"
    if not ignore.exists():
        target.mkdir(parents=True, exist_ok=True)
        ignore.write_text(_AUTH_IGNORE, encoding="utf-8")
        return
    body = ignore.read_text(encoding="utf-8")
    if ".auth" in body:
        return
    ignore.write_text(body.rstrip("\n") + "\n" + _AUTH_IGNORE, encoding="utf-8")
