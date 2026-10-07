"""Unit tests for `vidkit.terminal` — the PTY replayer and renderer.

Pure Python: no PTY, no ffmpeg, no rsvg. A recording is just a byte stream, so a
test can synthesise one and assert what the screen makes of it. That is the right
shape, because the thing under test is an *interpreter*, and the interesting cases
are the escape sequences a real program emits — easier to write down than to
provoke on demand.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vidkit import terminal

_SCRATCH = Path(__file__).resolve().parent.parent / ".pytest-tmp"


def _cast_path(name: str = "unit.cast") -> Path:
    _SCRATCH.mkdir(exist_ok=True)
    return _SCRATCH / name


# --------------------------------------------------------------------------- #
# the parser
# --------------------------------------------------------------------------- #
def test_plain_text_lands_on_the_screen():
    s = terminal.Screen(cols=20, rows=3)
    terminal.feed(s, b"hello\r\nworld")
    assert s.lines() == ["hello", "world"]


def test_carriage_return_overwrites_the_line():
    """A progress bar redraws in place; `\\r` is how it does that."""
    s = terminal.Screen(cols=20, rows=3)
    terminal.feed(s, b"10%\r20%\r30%")
    assert s.lines() == ["30%"]


def test_a_shorter_redraw_erases_the_tail():
    """The subtle half of `\\r`: overwriting `loading` with `ok` must not leave
    `ing` behind, or the screen shows a word nobody printed."""
    s = terminal.Screen(cols=20, rows=3)
    terminal.feed(s, b"loading\r\x1b[Kok")
    assert s.lines() == ["ok"]


def test_newline_scrolls_at_the_bottom():
    s = terminal.Screen(cols=10, rows=2)
    terminal.feed(s, b"one\r\ntwo\r\nthree")
    assert s.lines() == ["two", "three"]


def test_cursor_position_is_one_based():
    s = terminal.Screen(cols=20, rows=4)
    terminal.feed(s, b"abcdef\x1b[1;3HXY")
    assert s.lines()[0] == "abXYef"


def test_erase_in_line_modes():
    cases = (("0", ["abc"]), ("1", ["    ef"]), ("2", []))
    for mode, expected in cases:
        s = terminal.Screen(cols=10, rows=2)
        terminal.feed(s, f"abcdef\x1b[1;4H\x1b[{mode}K".encode())
        assert s.lines() == expected, f"erase mode {mode}"


def test_unknown_csi_is_dropped_not_printed():
    """Anything the parser does not understand must vanish. Printing it would put
    raw escape text on a screen that never displayed it."""
    s = terminal.Screen(cols=20, rows=3)
    terminal.feed(s, b"a\x1b[99;99;99zb")
    assert s.lines() == ["ab"]


def test_sgr_sets_and_resets_colour_and_bold():
    s = terminal.Screen(cols=20, rows=3)
    terminal.feed(s, b"\x1b[1;31mred\x1b[0mplain")
    line = s.cells[0]
    assert line[0].bold and line[0].fg is not None
    assert line[3].ch == "p" and not line[3].bold and line[3].fg is None


def test_bright_palette_differs_from_the_normal_one():
    normal, bright = terminal.Screen(10, 2), terminal.Screen(10, 2)
    terminal.feed(normal, b"\x1b[31mx")
    terminal.feed(bright, b"\x1b[91mx")
    assert normal.cells[0][0].fg != bright.cells[0][0].fg


def test_incomplete_escape_at_the_end_of_a_chunk_is_not_printed():
    """A chunk can split an escape sequence. The parser must wait for the rest
    rather than render half of it."""
    s = terminal.Screen(cols=20, rows=3)
    terminal.feed(s, b"ok\x1b[")
    assert s.lines() == ["ok"]


def test_tab_advances_to_the_next_stop():
    s = terminal.Screen(cols=40, rows=2)
    terminal.feed(s, b"a\tb")
    assert s.cells[0][8].ch == "b"


def test_invalid_utf8_becomes_replacement_not_an_exception():
    """A command killed mid-character leaves a torn byte. That is a fact about the
    run and should show as one rather than crashing the build."""
    s = terminal.Screen(cols=20, rows=3)
    terminal.feed(s, b"ok\xff\xfe")
    assert s.lines()[0].startswith("ok")


# --------------------------------------------------------------------------- #
# replay: the two entry points must agree
# --------------------------------------------------------------------------- #
def test_replay_events_keeps_the_measured_timestamps():
    """Snapshots carry the recorder's own clock, not a count of samples."""
    events = [(0.0, b"one\r\n"), (2.5, b"two\r\n"), (3.0, b"three\r\n")]
    s = terminal.replay_events(events, cols=20, rows=5, every=1.0)
    assert [round(at, 2) for at, _ in s.snapshots] == [0.0, 2.5]
    assert s.lines() == ["one", "two", "three"], "the live screen is always current"


