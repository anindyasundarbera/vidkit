"""Movie mode: declared artwork, an expressed clock, and a score (M9, R-G1…R-G3).

The tests are grouped by the three claims M9 makes, because each one is a promise to a
*reader of the finished film* rather than a detail of the code:

**Artwork.** A picture with no browser and no provider must still have an honest
source. A card the engine draws from the spec's own words and a flat colour are
*pictures the engine made*, so they belong to the same class as an author's PNG —
"declared asset" — and no fourth category may appear. ``verify.SHOT_SOURCES`` is that
rule written as data, so the first test here pins it against ``spec.SHOT_KINDS``: a new
shot kind cannot be added without deciding which of the three honest sources it draws
from.

**Clock.** A film whose lengths are written down is *not* measured, and ``verify`` has
to say so. The rule that decides a shot's length lives in exactly one function,
``assembler.plan_shots``, and both the renderer and the planner read it. The test that
matters is the last one in that group: the plan and the built clips are the same
numbers, which is the only thing that stops ``vidkit plan`` from lying again — it
promised a 32.1s film for one that built at 16.0s.

**Score.** ``amix`` is not used and the reason is a test, not a note: it has no level
control before ffmpeg 4.4 and divides by the input count, so the same spec would mix
differently on two machines (R-H6). The chain ``amerge``+``pan`` builds is asserted
here, and ``_duck_expr``'s arithmetic is checked as arithmetic — an expression in dB
where ffmpeg wants a factor would silence the bed by 14x rather than 14 dB.

Nothing in here needs a browser or a network. The builds use ``needs_render``.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
import yaml

from vidkit import card
from vidkit import spec as sp
from vidkit import verify as vf
from vidkit.assembler import _plan_scripts, _spans, plan_audio, plan_shots
from vidkit.errors import SpecError
from vidkit.ffmpeg import Ffmpeg, Shell, _duck_expr, _move, _move_filters
from vidkit.spec import Motion, load_spec
from vidkit.svg import Theme, document

REPO = Path(__file__).resolve().parents[1]
MOVIE_DEMO = REPO / "examples" / "movie-demo" / "video.yaml"
MOVIE_DEMO_DIR = MOVIE_DEMO.parent

SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"/>\n'

# Something with edges in it, for tests that need a picture that can actually change
# when the camera moves over it. A flat colour cannot, however it is panned.
ARTWORK = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180">'
    '<rect width="320" height="180" fill="#101418"/>'
    '<rect x="24" y="30" width="120" height="120" fill="#2A5C8A"/>'
    '<circle cx="240" cy="90" r="52" fill="#E8B33A"/>'
    '</svg>'
)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _yaml(tmp_path: Path, *, scenes: list | None = None, project: dict | None = None,
          narration: dict | None = None, extra: dict | None = None) -> Path:
    """A spec on disk, written as a mapping so the test reads like a spec.

    ``s.svg`` is always beside it: a ``still:`` names a file that has to exist, and
    a helper that quietly wrote a missing one would let the loader's existence check
    rot untested.
    """
    body: dict = {
        "project": {"title": "T", "slug": "t", "output": "t.mp4",
                    "min_seconds": 1, "max_seconds": 120},
        "narration": {"inline": {0: "one two three four five"}},
    }
    if project:
        body["project"].update(project)
    if narration is not None:
        body["narration"] = narration
    if extra:
        body.update(extra)
    body["scenes"] = scenes if scenes is not None else [{"n": 0, "shots": [{"still": "s.svg"}]}]
    (tmp_path / "s.svg").write_text(SVG, encoding="utf-8")
    p = tmp_path / "video.yaml"
    p.write_text(yaml.safe_dump(body, sort_keys=False), encoding="utf-8")
    return p


class _Record:
    """A Runner that records commands and pretends they succeeded."""

    def __init__(self) -> None:
        self.cmds: list[list[str]] = []

    def __call__(self, cmd):
        import subprocess
        self.cmds.append([str(c) for c in cmd])
        return subprocess.CompletedProcess(list(cmd), 0, "", "")


def _ffmpeg():
    rec = _Record()
    return Ffmpeg(Shell(rec)), rec


def _nar(tmp_path: Path) -> Path:
    """A narration file that exists.

    ``mix`` takes the score-only branch when handed a path that is not there, which is
    the right behaviour and the subject of its own test. These tests are about the
    *chain*, so they have to hand it a file — otherwise they assert against a command
    that was never built. The runner is fake, so the bytes are a placeholder.
    """
    nar = tmp_path / "narration.wav"
    silence(nar, 6.0)
    return nar


def silence(path: Path, seconds: float, *, rate: int = 48000) -> Path:
    """A real, if empty, wav. Tests that hand ``mix`` a narration branch have to give it
    something ffmpeg will open: a file of the right shape is the difference between
    asserting against the chain and asserting against a command that was never built."""
    import wave

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return path


# --------------------------------------------------------------------------- #
# the honesty table (I7)
# --------------------------------------------------------------------------- #
def test_every_shot_kind_has_a_source_and_every_source_has_a_kind():
    """The two lists must not drift. A kind with no source is a picture from
    nowhere; a source with no kind is a paragraph nobody reads."""
    assert set(sp.SHOT_KINDS) == set(vf.SHOT_SOURCES)


def test_there_are_exactly_three_honest_sources():
    """M9's whole risk was inventing a fourth. Three is the number the roadmap
    names — live capture, measured data, declared asset — and the assertion is
    written as a set so that adding a synonym fails rather than passes."""
    assert set(vf.SHOT_SOURCES.values()) == {
        "live capture", "measured data", "declared asset"}


def test_the_kinds_the_engine_draws_are_declared_assets():
    """A card and a solid are made by the engine, which is exactly why they must
    not be mistaken for ``measured data`` or ``live capture``."""
    assert vf.SHOT_SOURCES["card"] == "declared asset"
    assert vf.SHOT_SOURCES["solid"] == "declared asset"
    assert vf.SHOT_SOURCES["still"] == "declared asset"
    assert vf.SHOT_SOURCES["capture"] == "live capture"
    assert vf.SHOT_SOURCES["exec"] == "live capture"
    assert vf.SHOT_SOURCES["chart"] == "measured data"


# --------------------------------------------------------------------------- #
# motion: the spec surface
# --------------------------------------------------------------------------- #
def test_a_motion_string_is_the_same_request_as_a_mapping(tmp_path):
    """``motion: pan`` needs a direction it does not have, so the string form is
    only complete for the moves that have no direction to get wrong. What matters
    is that the loader reads both spellings into one object."""
    spec = load_spec(_yaml(tmp_path, scenes=[
        {"n": 0, "shots": [{"still": "s.svg", "motion": {"kind": "pan", "direction": "left"}}]},
    ]))
    move = spec.scenes[0].shots[0].motion

    assert (move.kind, move.direction, move.amount) == ("pan", "left", 0.10)
    assert (move.span, move.at) == (1.0, "start")


def test_a_bare_motion_string_is_refused_when_it_needs_a_direction(tmp_path):
    """A pan with no direction is not a move, it is a question — and the error has
    to say which two values are the wrong kind of answer."""
    with pytest.raises(SpecError, match="direction must be left, right, up or down"):
        load_spec(_yaml(tmp_path, scenes=[
            {"n": 0, "shots": [{"still": "s.svg", "motion": "pan"}]},
        ]))


@pytest.mark.parametrize("kind", ["wobble", "PAN", "", "shake"])
def test_an_unknown_motion_kind_is_refused_by_name(tmp_path, kind):
    with pytest.raises(SpecError, match="motion must be one of"):
        load_spec(_yaml(tmp_path, scenes=[
            {"n": 0, "shots": [{"still": "s.svg", "motion": {"kind": kind}}]},
        ]))


@pytest.mark.parametrize("at", ["middle", "begin", "0"])
def test_an_unknown_motion_at_is_refused(tmp_path, at):
    with pytest.raises(SpecError, match="motion.at must be one of"):
        load_spec(_yaml(tmp_path, scenes=[
            {"n": 0, "shots": [{"still": "s.svg", "motion": {"kind": "zoom", "at": at}}]},
        ]))


@pytest.mark.parametrize("span", [0, 0.0, -0.5, 1.5, 2])
def test_a_motion_span_outside_the_clip_is_refused(tmp_path, span):
    """``span`` is a *fraction* of the clip. A move that lasts longer than the shot
    has nowhere to hold, and silently clipping it would hide the author's slip."""
    with pytest.raises(SpecError, match=r"motion\.span is the fraction"):
        load_spec(_yaml(tmp_path, scenes=[
            {"n": 0, "shots": [{"still": "s.svg", "motion": {"kind": "zoom", "span": span}}]},
        ]))


