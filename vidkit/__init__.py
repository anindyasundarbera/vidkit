"""vidkit — a declarative toolkit for producing narrated, captioned screen-recordings.

vidkit turns a small YAML *spec* plus a data provider into:

* per-scene narration audio (TTS),
* real or captured still frames (screen recordings via Playwright, charts from data),
* a single captioned ``.mp4`` with burned-in subtitles, and
* a verification report that checks the non-negotiables (runtime window, banned
  phrases, missing assets, mock-mode leakage).

It is deliberately dependency-light: ``ffmpeg`` and ``rsvg-convert`` for rendering,
``playwright`` (optional) for capture, ``piper-tts`` (optional) for speech, and
``pyyaml`` (optional — JSON specs work without it).

The worked example lives in ``../examples`` and is host-coupled by design; the
library itself contains no product knowledge.
"""

from __future__ import annotations

__version__ = "1.0.0"

from .errors import SpecError, ToolError, VidkitError  # noqa: F401

__all__ = ["VidkitError", "SpecError", "ToolError", "__version__"]
