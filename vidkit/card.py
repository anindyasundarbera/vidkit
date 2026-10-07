"""Title cards and flat fields: the artwork the engine draws from the spec itself.

A **card** is typography — words the spec contains, set in the project's own theme,
optionally over a declared picture. A **solid** is one flat colour. Neither is a
picture of anything; neither *can* be. That is why they are shot *kinds* rather than
a ``still:`` with a blank filename: a still is a file that has to exist, and these
are not files at all.

They exist so a film can open on a title and rest between beats without an author
having to ship a PNG of a rectangle. The honesty rule is untouched by this: nothing
here invents a fact. A card sets the spec's own words in the spec's own palette, and
``verify`` classifies it as a **declared asset** — the same class as an author's PNG,
and one of the three honest sources. There is no fourth category.

A backdrop is *declared*, never discovered: it is resolved and checked to exist at
load time exactly as a ``still:`` is, so a title card cannot silently render over a
missing picture.
"""

from __future__ import annotations

from pathlib import Path

from .svg import THEME, Theme, document, esc, rect, text

#: share of the frame width a card's text block is allowed to fill
_TEXT_WIDTH = 0.70
#: how dark the scrim over a backdrop gets, so type stays readable on any photo
_SCRIM_STOPS = ((0.0, 0.05), (0.45, 0.45), (1.0, 0.80))


def solid_svg(colour: str, size: tuple[int, int], theme: Theme = THEME) -> str:
    """One flat field. No gradient, no vignette — a solid is a solid."""
    w, h = size
    return document(w, h, rect(0, 0, w, h, fill=colour), theme, background=False)


def _wrap(s: str, *, size: int, width: int) -> list[str]:
    """Greedy word wrap to a character count derived from the font size.

    Deliberately measure-free: the engine cannot ask a font its metrics without
    pulling in a text shaper, and a card that is one word too wide is a worse
    failure than a card that wraps a word early.
    """
    words, lines, cur = str(s).split(), [], ""
    for word in words:
        if not cur:
            cur = word
        elif len(cur) + 1 + len(word) <= width:
            cur = f"{cur} {word}"
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines or [""]


def _fitted(s: str, *, size: int, frame_w: int) -> tuple[list[str], int]:
    """Wrap ``s``, shrinking the type until it fits in a sane number of lines.

    A long title should get smaller, not spill off the card; three lines is the
    most a title card can carry before it stops reading as a title.
    """
    lines: list[str] = []
    pt = size
    for pt in range(size, max(int(size * 0.45), 12), -2):
        cols = max(8, int(round(frame_w * _TEXT_WIDTH / (pt * 0.52))))
        lines = _wrap(s, size=pt, width=cols)
        if len(lines) <= 3:
            return lines, pt
    return lines or [str(s)], pt


def card_svg(words: str, *, size: tuple[int, int], kicker: str = "",
             backdrop: Path | None = None, theme: Theme = THEME) -> str:
    """A title card: the spec's words, centred, over a colour or a declared picture.

    ``backdrop`` is an absolute path — rsvg resolves an ``xlink:href`` relative to
    the *SVG's* directory, and the card is written into ``build/stills``, so a
    relative path would point at the wrong place. The caller absolutises it.

    The backdrop is drawn with ``slice`` so a picture of any aspect fills the frame
    without distortion, and a scrim is laid over it so a title stays legible over a
    bright photograph. The scrim is a gradient rather than a flat wash because a
    flat wash would dim the *whole* picture and a title card's job is to show it.
    """
    w, h = size
    body: list[str] = []

    if backdrop is not None:
        stops = "".join(
            f'<stop offset="{o:.2f}" stop-color="#000000" stop-opacity="{a:.2f}"/>'
            for o, a in _SCRIM_STOPS
        )
        # the id is fixed: exactly one card is rendered per file, and rsvg sees one
        # document at a time
        body.append(
            f'  <defs><linearGradient id="scrim" x1="0" y1="0" x2="0" y2="1">'
            f"{stops}</linearGradient></defs>"
        )
        body.append(
            f'  <image x="0" y="0" width="{w}" height="{h}" '
            f'preserveAspectRatio="xMidYMid slice" '
            f'xlink:href="{esc(str(backdrop))}"/>'
        )
        body.append(f'  <rect width="{w}" height="{h}" fill="url(#scrim)"/>')
        ink, muted, rule = theme.darktext, theme.darkaccent, theme.accent
    else:
        ink, muted, rule = theme.ink, theme.muted, theme.accent

    title_pt = max(int(round(h * 0.085)), 18)
    lines, title_pt = _fitted(words, size=title_pt, frame_w=w)
    kicker_pt = max(int(round(title_pt * 0.34)), 11)
    line_h = int(round(title_pt * 1.24))

    block = len(lines) * line_h + (kicker_pt + 26 if kicker else 0) + 34
    y = (h - block) / 2 + title_pt

    if kicker:
        body.append(text(w / 2, y - title_pt * 0.95, kicker.upper(), size=kicker_pt,
                         fill=muted, weight=700, anchor="middle", letter=3))
    # a short accent rule: it tells the eye where the title begins without boxing it
    rule_w = min(w * 0.11, 190)
    body.append(rect((w - rule_w) / 2, y + 12, rule_w, 3, fill=rule, rx=1.5))
    y += 34

    for i, ln in enumerate(lines):
        body.append(text(w / 2, y + i * line_h, ln, size=title_pt, fill=ink,
                         weight=700, anchor="middle"))

    return document(w, h, "\n".join(body), theme, background=backdrop is None)