def test_the_final_screen_is_not_snapshotted_by_interval_sampling():
    """It falls between two samples whenever the last chunk arrives mid-interval.
    That is why the assembler appends it explicitly: for a command that prints one
    result and exits, the final screen *is* the shot, and a frame that is never
    sampled is a moment nobody can point at."""
    events = [(0.0, b"start\r\n"), (0.4, b"result\r\n")]
    s = terminal.replay_events(events, cols=20, rows=5, every=1.0)
    assert [round(at, 2) for at, _ in s.snapshots] == [0.0]
    assert s.lines() == ["start", "result"]


def test_replay_and_replay_events_agree():
    """The cast file is the portable form of the same recording, so a viewer that
    reads it must see what the renderer saw."""
    events = [(0.0, b"alpha\r\n"), (1.5, b"beta\r\n"), (2.5, b"gamma\r\n")]
    cast = terminal.write_cast(events, _cast_path("agree.cast"), cols=20, rows=5)
    direct = terminal.replay_events(events, cols=20, rows=5, every=1.0)
    via_file = terminal.replay(cast.read_bytes(), cols=20, rows=5, every=1.0)
    assert direct.snapshots, "no snapshots were taken at all"
    assert direct.lines() == via_file.lines()
    assert ([round(t, 3) for t, _ in direct.snapshots]
            == [round(t, 3) for t, _ in via_file.snapshots])


def test_replay_matches_final_screen_exactly():
    events = [(0.0, b"\x1b[1;32mPASS\x1b[0m\r\n"), (1.0, b"done\r\n")]
    s = terminal.replay_events(events, cols=40, rows=6)
    assert s.lines() == ["PASS", "done"]


# --------------------------------------------------------------------------- #
# the cast format
# --------------------------------------------------------------------------- #
def test_cast_round_trips_through_the_file():
    events = [(0.0, b"a"), (1.25, b"bb"), (2.0, b"\x1b[31mc")]
    p = terminal.write_cast(events, _cast_path("round.cast"), cols=80, rows=24,
                            meta={"label": "demo", "exit_code": 0})
    header, *rest = p.read_text().splitlines()
    assert json.loads(header)["version"] == 2
    assert json.loads(header)["width"] == 80
    assert json.loads(header)["vidkit"]["label"] == "demo"
    assert len(rest) == 3
    assert terminal.read_cast(p.read_bytes()) == [("o", 0.0, b"a"),
                                                  ("o", 1.25, b"bb"),
                                                  ("o", 2.0, b"\x1b[31mc")]


def test_read_cast_is_handed_bytes_and_must_not_call_str_methods_on_them():
    """This pins a real bug: `read_cast` used to call `str.startswith` on the
    lines it had just decoded, which raised on every call."""
    p = terminal.write_cast([(0.0, b"x\r\n")], _cast_path("bytes.cast"),
                            cols=10, rows=4)
    assert terminal.read_cast(p.read_bytes()) == [("o", 0.0, b"x\r\n")]


def test_read_cast_tolerates_a_half_written_file():
    """A killed build leaves a truncated cast. The part that did happen is still
    evidence, so it is kept rather than discarded."""
    good = terminal.write_cast([(0.0, b"a\r\n"), (1.0, b"b\r\n")],
                               _cast_path("torn.cast"), cols=10, rows=4).read_bytes()
    assert len(terminal.read_cast(good[:-12] + b'[1.5, "o", "b')) == 1


