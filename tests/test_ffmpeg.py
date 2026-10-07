"""Ffmpeg wrappers: filter construction, and geometry that is measured.

The aspect tests in here are deliberately split in two. The first group checks
the *filter chain* we build, which is fast and catches a regression in the
string. The second group actually runs ffmpeg and reads the pixels back, which
is the only way to know a scaling claim is true — a filter that *looks* correct
can still squash a full-page capture, and that is exactly the bug R-D5 named.

The real-render group skips when ffmpeg is absent, so the suite stays runnable
on a machine without it.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from vidkit.ffmpeg import Ffmpeg, Shell, fit_filters

HAVE_FFMPEG = shutil.which("ffmpeg") is not None
needs_ffmpeg = pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not installed")


# --------------------------------------------------------------------------- #
# filter chain
# --------------------------------------------------------------------------- #
def test_fit_filters_fills_the_box_and_never_stretches():
    vf = fit_filters((1920, 1080))
    assert "force_original_aspect_ratio=increase" in vf
    assert "crop=1920:1080" in vf
    # a bare `scale=w:h` is the bug this function exists to prevent: it maps any
    # source aspect onto the box. It must never appear without the guard.
    assert "scale=1920:1080:" in vf


def test_fit_filters_carries_the_requested_size():
    assert "crop=640:480" in fit_filters((640, 480))


# --------------------------------------------------------------------------- #
# still_to_clip — the command it builds
# --------------------------------------------------------------------------- #
class _Record:
    """A Runner that records commands and pretends they succeeded."""

    def __init__(self) -> None:
        self.cmds: list[list[str]] = []

    def __call__(self, cmd):
        self.cmds.append([str(c) for c in cmd])
        return subprocess.CompletedProcess(list(cmd), 0, "", "")


def _ffmpeg():
    rec = _Record()
    return Ffmpeg(Shell(rec)), rec


def test_still_to_clip_hold_crops_rather_than_scales(tmp_path: Path):
    ff, rec = _ffmpeg()
    ff.still_to_clip(tmp_path / "a.png", tmp_path / "a.mp4", 2.0,
                     size=(1280, 720), fps=30)
    vf = rec.cmds[0][rec.cmds[0].index("-vf") + 1]
    assert "force_original_aspect_ratio=increase" in vf
    assert "crop=1280:720" in vf
    assert "setsar=1" in vf


def test_still_to_clip_contain_letterboxes(tmp_path: Path):
    ff, rec = _ffmpeg()
    ff.still_to_clip(tmp_path / "a.png", tmp_path / "a.mp4", 2.0,
                     size=(1280, 720), fps=30, fit="contain")
    vf = rec.cmds[0][rec.cmds[0].index("-vf") + 1]
    assert "force_original_aspect_ratio=decrease" in vf
    assert "pad=1280:720" in vf
    assert "crop=" not in vf


def test_still_to_clip_zoom_fits_before_pushing_in(tmp_path: Path):
    ff, rec = _ffmpeg()
    ff.still_to_clip(tmp_path / "a.png", tmp_path / "a.mp4", 3.0,
                     size=(1280, 720), fps=30, effect="zoom", zoom=0.10)
    vf = rec.cmds[0][rec.cmds[0].index("-vf") + 1]
    # the zoom source is itself aspect-fitted, so the push-in cannot distort
    assert "force_original_aspect_ratio=increase" in vf
    assert "crop=1408:792" in vf
    assert "zoompan=" in vf
    assert "s=1280x720" in vf


# --------------------------------------------------------------------------- #
# real pixels — the tests that could actually catch R-D5
# --------------------------------------------------------------------------- #
def _dominant(rgb: tuple[int, int, int]) -> str:
    """Which channel a pixel leads in.

    Comparing raw bytes would be wrong: the clips are H.264/yuv420p, so a pure
    red comes back around (252, 0, 0). The tests care which colour region is on
    screen, not the exact codec round-trip.
    """
    r, g, b = rgb
    return max((("red", r), ("green", g), ("blue", b)), key=lambda kv: kv[1])[0]


def _is_dark(rgb: tuple[int, int, int]) -> bool:
    return max(rgb) < 60


def _solid(path: Path, w: int, h: int, colour: str) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", f"color=c={colour}:s={w}x{h}", "-frames:v", "1", str(path)],
        check=True, capture_output=True,
    )


@needs_ffmpeg
def test_hold_output_is_exactly_the_requested_frame(tmp_path: Path):
    ff = Ffmpeg()
    src = tmp_path / "tall.png"
    _solid(src, 400, 1200, "red")            # a full-page capture's shape
    out = tmp_path / "tall.mp4"
    ff.still_to_clip(src, out, 1.0, size=(1280, 720), fps=10)
    assert ff.clip_geometry(out) == (1280, 720)


@needs_ffmpeg
def test_a_square_is_not_stretched(tmp_path: Path):
    """A square source in a 2:1 frame: cover keeps the square, centre-cropped.

    Red is painted over everything, so the *shape* has to be read from a second
    colour. The source is a red square sitting in a blue column; after a cover
    fit the frame's top band must be blue (squared away) and its middle band red.
    A `scale=W:H` would have smeared blue and red across the full height instead.
    """
    ff = Ffmpeg()
    src = tmp_path / "sq.png"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "color=c=blue:s=600x1200", "-f", "lavfi",
         "-i", "color=c=red:s=600x600", "-filter_complex",
         "[0:v][1:v]overlay=0:300", "-frames:v", "1", str(src)],
        check=True, capture_output=True,
    )
    assert ff.still_geometry(src) == (600, 1200)

    out = tmp_path / "sq.mp4"
    ff.still_to_clip(src, out, 1.0, size=(600, 300), fps=10)

    raw = ff.frame_rgb(out, 0.0, tmp_path / "frame.raw", size=(600, 300))
    assert len(raw) == 600 * 300 * 3

    def at(x: int, y: int) -> tuple[int, int, int]:
        i = (y * 600 + x) * 3
        return raw[i], raw[i + 1], raw[i + 2]

    # 1200-tall source covering a 300-tall frame: the visible band is the source's
    # middle, y 450..750 — entirely inside the red square (300..900). The blue
    # column above and below the square must not be visible anywhere.
    assert _dominant(at(300, 5)) == "red", "the page's top edge was stretched in"
    assert _dominant(at(300, 150)) == "red"
    assert _dominant(at(300, 294)) == "red", "the page's bottom edge was stretched in"


@needs_ffmpeg
def test_cover_hides_the_vertical_extremes_of_a_full_page(tmp_path: Path):
    """A full-page capture is cropped, and the crop is centred.

    The source is a red field with a green strip at the very top. Fitting it to
    a 16:9 frame with `cover` must drop that strip (it is outside the centre),
    and a `contain` fit must keep it (letterboxed) — both are honest; only
    `scale=W:H` would have kept it *and* squashed the page.
    """
    ff = Ffmpeg()
    src = tmp_path / "page.png"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "color=c=red:s=400x1600", "-f", "lavfi",
         "-i", "color=c=green:s=400x100", "-filter_complex",
         "[0:v][1:v]overlay=0:0", "-frames:v", "1", str(src)],
        check=True, capture_output=True,
    )

    covered = tmp_path / "cover.mp4"
    ff.still_to_clip(src, covered, 1.0, size=(800, 450), fps=10)
    def top(raw: bytes) -> tuple[int, int, int]:
        return raw[0], raw[1], raw[2]

    raw = ff.frame_rgb(covered, 0.0, tmp_path / "c.raw", size=(800, 450))
    assert _dominant(top(raw)) == "red", "cover should have cropped the top strip away"

    contained = tmp_path / "contain.mp4"
    ff.still_to_clip(src, contained, 1.0, size=(800, 450), fps=10, fit="contain")
    raw = ff.frame_rgb(contained, 0.0, tmp_path / "d.raw", size=(800, 450))
    # letterboxed: dark bars top and bottom, the page's own top edge visible
    # between them — nothing hidden, and no distortion
    assert _is_dark(top(raw)), "contain should have letterboxed, not cropped"
    assert _dominant(raw[(800 * 225 + 400) * 3:][:3]) == "red"


@needs_ffmpeg
def test_geometry_probe_reads_the_file_not_the_filter(tmp_path: Path):
    ff = Ffmpeg()
    src = tmp_path / "x.png"
    _solid(src, 300, 900, "red")
    out = tmp_path / "x.mp4"
    ff.still_to_clip(src, out, 0.5, size=(640, 360), fps=10)
    w, h = ff.clip_geometry(out)
    assert (w, h) == (640, 360)
    assert ff.still_geometry(src) == (300, 900)


# --------------------------------------------------------------------------- #
# overlay_clip — the shot must survive underneath (R-D4)
# --------------------------------------------------------------------------- #
def test_overlay_clip_puts_the_graphic_over_the_shot():
    ff, rec = _ffmpeg()
    ff.overlay_clip(Path("a.mp4"), Path("g.png"), Path("o.mp4"),
                    position="bottom", opacity=0.9, fade=0.4)
    fc = rec.cmds[-1][rec.cmds[-1].index("-filter_complex") + 1]
    # two inputs, an overlay of the second onto the first, and the shot kept
    assert "[0:v][ov]overlay=" in fc
    assert "shortest=1" in fc
    assert "aa=0.900" in fc
    assert "H-h-40" in fc


def test_overlay_clip_can_sit_at_the_top():
    ff, rec = _ffmpeg()
    ff.overlay_clip(Path("a.mp4"), Path("g.png"), Path("o.mp4"), position="top")
    fc = rec.cmds[-1][rec.cmds[-1].index("-filter_complex") + 1]
    assert "overlay=(W-w)/2:40" in fc


@needs_ffmpeg
def test_overlay_clip_never_hides_the_whole_shot(tmp_path: Path):
    """A banner is drawn *into* a real picture, and the picture stays visible.

    Checked on the produced file: a red shot with a banner over its lower band
    must still be red above the band. An implementation that substituted the
    banner for the shot would fail here — which is the point, because the
    invariant is "never fabricated", not "has an overlay filter".
    """
    ff = Ffmpeg()
    shot = tmp_path / "shot.png"
    _solid(shot, 320, 180, "red")
    base = tmp_path / "base.mp4"
    ff.still_to_clip(shot, base, 2.0, size=(640, 360), fps=10)

    # a 640x100 opaque green strip, positioned where a bottom banner sits
    graphic = tmp_path / "g.png"
    _solid(graphic, 640, 100, "green")
    out = tmp_path / "out.mp4"
    ff.overlay_clip(base, graphic, out, position="bottom", opacity=1.0, fade=0.0)

    assert ff.clip_geometry(out) == (640, 360)
    assert abs(ff.duration(out) - ff.duration(base)) < 0.4, "the take keeps its length"

    raw = ff.frame_rgb(out, 1.0, tmp_path / "o.raw", size=(640, 360))

    def at(x: int, y: int) -> tuple[int, int, int]:
        i = (y * 640 + x) * 3
        return raw[i], raw[i + 1], raw[i + 2]

    assert _dominant(at(320, 40)) == "red", "the shot is still there above the banner"
    assert _dominant(at(320, 310)) == "green", "the banner is where it was declared"


@needs_ffmpeg
def test_overlay_clip_fades_and_a_huge_fade_cannot_erase_it(tmp_path: Path):
    """``fade`` is clamped to a third of the clip, so a banner is never declared
    but entirely absent — a declaration that renders nothing is a lie."""
    ff = Ffmpeg()
    shot = tmp_path / "shot.png"
    _solid(shot, 320, 180, "red")
    base = tmp_path / "base.mp4"
    ff.still_to_clip(shot, base, 3.0, size=(640, 360), fps=10)
    graphic = tmp_path / "g.png"
    _solid(graphic, 640, 100, "green")

    out = tmp_path / "out.mp4"
    ff.overlay_clip(base, graphic, out, position="bottom", opacity=1.0, fade=99.0)
    raw = ff.frame_rgb(out, 1.5, tmp_path / "m.raw", size=(640, 360))
    i = (310 * 640 + 320) * 3
    assert _dominant((raw[i], raw[i + 1], raw[i + 2])) == "green"


# --------------------------------------------------------------------------- #
# transitions at concat (R-D6)
# --------------------------------------------------------------------------- #
class _Timed:
    """A Runner that reports every clip as 2.0s long and records the commands.

    The durations matter: an xfade offset is measured against the *running*
    length of the chain so far, so a test that only pretends the clips are
    zero-length cannot tell a correct chain from a drifting one.
    """

    def __init__(self, seconds: float = 2.0) -> None:
        self.cmds: list[list[str]] = []
        self.seconds = seconds

    def __call__(self, cmd):
        self.cmds.append([str(c) for c in cmd])
        h, rem = divmod(self.seconds, 3600)
        m, sec = divmod(rem, 60)
        return subprocess.CompletedProcess(
            list(cmd), 0, "", f"  Duration: {int(h):02d}:{int(m):02d}:{sec:05.2f}, start")


def test_concat_with_transitions_builds_one_xfade_per_junction():
    rec = _Timed(2.0)
    ff = Ffmpeg(Shell(rec))
    ff.concat_with_transitions(
        [Path("a.mp4"), Path("b.mp4"), Path("c.mp4")], Path("out.mp4"),
        transitions={1: ("fade", 0.5), 2: ("wipe", 0.4)})
    cmd = rec.cmds[-1]
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "xfade=transition=fade:duration=0.500" in fc
    assert "xfade=transition=wipeleft:duration=0.400" in fc
    assert fc.count("xfade=") == 2
    # The offset is when the dissolve starts, measured against the *running*
    # length of the chain so far: clip 1 ends at 2.0, so 2.0 - 0.5 = 1.5;
    # the chain then runs to 2.0 + 2.0 - 0.5 = 3.5, so 3.5 - 0.4 = 3.1.
    # Measuring each junction against a single clip's own length, rather than
    # the accumulated one, is exactly the drift this guards.
    assert "offset=1.500[v1]" in fc
    assert "offset=3.100[v2]" in fc


def test_concat_with_transitions_falls_back_to_a_hard_cut():
    ff, rec = _ffmpeg()
    ff.concat_with_transitions([Path("a.mp4"), Path("b.mp4")], Path("out.mp4"),
                               transitions={1: ("cut", 0.0)})
    fc = rec.cmds[-1][rec.cmds[-1].index("-filter_complex") + 1]
    assert "concat=n=2:v=1:a=0" in fc
    assert "xfade" not in fc


def test_concat_with_transitions_refuses_a_single_clip():
    from vidkit.errors import ToolError

    ff, _ = _ffmpeg()
    with pytest.raises(ToolError, match="at least two clips"):
        ff.concat_with_transitions([Path("a.mp4")], Path("out.mp4"), transitions={})


@needs_ffmpeg
def test_a_fade_dissolves_and_does_not_change_the_runtime(tmp_path: Path):
    """The dissolve is real, and it is *free*: the total length is unchanged.

    Both halves matter. A dissolve that did not dissolve would be a decoration
    that claims to be a transition; a dissolve that shortened the film would
    drift the pictures away from the narration, which is the master clock.
    """
    ff = Ffmpeg()
    red, blue = tmp_path / "red.png", tmp_path / "blue.png"
    _solid(red, 320, 180, "red")
    _solid(blue, 320, 180, "blue")
    a, b = tmp_path / "a.mp4", tmp_path / "b.mp4"
    # the *outgoing* take is rendered longer by exactly the dissolve, as the
    # assembler does it, so the incoming picture starts when its own narration
    # starts and the old one lingers over the first beat of the new one
    ff.still_to_clip(red, a, 2.6, size=(320, 180), fps=25)
    ff.still_to_clip(blue, b, 2.0, size=(320, 180), fps=25)

    out = tmp_path / "out.mp4"
    ff.concat_with_transitions([a, b], out, transitions={1: ("fade", 0.6)})
    assert abs(ff.duration(out) - 4.0) < 0.1, ff.duration(out)

    def pixel(at: float) -> tuple[int, int, int]:
        raw = ff.frame_rgb(out, at, tmp_path / "o.raw", size=(320, 180))
        i = (90 * 320 + 40) * 3
        return raw[i], raw[i + 1], raw[i + 2]

    assert _dominant(pixel(1.5)) == "red"
    assert _dominant(pixel(3.2)) == "blue"
    # mid-dissolve both pictures are on screen at once — which a hard cut can
    # never produce
    mid = pixel(2.3)
    assert mid[0] > 30 and mid[2] > 30, mid


@needs_ffmpeg
def test_a_wipe_transition_really_wipes(tmp_path: Path):
    ff = Ffmpeg()
    red, blue = tmp_path / "red.png", tmp_path / "blue.png"
    _solid(red, 320, 180, "red")
    _solid(blue, 320, 180, "blue")
    a, b = tmp_path / "a.mp4", tmp_path / "b.mp4"
    ff.still_to_clip(red, a, 2.6, size=(320, 180), fps=25)
    ff.still_to_clip(blue, b, 2.0, size=(320, 180), fps=25)
    out = tmp_path / "out.mp4"
    ff.concat_with_transitions([a, b], out, transitions={1: ("wipe", 0.6)})

    raw = ff.frame_rgb(out, 2.3, tmp_path / "w.raw", size=(320, 180))

    def at(x: int) -> tuple[int, int, int]:
        i = (90 * 320 + x) * 3
        return raw[i], raw[i + 1], raw[i + 2]

    # a wipe boundary, not a blend: one side has turned, the other has not
    left, right = _dominant(at(20)), _dominant(at(300))
    assert left != right, (left, right)
    assert {left, right} == {"red", "blue"}
