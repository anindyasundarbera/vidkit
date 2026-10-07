"""Tests for the build's identity: what was built, from what, by what (R-F8).

The value of this module is that a reviewer who finds an ``.mp4`` a year later can
tell *which* build it is. So the tests are about refusal and honesty rather than
about pretty output: a reader that cannot trust a file must say so by returning
``None``, a tool that is missing must be recorded as missing rather than dropped,
and a ``verify`` must read the record a build wrote instead of inventing a fresh
one while describing someone else's build.
"""

from __future__ import annotations

import json
from pathlib import Path

import anyio

import pytest

from vidkit import provenance as pv
from vidkit.job import run_job

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples" / "hello-world"


def _record(**over):
    base = dict(action="build", spec="/tmp/video.yaml", spec_sha256="deadbeef",
                timeframe={"kind": "days", "days": 7}, started=1_700_000_000.0,
                ended=1_700_000_012.5)
    base.update(over)
    return pv.Provenance(**base)


# --------------------------------------------------------------------------- #
# The shape of the record
# --------------------------------------------------------------------------- #
def test_the_record_names_what_it_was_built_from_and_with():
    d = _record().to_dict()

    assert d["schema"] == pv.SCHEMA
    assert d["action"] == "build"
    assert d["spec_sha256"] == "deadbeef"
    assert d["timeframe"] == {"kind": "days", "days": 7}
    assert d["vidkit"] and d["runtime"]["python"] and d["runtime"]["machine"]
    assert isinstance(d["tools"], list) and isinstance(d["stages"], list)


def test_timestamps_are_utc_and_measured_not_estimated():
    d = _record().to_dict()

    assert d["built_at"].endswith("Z") and d["started_at"].endswith("Z")
    assert d["seconds"] == 12.5          # the real elapsed wall clock


def test_every_declared_tool_is_probed_even_when_absent():
    """`we did not check` and `it was not there` are different facts."""
    shell = _FakeShell(found={})
    tools = pv.probe_tools(shell)

    assert {t.name for t in tools} == set(pv.TOOLS)
    assert all(t.present is False for t in tools)
    assert all(t.version is None for t in tools)


def test_a_present_tool_is_recorded_with_its_version_and_path(monkeypatch):
    monkeypatch.setattr(pv, "_banner",
                        lambda path, args: "ffmpeg version 9.9.9-static")
    shell = _FakeShell(found={"ffmpeg": "/usr/bin/ffmpeg"})
    ffmpeg = next(t for t in pv.probe_tools(shell) if t.name == "ffmpeg")

    assert ffmpeg.present is True
    assert ffmpeg.version == "9.9.9-static"
    assert ffmpeg.path == "/usr/bin/ffmpeg"


def test_the_tool_list_is_cached_per_path(monkeypatch):
    """Probing the machine on every render would be five processes of waste."""
    calls = []
    monkeypatch.setattr(pv, "_TOOL_CACHE", {})
    monkeypatch.setattr(pv, "_probe_with", lambda shell: calls.append(1) or [])
    monkeypatch.setenv("PATH", "/one")

    pv.probe_tools()
    pv.probe_tools()
    assert len(calls) == 1
    # a different PATH is a different machine, as far as the cache is concerned
    monkeypatch.setenv("PATH", "/two")
    pv.probe_tools()
    assert len(calls) == 2


# --------------------------------------------------------------------------- #
# Reading: refuse rather than guess
# --------------------------------------------------------------------------- #
def test_reading_a_missing_record_is_none_not_an_exception(tmp_path):
    assert pv.Provenance.read(tmp_path) is None


def test_a_truncated_record_is_none(tmp_path):
    (tmp_path / pv.PROVENANCE_FILE).write_text('{"schema": 1, "vidkit"', encoding="utf-8")
    assert pv.Provenance.read(tmp_path) is None


def test_a_record_from_a_future_schema_is_refused(tmp_path):
    """Half-reading a shape we do not know would be worse than reading nothing."""
    (tmp_path / pv.PROVENANCE_FILE).write_text(
        json.dumps({"schema": pv.SCHEMA + 1, "action": "build"}), encoding="utf-8")
    assert pv.Provenance.read(tmp_path) is None


def test_a_record_round_trips(tmp_path):
    path = _record(story="hello-world").write(tmp_path)

    assert path.name == pv.PROVENANCE_FILE
    got = pv.Provenance.read(tmp_path)
    assert got is not None and got["story"] == "hello-world"


