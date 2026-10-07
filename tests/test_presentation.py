"""Presentation v2 (M4): the time axis, `fit:`, and overlays.

Three separate claims live in here, and each of them is a claim about honesty
rather than a claim about rendering:

* **R-D3** — an x axis with real dates must draw real elapsed time. An index
  axis silently compresses a three-month gap into one step, which is a story
  the data does not tell.
* **R-D5** — a still must be fitted, never stretched. (The rendering half of
  this lives in ``test_ffmpeg.py``, where the pixels are read back.)
* **R-D4** — an overlay is drawn *over* a shot and can never stand in for one.

Everything here is pure Python; the pixel evidence is in ``test_ffmpeg.py``.
"""

from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path

import pytest

from vidkit import overlay as ov
from vidkit.errors import SpecError
from vidkit.panels import axis_positions, parse_x
from vidkit.spec import load_spec

# --------------------------------------------------------------------------- #
# the time axis (R-D3)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("label,expected", [
    ("2026-01-01", date(2026, 1, 1)),
    ("2026/01/01", date(2026, 1, 1)),
    ("01/01/2026", date(2026, 1, 1)),
    ("2026-01-01T10:30:00", date(2026, 1, 1)),
    ("2026-01-01 10:30:00", date(2026, 1, 1)),
    ("Jan 2026", date(2026, 1, 1)),
    ("January 2026", date(2026, 1, 1)),
    ("2026-01", date(2026, 1, 1)),
])
def test_parse_x_reads_a_date(label, expected):
    assert parse_x(label) == expected


@pytest.mark.parametrize("label", [
    "3",           # an index — must not be read as a year or a day
    "March",       # a category — no year, so there is no date to plot
    "Q1 2026",
    "",
    "   ",
    "row 3",
])
def test_parse_x_refuses_anything_ambiguous(label):
    """Only unambiguously dated labels become a time axis. Reading ``"3"`` as a
    date would invent a timeline the data never had — the exact fabrication the
    whole toolkit exists to prevent."""
    assert parse_x(label) is None


def test_axis_positions_follows_real_time_not_list_order():
    points = [("2026-01-01", 1), ("2026-01-02", 2), ("2026-04-01", 3)]
    pos = axis_positions(points)
    assert pos[0] == 0.0 and pos[-1] == 1.0
    # one day out of ninety is a hair's width, not a third of the axis
    assert pos[1] < 0.02
    assert pos == sorted(pos)


def test_axis_positions_falls_back_to_index_for_categories():
    assert axis_positions([("a", 1), ("b", 2), ("c", 3)]) == [0.0, 0.5, 1.0]


def test_axis_positions_falls_back_when_the_labels_disagree():
    """One non-date anywhere means the axis is not a timeline at all."""
    assert axis_positions([("2026-01-01", 1), ("beta", 2)]) == [0.0, 1.0]


def test_axis_positions_shrugs_at_a_single_day():
    """All the same day: there is no elapsed time to show, so do not divide by
    zero and do not pretend."""
    assert axis_positions([("2026-01-01", 1), ("2026-01-01", 2)]) == [0.0, 1.0]


def test_line_series_draws_the_gap():
    from vidkit.svg import PanelDoc
    from vidkit import panels

    doc = PanelDoc(1920, 1080)
    panels.render("line_series", {"series": [
        {"label": "visits", "points": [["2026-01-01", 1],
                                        ["2026-01-02", 2],
                                        ["2026-04-01", 3]]}]},
        {"x0": 0, "x1": 1000, "y0": 0, "y1": 100}, doc)
    svg = doc.svg()
    # the middle point sits within a hair of the left edge instead of halfway
    xs = [float(p.split(",")[0]) for p in
          svg.split('points="')[1].split('"')[0].split()]
    assert xs[0] < 5 and xs[2] > 995
    assert xs[1] < 30


def test_x_axis_index_opts_out_of_the_time_axis():
    from vidkit.svg import PanelDoc
    from vidkit import panels

    doc = PanelDoc(1920, 1080)
    panels.render("line_series", {"series": [
        {"label": "v", "points": [["2026-01-01", 1], ["2026-04-01", 2]]}]},
        {"x0": 0, "x1": 1000, "y0": 0, "y1": 100, "x_axis": "index"}, doc)
    xs = [float(p.split(",")[0]) for p in
          doc.svg().split('points="')[1].split('"')[0].split()]
    assert xs == [0.0, 1000.0]


