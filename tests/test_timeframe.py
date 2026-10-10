"""Unit tests for the story & timeframe contract (M1 / R-A1…R-A4, R-F7).

Pure Python, no external tools: everything here runs in well under a second.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from vidkit.errors import SpecError
from vidkit.scaffold import scaffold_story
from vidkit.spec import STORY_MANIFEST, load_spec, load_story
from vidkit.timeframe import (
    find_window_claims,
    from_absolute,
    from_relative,
    parse_timeframe,
    timeframe_matches,
)


# --------------------------------------------------------------------------- #
# Building a window
# --------------------------------------------------------------------------- #
def test_relative_window_counts_days_inclusively():
    tf = from_relative(28, date(2026, 10, 6))
    assert tf.start == date(2026, 9, 9)
    assert tf.end == date(2026, 10, 6)
    assert tf.days == 28
    assert tf.label() == "2026-09-09 to 2026-10-06 (28 days)"


def test_one_day_window_labels_in_the_singular():
    tf = from_relative(1, date(2026, 10, 6))
    assert tf.start == tf.end == date(2026, 10, 6)
    assert tf.days == 1
    assert "(1 day)" in tf.label()


def test_absolute_window_keeps_its_own_length():
    tf = from_absolute(date(2026, 9, 7), date(2026, 10, 6))
    assert tf.days == 30
    assert tf.as_of == date(2026, 10, 6)


def test_absolute_window_rejects_reversed_ends():
    with pytest.raises(SpecError):
        from_absolute(date(2026, 10, 6), date(2026, 9, 7))


def test_prose_round_trips_through_the_parser():
    tf = from_relative(30, date(2026, 10, 6))
    again = parse_timeframe(tf.prose())
    assert again is not None
    assert (again.start, again.end) == (tf.start, tf.end)


def test_as_prompt_is_the_data_a_source_would_receive():
    tf = from_relative(28, date(2026, 10, 6), source="story")
    assert tf.as_prompt() == {
        "start": "2026-09-09", "end": "2026-10-06", "days": 28,
        "as_of": "2026-10-06", "label": "2026-09-09 to 2026-10-06 (28 days)",
    }


# --------------------------------------------------------------------------- #
# Parsing what a spec or a manifest wrote
# --------------------------------------------------------------------------- #
def test_parse_accepts_both_spellings():
    for raw in ({"days": 28, "as_of": "2026-10-06"},
                "2026-09-09..2026-10-06",
                "9 September 2026 to 6 October 2026"):
        tf = parse_timeframe(raw)
        assert tf is not None, raw
        assert (tf.start, tf.end) == (date(2026, 9, 9), date(2026, 10, 6)), raw


def test_parse_shorthand_day_string_ends_on_as_of():
    """A `28d` string ends on the window's end date, not on `as_of` + 1."""
    tf = parse_timeframe("28d", default_as_of=date(2026, 10, 6))
    assert (tf.start, tf.end) == (date(2026, 9, 9), date(2026, 10, 6))
    assert (tf.days, tf.floating) == (28, False)


def test_parse_shorthand_unit_strings_without_an_as_of_float():
    tf = parse_timeframe("28d")
    assert tf.floating is True
    assert tf.days == 28


def test_parse_weeks_and_months_and_years():
    assert parse_timeframe({"weeks": 4, "as_of": "2026-10-06"}).days == 28
    # calendared, not multiplied: 6 months back from 2026-10-06 is 184 days
    assert parse_timeframe({"months": 6, "as_of": "2026-10-06"}).days == 184
    assert parse_timeframe({"months": 6, "as_of": "2026-10-06"}).start == date(2026, 4, 6)


def test_parse_declares_when_a_relative_window_has_no_as_of():
    tf = parse_timeframe({"days": 28}, default_as_of=date(2026, 10, 6))
    assert tf.floating is True
    assert tf.as_of == date(2026, 10, 6)
    pinned = parse_timeframe({"days": 28, "as_of": "2026-10-06"})
    assert pinned.floating is False


def test_parse_none_and_blank_mean_not_declared():
    for raw in (None, "", "   "):
        assert parse_timeframe(raw) is None


def test_parse_empty_mapping_is_rejected_not_ignored():
    """An empty `timeframe: {}` is a typo, and must not silently mean "no window"."""
    with pytest.raises(SpecError):
        parse_timeframe({})


@pytest.mark.parametrize("raw, needle", [
    ({"dayz": 28}, "unknown key"),
    ({"days": 28, "start": "2026-09-09"}, "not both"),
    ({"start": "2026-09-09"}, "start and end"),
    ({"as_of": "2026-10-06"}, "needs `days`"),
    ({"days": 0}, ">= 1"),
    ({"days": "soon"}, "not a number"),
])
def test_parse_errors_are_actionable(raw, needle):
    with pytest.raises(SpecError) as exc:
        parse_timeframe(raw)
    assert needle in str(exc.value)


# --------------------------------------------------------------------------- #
# Reading a window back out of narration
# --------------------------------------------------------------------------- #
AS_OF = date(2026, 10, 6)