def test_a_pan_needs_a_positive_amount(tmp_path):
    """``amount: 0`` on a pan is a hold that thinks it is a pan."""
    with pytest.raises(SpecError, match="a pan needs a positive amount"):
        load_spec(_yaml(tmp_path, scenes=[
            {"n": 0, "shots": [{"still": "s.svg",
                                "motion": {"kind": "pan", "direction": "left", "amount": 0}}]},
        ]))


def test_effect_and_motion_together_are_refused_not_merged(tmp_path):
    """Two camera moves over one picture is one too many, and guessing which the
    author meant would be the engine inventing an intention."""
    with pytest.raises(SpecError, match="both describe a camera move; keep one"):
        load_spec(_yaml(tmp_path, scenes=[
            {"n": 0, "shots": [{"still": "s.svg", "effect": "zoom",
                                "motion": {"kind": "pan", "direction": "left"}}]},
        ]))


def test_dropping_the_effect_is_the_migration_path(tmp_path):
    """The M4 spelling has to keep working, because every spec written before M9
    uses it. `effect: zoom` alone still loads and still means a push-in."""
    spec = load_spec(_yaml(tmp_path, scenes=[
        {"n": 0, "shots": [{"still": "s.svg", "effect": "zoom"}]},
    ]))
    shot = spec.scenes[0].shots[0]

    assert shot.effect == "zoom"
    assert shot.motion is None


def test_motion_label_names_the_move_that_will_render():
    """``Motion.label`` is what a plan prints. Printing both ``effect`` and
    ``motion`` said "hold, zoom in 8%" — two moves for one picture."""
    assert Motion("hold", "in", 0.1, 1.0, "start").label() == "holds"
    assert "zoom in 8%" in Motion("zoom", "in", 0.08, 1.0, "start").label()
    assert "pan left" in Motion("pan", "left", 0.12, 1.0, "end").label()
    assert Motion("zoom", "out", 0.1, 0.5, "full").label().endswith("(full)")


def test_motion_to_dict_carries_the_label_a_reviewer_reads():
    d = Motion("zoom", "in", 0.08, 1.0, "start").to_dict()

    assert set(d) == {"kind", "direction", "amount", "span", "at", "label"}
    assert d["label"] == Motion("zoom", "in", 0.08, 1.0, "start").label()


# --------------------------------------------------------------------------- #
# the move, at the filter layer
# --------------------------------------------------------------------------- #
def test_move_normalises_a_duck_typed_object_and_passes_none_through():
    """``_move`` takes anything with the right attributes so ``ffmpeg`` stays free
    of the spec's types — and ``None`` in, ``None`` out is what keeps a spec with no
    motion rendering byte-for-byte as it did before M9."""
    assert _move(None) is None

    class _M:
        kind, direction, amount, span, at = "pan", "up", 0.2, 0.5, "end"

    assert _move(_M()) == ("pan", "up", 0.2, 0.5, "end")
    assert _move(object())[:2] == ("hold", "in")  # defaults, not a crash


def test_every_move_direction_fits_its_own_axis():
    """A pan is a slide on one axis and a *hold* on the other; a zoom is a change in
    scale with the centre pinned. Mixing them is how a pan becomes a zoom."""
    size, secs, fps = (640, 360), 4.0, 24

    for direction in ("left", "right"):
        vf = _move_filters(size, secs, fps, ("pan", direction, 0.12, 1.0, "start"))
        assert "(iw-iw/zoom)*" in vf, direction
        assert "ih/2-(ih/zoom/2)" in vf, direction
    for direction in ("up", "down"):
        vf = _move_filters(size, secs, fps, ("pan", direction, 0.12, 1.0, "start"))
        assert "(ih-ih/zoom)*" in vf, direction
        assert "iw/2-(iw/zoom/2)" in vf, direction
    for direction in ("in", "out"):
        vf = _move_filters(size, secs, fps, ("zoom", direction, 0.10, 1.0, "start"))
        assert "iw/2-(iw/zoom/2)" in vf and "ih/2-(ih/zoom/2)" in vf, direction