# --------------------------------------------------------------------------- #
# fit: (R-D5)
# --------------------------------------------------------------------------- #
BASE = {
    "project": {"title": "T", "slug": "t", "output": "t.mp4", "min_seconds": 10,
                "max_seconds": 20},
    "narration": {"inline": {"0": "hello world"}},
    "scenes": [{"n": 0, "title": "s", "shots": [{"still": "a.svg"}]}],
}


def _spec(tmp_path: Path, mutate, name="video.json") -> Path:
    raw = json.loads(json.dumps(BASE))
    mutate(raw)
    (tmp_path / "a.svg").write_text("<svg/>", encoding="utf-8")
    p = tmp_path / name
    p.write_text(json.dumps(raw), encoding="utf-8")
    return p


def test_fit_defaults_to_cover(tmp_path):
    spec = load_spec(_spec(tmp_path, lambda r: None))
    assert spec.scenes[0].shots[0].fit == "cover"


def test_fit_can_be_declared_contain(tmp_path):
    spec = load_spec(_spec(tmp_path, lambda r: r["scenes"][0]["shots"][0]
                           .update(fit="contain")))
    assert spec.scenes[0].shots[0].fit == "contain"


def test_fit_refuses_an_unknown_value(tmp_path):
    with pytest.raises(SpecError, match="fit must be one of contain, cover"):
        load_spec(_spec(tmp_path, lambda r: r["scenes"][0]["shots"][0]
                        .update(fit="stretch")))


# --------------------------------------------------------------------------- #
# overlays (R-D4)
# --------------------------------------------------------------------------- #
def test_no_overlay_by_default(tmp_path):
    assert load_spec(_spec(tmp_path, lambda r: None)).scenes[0].overlay is None


def test_banner_overlay_parses(tmp_path):
    spec = load_spec(_spec(tmp_path, lambda r: r["scenes"][0].update(
        overlay={"kind": "banner", "kicker": "Live", "text": "9 rows"})))
    o = spec.scenes[0].overlay
    assert o.kind == "banner" and o.text == "9 rows" and o.kicker == "Live"
    assert o.position == "bottom" and o.height == 0.16


def test_banner_overlay_needs_no_asset(tmp_path):
    """The banner is built from the scene's own words, so a spec with a banner
    and an empty asset directory still loads."""
    spec = load_spec(_spec(tmp_path, lambda r: r["scenes"][0].update(
        overlay={"kind": "banner"})))
    assert spec.scenes[0].overlay.src is None


def test_overlay_refuses_a_non_mapping(tmp_path):
    with pytest.raises(SpecError, match="overlay must be a mapping"):
        load_spec(_spec(tmp_path, lambda r: r["scenes"][0].update(overlay="x")))


def test_overlay_refuses_an_unknown_kind(tmp_path):
    with pytest.raises(SpecError, match="overlay kind must be one of banner, image"):
        load_spec(_spec(tmp_path, lambda r: r["scenes"][0].update(
            overlay={"kind": "sticker"})))


def test_overlay_refuses_a_bad_position(tmp_path):
    with pytest.raises(SpecError, match="overlay position must be one of bottom, top"):
        load_spec(_spec(tmp_path, lambda r: r["scenes"][0].update(
            overlay={"kind": "banner", "position": "middle"})))


def test_overlay_refuses_a_height_that_is_not_a_band(tmp_path):
    for bad in (0.01, 0.9):
        with pytest.raises(SpecError, match="overlay height must be between"):
            load_spec(_spec(tmp_path, lambda r, b=bad: r["scenes"][0].update(
                overlay={"kind": "banner", "height": b}), name=f"h{bad}.json"))


def test_image_overlay_needs_a_src(tmp_path):
    with pytest.raises(SpecError, match="an image overlay needs a src"):
        load_spec(_spec(tmp_path, lambda r: r["scenes"][0].update(
            overlay={"kind": "image"})))


def test_image_overlay_refuses_a_file_that_is_not_there(tmp_path):
    """An overlay is drawn from a file that exists, never invented — so a typo
    is a load-time refusal rather than a blank band in the finished film."""
    with pytest.raises(SpecError, match="overlay image not found: logo.png"):
        load_spec(_spec(tmp_path, lambda r: r["scenes"][0].update(
            overlay={"kind": "image", "src": "logo.png"})))


def test_image_overlay_loads_when_the_file_exists(tmp_path):
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    spec = load_spec(_spec(tmp_path, lambda r: r["scenes"][0].update(
        overlay={"kind": "image", "src": "logo.png"})))
    assert spec.scenes[0].overlay.src == "logo.png"


