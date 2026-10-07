"""Small SVG primitives + a restrained default theme.

These helpers keep panel renderers short and readable. Everything returns a
string; the caller joins them into an ``<svg>`` document.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field


def esc(value: object) -> str:
    return html.escape(str(value))


@dataclass
class Theme:
    bg: str = "#F7F5F0"
    ink: str = "#16232B"
    muted: str = "#5B6B75"
    line: str = "#E3DED3"
    accent: str = "#1F6FB2"
    accent2: str = "#B05A2A"
    good: str = "#7FB77E"
    panel: str = "#FFFFFF"
    dark: str = "#16232B"
    darktext: str = "#E8EEF2"
    darkaccent: str = "#8FBEDC"
    font: str = "Liberation Sans, DejaVu Sans, sans-serif"
    mono: str = "Liberation Mono, DejaVu Sans Mono, monospace"


THEME = Theme()


def document(width: int, height: int, body: str, theme: Theme = THEME,
             background: bool = True) -> str:
    bg_rect = f'  <rect width="{width}" height="{height}" fill="{theme.bg}"/>\n' if background else ""
    # ``xmlns:xlink`` is declared on every document even when nothing uses it. It costs
    # 44 bytes and it is the difference between a card with a backdrop rendering and
    # rsvg refusing the whole file with "Namespace prefix xlink for href on image is
    # not defined" — an error that names neither the card nor the backdrop.
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">\n'
        f'  <defs><style>text{{font-family:"{theme.font}";}}</style></defs>\n'
        f"{bg_rect}{body}\n</svg>\n"
    )


def text(x: float, y: float, s: object, *, size: int = 22, fill: str = THEME.ink,
         weight: int = 400, anchor: str = "start", italic: bool = False,
         mono: bool = False, letter: float | None = None, escape: bool = True) -> str:
    attrs = [
        f'x="{x:.1f}"', f'y="{y:.1f}"', f'font-size="{size}"', f'fill="{fill}"',
        f'font-weight="{weight}"',
    ]
    if anchor != "start":
        attrs.append(f'text-anchor="{anchor}"')
    if italic:
        attrs.append('font-style="italic"')
    if letter is not None:
        attrs.append(f'letter-spacing="{letter}"')
    style = f' style="font-family:{THEME.mono}"' if mono else ""
    body = esc(s) if escape else str(s)
    return f'  <text {" ".join(attrs)}{style}>{body}</text>'


def rect(x: float, y: float, w: float, h: float, *, fill: str = "none",
         stroke: str | None = None, rx: float = 0, sw: float = 1,
         dash: str | None = None) -> str:
    attrs = [f'x="{x:.1f}"', f'y="{y:.1f}"', f'width="{w:.1f}"', f'height="{h:.1f}"',
             f'fill="{fill}"']
    if rx:
        attrs.append(f'rx="{rx}"')
    if stroke:
        attrs.append(f'stroke="{stroke}" stroke-width="{sw}"')
    if dash:
        attrs.append(f'stroke-dasharray="{dash}"')
    return f'  <rect {" ".join(attrs)}/>'


def line(x1: float, y1: float, x2: float, y2: float, *, stroke: str = THEME.line,
         sw: float = 2, dash: str | None = None) -> str:
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return f'  <line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{stroke}" stroke-width="{sw}"{d}/>'


def circle(cx: float, cy: float, r: float, *, fill: str = THEME.accent) -> str:
    return f'  <circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r}" fill="{fill}"/>'


def polyline(points: list[tuple[float, float]], *, stroke: str = THEME.accent,
             sw: float = 3, fill: str = "none") -> str:
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    return f'  <polyline points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'


def text_block(x: float, y: float, s: object, *, size: int = 22, fill: str = THEME.ink,
               width: int = 92, line_height: int = 34, max_lines: int | None = None,
               escape: bool = True) -> str:
    """Wrap ``s`` to ``width`` characters and emit one <text> per line."""
    words, lines, cur = str(s).split(), [], ""
    for w in words:
        if len(cur) + 1 + len(w) <= width:
            cur = (cur + " " + w).strip()
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    if max_lines:
        lines = lines[:max_lines]
    return "\n".join(text(x, y + i * line_height, ln, size=size, fill=fill,
                          escape=escape) for i, ln in enumerate(lines))


@dataclass
class PanelDoc:
    """Accumulates body fragments at a fixed canvas size."""
    width: int
    height: int
    theme: Theme = field(default_factory=lambda: THEME)
    parts: list[str] = field(default_factory=list)

    def add(self, *fragments: str) -> "PanelDoc":
        self.parts.extend(fragments)
        return self

    def head(self, title: str, kicker: str = "") -> "PanelDoc":
        t = self.theme
        self.parts.append(rect(0, 0, self.width, 6, fill=t.accent))
        y = 86
        if kicker:
            self.parts.append(text(80, y, kicker.upper(), size=22, fill=t.accent,
                                   weight=700, letter=2))
            y += 60
        self.parts.append(text(80, y, title, size=52, weight=800, fill=t.ink))
        return self

    def foot(self, s: str) -> "PanelDoc":
        self.parts.append(text(80, self.height - 208, s, size=22, fill=self.theme.muted,
                               italic=True))
        return self

    def svg(self) -> str:
        return document(self.width, self.height, "\n".join(self.parts), self.theme)
