"""Tests for the MCP tool functions and server wiring.

The ``tool_*`` functions are pure (data in, data out) and importable without the ``mcp``
package, so most tests run with no optional dependency. Tests that touch the server skip
when ``mcp`` is absent.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from vidkit.errors import ToolError
from vidkit import mcp_server as m

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "hello-world" / "video.yaml"


# --------------------------------------------------------------------------- #
def test_panel_kinds_tool_lists_builtins():
    out = m.tool_panel_kinds()
    assert "line_series" in out["kinds"]
    assert "terminal" in out["kinds"]
    assert len(out["kinds"]) >= 8


def test_docs_tool_index_and_named():
    index = m.tool_docs(None)
    assert "spec-reference" in index  # the index links to other docs
    spec = m.tool_docs("spec-reference")
    assert "project" in spec and "# Spec reference" in spec
    # a name with .md also resolves
    assert m.tool_docs("concepts.md").startswith("#")


def test_docs_tool_routes_by_module():
    # bare stems resolve regardless of module folder
    assert m.tool_docs("concepts").startswith("# Concepts")
    assert m.tool_docs("mcp-server").startswith("# vidkit as an MCP server")
    assert m.tool_docs("provenance").startswith("# Provenance")
    # module-qualified names resolve too
    assert m.tool_docs("authoring/spec-reference").startswith("# Spec reference")


def test_docs_index_tool_lists_modules():
    rep = m.tool_docs_index()
    ids = {mod["id"] for mod in rep["modules"]}
    assert {"foundations", "authoring", "capture", "verification",
            "operations", "guides", "plan"} <= ids
    files = [d["file"] for mod in rep["modules"] for d in mod["docs"]]
    assert "authoring/spec-reference.md" in files


def test_docs_tool_exposes_plan_docs():
    """The plan/ module must be readable through the same route as every other doc.

    ``docs/plan/*.md`` are registered in ``docs/modules.yaml``, so they resolve
    by bare stem and by module-qualified path. ``ROADMAP`` is deliberately NOT
    one of them: a file of that name here would shadow the root ``ROADMAP.md``
    that owns the requirement IDs, because module docs win over root docs in
    the route builder. Hence ``FEATURE-ROADMAP``.
    """
    plan_docs = {
        "PLAN": ("# PLAN.md", "what we are doing"),
        "HISTORY": ("# HISTORY.md", "append-only"),
        "DECISIONS": ("# DECISIONS.md", None),
        "OPENMONTAGE": ("# OPENMONTAGE", None),
        "FEATURE-ROADMAP": ("# FEATURE-ROADMAP.md", None),
    }
    for stem, (heading, needle) in plan_docs.items():
        text = m.tool_docs(stem)
        assert text.startswith(heading), (stem, text[:60])
        if needle:
            assert needle.lower() in text.lower(), (stem, needle)

    # module-qualified route to the same files
    assert m.tool_docs("plan/DECISIONS").startswith("# DECISIONS.md")
    assert m.tool_docs("plan/PLAN.md").startswith("# PLAN.md")

    # the plan module is advertised in the index, with all five docs
    rep = m.tool_docs_index()
    plan = next(mod for mod in rep["modules"] if mod["id"] == "plan")
    assert len(plan["docs"]) == 5

    # and no plan doc steals the root ROADMAP route
    assert "FEATURE-ROADMAP" in m._doc_routes()


def test_docs_tool_unknown_name_raises():
    with pytest.raises(ToolError):
        m.tool_docs("does-not-exist")


def test_resolve_spec_missing_raises():
    with pytest.raises(ToolError):
        m.resolve_spec("/no/such/spec.yaml")


@pytest.mark.skipif(not EXAMPLE.exists(), reason="example spec missing")
def test_plan_tool_on_example():
    rep = m.tool_plan(str(EXAMPLE))
    assert rep["slug"] == "hello-world"
    assert len(rep["scenes"]) == 8
    assert rep["narration_words"] > 100
    assert isinstance(rep["within_window"], bool)
    assert "measured" in rep["required"]


def test_doctor_tool_environment():
    rep = m.tool_doctor(None)
    names = {t["name"] for t in rep["tools"]}
    assert {"ffmpeg", "rsvg-convert", "piper (TTS)"} <= names
    assert isinstance(rep["ok"], bool)


@pytest.mark.skipif(not EXAMPLE.exists(), reason="example spec missing")
def test_doctor_tool_with_spec():
    rep = m.tool_doctor(str(EXAMPLE))
    assert rep["spec"]["slug"] == "hello-world"
    assert rep["spec"]["scenes"] == 8


def test_verify_report_tool_missing_file(tmp_path):
    spec = tmp_path / "video.yaml"
    spec.write_text(
        "project: {title: T, slug: t, output: t.mp4, min_seconds: 1, max_seconds: 10}\n"
        "narration: {inline: {0: 'hi'}}\n"
        "scenes: [{n: 0, shots: [{still: missing.svg}]}]\n",
        encoding="utf-8",
    )
    (tmp_path / "missing.svg").write_text("<svg/>", encoding="utf-8")
    with pytest.raises(ToolError):
        m.tool_verify_report(str(spec), str(tmp_path / "out"))


@pytest.mark.needs_render
def test_provenance_tool_reads_what_build_wrote(tmp_path):
    """The MCP surface answers "which build is this?" from the file, not from a wish."""
    from vidkit.job import run_job

    built = run_job("build", story=str(EXAMPLE), out=str(tmp_path))
    got = m.tool_provenance(str(EXAMPLE), str(tmp_path))

    assert got["schema"] == 1
    assert got["action"] == "build"
    assert got["spec_sha256"] == built["provenance"]["spec_sha256"]
    assert {t["name"] for t in got["tools"]} == {"ffmpeg", "ffprobe", "rsvg-convert",
                                               "pdftoppm", "gs"}


def test_provenance_tool_before_a_build_refuses_with_a_reason(tmp_path):
    spec = tmp_path / "video.yaml"
    spec.write_text(
        "project: {title: T, slug: t, output: t.mp4, min_seconds: 1, max_seconds: 10}\n"
        "narration: {inline: {0: 'hi'}}\n"
        "scenes: [{n: 0, shots: [{still: s.svg}]}]\n",
        encoding="utf-8",
    )
    (tmp_path / "s.svg").write_text("<svg/>", encoding="utf-8")

    with pytest.raises(ToolError, match="run build first"):
        m.tool_provenance(str(spec), str(tmp_path / "out"))


def test_actions_tool_and_the_job_module_agree():
    from vidkit.job import actions_help

    assert m.tool_actions()["actions"] == actions_help()


def test_default_spec_prefers_example():
    # From the vidkit root, the example spec is the default. Assert the intent
    # (a resolvable spec) rather than a specific slug: the repo may ship more
    # than one example, and the pick is alphabetical by design.
    import os
    cwd = os.getcwd()
    try:
        os.chdir(Path(__file__).resolve().parents[1])
        found = m.default_spec()
        assert found is not None
        assert found.endswith(("video.yaml", "video.yml"))
        assert Path(found).exists()
        # The default must be a spec the loader actually accepts.
        assert m.tool_plan(str(found))["slug"]
    finally:
        os.chdir(cwd)


def test_default_spec_picks_examples_deterministically():
    """`default_spec()` is alphabetical, so adding an example must not be silent.

    The examples/ pattern is the one an outside user hits, and it is sorted —
    this test pins that a shipped example is selected at all, and that the
    choice is stable across calls rather than filesystem-order dependent.
    """
    import os
    repo = Path(__file__).resolve().parents[1]
    if not (repo / "examples").is_dir():
        pytest.skip("no examples/ directory")
    cwd = os.getcwd()
    try:
        os.chdir(repo)
        picks = {m.default_spec() for _ in range(3)}
        assert len(picks) == 1, f"unstable default spec: {picks}"
        assert next(iter(picks)).startswith(str(repo / "examples"))
    finally:
        os.chdir(cwd)


# --------------------------------------------------------------------------- #
def test_stdout_to_stderr_redirects_prints():
    """The guard must keep stray prints off stdout (which carries JSON-RPC)."""
    import io
    import sys

    fake_out, fake_err = io.StringIO(), io.StringIO()
    real_out, real_err = sys.stdout, sys.stderr
    try:
        sys.stdout, sys.stderr = fake_out, fake_err
        with m.stdout_to_stderr():
            print("should-not-be-on-stdout")
    finally:
        sys.stdout, sys.stderr = real_out, real_err
    assert fake_out.getvalue() == ""
    assert "should-not-be-on-stdout" in fake_err.getvalue()


def test_build_server_registers_toolset():
    pytest.importorskip("mcp")
    import anyio

    server = m.build_server()

    async def go():
        tools = await server.list_tools()
        return [t.name for t in tools]

    names = anyio.run(go)
    assert {"vidkit_run", "vidkit_actions", "vidkit_init", "vidkit_capture_plan",
            "vidkit_doctor", "vidkit_plan", "vidkit_build", "vidkit_verify",
            "vidkit_provenance", "vidkit_docs", "vidkit_docs_index",
            "vidkit_panel_kinds"} <= set(names)
    assert len(names) == 15


def test_build_server_resources():
    pytest.importorskip("mcp")
    import anyio

    server = m.build_server()

    async def go():
        res = await server.list_resources()
        tmpl = await server.list_resource_templates()
        return [str(r.uri) for r in res], [t.uriTemplate for t in tmpl]

    resources, templates = anyio.run(go)
    assert "vidkit://actions" in resources
    assert "vidkit://docs/index" in resources
    assert "vidkit://docs/modules" in resources
    assert "vidkit://docs/{name}" in templates


def test_server_tool_call_roundtrip():
    pytest.importorskip("mcp")
    import anyio

    server = m.build_server()

    async def go():
        out = await server.call_tool("vidkit_panel_kinds", {})
        return out[0].text

    text = anyio.run(go)
    assert "line_series" in text


# --------------------------------------------------------------------------- #
# The agent surface (R-G1/R-G3/R-G4)
# --------------------------------------------------------------------------- #
def test_run_tool_bounds_the_call_with_a_timeout(monkeypatch):
    """A tool call has no Ctrl-C, so an overrun must come back as a manifest."""
    from vidkit import job

    def _everlasting(*a, **kw):
        time.sleep(5)
        return {"ok": True}

    monkeypatch.setattr(job, "run_job", _everlasting)
    out = m.tool_run("build", story="whatever", timeout=0.05)

    assert out["ok"] is False
    assert out["failure"]["kind"] == "tool"
    assert "did not finish within" in out["failure"]["message"]


def test_a_timeout_of_zero_means_no_ceiling(monkeypatch):
    from vidkit import job

    monkeypatch.setattr(job, "run_job", lambda *a, **kw: {"ok": True})
    assert m.tool_run("plan", story="x", timeout=0)["ok"] is True


def test_run_tool_plans_a_story():
    out = m.tool_run("plan", story=str(EXAMPLE.parent))
    assert out["ok"] is True
    assert out["plan"]["slug"] == "hello-world"
    assert out["progress"]["steps"]


def test_run_tool_answers_a_refusal_without_raising():
    out = m.tool_run("plan", story="does-not-exist")
    assert out["ok"] is False
    assert out["failure"]["kind"] == "tool"
    assert out["failure"]["hint"]


def test_run_tool_reaches_the_whole_vocabulary():
    from vidkit.job import ACTIONS

    listed = {row["action"] for row in m.tool_actions()["actions"]}
    assert listed == set(ACTIONS)
    assert m.tool_actions()["actions"][0]["does"]


def test_init_tool_scaffolds_and_then_refuses(tmp_path):
    target = tmp_path / "from-mcp"
    first = m.tool_init(str(target), title="From MCP")
    assert first["ok"] is True
    assert (target / "video.yaml").exists()

    again = m.tool_init(str(target))
    assert again["ok"] is False
    assert "refusing to overwrite" in again["failure"]["message"]


def test_capture_plan_lists_what_would_be_filmed():
    kit = Path(__file__).resolve().parents[1] / "examples" / "capture-kit" / "video.yaml"
    if not kit.exists():
        pytest.skip("the capture fixture is not present")

    out = m.tool_capture_plan(str(kit))
    names = [c["name"] for c in out["captures"]]
    assert "usage" in names
    assert out["needs_playwright"] is True

    usage = next(c for c in out["captures"] if c["name"] == "usage")
    assert usage["url"]
    assert usage["asserts"], "an assertion is the reason a capture is trustworthy"
    # the artifact captures must come last, so the file they need already exists
    by_artifact = [c["name"] for c in out["captures"] if c["artifact"]]
    assert by_artifact == names[-len(by_artifact):]


def test_capture_plan_announces_nothing_on_stdout(capsys):
    """A tool's return value must be the only thing on the wire."""
    m.tool_capture_plan(str(EXAMPLE))
    assert capsys.readouterr().out == ""


def test_run_resource_is_the_action_list():
    pytest.importorskip("mcp")
    import anyio

    server = m.build_server()

    async def go():
        return await server.read_resource("vidkit://actions")

    out = anyio.run(go)
    part = out[0] if isinstance(out, tuple) else next(iter(out))
    text = getattr(part, "content", None) or part.text
    assert "init" in text and "verify" in text


def test_run_tool_is_callable_over_the_server():
    pytest.importorskip("mcp")
    import anyio

    server = m.build_server()

    async def go():
        out = await server.call_tool("vidkit_run", {"action": "doctor"})
        return out[0].text

    text = anyio.run(go)
    assert '"ok"' in text