# --------------------------------------------------------------------------- #
# the banner graphic
# --------------------------------------------------------------------------- #
def test_an_overlay_cannot_stand_in_for_a_shot(tmp_path):
    """An overlay is decoration on evidence. Letting it fill an empty scene
    would put a frame on screen with nothing behind it, which is the one thing
    this project exists to prevent."""
    def empty(raw):
        raw["scenes"][0]["overlay"] = {"kind": "banner", "text": "nothing behind this"}
        raw["scenes"][0]["shots"] = []
    with pytest.raises(SpecError, match="scene 0 has no shots"):
        load_spec(_spec(tmp_path, empty))


def test_banner_size_is_a_band_inside_the_frame():
    w, h = ov.banner_size((1920, 1080), 0.16)
    assert w < 1920, "the banner does not run off the sides"
    assert abs(h - 173) <= 1
    assert h < 1080 / 2, "a banner is a band, not a panel"


def test_banner_size_survives_a_degenerate_request():
    w, h = ov.banner_size((1, 1), 0.04)
    assert w >= 16 and h >= 16


def test_banner_svg_is_a_transparent_document():
    svg = ov.banner_svg("Nine hundred rows", "Live", (1200, 160))
    assert svg.startswith("<svg")
    assert "Nine hundred rows" in svg and "LIVE" in svg
    assert "<rect width=\"1200\"" not in svg.split("</defs>")[0], "no opaque backdrop"


def test_banner_svg_escapes_the_scene_title():
    """Scene titles are data, and data that reaches an SVG is escaped. A title
    is not an injection point."""
    svg = ov.banner_svg("a & b <b>", "", (400, 80))
    assert "&amp;" in svg and "&lt;b&gt;" in svg


def test_svg_size_reads_the_declared_geometry(tmp_path):
    p = tmp_path / "d.svg"
    p.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="940" height="620" '
                 'viewBox="0 0 940 620"></svg>', encoding="utf-8")
    assert ov.svg_size(p) == (940, 620)


def test_svg_size_is_none_when_the_file_does_not_say(tmp_path):
    p = tmp_path / "d.svg"
    p.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"></svg>',
                 encoding="utf-8")
    assert ov.svg_size(p) is None


# --------------------------------------------------------------------------- #
# the verify check behind the aspect claim
# --------------------------------------------------------------------------- #
def test_declared_size_check_probes_the_frames(tmp_path):
    """A geometry claim must be read back from the produced film, not inferred
    from the filter string — the filter can look right and still be wrong."""
    from vidkit.assembler import make_context
    from vidkit.ffmpeg import Ffmpeg
    from vidkit.verify import verify_output

    spec_path = _spec(tmp_path, lambda r: r["project"].update(size=[640, 360]))
    ctx = make_context(spec_path, tmp_path / "out")
    ctx.ensure_dirs()

    ff = Ffmpeg()
    if not ff.available:
        pytest.skip("ffmpeg not installed")
    track = ctx.clips / "video-track.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "color=c=red:s=640x360", "-frames:v", "1", str(ctx.stills / "a.png")],
        check=True, capture_output=True)
    ff.still_to_clip(ctx.stills / "a.png", track, 1.0, size=(640, 360), fps=10)

    from vidkit.assembler import Assets
    assets = Assets(video_track=track)
    rep = verify_output(ctx, assets, {0: "hello"})
    check = next(c for c in rep.checks if c.name == "frames are the declared size")
    assert check.ok, check.detail
    assert rep.facts["video_size"] == [640, 360]

    # and a film of the wrong size must fail the same check
    wrong = ctx.clips / "wrong.mp4"
    ff.still_to_clip(ctx.stills / "a.png", wrong, 1.0, size=(320, 180), fps=10)
    rep = verify_output(ctx, Assets(video_track=wrong), {0: "hello"})
    check = next(c for c in rep.checks if c.name == "frames are the declared size")
    assert not check.ok and "320x180" in check.detail


# --------------------------------------------------------------------------- #
# the three new panel kinds (R-D1/D2)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("kind,data,needle", [
    ("progress", {"steps": [{"label": "indexed", "done": True},
                            {"label": "captured", "active": True, "note": "2 of 5"}]},
     "captured"),
    ("comparison", {"left": {"title": "before", "items": ["9 rows"]},
                    "right": {"title": "after", "items": ["908 rows"]}}, "908 rows"),
    ("quote", {"text": "Measure, then draw.", "who": "the owner"}, "the owner"),
])
def test_new_panel_kinds_draw_their_data(kind, data, needle):
    from vidkit import panels
    from vidkit.svg import PanelDoc

    doc = PanelDoc(1920, 1080).head("T", "k")
    panels.render(kind, data, {}, doc)
    assert needle in doc.svg()