def test_find_claims_reads_absolute_and_relative_windows():
    cases = {
        "the last 28 days": 28,
        "over the past 30 days": 30,
        "2026-09-09 to 2026-10-06": 28,
        "9 September 2026 to 6 October 2026": 28,
        "the last six months": None,          # resolved against as_of
    }
    for text, days in cases.items():
        claims = find_window_claims(text, as_of=AS_OF)
        assert len(claims) == 1, text
        if days is not None:
            assert claims[0].days == days, text


def test_find_claims_says_nothing_about_silent_prose():
    assert find_window_claims("Nothing here is about time.", as_of=AS_OF) == []


def test_find_claims_reads_a_numeric_range_span():
    for text in ("2026-09-09 to 2026-10-06", "9 September 2026 to 6 October 2026"):
        claims = find_window_claims(text, as_of=AS_OF)
        assert len(claims) == 1, text
        assert (claims[0].start, claims[0].end) == (date(2026, 9, 9), date(2026, 10, 6))


def test_find_claims_anchors_a_relative_claim_to_a_named_end_date():
    """`the last 28 days to 2026-10-06` is one claim, and it can be checked exactly."""
    claims = find_window_claims("the last 28 days to 2026-10-06", as_of=AS_OF)
    assert len(claims) == 1
    assert claims[0].days == 28
    assert claims[0].end_anchor == date(2026, 10, 6)
    assert claims[0].exact is False


def test_a_relative_claim_with_an_anchor_is_compared_on_both_ends():
    tf = from_relative(28, AS_OF)
    ok, _ = timeframe_matches(tf, find_window_claims("the last 28 days to 2026-10-06",
                                                     as_of=AS_OF)[0])
    assert ok
    # same day count, wrong end date: must not be waved through
    bad, why = timeframe_matches(tf, find_window_claims("the last 28 days to 2026-09-30",
                                                        as_of=AS_OF)[0])
    assert not bad
    assert "2026-09-30" in why


def test_timeframe_matches_accepts_the_exact_window_and_rejects_a_neighbour():
    tf = from_relative(28, AS_OF)
    ok, detail = timeframe_matches(tf, find_window_claims("the last 28 days", as_of=AS_OF)[0])
    assert ok and "28" in detail

    # 90 days is not 28, and the detail has to say which side said what
    bad, why = timeframe_matches(tf, find_window_claims("the last 90 days", as_of=AS_OF)[0])
    assert not bad
    assert "2026-09-09 to 2026-10-06" in why


def test_timeframe_matches_reports_a_day_count_without_an_end_anchor():
    tf = from_relative(28, AS_OF)
    ok, detail = timeframe_matches(tf, find_window_claims("a 28-day window", as_of=AS_OF)[0])
    assert ok
    assert "28" in detail


# --------------------------------------------------------------------------- #
# The story folder
# --------------------------------------------------------------------------- #
def _story(tmp_path: Path, *, narration: str = "**hello there.**",
           timeframe: dict | None = None, manifest: str | None = None) -> Path:
    (tmp_path / "narration.md").write_text(
        "# t\n\n## Scene 0 — Title · 0:00–0:05\n\n" + narration + "\n", encoding="utf-8")
    spec: dict = {
        "project": {"title": "T", "slug": "t", "output": "t.mp4",
                    "min_seconds": 1, "max_seconds": 100},
        "narration": {"source": "narration.md"},
        "scenes": [{"n": 0, "title": "s", "shots": [{"still": "s.svg"}]}],
    }
    (tmp_path / "s.svg").write_text("<svg/>", encoding="utf-8")
    if timeframe is not None:
        spec["timeframe"] = timeframe
    (tmp_path / "video.json").write_text(json.dumps(spec), encoding="utf-8")
    if manifest is not None:
        (tmp_path / STORY_MANIFEST).write_text(manifest, encoding="utf-8")
    return tmp_path / "video.json"


def test_story_identity_is_synthesised_from_the_folder(tmp_path):
    spec = load_spec(_story(tmp_path))
    assert spec.story is not None
    assert spec.story.slug == _slug(tmp_path.name)
    assert spec.story.declared is False
    assert spec.story.timeframe is None


def _slug(text: str) -> str:
    from vidkit.spec import _slugify
    return _slugify(text)


def test_story_manifest_is_read_and_validated(tmp_path):
    p = _story(tmp_path, manifest="title: Real Title\nslug: real-slug\n")
    story = load_story(tmp_path)
    assert (story.slug, story.title, story.declared) == ("real-slug", "Real Title", True)
    assert load_spec(p).story.slug == "real-slug"


def test_story_manifest_rejects_an_unknown_key(tmp_path):
    _story(tmp_path, manifest="slug: s\ntitlee: typo\n")
    with pytest.raises(SpecError) as exc:
        load_story(tmp_path)
    assert "titlee" in str(exc.value)


def test_load_spec_will_not_overwrite_a_story_manifest(tmp_path):
    _story(tmp_path, manifest="slug: s\n")
    with pytest.raises(SpecError) as exc:
        scaffold_story(tmp_path)
    assert "refusing to overwrite" in str(exc.value)