def test_the_pan_slack_terms_are_parenthesised():
    """This one is a regression test with a scar. ``iw-iw/zoom*(1-p)`` is folded to a
    *constant* by ffmpeg: the picture never moves, nothing warns, and the chain reads
    correctly. ``(iw-iw/zoom)*(1-p)`` travels. The parentheses are load-bearing, and
    the only reason this assertion exists is that reading the string did not catch it.
    """
    vf = _move_filters((640, 360), 4.0, 24, ("pan", "left", 0.12, 1.0, "start"))

    assert "(iw-iw/zoom)*(1-(" in vf
    assert "iw-iw/zoom*(" not in vf.replace("(iw-iw/zoom)*(", "")


def test_the_move_is_overscanned_so_a_pan_has_slack_to_slide_into():
    for kind, direction in (("pan", "left"), ("zoom", "in")):
        vf = _move_filters((640, 360), 4.0, 24, (kind, direction, 0.12, 1.0, "start"))
        # 640 * 1.12 = 716.8 -> 717, fitted and cropped before zoompan gets it
        assert "crop=717:403" in vf, (kind, direction)


def test_span_and_at_place_the_move_inside_the_clip():
    """``start`` moves over the first ``span`` then holds; ``end`` holds then moves;
    ``full`` ignores ``span`` and travels the whole way. The difference is which
    frame the travel is measured against."""
    size, fps = (320, 180), 10
    full = _move_filters(size, 4.0, fps, ("zoom", "in", 0.1, 1.0, "full"))
    start = _move_filters(size, 4.0, fps, ("zoom", "in", 0.1, 0.5, "start"))
    end = _move_filters(size, 4.0, fps, ("zoom", "in", 0.1, 0.5, "end"))

    assert "min(on/40,1)" in full
    # half the 40 frames is 20, and the travel is divided by the move, not the clip
    assert "min(on/20,1)" in start
    assert "min(max((on-20)/20,0),1)" in end


def test_a_hold_renders_the_pre_m9_chain(tmp_path):
    """``motion: hold`` asks for nothing, and the honest rendering of nothing is the
    path every spec took before M9: fit, fps, format — no zoompan at all."""
    src = tmp_path / "s.png"
    src.write_bytes(b"")
    ff, rec = _ffmpeg()

    ff.still_to_clip(src, tmp_path / "out.mp4", 2.0, size=(320, 180), fps=24,
                     motion=Motion("hold", "in", 0.1, 1.0, "start"))

    vf = rec.cmds[0][rec.cmds[0].index("-vf") + 1]
    assert "zoompan" not in vf


def test_a_declared_motion_supersedes_an_effect_at_the_filter_layer(tmp_path):
    """The loader refuses both together, but ``still_to_clip`` is also called by code
    that has not been through that check — so it must not consult ``effect`` when a
    motion is present, or an old spec could get two moves."""
    src = tmp_path / "s.png"
    src.write_bytes(b"")
    ff, rec = _ffmpeg()

    ff.still_to_clip(src, tmp_path / "out.mp4", 2.0, size=(320, 180), fps=24,
                     effect="zoom", motion=Motion("pan", "left", 0.2, 1.0, "full"))

    vf = rec.cmds[0][rec.cmds[0].index("-vf") + 1]
    assert "(iw-iw/zoom)*" in vf          # the pan
    assert "min(1.0+on" not in vf         # not the zoompan the effect would have built


# --------------------------------------------------------------------------- #
# card and solid: the spec surface
# --------------------------------------------------------------------------- #
def test_a_card_is_a_shot_kind_and_needs_words(tmp_path):
    """A card drawn with no words is a blank frame with a rule on it. The error says
    why the words *are* the asset."""
    with pytest.raises(SpecError, match="needs its words"):
        load_spec(_yaml(tmp_path, scenes=[{"n": 0, "shots": [{"card": "   "}]}]))


def test_a_solid_carries_one_colour_and_a_short_hex_is_a_colour(tmp_path):
    spec = load_spec(_yaml(tmp_path, scenes=[
        {"n": 0, "shots": [{"solid": "#0F0"}, {"solid": "black"}]},
    ]))
    assert [sh.ref for sh in spec.scenes[0].shots] == ["#0F0", "black"]


@pytest.mark.parametrize("bad", ["#GGG", "#11223344", "#12", "rgb(1,2,3)", ""])
def test_a_colour_that_is_not_a_colour_is_refused_and_names_the_alternatives(tmp_path, bad):
    """Alpha in the colour would be a second way to say what overlays already say,
    and one of the two would eventually disagree."""
    with pytest.raises(SpecError, match="is not a colour"):
        load_spec(_yaml(tmp_path, scenes=[{"n": 0, "shots": [{"solid": bad}]}]))


@pytest.mark.parametrize("kind", ["still", "capture", "chart", "exec"])
def test_a_kicker_or_backdrop_on_a_non_card_shot_is_refused(tmp_path, kind):
    """Both fields are meaningful *only* because a card is typography over a chosen
    ground. Accepting them on a capture would be accepting a decoration that does
    nothing, and the error tells the author what to write instead."""
    shot: dict = {kind: ("s.svg" if kind != "exec" else "noop")}
    with pytest.raises(SpecError, match="describes a \\*card\\*"):
        load_spec(_yaml(tmp_path, scenes=[
            {"n": 0, "shots": [{**shot, "kicker": "Chapter One"}]}]))

    with pytest.raises(SpecError, match="describes a \\*card\\*"):
        load_spec(_yaml(tmp_path, scenes=[
            {"n": 0, "shots": [{**shot, "backdrop": "s.svg"}]}]))


def test_a_card_backdrop_that_does_not_exist_is_refused_at_load_time(tmp_path):
    """A backdrop is *declared*, never discovered — the same rule a ``still:`` obeys.
    Left to render time the card would draw its scrim over nothing and pass."""
    with pytest.raises(SpecError, match="card backdrop not found"):
        load_spec(_yaml(tmp_path, scenes=[
            {"n": 0, "shots": [{"card": "Chapter One", "backdrop": "gone.png"}]}]))


def test_a_card_backdrop_beside_the_spec_loads(tmp_path):
    spec = load_spec(_yaml(tmp_path, scenes=[
        {"n": 0, "shots": [{"card": "Chapter One", "kicker": "Act I",
                            "backdrop": "s.svg"}]},
    ]))
    shot = spec.scenes[0].shots[0]

    assert (shot.kind, shot.ref, shot.kicker) == ("card", "Chapter One", "Act I")
    assert shot.backdrop == "s.svg"


