"""Tests for the machine-readable CLI: ``vidkit run`` and ``--json`` (R-G2).

The contract these tests hold to: stdout carries the manifest and nothing else — not
a stray progress line, not a warning — so a caller can pipe it straight into ``jq``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vidkit import cli

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = str(REPO / "examples" / "hello-world" / "video.yaml")


def call(capsys, *argv: str) -> tuple[int, dict, str]:
    """Run the CLI in-process and hand back (exit code, parsed stdout, stderr)."""
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, json.loads(captured.out), captured.err


# --------------------------------------------------------------------------- #
def test_json_plan_prints_a_parseable_manifest(capsys):
    code, out, err = call(capsys, "--json", "plan", EXAMPLE)

    assert code == 0
    assert out["ok"] is True
    assert out["action"] == "plan"
    assert out["plan"]["slug"] == "hello-world"
    # stdout is the manifest, so nothing else may be on it
    assert err == ""


def test_json_doctor_needs_no_story(capsys):
    code, out, _ = call(capsys, "--json", "doctor")

    assert out["action"] == "doctor"
    assert out["doctor"]["tools"]
    assert out["spec"] is None
    # A machine that is missing a tool is a *verdict*, not a crash. The exit code
    # has to agree with the report either way, so this test is honest on a lean
    # machine and on a fully equipped one.
    assert (code == 0) == out["doctor"]["ok"]


def test_json_init_then_plan_round_trip(capsys, tmp_path):
    target = tmp_path / "cli-story"
    code, out, _ = call(capsys, "--json", "init", str(target))
    assert (code, out["ok"]) == (0, True)

    code, out, _ = call(capsys, "--json", "plan", str(target))
    assert (code, out["ok"]) == (0, True)
    assert out["plan"]["scenes"]


def test_json_refusal_exits_1_with_a_failure_block(capsys):
    code, out, _ = call(capsys, "--json", "plan", str(tmp_path_of_nothing()))

    assert code == 1
    assert out["ok"] is False
    assert out["failure"]["kind"] == "tool"
    assert out["failure"]["hint"]


def test_run_verb_prints_the_same_manifest_as_json(capsys):
    plan_code, plan, _ = call(capsys, "--json", "plan", EXAMPLE)
    run_code, run, _ = call(capsys, "run", "plan", "--story", EXAMPLE)

    assert plan_code == run_code == 0
    assert run["action"] == plan["action"] == "plan"
    assert run["plan"]["slug"] == plan["plan"]["slug"]


def test_run_verb_takes_a_timeframe(capsys):
    code, out, _ = call(capsys, "run", "plan", "--story", EXAMPLE, "--timeframe", "30d",
                        "--as-of", "2026-10-06")

    assert code == 0
    assert out["timeframe"]["source"] == "override"


def test_run_verb_help_lists_every_action(capsys):
    with pytest.raises(SystemExit):
        cli.main(["run", "--help"])
    text = capsys.readouterr().out

    for action in ("init", "doctor", "plan", "build", "capture", "tts", "verify"):
        assert action in text


def test_progress_lines_go_to_stderr_not_stdout(capsys):
    code, out, err = call(capsys, "--json", "--progress", "plan", EXAMPLE)

    assert code == 0
    assert out["ok"] is True  # stdout still parses
    assert "planned" in err or "story" in err


def test_the_flags_are_accepted_after_the_verb_too(capsys):
    """A user types `vidkit plan SPEC --json`, not only `vidkit --json plan SPEC`."""
    code, out, _ = call(capsys, "plan", EXAMPLE, "--json")

    assert (code, out["ok"]) == (0, True)
    assert out["action"] == "plan"


def test_json_and_progress_after_the_verb(capsys):
    code, out, err = call(capsys, "plan", EXAMPLE, "--json", "--progress")

    assert (code, out["ok"]) == (0, True)
    assert err, "the run's log should reach stderr"


def test_progress_without_json_says_why(capsys):
    code = cli.main(["--progress", "plan", EXAMPLE])
    assert code == 1
    assert "--json" in capsys.readouterr().err


def test_json_docs_answers_with_its_own_shape(capsys):
    code, out, _ = call(capsys, "--json", "docs", "--index")
    assert code == 0
    assert out["modules"] or out["docs"]


def test_json_on_a_non_job_says_so_instead_of_pretending(capsys):
    code, out, _ = call(capsys, "--json", "auth", "http://example.test")
    assert code == 1
    assert out["failure"]["kind"] == "usage"


def test_json_run_init_really_inits(capsys):
    """`--json run ACTION` must honour ACTION — it is the one flag combination that
    carries an action of its own, and taking the verb (`run`) for the action turned
    every such call into a build."""
    import tempfile

    target = Path(tempfile.mkdtemp()) / "from-json-run"
    code, out, _ = call(capsys, "--json", "run", "init", "--story", str(target),
                        "--title", "Via run")

    assert code == 0
    assert out["action"] == "init"
    assert (target / "video.yaml").exists()
    # and the story it wrote is real: planning it is the next call
    code, out, _ = call(capsys, "--json", "run", "plan", "--story", str(target))
    assert (code, out["ok"]) == (0, True)


def test_json_matches_plain_run_for_every_read_only_action(capsys):
    """`--json` is a shape, not a second behaviour: the two paths must agree.

    The verdict is whatever the machine can honestly say, so the exit codes are
    compared to each other rather than to zero.
    """
    import tempfile

    target = Path(tempfile.mkdtemp()) / "story"
    call(capsys, "--json", "run", "init", "--story", str(target))
    for action in ("plan", "doctor"):
        json_code, json_out, _ = call(capsys, "--json", "run", action, "--story", str(target))
        plain_code = cli.main(["run", action, "--story", str(target)])
        capsys.readouterr()
        assert json_code == plain_code
        assert json_out["action"] == action
        assert json_out["ok"] == (plain_code == 0)


def test_plain_plan_still_prints_prose(capsys):
    """--json is opt-in: the terminal output must be unchanged without it."""
    code = cli.main(["plan", EXAMPLE])
    text = capsys.readouterr().out

    assert code == 0
    assert text.startswith("vidkit hello world")
    assert "  scenes:" in text


def tmp_path_of_nothing() -> Path:
    import tempfile

    return Path(tempfile.mkdtemp()) / "no-such-story"