def test_progress_refuses_an_empty_row():
    from vidkit import panels
    from vidkit.svg import PanelDoc

    with pytest.raises(SpecError, match="progress: no steps"):
        panels.render("progress", {"steps": []}, {}, PanelDoc(1920, 1080))


def test_comparison_draws_both_sides_at_the_same_size():
    """The two columns differ in content only — never in geometry or type, or
    the layout would be making the argument instead of the data."""
    from vidkit import panels
    from vidkit.svg import PanelDoc

    doc = PanelDoc(1920, 1080)
    panels.render("comparison", {"left": {"title": "before", "items": ["a"]},
                                 "right": {"title": "after", "items": ["b"]}},
                  {}, doc)
    rects = [ln for ln in doc.svg().splitlines()
             if ln.strip().startswith("<rect") and 'width="1920"' not in ln]
    boxes = [(float(ln.split('x="')[1].split('"')[0]),
              float(ln.split('width="')[1].split('"')[0])) for ln in rects]
    assert len(boxes) == 2, boxes
    assert boxes[0][1] == boxes[1][1], "the two columns are the same width"
    # mirror images about the centre: layout never favours one side
    left_x, right_x, w = boxes[0][0], boxes[1][0], boxes[0][1]
    assert abs(left_x - (1920 - right_x - w)) < 0.5, boxes


def test_quote_needs_something_to_quote():
    from vidkit import panels
    from vidkit.svg import PanelDoc

    with pytest.raises(SpecError, match="quote: nothing to quote"):
        panels.render("quote", {}, {}, PanelDoc(1920, 1080))


# --------------------------------------------------------------------------- #
# transitions (R-D6)
# --------------------------------------------------------------------------- #
def test_transition_defaults_to_a_hard_cut(tmp_path):
    spec = load_spec(_spec(tmp_path, lambda r: None))
    assert spec.project.transition == "cut"


@pytest.mark.parametrize("kind", ["fade", "wipe", "slide"])
def test_transition_can_be_declared(tmp_path, kind):
    spec = load_spec(_spec(tmp_path, lambda r: r["project"].update(transition=kind)))
    assert spec.project.transition == kind


def test_transition_refuses_an_unknown_kind(tmp_path):
    with pytest.raises(SpecError, match="project.transition must be one of cut"):
        load_spec(_spec(tmp_path, lambda r: r["project"].update(transition="page-turn")))


def test_transition_seconds_must_be_a_beat_not_a_shot(tmp_path):
    """A transition is a beat between two filmed states. Long enough to be a
    shot of its own and it stops being a way of cutting."""
    for bad in (0.0, 5.0):
        with pytest.raises(SpecError, match="transition_seconds must be between"):
            load_spec(_spec(tmp_path, lambda r, b=bad: r["project"].update(
                transition="fade", transition_seconds=b), name=f"t{bad}.json"))


def test_a_hard_cut_accepts_any_transition_seconds(tmp_path):
    """``cut`` ignores the duration, so it is not validated — a spec that turns
    transitions off should not have to also delete the number."""
    spec = load_spec(_spec(tmp_path, lambda r: r["project"].update(
        transition="cut", transition_seconds=9.0)))
    assert spec.project.transition_seconds == 9.0


# --------------------------------------------------------------------------- #
# transitions through the whole pipeline
# --------------------------------------------------------------------------- #
def _two_scene_spec(tmp_path: Path, *, transition="cut", seconds=0.6, overlay=None):
    """``min_seconds: 4`` and five words a scene is 2.0 s of narration a scene,
    so the finished film must be 4.0 s whatever the transition does."""
    for name, colour in (("red.svg", "#ff0000"), ("blue.svg", "#0000ff")):
        (tmp_path / name).write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180">'
            f'<rect width="320" height="180" fill="{colour}"/></svg>', encoding="utf-8")
    scenes = [{"n": 1, "title": "A", "shots": [{"still": "red.svg"}]},
              {"n": 2, "title": "B", "shots": [{"still": "blue.svg"}]}]
    if overlay is not None:
        scenes[0]["overlay"] = overlay
    raw = {
        "project": {"slug": "t", "title": "T", "output": "t.mp4", "size": [320, 180],
                    "fps": 25, "min_seconds": 4, "max_seconds": 60,
                    "transition": transition, "transition_seconds": seconds},
        "scenes": scenes,
        "guard": {"require_audio": False},
        "narration": {"inline": {1: "one two three four five",
                                 2: "one two three four five"}},
    }
    p = tmp_path / "video.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    return p


