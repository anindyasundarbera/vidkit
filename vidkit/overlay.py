"""Scene overlays (R-D4): a graphic drawn *over* a shot, never instead of it.

Two kinds, and the difference is the point of the feature:

* **banner** — a lower-third strip built by the engine from the scene's own
  words. It costs no asset and cannot go stale, so it is the default.
* **image** — a file the author supplies. It is drawn as itself.

Neither can replace the shot underneath. The product is always visible; the
overlay only says something *about* it. That is why compositing happens in
``Ffmpeg.overlay_clip`` rather than by substituting the still.
"""

from __future__ import annotations

import re
from pathlib import Path

from .svg import THEME, document, rect, text

# the banner's share of the frame width left empty on each side
_MARGIN = 64
# distance from the frame edge, in pixels, for a top/bottom placement
_EDGE = 40

_SVG_SIZE = re.compile(r"<svg[^>]*?width=\"([\d.]+)\"[^>]*?height=\"([\d.]+)\"")


def banner_size(size: tuple[int, int], height: float) -> tuple[int, int]:
    """Pixel size of a banner strip for ``size`` at ``height`` (a frame share)."""
    w, h = size
    return (max(w - 2 * _MARGIN, 16), max(int(round(h * height)), 16))


def banner_svg(title: str, kicker: str, size: tuple[int, int],
               theme=THEME) -> str:
    """A lower-third strip: an accent rule, an optional eyebrow, the title.

    Deliberately plain. A banner is a caption for a real picture, and any
    ornament here competes with the product it is captioning.
    """
    w, h = size
    body = [rect(0, 0, w, h, rx=14, fill=theme.dark),
            rect(0, 0, 9, h, fill=theme.accent)]
    kicker_size = max(int(round(h * 0.17)), 10)
    title_size = max(int(round(h * 0.30)), 12)
    y = h * 0.44
    if kicker:
        body.append(text(40, y, kicker.upper(), size=kicker_size,
                         fill=theme.darkaccent, weight=700, letter=2))
        y += title_size + 8
    body.append(text(40, y, title, size=title_size, fill=theme.darktext,
                     weight=700))
    return document(w, h, "\n".join(body), theme, background=False)


def svg_size(path: Path) -> tuple[int, int] | None:
    """The declared pixel size of an SVG file, if it states one."""
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:2000]
    except OSError:
        return None
    m = _SVG_SIZE.search(head)
    if not m:
        return None
    return int(float(m.group(1))), int(float(m.group(2)))


def edge_y(position: str) -> str:
    """The ffmpeg expression for a placement's y origin.

    Written against ``H``/``h`` — the *main* frame height and the *overlay*
    height — so a band stays pinned to its edge whatever the banner's size.
    """
    return f"{_EDGE}" if position == "top" else f"H-h-{_EDGE}"