# --------------------------------------------------------------------------- #
# The pipeline writes it, and verify reads it
# --------------------------------------------------------------------------- #
@pytest.mark.needs_render
def test_a_build_writes_a_provenance_record(tmp_path):
    manifest = run_job("build", story=str(EXAMPLE), out=str(tmp_path))

    assert manifest["ok"] is True
    assert manifest["provenance"]["action"] == "build"
    record = pv.Provenance.read(tmp_path / "_build")
    assert record is not None
    assert record["spec_sha256"] == manifest["provenance"]["spec_sha256"]
    assert record["stages"], "a build must say which stages it ran"
    assert record["story"] == "hello-world"
    assert {t["name"] for t in record["tools"]} == set(pv.TOOLS)
    assert (tmp_path / "_build" / pv.PROVENANCE_FILE).exists()


@pytest.mark.needs_render
def test_a_verify_reads_the_record_rather_than_writing_one(tmp_path):
    """Describing someone else's build with a fresh record is fabrication."""
    run_job("build", story=str(EXAMPLE), out=str(tmp_path))
    before = (tmp_path / "_build" / pv.PROVENANCE_FILE).read_text(encoding="utf-8")

    manifest = run_job("verify", story=str(EXAMPLE), out=str(tmp_path))

    assert manifest["ok"] is True
    assert manifest["provenance"]["action"] == "build", "verify must not relabel the build"
    assert manifest["report"]["facts"]["provenance"]["spec_sha256"] == \
        manifest["provenance"]["spec_sha256"]
    assert (tmp_path / "_build" / pv.PROVENANCE_FILE).read_text(encoding="utf-8") == before


def test_a_read_only_action_carries_no_provenance(tmp_path):
    """`plan` renders nothing, so there is nothing to identify."""
    manifest = run_job("plan", story=str(EXAMPLE), out=str(tmp_path))

    assert manifest["provenance"] is None
    assert not (tmp_path / "_build" / pv.PROVENANCE_FILE).exists()


def test_provenance_is_never_invented_for_a_build_that_never_ran(tmp_path):
    refused = run_job("build", story=str(tmp_path / "no-such-story"), out=str(tmp_path))

    assert refused["ok"] is False
    assert refused["provenance"] is None


def test_asking_for_provenance_before_a_build_is_a_refusal_not_a_guess(tmp_path):
    manifest = run_job("provenance", story=str(EXAMPLE), out=str(tmp_path))

    assert manifest["ok"] is False
    assert manifest["provenance"] is None
    assert "build" in manifest["failure"]["hint"]


@pytest.mark.needs_render
def test_the_provenance_action_and_a_verify_agree_with_the_build(tmp_path):
    """Three surfaces, one answer — the file the build wrote."""
    built = run_job("build", story=str(EXAMPLE), out=str(tmp_path))
    read = run_job("provenance", story=str(EXAMPLE), out=str(tmp_path))

    assert read["ok"] is True
    assert read["artifacts"]["provenance_json"]["ok"] is True
    for key in ("spec_sha256", "built_at", "story", "timeframe"):
        assert read["provenance"][key] == built["provenance"][key], key


# --------------------------------------------------------------------------- #
class _FakeShell:
    """A shell that answers `which` without touching the machine."""

    def __init__(self, found: dict[str, str]):
        self.found = found

    def which(self, name: str) -> str | None:
        return self.found.get(name)


@pytest.mark.needs_render
def test_the_verb_and_the_json_and_the_tool_all_name_the_same_build(tmp_path):
    """The plain verb, `--json`, and the MCP tool are three readers of one file.

    The plain verb exists so a person can read a build's identity without `jq`. It
    was advertised in the help text and in the docs while being *dispatched nowhere* —
    it printed the help screen and exited `0`, which is a success code for doing
    nothing. This test drives all three so they cannot drift apart again.
    """
    from vidkit import cli, mcp_server

    built = run_job("build", story=str(EXAMPLE), out=str(tmp_path))
    assert built["ok"] is True

    manifest = run_job("provenance", story=str(EXAMPLE), out=str(tmp_path))
    # `tool_provenance` hopped off the event loop with the rest of the blocking
    # tools, so it is a coroutine now: calling it without awaiting yields a
    # coroutine object, and every assertion below would then be comparing a
    # coroutine to a dict — a test that cannot fail.
    tool = anyio.run(
        mcp_server.tool_provenance, str(EXAMPLE / "video.yaml"), str(tmp_path))
    from vidkit.reports import format_provenance

    text = format_provenance(manifest["provenance"])

    assert manifest["provenance"] == tool, "the job and the tool must read the same bytes"
    assert built["provenance"]["spec_sha256"] in text
    assert "build" in text.splitlines()[0]
    # and the verb itself reaches the same record rather than the help screen
    import io
    import contextlib
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cli.main(["provenance", str(EXAMPLE / "video.yaml"), "--out", str(tmp_path)])
    assert code == 0
    assert out.getvalue() == text + "\n"