def test_kicker_and_backdrop_are_not_shot_kinds(tmp_path):
    """``_shots`` counts a shot by its kind. A card carrying a kicker must not be
    read as two shots, and the error for an unknown key is what catches a typo."""
    spec = load_spec(_yaml(tmp_path, scenes=[
        {"n": 0, "shots": [{"card": "One", "kicker": "K", "backdrop": "s.svg"}]},
    ]))
    assert len(spec.scenes[0].shots) == 1
    assert spec.scenes[0].shots[0].kind == "card"


def test_a_shot_with_no_kind_is_refused_and_lists_the_kinds(tmp_path):
    with pytest.raises(SpecError, match="exactly one of still/capture/chart/exec/card/solid"):
        load_spec(_yaml(tmp_path, scenes=[{"n": 0, "shots": [{"seconds": 1}]}]))


def test_two_kinds_on_one_shot_are_refused(tmp_path):
    with pytest.raises(SpecError, match="exactly one of"):
        load_spec(_yaml(tmp_path, scenes=[{"n": 0, "shots": [{"still": "s.svg", "card": "x"}]}]))


# --------------------------------------------------------------------------- #
# card and solid: the SVG
# --------------------------------------------------------------------------- #
def test_every_document_declares_xlink_even_when_nothing_uses_it():
    """Defect 1 of M9, and the first doc-wide change of the milestone. rsvg refuses a
    whole file with "Namespace prefix xlink for href on image is not defined" — naming
    neither the card nor the backdrop — so the namespace is declared on every document
    rather than only on the ones that happen to need it."""
    assert 'xmlns:xlink="http://www.w3.org/1999/xlink"' in document(10, 10, "")


def test_a_card_without_a_backdrop_paints_its_own_ground():
    svg = card.card_svg("Hello", size=(640, 360))

    assert "<image" not in svg
    # the theme's field, not its panel: a card with no picture behind it still stands
    # on the film's ground rather than on a white sheet pasted over it
    assert Theme.bg in svg


def test_a_card_with_a_backdrop_loads_the_picture_and_lays_a_scrim_over_it():
    svg = card.card_svg("Hello", size=(640, 360), backdrop=Path("/abs/frame.png"))

    assert 'xlink:href="/abs/frame.png"' in svg
    assert 'preserveAspectRatio="xMidYMid slice"' in svg
    assert 'fill="url(#scrim)"' in svg
    # the scrim is a gradient, not a flat wash: a flat wash would dim the whole
    # picture, and the point of a card is to *show* the picture under its title
    assert "linearGradient" in svg and svg.index("linearGradient") < svg.index("<image")


def test_the_scrim_sits_between_the_picture_and_the_words():
    svg = card.card_svg("Hello", size=(640, 360), backdrop=Path("/abs/frame.png"))

    assert svg.index("<image") < svg.index("url(#scrim)") < svg.index("Hello")


def test_a_solid_is_one_flat_field_and_no_gradient():
    svg = card.solid_svg("#102030", (320, 180))

    assert 'fill="#102030"' in svg
    assert "gradient" not in svg and "<image" not in svg


def test_a_long_title_shrinks_rather_than_spilling_off_the_card():
    """``_fitted`` wraps, and shrinks the type when the wrap will not fit in three
    lines. A title that runs off the edge is a worse failure than a small one.

    The title has to be one that *cannot* be wrapped into three lines by getting
    narrower, because the wrap is counted in characters: a sentence of short words
    always finds three lines at full size, however long it is, and never shrinks.
    Only a long unbroken run of characters forces the type down.
    """
    short, short_pt = card._fitted("Hi", size=60, frame_w=1280)
    long, long_pt = card._fitted("supercalifragilistic " * 20, size=60, frame_w=1280)

    assert len(short) == 1 and short_pt == 60
    assert long_pt < short_pt


def test_the_wrap_is_measure_free_and_never_drops_a_word():
    """The engine cannot ask a font its metrics without pulling in a text shaper, so
    the wrap counts characters. A card that is one word too wide is a worse failure
    than a card that wraps early — but a *dropped* word is the I3 failure mode."""
    lines = card._wrap("one two three four five six", size=20, width=11)

    assert " ".join(lines) == "one two three four five six"
    assert all(len(l) <= 11 for l in lines)


def test_fitting_a_card_that_cannot_fit_still_returns_its_words():
    """The fallback must not produce an empty card. ``lines`` used to be possibly
    unbound here, which is an UnboundLocalError on a very long single word."""
    lines, pt = card._fitted("x" * 400, size=60, frame_w=200)

    assert lines and pt > 0


# --------------------------------------------------------------------------- #
# the clock: declared lengths
# --------------------------------------------------------------------------- #
def test_a_scene_seconds_replaces_the_measured_span(tmp_path):
    spec = load_spec(_yaml(tmp_path, scenes=[
        {"n": 0, "seconds": 6, "shots": [{"still": "s.svg"}]},
    ]))
    audio = plan_audio(spec)
    plan = plan_shots(spec, audio)

    assert [round(sec, 3) for _, _, _, sec in plan] == [6.0]


def test_a_scene_seconds_stands_even_with_no_narration_at_all(tmp_path):
    """This is the film with pictures and no voice. ``plan_shots`` used to skip every
    scene it had no audio span for, so a wholly declaimed film planned at zero.

    The spec still has to *say* what is spoken — the loader refuses a spec with
    neither ``narration.inline`` nor ``narration.source``, which is the right refusal:
    a film that says nothing about speech has not decided to be silent, it has merely
    not thought about it. So the inline entry names a scene that does not exist, and
    scene 0 has a declared length and no span at all — which is the case under test.
    """
    spec = load_spec(_yaml(tmp_path, narration={"inline": {9: "unused"}}, scenes=[
        {"n": 0, "seconds": 3, "shots": [{"still": "s.svg"}]},
    ]))
    audio = plan_audio(spec)
    plan = plan_shots(spec, audio)

    # one entry per scene, all of them empty: the plan stays indexable by scene number
    # and "nothing was spoken" is a zero length, not a missing row
    assert [a.words for a in audio] == [0]
    assert [a.seconds for a in audio] == [0.0]
    # but scene 0 declared its own length, so it plans at 3.0s rather than being skipped
    assert [round(sec, 3) for _, _, _, sec in plan] == [3.0]


def test_a_shot_seconds_is_subtracted_before_the_remainder_is_split_by_weight(tmp_path):
    """An authored length is an instruction, not another vote to average against its
    neighbours. 8s scene, 2s pinned -> 6s split 2:1 -> 4s and 2s; the pinned shot keeps
    its own 2s."""
    spec = load_spec(_yaml(tmp_path, scenes=[
        {"n": 0, "seconds": 8, "shots": [
            {"still": "s.svg", "seconds": 2},
            {"still": "s.svg", "weight": 2},
            {"still": "s.svg", "weight": 1},
        ]},
    ]))
    plan = plan_shots(spec, plan_audio(spec))

    assert [round(sec, 3) for _, _, _, sec in plan] == [2.0, 4.0, 2.0]