def _track_rgb(ff, track: Path, at: float, size=(320, 180)):
    raw = ff.frame_rgb(track, at, track.parent / "f.raw", size=size)
    w, h = size

    def px(x, y):
        return tuple(raw[((y * w) + x) * 3:((y * w) + x) * 3 + 3])

    return px


@pytest.mark.parametrize("transition", ["fade", "wipe", "slide"])
def test_a_transition_never_changes_the_runtime(tmp_path, transition):
    """Narration is the master clock. A dissolve *overlaps* two takes, so the
    time it overlaps must be taken back — otherwise every transition silently
    desynchronises the pictures from the voice."""
    from vidkit.assembler import run
    from vidkit.ffmpeg import Ffmpeg

    ff = Ffmpeg()
    if not ff.available:
        pytest.skip("ffmpeg not installed")
    spec_path = _two_scene_spec(tmp_path, transition=transition)
    assets = run(spec_path, out_dir=tmp_path / "out")
    track = tmp_path / "out" / "_build" / "clips" / "video-track.mp4"
    spoken = sum(a.seconds for a in assets.scene_audio)
    assert abs(ff.duration(track) - spoken) < 0.05
    assert abs(spoken - 4.0) < 0.01


def test_a_wipe_is_a_boundary_and_not_a_blend(tmp_path):
    """`wipe` is the honest alternative to `fade`: it says "this replaced that"
    at a definite instant. A blend where a boundary was promised would be a
    different claim, so the seam is read back off the pixels."""
    from vidkit.assembler import run
    from vidkit.ffmpeg import Ffmpeg

    ff = Ffmpeg()
    if not ff.available:
        pytest.skip("ffmpeg not installed")
    spec_path = _two_scene_spec(tmp_path, transition="wipe")
    run(spec_path, out_dir=tmp_path / "out")
    track = tmp_path / "out" / "_build" / "clips" / "video-track.mp4"
    # the dissolve runs 2.0 -> 2.6; halfway through, both pictures are on screen
    px = _track_rgb(ff, track, 2.3)
    left, right = px(20, 90), px(300, 90)
    assert left[0] > 150 and left[2] < 100, left   # red still standing on the left
    assert right[2] > 150 and right[0] < 100, right  # blue has entered from the right


def test_a_hard_cut_leaves_no_seam_at_all(tmp_path):
    """The control for the test above: with no transition the very same moment
    is one picture or the other, never two."""
    from vidkit.assembler import run
    from vidkit.ffmpeg import Ffmpeg

    ff = Ffmpeg()
    if not ff.available:
        pytest.skip("ffmpeg not installed")
    spec_path = _two_scene_spec(tmp_path, transition="cut")
    run(spec_path, out_dir=tmp_path / "out")
    track = tmp_path / "out" / "_build" / "clips" / "video-track.mp4"
    px = _track_rgb(ff, track, 1.9)
    assert px(20, 90) == px(300, 90)


def test_overlays_and_transitions_survive_a_resumed_concat(tmp_path):
    """`--from concat` re-reads the clips directory. The pre-overlay takes live
    in `clips/base/`, so a resumed run must still find exactly the finished ones
    — and the overlay must still be on the outgoing clip when the dissolve
    starts, because the extra time the dissolve needs is added to *that* clip."""
    from vidkit.assembler import run
    from vidkit.ffmpeg import Ffmpeg

    ff = Ffmpeg()
    if not ff.available:
        pytest.skip("ffmpeg not installed")
    spec_path = _two_scene_spec(tmp_path, transition="fade",
                                overlay={"kind": "banner", "text": "the seam"})
    out = tmp_path / "out"
    run(spec_path, out_dir=out)
    first = ff.duration(out / "_build" / "clips" / "video-track.mp4")

    resumed = run(spec_path, out_dir=out, from_stage="concat")
    track = out / "_build" / "clips" / "video-track.mp4"
    assert abs(ff.duration(track) - first) < 0.05
    assert resumed.video_track == track
    px = _track_rgb(ff, track, 1.0)
    assert px(160, 40)[0] > 150, px(160, 40)   # the shot is still the shot
    assert sum(px(160, 160)) > 200, px(160, 160)  # and the banner is over it