# --------------------------------------------------------------------------- #
# Resolution precedence and the narration guard
# --------------------------------------------------------------------------- #
def test_spec_wins_over_the_story_manifest(tmp_path):
    _story(tmp_path, manifest="timeframe:\n  start: 2026-01-01\n  end: 2026-01-31\n")
    spec = load_spec(tmp_path / "video.json", timeframe=parse_timeframe("7d"))
    assert spec.timeframe.days == 7
    assert spec.timeframe.source == "override"


def test_a_disagreeing_narration_window_loads_and_is_caught_by_verify(tmp_path):
    """Load rejects what the spec cannot *guarantee*; mere disagreement is verify's job.

    Here the spec pins a window, so narration saying 90 days is checkable — it is
    simply wrong. That must reach :func:`verify_output` (R-F7), not be guessed at
    load time and not be silently accepted.
    """
    p = _story(tmp_path, narration="**This covers the last 90 days to 2026-10-06.**")
    spec = load_spec(p, timeframe=parse_timeframe("28d", default_as_of=date(2026, 10, 6)))
    assert spec.timeframe.days == 28


def test_verify_rejects_a_narration_window_that_disagrees_with_the_spec(tmp_path):
    from vidkit.assembler import Assets, make_context
    from vidkit.verify import verify_output

    p = _story(tmp_path, narration="**This covers the last 90 days to 2026-10-06.**")
    ctx = make_context(p, tmp_path / "out", timeframe="28d", as_of=date(2026, 10, 6))
    rep = verify_output(ctx, Assets(), {0: "This covers the last 90 days to 2026-10-06."})
    check = next(c for c in rep.checks if c.name == "timeframe consistent with spec")
    assert check.ok is False
    assert "90" in check.detail and "2026-09-09 to 2026-10-06" in check.detail


def test_verify_accepts_a_narration_window_that_agrees_with_the_spec(tmp_path):
    from vidkit.assembler import Assets, make_context
    from vidkit.verify import verify_output

    p = _story(tmp_path, narration="**This covers 9 September 2026 to 6 October 2026.**")
    ctx = make_context(p, tmp_path / "out", timeframe="28d", as_of=date(2026, 10, 6))
    rep = verify_output(ctx, Assets(), {0: "This covers 9 September 2026 to 6 October 2026."})
    check = next(c for c in rep.checks if c.name == "timeframe consistent with spec")
    assert check.ok is True, check.detail


def test_a_matching_narration_window_is_accepted(tmp_path):
    p = _story(tmp_path, narration="**This covers 9 September 2026 to 6 October 2026.**")
    spec = load_spec(p, timeframe=parse_timeframe("28d", default_as_of=date(2026, 10, 6)))
    assert spec.timeframe.days == 28


def test_narration_may_not_state_a_date_when_the_window_floats(tmp_path):
    p = _story(tmp_path, narration="**This covers 9 September 2026 to 6 October 2026.**")
    with pytest.raises(SpecError) as exc:
        load_spec(p, timeframe=parse_timeframe({"days": 28}, default_as_of=None))
    assert "pins no `as_of`" in str(exc.value)


def test_a_floating_window_may_state_only_the_day_count(tmp_path):
    p = _story(tmp_path, timeframe={"days": 28}, narration="**This covers the last 28 days.**")
    spec = load_spec(p, timeframe=None, as_of=date(2026, 10, 6))
    assert spec.timeframe.floating is True
    assert spec.timeframe.days == 28


# --------------------------------------------------------------------------- #
# Scaffolding
# --------------------------------------------------------------------------- #
def test_scaffold_writes_a_runable_story(tmp_path):
    target = tmp_path / "my-story"
    written = scaffold_story(target, title="My Story", timeframe=from_relative(14, AS_OF))
    assert {p.name for p in written} == {STORY_MANIFEST, "video.yaml", "provider.py",
                                         "narration.md"}

    spec = load_spec(target / "video.yaml")
    assert spec.story.declared is True
    assert spec.story.title == "My Story"
    assert spec.timeframe.days == 14
    # the narration states exactly the window the spec resolved: passes by construction
    claims = find_window_claims((target / "narration.md").read_text(encoding="utf-8"),
                               as_of=spec.timeframe.end)
    assert claims
    assert all(timeframe_matches(spec.timeframe, c)[0] for c in claims)


def test_scaffold_refuses_to_clobber_existing_files(tmp_path):
    target = tmp_path / "s"
    scaffold_story(target, timeframe=from_relative(7, AS_OF))
    with pytest.raises(SpecError) as exc:
        scaffold_story(target)
    assert "refusing to overwrite" in str(exc.value)


def test_scaffold_sizes_its_runtime_window_to_its_own_words(tmp_path):
    """A scaffold must pass its own `runtime within window` check."""
    target = tmp_path / "s"
    scaffold_story(target, timeframe=from_relative(7, AS_OF))
    spec = load_spec(target / "video.yaml")
    from vidkit.narration import parse_scene_script
    words = sum(len(s.spoken.split()) for s in parse_scene_script(
        (target / "narration.md").read_text(encoding="utf-8")))
    est = words / 2.5
    assert spec.project.min_seconds <= est <= spec.project.max_seconds