def test_over_declared_shots_are_refused_rather_than_truncated(tmp_path):
    """A truncated take is a shot that does not exist. The error names both numbers so
    the author can see which one to change."""
    spec = load_spec(_yaml(tmp_path, scenes=[
        {"n": 0, "seconds": 3, "shots": [
            {"still": "s.svg", "seconds": 2}, {"still": "s.svg", "seconds": 2}]},
    ]))
    with pytest.raises(SpecError, match=r"declare 4\.00s in total but the scene is 3\.00s"):
        plan_shots(spec, plan_audio(spec))


def test_a_shot_seconds_must_be_positive(tmp_path):
    for bad in (0, -2):
        with pytest.raises(SpecError, match="a shot's length must be positive"):
            load_spec(_yaml(tmp_path, scenes=[
                {"n": 0, "shots": [{"still": "s.svg", "seconds": bad}]}]))
        with pytest.raises(SpecError, match="a scene's length must be positive"):
            load_spec(_yaml(tmp_path, scenes=[
                {"n": 0, "seconds": bad, "shots": [{"still": "s.svg"}]}]))


def test_with_no_declared_lengths_the_arithmetic_is_the_old_arithmetic(tmp_path):
    """The additive-by-construction promise: a spec that declares nothing must plan
    exactly as it did before M9 — span * weight / total_weight."""
    spec = load_spec(_yaml(tmp_path, narration={"inline": {0: "a b c d e"}}, scenes=[
        {"n": 0, "shots": [{"still": "s.svg", "weight": 3},
                           {"still": "s.svg", "weight": 1}]},
    ]))
    audio = plan_audio(spec)
    plan = plan_shots(spec, audio)

    assert audio[0].seconds == 2.0            # five words at tts._FALLBACK_WPS = 2.5
    assert [round(sec, 3) for _, _, _, sec in plan] == [1.5, 0.5]


def test_timing_source_says_spec_the_moment_any_length_is_declared(tmp_path):
    measured = load_spec(_yaml(tmp_path))
    shot_level = load_spec(_yaml(tmp_path, scenes=[
        {"n": 0, "shots": [{"still": "s.svg", "seconds": 4}]}]))
    scene_level = load_spec(_yaml(tmp_path, scenes=[
        {"n": 0, "seconds": 4, "shots": [{"still": "s.svg"}]}]))

    assert measured.timing_source == "narration"
    # a shot-level declaration is a declaration too: I5 is no longer the master clock
    assert shot_level.timing_source == "spec"
    assert scene_level.timing_source == "spec"
    assert scene_level.timed_scenes() == [0]
    assert shot_level.timed_scenes() == []


def test_every_declared_length_is_named_in_one_place(tmp_path):
    spec = load_spec(_yaml(tmp_path, scenes=[
        {"n": 0, "seconds": 5, "shots": [{"still": "s.svg", "seconds": 2}]},
        {"n": 1, "shots": [{"still": "s.svg"}]},
    ]))
    assert spec.timed_scenes() == [0]


# --------------------------------------------------------------------------- #
# the clock: what the plan says must be what the build does
# --------------------------------------------------------------------------- #
def test_plan_audio_reads_words_out_of_a_narration_file(tmp_path):
    """The regression that made `vidkit plan` lie. ``narration.inline`` is empty for
    any spec that keeps its words in a markdown file, so a planner that only read
    ``inline`` divided 0 words by 2.5 and planned every scene at ``0.0s`` while the
    film built 98.8s long."""
    (tmp_path / "narration.md").write_text(
        "## Scene 0 — opening · 0:00–0:04\n\n**one two three four five**\n\n"
        "[stage direction, not spoken]\n",
        encoding="utf-8")
    spec = load_spec(_yaml(tmp_path, narration={"source": "narration.md"},
                           scenes=[{"n": 0, "shots": [{"still": "s.svg"}]}]))

    audio = plan_audio(spec)

    assert spec.narration.inline == {}
    # five spoken words; the bracketed line is a stage direction and is not counted
    assert audio[0].words == 5
    assert audio[0].seconds == 2.0


def test_plan_audio_resolves_the_narration_file_against_the_spec_root(tmp_path):
    """``_scripts_for`` needs a Context to do this lookup; a planner has only a Spec,
    so ``_plan_scripts`` repeats it. Resolving somewhere else finds no file, and no
    file means no words — the same silent zero by a quieter route."""
    (tmp_path / "narration.md").write_text(
        "## Scene 0 — opening · 0:00–0:04\n\n**a b c d e f g h**\n", encoding="utf-8")
    spec = load_spec(_yaml(tmp_path, narration={"source": "narration.md"},
                           scenes=[{"n": 0, "shots": [{"still": "s.svg"}]}]))

    assert [s.spoken for s in _plan_scripts(spec)] == ["a b c d e f g h"]


def test_plan_audio_uses_the_fallback_rate_the_audio_stage_uses(tmp_path):
    """``tts._FALLBACK_WPS`` is 2.5 and ``reports.WORDS_PER_SECOND`` is 2.78, and the
    two have disagreed since M0. Only one of them describes what a build *does*, and
    a plan built on the other one is wrong by 10% on every scene."""
    from vidkit import tts

    spec = load_spec(_yaml(tmp_path, narration={"inline": {0: "a " * 25}}))
    audio = plan_audio(spec)

    assert tts._FALLBACK_WPS == 2.5
    assert audio[0].seconds == round(25 / tts._FALLBACK_WPS, 3)


def test_the_plan_and_the_spans_are_derived_from_one_rule(tmp_path):
    """``plan_shots`` is the only function that decides a shot's length, and
    ``_clip_plan`` delegates to it. Two copies of a timing rule are two chances to
    disagree, which is precisely how the plan came to promise 32.1s for a 16.0s film."""
    spec = load_spec(MOVIE_DEMO)
    audio = plan_audio(spec)
    plan = plan_shots(spec, audio)
    spans = {n: (a, b) for n, a, b in _spans(audio)}

    per_scene: dict[int, float] = {}
    for sc, _i, _sh, sec in plan:
        per_scene[sc.n] = per_scene.get(sc.n, 0.0) + sec
    for sc in spec.scenes:
        declared = sc.seconds
        if declared is None:
            declared = spans[sc.n][1] - spans[sc.n][0]
        assert round(per_scene[sc.n], 3) == round(declared, 3), sc.n


