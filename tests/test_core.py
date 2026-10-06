"""Unit tests for vidkit — pure-Python modules, no external tools required."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vidkit.errors import SpecError
from vidkit.narration import build_srt, parse_scene_script, wrap_caption, word_count
from vidkit.svg import PanelDoc, document, esc, text
from vidkit import panels
from vidkit.spec import load_spec


# --------------------------------------------------------------------------- #
NARRATION = """\
# Demo

## Scene 0 — Title · 0:00–0:10

[stage direction, not spoken]

**Two sources, one picture.**

## Scene 1 — Scope · 0:10–0:32

**This is read live from the gateway, scoped to a single dataset tag.**
"""


def test_parse_scene_script_reads_bold_lines_only():
    scenes = parse_scene_script(NARRATION)
    assert [s.n for s in scenes] == [0, 1]
    assert scenes[0].spoken == "Two sources, one picture."
    assert "stage direction" not in scenes[0].spoken
    assert scenes[1].spoken.startswith("This is read live")


def test_parse_scene_script_requires_headers():
    with pytest.raises(SpecError):
        parse_scene_script("# no scenes here\n\njust prose")


def test_wrap_caption_respects_width_and_line_count():
    lines = wrap_caption("One location on the map. Two completely different kinds of evidence.")
    assert len(lines) <= 2
    assert all(len(line) <= 42 for line in lines)


def test_build_srt_is_faithful_and_timed():
    scenes = {0: "Two sources, one picture.", 1: "Read live from the gateway."}
    spans = [(0, 0.0, 8.0), (1, 8.0, 20.0)]
    srt = build_srt(scenes, spans)
    assert srt.startswith("1\n00:00:00,000 -->")
    # cue count >= 2, monotonic timestamps
    times = [ln for ln in srt.splitlines() if "-->" in ln]
    assert len(times) >= 2
    # fidelity is asserted inside build_srt; make sure no word vanished
    assert "gateway" in srt and "picture" in srt


def test_build_srt_rejects_unreadable_captions():
    scenes = {0: "x" * 200}          # one unbreakable token
    with pytest.raises(SpecError):
        build_srt(scenes, [(0, 0.0, 5.0)])


def test_word_count():
    assert word_count("Two sources, one clear picture.") == 5


# --------------------------------------------------------------------------- #
def test_svg_escapes_html():
    assert esc("<script>") == "&lt;script&gt;"


def test_document_wraps_body():
    doc = document(100, 50, text(1, 2, "hi"))
    assert doc.startswith("<svg")
    assert doc.rstrip().endswith("</svg>")
    assert "hi" in doc


def test_panel_doc_head_and_foot():
    d = PanelDoc(1920, 1080).head("Title", "kicker").foot("note")
    svg = d.svg()
    assert "Title" in svg and "KICKER" in svg and "note" in svg


# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("kind", ["line_series", "bar_profile", "stat_cards",
                                  "terminal", "endpoints", "strip", "kv_table",
                                  "text_panel"])
def test_every_builtin_panel_renders(kind):
    sample = {
        "line_series": {"series": [{"label": "a", "points": [{"x": "d1", "y": 1},
                                                             {"x": "d2", "y": 5}]}],
                        "thresholds": [{"value": 4, "label": "limit"}]},
        "bar_profile": [{"label": "A", "value": 10}, {"label": "B", "value": 4}],
        "stat_cards": [{"label": "obs", "value": 908}],
        "terminal": {"lines": ["[HIGH] site", "  detail"]},
        "endpoints": [{"path": "/api/x", "note": "does a thing"}],
        "strip": {"cells": [True, False, True], "headline": "2/3", "sub": ["a", "b"]},
        "kv_table": [{"k": "key", "v": "value"}],
        "text_panel": {"paragraphs": ["hello world"]},
    }[kind]
    d = PanelDoc(1920, 1080).head("T", "k")
    panels.render(kind, sample, {}, d)
    assert d.svg().count("<svg") == 1


def test_unknown_panel_kind_raises():
    with pytest.raises(SpecError):
        panels.render("nope", {}, {}, PanelDoc(10, 10))


def test_register_custom_kind():
    def fn(data, options, doc):
        doc.add(text(1, 1, "custom"))
    panels.register("custom_test", fn)
    assert "custom_test" in panels.kinds()
    d = PanelDoc(10, 10)
    panels.render("custom_test", None, {}, d)
    assert "custom" in d.svg()


# --------------------------------------------------------------------------- #
SPEC = {
    "project": {"title": "T", "slug": "t", "output": "t.mp4", "min_seconds": 10,
                "max_seconds": 20},
    "narration": {"inline": {"0": "hello world"}},
    "captures": [{"name": "dash", "url": "http://x/", "assert": {"selector": "#m",
                                                                 "contains": "live"}}],
    "scenes": [{"n": 0, "title": "s", "shots": [{"capture": "dash"}]}],
    "guard": {"banned": ["legal limit"], "required": ["synthetic"]},
}


def _write_spec(tmp_path: Path, spec: dict, name="video.json") -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(spec), encoding="utf-8")
    return p


def test_load_spec_json(tmp_path):
    spec = load_spec(_write_spec(tmp_path, SPEC))
    assert spec.project.slug == "t"
    assert spec.size == (1920, 1080)
    assert spec.captures[0].assert_.contains == "live"
    assert spec.guard.banned == ["legal limit"]


def test_load_spec_rejects_unknown_capture_ref(tmp_path):
    bad = json.loads(json.dumps(SPEC))
    bad["scenes"][0]["shots"] = [{"capture": "does-not-exist"}]
    # no provider -> should fail validation
    with pytest.raises(SpecError):
        load_spec(_write_spec(tmp_path, bad))


def test_load_spec_requires_output(tmp_path):
    bad = json.loads(json.dumps(SPEC))
    del bad["project"]["output"]
    with pytest.raises(SpecError):
        load_spec(_write_spec(tmp_path, bad))


def test_load_spec_rejects_bad_window(tmp_path):
    bad = json.loads(json.dumps(SPEC))
    bad["project"]["min_seconds"] = 30
    bad["project"]["max_seconds"] = 20
    with pytest.raises(SpecError):
        load_spec(_write_spec(tmp_path, bad))


def test_load_spec_yaml_roundtrip(tmp_path):
    yaml = pytest.importorskip("yaml")
    p = tmp_path / "video.yaml"
    p.write_text(yaml.safe_dump(SPEC), encoding="utf-8")
    spec = load_spec(p)
    assert spec.project.title == "T"


# --------------------------------------------------------------------------- #
# guard.require_audio — a silent cut must be declared, never accidental.
def test_require_audio_defaults_to_true(tmp_path):
    spec = load_spec(_write_spec(tmp_path, SPEC))
    assert spec.guard.require_audio is True


def test_require_audio_can_be_declared_off(tmp_path):
    raw = json.loads(json.dumps(SPEC))
    raw["guard"]["require_audio"] = False
    spec = load_spec(_write_spec(tmp_path, raw))
    assert spec.guard.require_audio is False


def test_verify_passes_declared_silent_cut_but_fails_undeclared(tmp_path):
    """The whole point of the flag: silence is allowed only when opted into."""
    from vidkit.assembler import Assets, make_context
    from vidkit.verify import verify_output

    raw = json.loads(json.dumps(SPEC))
    raw["scenes"] = [{"n": 0, "title": "s", "shots": [{"still": "a.svg"}]}]
    raw["captures"] = []
    raw["guard"] = {}

    (tmp_path / "a.svg").write_text("<svg/>", encoding="utf-8")

    # No audio was produced (no TTS engine), so the report must disagree with
    # the two settings.
    for declared, expected_ok in ((False, True), (True, False)):
        raw["guard"] = {"require_audio": declared}
        spec_path = _write_spec(tmp_path, raw, name=f"v{declared}.json")
        ctx = make_context(spec_path, tmp_path / f"out{declared}")
        rep = verify_output(ctx, Assets(), {0: "hello world"})
        audio = next(c for c in rep.checks if c.name == "audio present")
        assert audio.ok is expected_ok, (declared, audio.detail)
        if not declared:
            assert "declared" in audio.detail