def test_read_cast_skips_junk_lines():
    data = b'{"version": 2}\nnot json\n[0.5, "o", "hi"]\n\n'
    assert terminal.read_cast(data) == [("o", 0.5, b"hi")]


# --------------------------------------------------------------------------- #
# strip_ansi
# --------------------------------------------------------------------------- #
def test_strip_ansi_returns_what_a_human_would_have_read():
    raw = b"\x1b[1;32mPASS\x1b[0m 3 tests\r\n\x1b[31mFAIL\x1b[0m 0\r\n"
    text = terminal.strip_ansi(raw)
    assert "PASS 3 tests" in text and "FAIL 0" in text
    assert "\x1b" not in text


def test_strip_ansi_respects_the_final_carriage_return():
    assert terminal.strip_ansi(b"1%\r50%\r100%") == "100%"


# --------------------------------------------------------------------------- #
# the SVG renderer
# --------------------------------------------------------------------------- #
def test_render_svg_is_well_formed_and_the_declared_size():
    from xml.etree import ElementTree
    s = terminal.Screen(cols=20, rows=4)
    terminal.feed(s, b"hello\r\nworld")
    svg = terminal.render_svg(s, (640, 360), title="demo")
    root = ElementTree.fromstring(svg)
    assert root.get("width") == "640" and root.get("height") == "360"
    assert root.tag.endswith("svg")


def test_render_svg_escapes_markup_the_program_printed():
    """A command can print `<` or `&`. Those are characters on the screen, not
    markup, and emitting them raw would produce invalid SVG."""
    from xml.etree import ElementTree
    s = terminal.Screen(cols=40, rows=3)
    terminal.feed(s, b"a < b & c > d \"q\"")
    svg = terminal.render_svg(s, (320, 180))
    ElementTree.fromstring(svg)          # raises if anything is unescaped
    assert "&lt;" in svg and "&amp;" in svg


def test_render_svg_groups_runs_of_identically_styled_cells():
    """A 100x30 grid as one element per character would be 3000 nodes. Runs are
    merged so the SVG stays a picture of the text, not of the grid."""
    s = terminal.Screen(cols=100, rows=10)
    terminal.feed(s, b"x" * 90)
    svg = terminal.render_svg(s, (800, 300))
    assert svg.count("<text") < 40


def test_render_svg_scales_a_narrow_screen_onto_a_wide_canvas():
    s = terminal.Screen(cols=10, rows=2)
    terminal.feed(s, b"short")
    assert terminal.render_svg(s, (1280, 720)).count("<text") >= 1


# --------------------------------------------------------------------------- #
# screen as a value
# --------------------------------------------------------------------------- #
def test_snapshot_is_a_copy_not_a_view():
    """Snapshots exist so a shot can pick a moment. If they aliased the live grid,
    every frame of a recording would show its ending."""
    s = terminal.Screen(cols=10, rows=3)
    terminal.feed(s, b"first")
    snap = s.snapshot(1.0)
    terminal.feed(s, b"\rlast")
    assert snap.lines() == ["first"]
    # `last` is four characters over `first`'s five, and without an erase the tail
    # survives. That is what a terminal actually does, and the recording shows it
    # rather than tidying it up.
    assert s.lines() == ["lastt"]


def test_snapshot_does_not_carry_its_own_snapshots():
    s = terminal.Screen(cols=10, rows=2)
    terminal.feed(s, b"x")
    assert s.snapshot(0.0).snapshots == []


def test_lines_drops_trailing_blank_rows_and_spaces():
    s = terminal.Screen(cols=10, rows=5)
    terminal.feed(s, b"a   \r\n")
    assert s.lines() == ["a"]


@pytest.mark.parametrize("cols,rows", [(1, 1), (2, 1), (1, 2), (80, 24)])
def test_a_tiny_or_a_normal_screen_never_indexes_out_of_range(cols, rows):
    s = terminal.Screen(cols=cols, rows=rows)
    terminal.feed(s, b"abcdefghij\r\nijklmnop\x1b[5;5HX\x1b[2K\x1b[1A\x1b[K")
    assert len(s.cells) == rows and all(len(r) == cols for r in s.cells)