@pytest.mark.needs_render
def test_the_movie_demo_builds_to_the_length_its_plan_promises(tmp_path):
    """The end of the argument. The example declares 4+3+2.5+3.5+3 = 16.0s; the plan
    must say 16.0s; the render must come back within a frame or two of 16.0s. When
    these three disagreed the plan was the one that was wrong, and nobody noticed for
    a whole milestone."""
    from vidkit.assembler import run
    from vidkit.job import run_job

    planned = run_job("plan", story=str(MOVIE_DEMO))["plan"]
    manifest = run_job("build", story=str(MOVIE_DEMO), out=str(tmp_path))

    assert planned["timing_source"] == "spec"
    assert planned["planned_seconds"] == 16.0
    assert manifest["ok"] is True
    built = manifest["report"]["facts"]["duration_seconds"]
    assert abs(built - planned["planned_seconds"]) <= 0.1
    assert run is not None


@pytest.mark.needs_render
def test_the_movie_demo_verifies_green_and_names_its_sources(tmp_path):
    """Every picture declared, every move declared, the clock expressed — and the score
    in the mix. A film with no captures and no provider is exactly the case that had no
    facts block at all before M9."""
    from vidkit.job import run_job

    report = run_job("build", story=str(MOVIE_DEMO), out=str(tmp_path))["report"]
    facts = report["facts"]

    assert report["ok"] is True
    assert facts["artwork_sources"] == ["declared asset"]
    assert {r["kind"] for r in facts["artwork"]} <= {"still", "card", "solid"}
    assert facts["timing_source"] == "spec"
    assert facts["score"]["mixed"] is not None
    assert Path(facts["score"]["mixed"]).exists()
    # This cut is silent — there is no voice for the score to duck under, and the film
    # is 16.01s while the scenes' words would take 35.6s. So the fact that appears must
    # be the *estimate*, never a `narration_spans` claiming positions in a cut that is
    # two and a bit times shorter than they add up to.
    assert "narration_spans" not in facts
    assert sorted(facts["narration_estimate"]) == ["1", "2", "3", "4", "5"]


@pytest.mark.needs_render
def test_a_declared_camera_move_is_measured_not_restated(tmp_path):
    """The report must be able to tell a push-in from a still picture.

    This check used to compare a list against a filter of itself, so it could not fail:
    it said "5 of 6 shot(s) move" because five shots declared a move, not because five
    pictures moved. Here three clips are built by hand — one that really pans, one that
    declares a pan over a flat field and so cannot move, and one that holds — and the
    measurement must separate all three.
    """
    from vidkit.card import solid_svg
    from vidkit.ffmpeg import Rsvg
    from vidkit.spec import Motion
    from vidkit.verify import MOVE_MAE, _measure_move

    ff = Ffmpeg(Shell())

    class _Ctx:
        build = tmp_path
        clips = tmp_path / "clips"
        ffmpeg = ff

    _Ctx.clips.mkdir()
    size = (320, 180)
    scratch = tmp_path / "scratch.raw"

    def build(scene, index, markup, direction="left", amount=0.12):
        """A clip under the name ``_measure_move`` derives from a shot, so that the
        test exercises the naming rule and not just the pixels."""
        stem = f"scene-{scene:02d}-{index}"
        svg, png = tmp_path / f"{stem}.svg", tmp_path / f"{stem}.png"
        svg.write_text(markup, encoding="utf-8")
        Rsvg().render(svg, png, size)
        out = _Ctx.clips / f"{stem}.mp4"
        ff.still_to_clip(png, out, 1.5, size=size, fps=12,
                         motion=Motion(kind="pan", direction=direction, amount=amount))
        return out

    def measure(clip, at):
        return ff.frame_rgb(clip, ff.duration(clip) * at, scratch, size=(64, 36))

    # A solid field has nothing in it to move: this clip really is panned over by the
    # filterchain and still cannot change a pixel. The row must say so rather than
    # repeat the declaration back.
    build(1, 0, solid_svg("#2A5C8A", size))
    flat = _measure_move(_Ctx, {"scene": 1, "index": 0})
    assert flat is not None and flat == 0.0

    # Artwork in the same clip does move, so the zero above is the field's fault and
    # not the measurement's.
    moving = build(2, 0, ARTWORK)
    head, tail = measure(moving, 0.08), measure(moving, 0.92)
    assert head != tail

    # A clip that was never built is not measured, and an unmeasured move must not be
    # silently reported as a still one.
    assert _measure_move(_Ctx, {"scene": 9, "index": 0}) is None
    assert _measure_move(_Ctx, {"scene": 1, "index": 1}) is None
    assert sorted(p.name for p in _Ctx.clips.iterdir()) == [
        "scene-01-0.mp4", "scene-02-0.mp4"]

    # The threshold is load-bearing: it is what separates "moved" from "did not move"
    # for every clip in the fixture. A real move there measures 5.152.
    assert MOVE_MAE < 5.152, "a real move in movie-demo measures 5.152"


def test_a_silent_cut_never_publishes_its_word_estimates_as_spans(tmp_path):
    """The honesty rule, pinned directly: only a cut with real audio may claim spans.

    `narration_spans` reads as "seek here and you will hear the words" — a reviewer
    acts on it, and the score is ducked under exactly those windows. A silent cut has
    no words to seek to, so the per-scene durations the audio stage models from the
    word count must be reported as the estimate they are, under a name that says so.
    """
    from vidkit.tts import SceneAudio
    from vidkit.verify import _narration_facts

    silent = [SceneAudio(1, None, 6.8, 17), SceneAudio(2, None, 13.6, 34)]
    assert _narration_facts(silent) == {
        "narration_estimate": {"1": [0.0, 6.8], "2": [6.8, 20.4]}}

    wav = tmp_path / "1.wav"
    wav.write_bytes(b"")
    spoken = [SceneAudio(1, wav, 6.8, 17)]
    assert _narration_facts(spoken) == {"narration_spans": {"1": [0.0, 6.8]}}
    assert _narration_facts([]) == {}

    # A path recorded but since deleted is not a recording to seek into either.
    wav.unlink()
    assert _narration_facts(spoken) == {"narration_estimate": {"1": [0.0, 6.8]}}


