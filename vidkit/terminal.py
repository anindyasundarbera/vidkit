"""Render a recorded terminal faithfully — as data, from the real byte stream.

The only honest way to show a terminal in a video is to show the one that was
actually there. So vidkit records the PTY's bytes (see :mod:`vidkit.exec`) and this
module turns them back into what a person would have seen.

Two consumers, one implementation:

* :func:`render_svg` draws the screen as SVG, which the existing ``rsvg`` path
  rasterises — so a terminal shot is a still like any other and needs no new
  pipeline stage.
* :func:`write_cast` writes an asciinema v2 cast, which is a *playable* artifact:
  the same evidence can be opened in a browser and stepped through. A still is a
  summary; a cast is the recording.

Design note
-----------
This is deliberately a small, well-specified subset of the ANSI/VT dialect a
shell prompt actually emits — cursor motion, erase, SGR colour/bold. It is not a
terminal emulator and does not pretend to be: an escape sequence it does not know
is *dropped*, never guessed at. Guessing is what would make a rendering a
plausible lie, and the whole reason this module exists is to avoid one.
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass, field
from pathlib import Path

#: The palette a terminal actually uses, so a recording is not re-coloured into
#: something prettier than the machine produced.
PALETTE = (
    "#16232B", "#C0392B", "#27AE60", "#B7791F",
    "#2A6FB2", "#8E44AD", "#17777F", "#C9CFD4",
)
BRIGHT = (
    "#5B6B75", "#E74C3C", "#2ECC71", "#F1C40F",
    "#5DADE2", "#AF7AC5", "#48C9B0", "#FFFFFF",
)


@dataclass
class Cell:
    ch: str = " "
    fg: str | None = None            # None = the theme's ink
    bg: str | None = None
    bold: bool = False


@dataclass
class Screen:
    """A character grid with the cursor state needed to replay a stream onto it."""

    cols: int = 100
    rows: int = 30
    cells: list[list[Cell]] = field(default_factory=list)
    cursor: tuple[int, int] = (0, 0)          # (row, col)
    fg: str | None = None                    # the pen the stream left behind
    bg: str | None = None
    bold: bool = False
    #: Every distinct screen the stream produced, as ``(seconds, snapshot)``.
    #: Kept so a shot can pick a moment instead of only the final frame.
    snapshots: list[tuple[float, "Screen"]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.cells:
            self.cells = [[Cell() for _ in range(self.cols)] for _ in range(self.rows)]

    # -- editing ---------------------------------------------------------- #
    def _scroll(self) -> None:
        self.cells.pop(0)
        self.cells.append([Cell() for _ in range(self.cols)])

    def newline(self) -> None:
        r, _ = self.cursor
        if r + 1 >= self.rows:
            self._scroll()
            r = self.rows - 1
        else:
            r += 1
        self.cursor = (r, 0)

    def put(self, ch: str) -> None:
        r, c = self.cursor
        self.cells[r][c] = Cell(ch, self.fg, self.bg, self.bold)
        if c + 1 >= self.cols:
            self.newline()
        else:
            self.cursor = (r, c + 1)

    # -- output ----------------------------------------------------------- #
    def lines(self) -> list[str]:
        out = []
        for row in self.cells:
            out.append("".join(c.ch for c in row).rstrip())
        while out and not out[-1]:
            out.pop()
        return out

    def snapshot(self, seconds: float) -> "Screen":
        clone = Screen(cols=self.cols, rows=self.rows,
                       cells=[[Cell(**vars(c)) for c in row] for row in self.cells])
        clone.cursor = self.cursor
        clone.fg, clone.bg, clone.bold = self.fg, self.bg, self.bold
        clone.snapshots = []
        self.snapshots.append((seconds, clone))
        return clone


# --------------------------------------------------------------------------- #
# the tiny VT parser
# --------------------------------------------------------------------------- #
def _colour(idx: int) -> str | None:
    if idx < 8:
        return PALETTE[idx]
    if 8 <= idx < 16:
        return BRIGHT[idx - 8]
    return None


def _apply_sgr(screen: Screen, params: list[int]) -> None:
    if not params:
        params = [0]
    for p in params:
        if p == 0:
            screen.fg = screen.bg = None
            screen.bold = False
        elif p == 1:
            screen.bold = True
        elif p == 22:
            screen.bold = False
        elif 30 <= p <= 37:
            screen.fg = _colour(p - 30)
        elif 90 <= p <= 97:
            screen.fg = _colour(p - 90 + 8)
        elif p == 39:
            screen.fg = None
        elif 40 <= p <= 47:
            screen.bg = _colour(p - 40)
        elif 100 <= p <= 107:
            screen.bg = _colour(p - 100 + 8)
        elif p == 49:
            screen.bg = None


def _csi(screen: Screen, body: str) -> None:
    """Handle one ``ESC [ … final`` sequence. Unknown finals are dropped."""
    if not body:
        return
    final, params_text = body[-1], body[:-1]
    private = params_text.startswith("?")
    if private:
        params_text = params_text[1:]
    parts = [p for p in params_text.split(";")] if params_text else []
    nums: list[int] = []
    for p in parts:
        try:
            nums.append(int(p) if p else 0)
        except ValueError:
            nums.append(0)
    n = nums[0] if nums else 0
    rows, cols = screen.rows, screen.cols
    r, c = screen.cursor

    if final == "m":
        _apply_sgr(screen, nums)
    elif final == "H" or final == "f":
        row = (nums[0] if len(nums) > 0 and nums[0] else 1) - 1
        col = (nums[1] if len(nums) > 1 and nums[1] else 1) - 1
        screen.cursor = (max(0, min(row, rows - 1)), max(0, min(col, cols - 1)))
    elif final == "A":
        screen.cursor = (max(0, r - max(1, n)), c)
    elif final == "B":
        screen.cursor = (min(rows - 1, r + max(1, n)), c)
    elif final == "C":
        screen.cursor = (r, min(cols - 1, c + max(1, n)))
    elif final == "D":
        screen.cursor = (r, max(0, c - max(1, n)))
    elif final == "G":
        screen.cursor = (r, max(0, min((n or 1) - 1, cols - 1)))
    elif final == "d":
        screen.cursor = (max(0, min((n or 1) - 1, rows - 1)), c)
    elif final == "K":
        mode = n
        if mode == 0:
            for x in range(c, cols):
                screen.cells[r][x] = Cell()
        elif mode == 1:
            for x in range(0, c + 1):
                screen.cells[r][x] = Cell()
        else:
            for x in range(cols):
                screen.cells[r][x] = Cell()
    elif final == "J":
        mode = n
        if mode == 0:
            for x in range(c, cols):
                screen.cells[r][x] = Cell()
            for y in range(r + 1, rows):
                screen.cells[y] = [Cell() for _ in range(cols)]
        elif mode == 1:
            for x in range(0, c + 1):
                screen.cells[r][x] = Cell()
            for y in range(0, r):
                screen.cells[y] = [Cell() for _ in range(cols)]
        else:
            for y in range(rows):
                screen.cells[y] = [Cell() for _ in range(cols)]
            screen.cursor = (0, 0)
    # anything else: dropped on purpose


def feed(screen: Screen, data: bytes) -> None:
    """Replay a raw chunk onto the screen.

    Bytes are decoded with ``replace`` so a truncated multi-byte character
    becomes U+FFFD rather than an exception — a partly-written line is a fact
    about a command that was killed, and it should show as one.
    """
    text = data.decode("utf-8", "replace")
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\x1b":
            if i + 1 < len(text) and text[i + 1] == "[":
                j = i + 2
                while j < len(text) and not ("@" <= text[j] <= "~"):
                    j += 1
                if j >= len(text):
                    return                      # incomplete: wait for more bytes
                _csi(screen, text[i + 2:j + 1])
                i = j + 1
                continue
            if i + 1 < len(text) and text[i + 1] in "()#%":
                i += 3
                continue
            i += 2                              # ESC c, ESC 7, … : dropped
            continue
        if ch == "\n":
            screen.newline()
        elif ch == "\r":
            r, _ = screen.cursor
            screen.cursor = (r, 0)
        elif ch == "\b":
            r, c = screen.cursor
            screen.cursor = (r, max(0, c - 1))
        elif ch == "\t":
            r, c = screen.cursor
            nxt = min(screen.cols - 1, (c // 8 + 1) * 8)
            screen.cursor = (r, nxt)
        elif ch == "\x07":
            pass
        elif ch < " ":
            pass
        else:
            screen.put(ch)
        i += 1


def replay_events(events: list[tuple[float, bytes]], cols: int = 100, rows: int = 30,
                  every: float = 0.0) -> Screen:
    """Rebuild the screen from ``(seconds, payload)`` pairs.

    This is the lossless path: the pairs are what the recorder actually saw,
    timestamps included, so a snapshot's time is *measured* rather than implied
    by a position in a file. :func:`replay` is the same operation on the
    portable cast form, which is what a viewer reads; this is what the engine
    reads, so a rendered frame and a published cast can never disagree about
    when something happened.
    """
    screen = Screen(cols=cols, rows=rows)
    last = -1.0
    for at, payload in events:
        feed(screen, payload)
        if every > 0 and at - last >= every:
            screen.snapshot(at)
            last = at
    return screen


def replay(cast_bytes: bytes, cols: int = 100, rows: int = 30,
           every: float = 0.0) -> Screen:
    """Rebuild the screen from a recorded cast.

    ``every > 0`` also keeps a snapshot at that interval, which is what lets a
    shot choose a *moment* (the instant a test went green) rather than only the
    final frame.
    """
    return replay_events(
        [(at, payload) for kind, at, payload in read_cast(cast_bytes) if kind == "o"],
        cols=cols, rows=rows, every=every)


# --------------------------------------------------------------------------- #
# asciinema v2 casts — the playable form of the same evidence
# --------------------------------------------------------------------------- #
def write_cast(events: list[tuple[float, bytes]], out: Path, *, cols: int, rows: int,
               meta: dict | None = None) -> Path:
    """Write ``events`` as an asciinema v2 cast.

    The format is three lines of JSON header followed by one JSON array per
    output event. It is small enough to write by hand, and it can be replayed by
    anything that understands a terminal — including this module.
    """
    header = {"version": 2, "width": cols, "height": rows,
              "env": {"TERM": "xterm-256color", "SHELL": "/bin/sh"},
              "vidkit": meta or {}}
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(header) + "\n")
        for at, payload in events:
            fh.write(json.dumps([round(at, 4), "o",
                                 payload.decode("utf-8", "replace")]) + "\n")
    return out


def read_cast(data: bytes) -> list[tuple[str, float, bytes]]:
    """Read a cast into ``(kind, seconds, payload)`` triples.

    Tolerant by design: a malformed line is skipped rather than fatal, because a
    half-written cast from a killed build is still the record of the part that
    did happen.
    """
    out: list[tuple[str, float, bytes]] = []
    for raw in data.splitlines():
        line = raw.decode("utf-8", "replace").strip()
        if not line or not line.startswith("["):
            continue
        try:
            at, kind, payload = json.loads(line)
        except (ValueError, TypeError):
            continue
        out.append((str(kind), float(at), str(payload).encode("utf-8")))
    return out


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #
def render_svg(screen: Screen, size: tuple[int, int], *, title: str = "",
               chrome: bool = True, font_size: int = 22) -> str:
    """Draw the screen as an SVG, sized to the project canvas.

    ``chrome`` draws the window frame and title bar. It is part of the picture
    rather than decoration: a viewer needs to know they are looking at a
    terminal, and the title says *which* command produced it.
    """
    width, height = size
    cell_h = font_size * 1.35
    bar = 44 if chrome else 0
    pad = 40
    rows = min(screen.rows, max(1, int((height - bar - pad * 2) // cell_h)))
    lines = screen.lines()[:rows]
    font = "DejaVu Sans Mono, Liberation Mono, monospace"

    parts: list[str] = []
    parts.append(f'<rect width="{width}" height="{height}" fill="#16232B"/>')
    if chrome:
        parts.append(f'<rect x="0" y="0" width="{width}" height="{bar}" fill="#0E171D"/>')
        for i, colour in enumerate(("#FF5F57", "#FEBC2E", "#28C840")):
            parts.append(f'<circle cx="{28 + i * 26}" cy="{bar/2}" r="9" fill="{colour}"/>')
        if title:
            parts.append(
                f'<text x="{width/2}" y="{bar/2 + 8}" text-anchor="middle" '
                f'font-family="{font}" font-size="20" fill="#8FA3B0">'
                f"{html.escape(title)}</text>")
    parts.append(f'<clipPath id="screen"><rect x="{pad}" y="{bar + pad}" '
                 f'width="{width - pad * 2}" height="{height - bar - pad * 2}"/>'
                 "</clipPath>")
    parts.append('<g clip-path="url(#screen)">')
    cell_w = font_size * 0.602

    def flush(row_index: int, start_col: int, cells: list[Cell]) -> None:
        if not cells:
            return
        y = bar + pad + (row_index + 0.85) * cell_h
        s = html.escape("".join(c.ch for c in cells))
        fg = cells[0].fg or "#E8EEF2"
        weight = "700" if cells[0].bold else "400"
        parts.append(
            f'<text x="{pad + start_col * cell_w:.1f}" y="{y:.1f}" '
            f'font-family="{font}" font-size="{font_size}" fill="{fg}" '
            f'font-weight="{weight}">{s}</text>')

    for r, row in enumerate(screen.cells[:rows]):
        # runs of identically-styled cells become one <text>, so a 100x30 grid
        # does not become 3000 elements
        run: list[Cell] = []
        start = 0
        for c, cell in enumerate(row):
            if not run:
                run, start = [cell], c
            elif (cell.fg, cell.bg, cell.bold) == (run[0].fg, run[0].bg, run[0].bold):
                run.append(cell)
            else:
                flush(r, start, run)
                run, start = [cell], c
        flush(r, start, run)
    parts.append("</g>")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
            f'height="{height}" viewBox="0 0 {width} {height}">\n'
            + "\n".join(parts) + "\n</svg>\n")


def strip_ansi(data: bytes) -> str:
    """Plain text of a stream, for anyone who wants to grep the transcript.

    This is what lands in ``verify.json`` — a machine-readable account of what the
    command said, so a check can assert against real output instead of a picture
    of it.
    """
    screen = Screen(cols=1000, rows=200)
    feed(screen, data)
    return "\n".join(screen.lines())
