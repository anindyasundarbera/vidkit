"""Tests for the job contract: one entry point, one manifest, failures as data.

The contract is the thing an external agent meets first, so the tests here are as
much about what a *caller* can rely on as about what the code does: the manifest
always has the same keys, a refusal never raises, a reported artifact is really on
disk, and the timeline carries measured seconds rather than estimates.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vidkit.job import ACTIONS, Progress, actions_help, run_job, stages_for

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples" / "hello-world"


# --------------------------------------------------------------------------- #
# The shape of the answer
# --------------------------------------------------------------------------- #
#: Present on *every* manifest, whatever happened. An action's own results are
#: added on top — `plan` grows a `plan` key — but these are never missing, so a
#: caller can read them before it knows whether the job worked.
BASE_KEYS = {"action", "ok", "story", "out", "spec", "timeframe", "artifacts",
             "report", "timeline", "failure", "progress", "vidkit"}


def test_a_manifest_always_has_the_same_base_keys():
    plan = run_job("plan", story=str(EXAMPLE))
    refused = run_job("plan", story=str(EXAMPLE / "nope"))

    assert BASE_KEYS <= set(plan)
    assert BASE_KEYS <= set(refused)
    assert plan["ok"] is True
    assert refused["ok"] is False


def test_a_refusal_still_reports_the_window_it_was_about():
    """An agent that asked for `7d` should be able to see what it asked for."""
    manifest = run_job("plan", story=str(EXAMPLE), timeframe="7d")

    assert manifest["ok"] is False  # the narration pins a different window
    assert manifest["timeframe"]["source"] == "override"
    assert manifest["timeframe"]["days"] == 7


def test_verify_reports_the_spans_it_looked_at(tmp_path):
    """A verify with an empty timeline would be describing a film it never read."""
    story = tmp_path / "story"
    assert run_job("init", story=str(story), timeframe="14d")["ok"] is True
    assert run_job("build", story=str(story), out=str(tmp_path / "out"))["ok"] is True

    manifest = run_job("verify", story=str(story), out=str(tmp_path / "out"))

    assert manifest["ok"] is True
    assert manifest["timeline"], "the per-scene spans should survive a verify"
    assert manifest["timeline"][0]["n"] == 0
    assert manifest["timeline"][-1]["end"] > 0


def test_a_manifest_is_json_serializable():
    manifest = run_job("plan", story=str(EXAMPLE))
    # if this raised, the manifest could not go over MCP at all
    assert json.loads(json.dumps(manifest))["action"] == "plan"


def test_the_version_is_reported():
    from vidkit import __version__

    assert run_job("plan", story=str(EXAMPLE))["vidkit"] == __version__


# --------------------------------------------------------------------------- #
# Refusals are data, never exceptions
# --------------------------------------------------------------------------- #
def test_an_unknown_action_is_answered_not_raised():
    manifest = run_job("frobnicate", story=str(EXAMPLE))

    assert manifest["ok"] is False
    assert manifest["failure"]["kind"] == "tool"
    assert "unknown action" in manifest["failure"]["message"]
    assert "vidkit_actions" in manifest["failure"]["hint"]


def test_no_story_at_all_says_so():
    manifest = {
        "ok": run_job("plan")["ok"],
        "failure": run_job("plan")["failure"],
    }
    assert manifest["ok"] is False
    assert manifest["failure"]["kind"] == "tool"
    assert "no story given" in manifest["failure"]["message"]
    assert "story" in manifest["failure"]["hint"]


def test_a_folder_without_a_spec_names_the_folder(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    manifest = run_job("plan", story=str(empty))

    assert manifest["ok"] is False
    assert "no video.yaml" in manifest["failure"]["message"]
    assert str(empty) in manifest["failure"]["message"]


def test_a_bad_spec_is_reported_with_its_kind(tmp_path):
    spec = tmp_path / "video.yaml"
    spec.write_text("project:\n  title: x\n", encoding="utf-8")
    manifest = run_job("plan", story=str(spec))

    assert manifest["ok"] is False
    assert manifest["failure"]["kind"] == "spec"
    assert manifest["failure"]["story"] == str(spec)


def test_a_failure_names_the_action_that_failed():
    manifest = run_job("build", story=str(EXAMPLE / "nope"))
    assert manifest["failure"]["action"] == "build"


def test_verifying_nothing_is_its_own_answer(tmp_path):
    """'There is nothing to verify' must not look like 'the render failed'."""
    manifest = run_job("verify", story=str(EXAMPLE), out=str(tmp_path / "empty"))

    assert manifest["ok"] is False
    assert manifest["failure"]["kind"] == "missing"
    assert "nothing to verify" in manifest["failure"]["message"]
    assert "build" in manifest["failure"]["hint"]
    # the report still comes back, because it says *which* checks could not run
    assert manifest["report"] is not None


# --------------------------------------------------------------------------- #
# doctor and plan render nothing
# --------------------------------------------------------------------------- #
def test_doctor_runs_without_a_story():
    """The machine can be checked before a story exists — that is the point."""
    manifest = run_job("doctor")

    assert manifest["ok"] is True
    assert manifest["doctor"]["tools"]
    assert manifest["doctor"]["panel_kinds"]
    assert manifest["artifacts"] == {}
    assert manifest["spec"] is None


def test_doctor_reports_the_spec_when_given_one():
    manifest = run_job("doctor", story=str(EXAMPLE))
    assert manifest["doctor"]["spec"]["slug"] == "hello-world"
    assert manifest["doctor"]["spec"]["scenes"] == 8


def test_plan_carries_the_scenes_and_the_window():
    manifest = run_job("plan", story=str(EXAMPLE))
    plan = manifest["plan"]

    assert plan["slug"] == "hello-world"
    assert len(plan["scenes"]) == 8
    assert plan["est_seconds"] > 0
    assert plan["within_window"] is True
    assert manifest["timeframe"]["label"].startswith("2026-09-07")


def test_a_timeframe_override_reaches_the_plan():
    manifest = run_job("plan", story=str(EXAMPLE), timeframe="7d")
    assert manifest["timeframe"]["source"] == "override"
    assert manifest["timeframe"]["days"] == 7


# --------------------------------------------------------------------------- #
# init
# --------------------------------------------------------------------------- #
def test_init_scaffolds_a_story_and_says_what_it_wrote(tmp_path):
    target = tmp_path / "new-story"
    manifest = run_job("init", story=str(target), title="A New Story")

    assert manifest["ok"] is True
    assert (target / "video.yaml").exists()
    assert (target / "story.yaml").exists()
    assert manifest["spec"] == str(target / "video.yaml")
    assert len(manifest["created"]) == 4
    for name, art in manifest["artifacts"].items():
        assert art["ok"] is True, name
        assert art["bytes"] > 0, name


def test_init_refuses_to_overwrite_and_says_which_files(tmp_path):
    target = tmp_path / "new-story"
    run_job("init", story=str(target))
    again = run_job("init", story=str(target))

    assert again["ok"] is False
    assert again["failure"]["kind"] == "spec"
    assert "refusing to overwrite" in again["failure"]["message"]
    # untouched, not truncated
    assert (target / "video.yaml").stat().st_size > 0


def test_init_without_a_target_says_what_to_pass():
    manifest = run_job("init")
    assert manifest["ok"] is False
    assert "story" in manifest["failure"]["message"]
    assert "story" in manifest["failure"]["hint"]


def test_an_initialized_story_can_be_planned(tmp_path):
    """The MCP round trip: `init`, then plan what was created."""
    target = tmp_path / "fresh"
    assert run_job("init", story=str(target))["ok"] is True

    planned = run_job("plan", story=str(target))
    assert planned["ok"] is True
    assert planned["plan"]["scenes"]
    assert planned["story"] == str(target)


# --------------------------------------------------------------------------- #
# Progress
# --------------------------------------------------------------------------- #
def test_progress_is_the_pipelines_own_narration():
    manifest = run_job("plan", story=str(EXAMPLE))
    steps = manifest["progress"]["steps"]

    assert steps, "a job must say what it did"
    assert manifest["progress"]["seconds"] >= 0
    assert all({"name", "kind", "ok", "detail", "seconds"} <= set(s) for s in steps)
    assert steps[-1]["name"] == "planned"


def test_progress_steps_are_classified():
    class _Fake:
        pass

    progress = Progress()
    from vidkit.job import _LineTicker

    sink = _LineTicker(progress)
    sink.write("[vidkit] panels: 8\n[PASS] output exists — x\nWARN no TTS engine\n")
    sink.flush()

    kinds = [s["kind"] for s in progress.steps]
    assert kinds == ["log", "check", "warn"]
    assert progress.steps[1]["ok"] is True


def test_a_progress_hook_sees_each_step_as_it_happens():
    seen: list[str] = []
    run_job("plan", story=str(EXAMPLE), on_progress=seen.append)

    assert seen
    assert any(line.startswith("planned") for line in seen)


def test_progress_does_not_leak_onto_stdout(capsys):
    run_job("plan", story=str(EXAMPLE))
    captured = capsys.readouterr()
    assert captured.out == ""


# --------------------------------------------------------------------------- #
# The artifact manifest describes the run, not the wish
# --------------------------------------------------------------------------- #
def test_a_missing_file_is_never_reported_as_an_artifact():
    from vidkit.job import _artifact

    assert _artifact(None) is None
    assert _artifact(Path("/no/such/file.mp4")) is None


def test_an_empty_file_is_reported_but_not_as_ok(tmp_path):
    from vidkit.job import _artifact

    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")
    assert _artifact(empty) == {"path": str(empty), "bytes": 0, "ok": False}


def test_a_real_file_is_reported_with_its_size(tmp_path):
    from vidkit.job import _artifact

    real = tmp_path / "clip.mp4"
    real.write_bytes(b"x" * 12)
    assert _artifact(real) == {"path": str(real), "bytes": 12, "ok": True}


# --------------------------------------------------------------------------- #
# The action vocabulary
# --------------------------------------------------------------------------- #
def test_the_action_list_is_data_an_agent_can_read():
    listed = actions_help()

    assert [row["action"] for row in listed] == list(ACTIONS)
    assert all(row["does"] for row in listed)
    assert len(ACTIONS) == 7


def test_stage_selection_is_declared_per_action():
    assert stages_for("build") is None  # the whole pipeline
    assert stages_for("capture") == ["capture"]
    assert stages_for("tts") == ["narration"]


def test_only_and_from_stage_cannot_be_combined():
    manifest = run_job("build", story=str(EXAMPLE), only=["panels"], from_stage="clips")

    assert manifest["ok"] is False
    assert "mutually exclusive" in manifest["failure"]["message"]


def test_a_stage_that_needs_data_says_how_to_get_it(tmp_path):
    """Selecting `panels` alone without a snapshot must explain the fix."""
    manifest = run_job("build", story=str(EXAMPLE), out=str(tmp_path / "bare"),
                       only=["panels"])
    assert manifest["ok"] is False
    assert "no dataset snapshot" in manifest["failure"]["message"]
    assert "refresh" in manifest["failure"]["hint"]


@pytest.mark.parametrize("action", ["plan", "doctor"])
def test_read_only_actions_write_no_build_directory(action, tmp_path):
    run_job(action, story=str(EXAMPLE), out=str(tmp_path / "unused"))
    assert not (tmp_path / "unused").exists()