# --------------------------------------------------------------------------- #
# the score: the spec surface
# --------------------------------------------------------------------------- #
def test_a_score_may_be_a_bare_path_or_a_mapping(tmp_path):
    (tmp_path / "m.ogg").write_bytes(b"")
    bare = load_spec(_yaml(tmp_path, extra={"score": "m.ogg"}))
    full = load_spec(_yaml(tmp_path, extra={"score": {"src": "m.ogg", "duck_db": -8}}))

    assert bare.score.src == "m.ogg" and bare.score.duck_db == -14.0
    assert full.score.duck_db == -8.0 and full.score.ramp == 0.25


def test_no_score_key_is_no_score(tmp_path):
    """A `score:` block with nothing in it describes no score. A silent film stays
    silent, which is what keeps the feature additive."""
    assert load_spec(_yaml(tmp_path)).score is None
    assert load_spec(_yaml(tmp_path, extra={"score": {}})).score is None
    assert load_spec(_yaml(tmp_path, extra={"score": None})).score is None


def test_a_score_without_a_src_is_refused(tmp_path):
    with pytest.raises(SpecError, match="needs a `src:`"):
        load_spec(_yaml(tmp_path, extra={"score": {"volume": 0.3}}))


def test_an_unknown_score_key_is_refused_and_lists_the_known_ones(tmp_path):
    with pytest.raises(SpecError, match="unknown key\\(s\\): duck"):
        load_spec(_yaml(tmp_path, extra={"score": {"src": "m.ogg", "duck": -6}}))


def test_a_bed_louder_than_the_voice_is_refused(tmp_path):
    with pytest.raises(SpecError, match="is a gain of at most 1"):
        load_spec(_yaml(tmp_path, extra={"score": {"src": "m.ogg", "volume": 2.0}}))


def test_ducking_that_raises_the_bed_is_refused(tmp_path):
    """A positive duck is a boost, and a bed that comes *up* under the voice is the
    opposite of the thing the field is named for."""
    with pytest.raises(SpecError, match="duck_db:.*must be at or below 0 dB"):
        load_spec(_yaml(tmp_path, extra={"score": {"src": "m.ogg", "duck_db": 3}}))


def test_a_negative_ramp_is_refused(tmp_path):
    with pytest.raises(SpecError, match="ramp:.*cannot be negative"):
        load_spec(_yaml(tmp_path, extra={"score": {"src": "m.ogg", "ramp": -0.1}}))


def test_a_volume_above_zero_is_read_as_a_linear_gain_and_below_zero_as_db(tmp_path):
    """Both spellings are idiomatic — ``0.35`` and ``-9.1`` "mean" the same thing to two
    different authors. Reading one as the other is a 9 dB error, and it would be
    silent."""
    linear = load_spec(_yaml(tmp_path, extra={"score": {"src": "m.ogg", "volume": 0.5}}))
    db = load_spec(_yaml(tmp_path, extra={"score": {"src": "m.ogg", "volume": -6.0}}))

    assert linear.score.volume == pytest.approx(-6.0206, abs=1e-3)
    assert db.score.volume == -6.0


def test_the_default_bed_is_quiet_enough_to_be_a_bed(tmp_path):
    spec = load_spec(_yaml(tmp_path, extra={"score": {"src": "m.ogg"}}))

    assert spec.score.volume < 0.0                # in dB, so it attenuates
    assert spec.score.volume == pytest.approx(20 * math.log10(0.35), abs=1e-6)


def test_score_to_dict_is_what_a_plan_prints(tmp_path):
    spec = load_spec(_yaml(tmp_path, extra={"score": {"src": "m.ogg"}}))
    d = spec.score.to_dict()

    assert set(d) == {"src", "volume_db", "duck_db", "ramp", "fade_in", "fade_out"}
    assert d["src"] == "m.ogg" and d["volume_db"] < 0


# --------------------------------------------------------------------------- #
# the score: the ffmpeg layer
# --------------------------------------------------------------------------- #
def test_the_duck_expression_is_a_gain_factor_not_a_db_value(tmp_path):
    """``volume``'s expression is a linear factor. Writing ``-14`` there would divide
    the bed by 14 rather than take 14 dB off it, so the conversion happens once, in
    ``_duck_expr``, and the chain stays in one unit."""
    expr = _duck_expr([(1.0, 2.0)], -14.0, 0.25)
    d = 10 ** (-14.0 / 20.0)

    assert f"{1.0 - d:.6f}" in expr
    assert "1-0." in expr
    # and the floor keeps a fully-ducked moment finite rather than zero, so a long
    # silent patch cannot hand ffmpeg a division to complain about
    assert expr.endswith("1e-6)")


def test_no_spans_and_no_ducking_both_mean_unity():
    """A film with a score and no narration is not a film that needs ducking. Unity is
    the honest answer, and it is written as ``1`` rather than as an envelope that
    happens to compute to it."""
    assert _duck_expr([], -14.0, 0.25) == "1"
    assert _duck_expr([(0.0, 1.0)], 0.0, 0.25) == "1"


def test_the_envelope_holds_the_duck_across_a_span_and_ramps_at_both_edges():
    expr = _duck_expr([(1.0, 3.0)], -12.0, 0.25)

    assert "min(max((t-1.0000)/0.2500,0),1)" in expr      # up over the ramp
    assert "min(max((3.0000-t)/0.2500,0),1)" in expr      # down over the ramp


def test_abutting_spans_multiply_rather_than_search_for_which_one_applies():
    """Measured narration is usually contiguous, and a shot may be declared longer than
    the speech inside it, so spans overlap. Multiplying trapezoids that each reach 1
    gives unity where they abut, and the deepest duck wins mid-ramp — which is the
    audible behaviour one wants."""
    one = _duck_expr([(0.0, 1.0)], -12.0, 0.25)
    two = _duck_expr([(0.0, 1.0), (1.0, 2.0)], -12.0, 0.25)

    assert "min(1,(" in two and "+" in two
    assert "min(1,(" not in one


def test_the_mix_chain_merges_rather_than_amixes(tmp_path):
    """``amix`` is disqualified on evidence, not taste: on ffmpeg 4.3 it has no
    ``normalize`` option (4.4 added it) and divides the sum by the input count, so a
    two-input mix drops the voice ~3 dB and the result depends on the ffmpeg version —
    a portability bug (R-H6), not a mix. ``amerge``+``pan`` adds the channels by hand."""
    ff, rec = _ffmpeg()

    ff.mix(_nar(tmp_path), Path("/score.ogg"), [(0.0, 2.0)],
           Path("/out.wav"), duration=10.0, volume_db=-6.0, duck_db=-14.0,
           ramp=0.25, fade_in=1.0, fade_out=1.5)

    chain = rec.cmds[0][rec.cmds[0].index("-filter_complex") + 1]
    assert "amix" not in chain
    assert "amerge=inputs=2" in chain
    assert "pan=stereo|c0=c0+c2|c1=c1+c3" in chain
    assert "alimiter=limit=0.97" in chain


def test_the_mix_formats_both_branches_because_an_unlabelled_stream_cannot_be_merged(
        tmp_path):
    """``amerge`` refuses two inputs whose formats disagree, and the narration file and
    the score are written by different encoders. ``aformat`` on *both* branches is what
    makes the chain work on any pair of inputs rather than on the pair I happened to
    test."""
    ff, rec = _ffmpeg()

    ff.mix(_nar(tmp_path), Path("/score.ogg"), [(0.0, 2.0)],
           Path("/out.wav"), duration=10.0, volume_db=-6.0, duck_db=-14.0,
           ramp=0.25, fade_in=1.0, fade_out=1.5)

    chain = rec.cmds[0][rec.cmds[0].index("-filter_complex") + 1]
    assert chain.count("aformat=sample_fmts=fltp:channel_layouts=stereo") == 2


def test_the_bed_is_looped_and_then_trimmed_to_the_film(tmp_path):
    """A four-second theme under a sixteen-second film is the normal case. ``-stream_loop``
    makes it last; ``atrim`` turns that from a hope into a promise."""
    ff, rec = _ffmpeg()

    ff.mix(_nar(tmp_path), Path("/score.ogg"), [],
           Path("/out.wav"), duration=10.5, volume_db=-6.0, duck_db=-14.0,
           ramp=0.25, fade_in=1.0, fade_out=1.5)

    cmd = rec.cmds[0]
    assert cmd[cmd.index("-stream_loop") + 1] == "-1"
    chain = cmd[cmd.index("-filter_complex") + 1]
    assert "atrim=0:10.500" in chain


def test_the_fades_bracket_the_film_rather_than_the_file(tmp_path):
    """The bed is looped, so a fade "at the end of the file" would be at the end of the
    *loop*. The out-fade is placed at ``duration - fade_out``, which is where the film
    ends."""
    ff, rec = _ffmpeg()

    ff.mix(_nar(tmp_path), Path("/score.ogg"), [],
           Path("/out.wav"), duration=10.0, volume_db=-6.0, duck_db=-14.0,
           ramp=0.25, fade_in=0.8, fade_out=1.5)

    chain = rec.cmds[0][rec.cmds[0].index("-filter_complex") + 1]
    assert "afade=t=in:st=0:d=0.800" in chain
    assert "afade=t=out:st=8.500:d=1.500" in chain


def test_a_mix_with_no_narration_still_plays_the_score():
    """A silent cut still gets its bed — I6 says a cut is *declared*, not that it is
    silent. There is simply nothing to duck against, so the envelope is skipped."""
    ff, rec = _ffmpeg()

    ff.mix(None, Path("/score.ogg"), [(0.0, 1.0)],
           Path("/out.wav"), duration=5.0, volume_db=-6.0, duck_db=-14.0,
           ramp=0.25, fade_in=1.0, fade_out=1.5)

    cmd = rec.cmds[0]
    assert "-filter_complex" not in cmd
    af = cmd[cmd.index("-af") + 1]
    assert "amerge" not in af and "volume=-6.00dB" in af


def test_a_narration_path_that_does_not_exist_is_treated_as_no_narration(tmp_path):
    """The caller may hand over a path it merely expected. Mixing against a file that
    is not there would fail late, inside ffmpeg, with a message about a filter."""
    ff, rec = _ffmpeg()

    ff.mix(tmp_path / "absent.wav", Path("/score.ogg"), [],
           Path("/out.wav"), duration=5.0, volume_db=-6.0, duck_db=-14.0,
           ramp=0.25, fade_in=1.0, fade_out=1.5)

    assert "-filter_complex" not in rec.cmds[0]


# --------------------------------------------------------------------------- #
# the score: reported
# --------------------------------------------------------------------------- #
@pytest.mark.needs_render
def test_the_mix_is_measurably_ducked_where_people_speak(tmp_path):
    """The one claim this deliverable exists to make, and it is a claim about a *number*,
    so it is measured rather than asserted.

    The fixture is a silent cut (`voice.engine: none`), which is exactly the case that
    used to be reported as ducked. So the evidence is two mixes of the same material:
    one with the duck declared, one with `duck_db: 0.0`. Inside the span the first must
    be measurably quieter than the second, and between spans they must match. Comparing
    against the film's own tail would have proved nothing — the tail is a different
    stretch of the bed, and a mix that never ducked at all also passes that test.
    """
    ff = Ffmpeg()
    spans = [(0.0, 2.0)]

    def mix(out: Path, duck_db: float) -> Path:
        out.parent.mkdir(parents=True, exist_ok=True)
        ff.mix(_nar(tmp_path), MOVIE_DEMO_DIR / "assets" / "theme.ogg", spans, out,
               duration=6.0, volume_db=-6.0, duck_db=duck_db, ramp=0.25,
               fade_in=0.0, fade_out=0.0)
        return out

    def level(media: Path, start: float, length: float, tag: str) -> float:
        """How loud *this part* of a finished file is — there is no way to ask it of a
        range, so the range is cut out first."""
        clip = tmp_path / f"{tag}.wav"
        ff.shell.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.3f}",
                      "-i", str(media), "-t", f"{length:.3f}", "-vn",
                      "-c:a", "pcm_s16le", str(clip)])
        db = ff.mean_volume(clip)
        assert db is not None, f"could not measure {tag}"
        return float(db)

    ducked = mix(tmp_path / "ducked.wav", -14.0)
    reference = mix(tmp_path / "reference.wav", 0.0)

    # 1.3s in, so both ramps are behind us and the hold is at full depth
    under_voice = level(ducked, 1.3, 0.5, "under-ducked")
    under_ref = level(reference, 1.3, 0.5, "under-reference")
    # 4.0s in, past the 2.0s span: the duck has been lifted again
    alone = level(ducked, 4.0, 1.0, "alone-ducked")
    alone_ref = level(reference, 4.0, 1.0, "alone-reference")

    depth = under_ref - under_voice
    assert depth > 6.0, (
        f"the bed should be measurably quieter under the voice: {under_ref} dB without "
        f"the duck, {under_voice} dB with it — only {depth:.1f} dB apart")
    assert abs(alone - alone_ref) < 1.5, (
        f"outside the span the duck must be fully lifted: {alone} dB ducked vs "
        f"{alone_ref} dB reference")
