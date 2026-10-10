"""Tests for the MCP tool functions and server wiring.

The ``tool_*`` functions are pure (data in, data out) and importable without the ``mcp``
package, so most tests run with no optional dependency. Tests that touch the server skip
when ``mcp`` is absent.
"""

from __future__ import annotations

import ast
import inspect
import json
import time
from pathlib import Path

import pytest
from conftest import arun, mcp_resource_template_uri, mcp_resource_text, mcp_tool_text

from vidkit import mcp_server as m
from vidkit.errors import ToolError

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "hello-world" / "video.yaml"


def call(fn, /, *args, **kwargs):
    """Call a ``tool_*`` function from a plain test.

    Half the tools are ``async def`` because their bodies hop off the event loop, and
    a coroutine called from a sync test is a coroutine object, not an answer — the
    test would then "pass" an assertion about a `ToolError` it never raised. Driving
    the coroutine is what makes the test test the tool.
    """
    out = fn(*args, **kwargs)
    if not inspect.isawaitable(out):
        return out
    return arun(out)


def refuses(fn, /, *args, **kwargs):
    """The `pytest.raises` counterpart of `call`, for the same reason.

    ``pytest.raises`` cannot see an exception that has not been raised yet, so a
    refusal asserted against an un-awaited coroutine silently passes for the wrong
    reason. Await inside the block so the `ToolError` really lands here.
    """
    out = fn(*args, **kwargs)
    if inspect.isawaitable(out):
        arun(out)


@pytest.fixture(autouse=True)
def _clean_project():
    """Every test starts with the server's project unpinned.

    ``set_project`` pins module state, and a test that pinned it would silently
    redirect any later test that resolves a project implicitly — a leak that would
    show up as an unrelated failure a long way from here.
    """
    m.set_project(None)
    yield
    m.set_project(None)


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


def test_doctor_names_the_mcp_package():
    """The one row an agent needs before it can reach any other.

    `mcp` is a declared extra, not a `[dev]` one, so a healthy engine on a machine
    that has not installed it has *every* tool unreachable — and until this row
    existed, `doctor` said nothing about it at all. The check is deliberately about
    presence in the report, not about presence on this machine, so it means the same
    thing on a host that has the extra and one that does not.
    """
    rep = m.tool_doctor(None)
    rows = {t["name"]: t for t in rep["tools"]}
    assert "mcp" in rows
    assert rows["mcp"]["required"] is False
    assert isinstance(rows["mcp"]["present"], bool)


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
        refuses(m.tool_verify_report, str(spec), str(tmp_path / "out"))


@pytest.mark.needs_render
def test_provenance_tool_reads_what_build_wrote(tmp_path):
    """The MCP surface answers "which build is this?" from the file, not from a wish."""
    from vidkit.job import run_job

    built = run_job("build", story=str(EXAMPLE), out=str(tmp_path))
    got = call(m.tool_provenance, str(EXAMPLE), str(tmp_path))

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
        refuses(m.tool_provenance, str(spec), str(tmp_path / "out"))


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


@pytest.mark.needs_mcp
def test_build_server_registers_toolset():
    pytest.importorskip("mcp")

    server = m.build_server()

    async def go():
        tools = await server.list_tools()
        return [t.name for t in tools]

    names = arun(go)
    assert {"vidkit_run", "vidkit_actions", "vidkit_init", "vidkit_capture_plan",
            "vidkit_doctor", "vidkit_plan", "vidkit_build", "vidkit_verify",
            "vidkit_provenance", "vidkit_docs", "vidkit_docs_index",
            "vidkit_panel_kinds"} <= set(names)
    # The studio verbs. A sitting is looked at, decided about, and done again, so
    # each of these does one step of that and writes down what happened.
    assert {"session_open", "session_list", "session_status", "session_close",
            "session_capture", "session_build", "session_exec", "session_report",
            "take_list", "take_record", "take_select",
            "env_up", "env_down", "env_status",
            "browser_open", "browser_act", "browser_shot", "browser_status",
            "browser_close"} <= set(names)
    assert len(names) == 34


@pytest.mark.needs_mcp
def test_build_server_resources():
    pytest.importorskip("mcp")

    server = m.build_server()

    async def go():
        res = await server.list_resources()
        tmpl = await server.list_resource_templates()
        return [str(r.uri) for r in res], [mcp_resource_template_uri(t) for t in tmpl]

    resources, templates = arun(go)
    assert "vidkit://actions" in resources
    assert "vidkit://docs/index" in resources
    assert "vidkit://docs/modules" in resources
    assert "vidkit://docs/{name}" in templates
    # A session's state has to be readable as a resource, not only as a tool call:
    # a client that can *address* the record can put it in a prompt without a round
    # trip, and the resource is served from the same function the tool is.
    assert "vidkit://sessions/{session}/status" in templates
    assert "vidkit://sessions/{session}/takes" in templates
    assert "vidkit://sessions/{session}/report" in templates


@pytest.mark.needs_mcp
def test_session_resources_serve_the_same_answer_as_the_tools(tmp_path):
    """The resource and the tool are one reading of one record, not two.

    A resource URI names only the session, so the server has to be told which project
    it serves — ``--project`` for a deployed server, ``set_project`` here. Both paths
    then resolve the same record, and because ``next`` is derived only from the record
    and the disk, they must agree; if they did not, one of them would be inventing a
    fact.
    """
    pytest.importorskip("mcp")

    spec = tmp_path / "story"
    spec.mkdir()
    (spec / "video.yaml").write_text(
        "project: {name: res}\n"
        "scenes:\n"
        "  - id: s1\n"
        "    title: One\n"
        "    narration: |\n"
        "      ## Scene 1 · 0:00 - 0:05\n"
        "      **Hello.**\n"
        "    shots:\n"
        "      - panel: {kind: title, title: Hi}\n",
        encoding="utf-8")
    out = tmp_path / "out"          # where the record lives
    opened = m.tool_session_open(spec=str(spec / "video.yaml"), out=str(out))
    assert opened["out_dir"] == str(out.resolve())
    # The record is not the output. `out_dir` is where the film lands; `record_dir` is
    # the transcript of the sitting, and a session that named the same directory for
    # both would be reporting a fact about neither.
    assert opened["record_dir"] == str(out.resolve() / ".vidkit" / "sessions")
    assert opened["record_dir"] != opened["out_dir"]
    assert (out / ".vidkit" / "sessions" / f"{opened['id']}.json").is_file()
    assert opened["spec"] == str((spec / "video.yaml").resolve())

    listing = m.tool_session_list(out=str(out))
    assert listing["sessions_dir"] == str(out.resolve() / ".vidkit" / "sessions")
    assert [s["id"] for s in listing["sessions"]] == [opened["id"]]

    m.set_project(out)
    server = m.build_server()
    session_id = opened["id"]

    async def go():
        return mcp_resource_text(await server.read_resource(
            f"vidkit://sessions/{session_id}/status"))

    served = json.loads(arun(go))
    direct = call(m.tool_session_status, session_id, str(out))
    assert served["next"] == direct["next"]
    assert served["id"] == direct["id"]


@pytest.mark.needs_mcp
def test_server_tool_call_roundtrip():
    pytest.importorskip("mcp")

    server = m.build_server()

    async def go():
        out = await server.call_tool("vidkit_panel_kinds", {})
        return mcp_tool_text(out)

    text = arun(go)
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


@pytest.mark.needs_mcp
def test_run_resource_is_the_action_list():
    pytest.importorskip("mcp")

    server = m.build_server()

    async def go():
        return await server.read_resource("vidkit://actions")

    out = arun(go)
    text = mcp_resource_text(out)
    assert "init" in text and "verify" in text


@pytest.mark.needs_mcp
def test_run_tool_is_callable_over_the_server():
    pytest.importorskip("mcp")

    server = m.build_server()

    async def go():
        out = await server.call_tool("vidkit_run", {"action": "doctor"})
        return mcp_tool_text(out)

    text = arun(go)
    assert '"ok"' in text


# --------------------------------------------------------------------------- #
# the registration closures, structurally
# --------------------------------------------------------------------------- #
def _tool_closures() -> list[tuple[str, "ast.AST", list[str], bool]]:
    """Every function in the module that wraps a `tool_*`: name, node, calls, is_async."""

    tree = ast.parse(Path(m.__file__).read_text(encoding="utf-8"))
    wrappers = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        calls = []
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            f = sub.func
            if isinstance(f, ast.Name) and f.id.startswith("tool_"):
                calls.append((f.id, _is_awaited(node, sub)))
        if calls:
            wrappers.append((node.name, node, calls,
                             isinstance(node, ast.AsyncFunctionDef)))
    return wrappers


def _is_awaited(owner, call) -> bool:
    """Whether `call` is inside an `await` within `owner`.

    `ast` has no parent links, so this asks the question the other way round: walk the
    owner's own `Await` nodes and see whether this call is one of them.
    """

    for node in ast.walk(owner):
        if isinstance(node, ast.Await):
            for inner in ast.walk(node):
                if inner is call:
                    return True
    return False


def test_every_registration_closure_awaits_exactly_what_it_wraps():
    """A closure must `await` a coroutine and must not `await` a plain value.

    This is the defect that put a JSON *string* — `'<coroutine object
    tool_browser_shot at 0x…>'` — on the wire, and then the same defect inverted, where
    `vidkit://sessions/{s}/status` awaited the *sync* `tool_session_status` and FastMCP
    answered `'dict' object can't be awaited`. Neither is visible to a normal test: the
    client gets a `str` either way. So the invariant is checked against the source.
    """

    tree = ast.parse(Path(m.__file__).read_text(encoding="utf-8"))
    coroutine = {n.name for n in ast.walk(tree)
                 if isinstance(n, ast.AsyncFunctionDef) and n.name.startswith("tool_")}
    plain = {n.name for n in ast.walk(tree)
             if isinstance(n, ast.FunctionDef)
             and not isinstance(n, ast.AsyncFunctionDef)
             and n.name.startswith("tool_")}
    assert coroutine and plain, "the tool set was not found — this scan is lying"

    bad = []
    for name, _node, calls, is_async in _tool_closures():
        for callee, awaited in calls:
            if callee in plain and awaited:
                bad.append(f"{name} awaits {callee}, which is not a coroutine")
            if callee in coroutine and not awaited:
                bad.append(f"{name} calls the coroutine {callee} without awaiting it")
    assert not bad, "\n".join(bad)


def test_the_async_tools_are_the_ones_that_leave_the_loop():
    """A tool is `async` because something in it blocks, and for no other reason.

    Both directions are a defect. A blocking body behind a *sync* tool stops the whole
    server — FastMCP runs sync tools on the event loop, proven with a probe — and an
    `async` tool whose body never leaves the loop makes every caller await a hop it did
    not need. So: the async set is pinned by name, and each one is shown to hop.
    """
    import inspect

    pinned = {
        "tool_browser_act", "tool_browser_close", "tool_browser_open", "tool_browser_shot",
        "tool_browser_status", "tool_build", "tool_capture", "tool_env_down",
        "tool_env_status", "tool_env_up", "tool_provenance", "tool_session_build",
        "tool_session_capture", "tool_session_close", "tool_session_exec",
        "tool_session_report", "tool_take_list", "tool_take_record", "tool_take_select",
        "tool_tts", "tool_verify", "tool_verify_report",
    }
    actual = {name for name in dir(m)
              if name.startswith("tool_") and inspect.iscoroutinefunction(getattr(m, name))}
    assert actual == pinned, (
        f"the async tool set changed: extra {actual - pinned}, missing {pinned - actual}")

    src = Path(m.__file__).read_text(encoding="utf-8")
    lines = src.splitlines()
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.AsyncFunctionDef) or node.name not in pinned:
            continue
        body = "\n".join(lines[node.lineno - 1:node.end_lineno])
        assert any(hop in body for hop in ("_offloop", "_driver", "_loop", "run_sync")), (
            f"{node.name} is `async` but its body never leaves the event loop")


def test_a_run_reports_whether_its_ceiling_was_really_installed():
    """A bound that could not be installed must not be reported as one that was.

    `_deadline` uses SIGALRM, which only exists on the main thread. `tool_run` has to
    stay synchronous for it to work at all — a sync tool body has already blocked the
    event loop, so it cannot hop off it, and an `async` one would silently lose the
    alarm. The consequence is that the ceiling is *conditional*, and this is the check
    that the condition is reported instead of assumed.
    """
    import threading

    out = call(m.tool_run, "plan", story=str(EXAMPLE.parent), timeout=30)
    assert out["timeout_enforced"] is True
    assert "timeout_note" not in out

    # `timeout=0` asked for no ceiling, so there is nothing true to say about one.
    loose = call(m.tool_run, "plan", story=str(EXAMPLE.parent), timeout=0)
    assert loose["timeout_enforced"] is None
    assert "timeout_note" not in loose

    seen = {}

    def off_the_loop():
        seen["out"] = m.tool_run("plan", story=str(EXAMPLE.parent), timeout=30)

    worker = threading.Thread(target=off_the_loop, name="off-the-loop")
    worker.start()
    worker.join()
    note = seen["out"]
    assert seen["out"].get("ok") is True, "a plan must not be lost to a missing alarm"
    assert note["timeout_enforced"] is False, note
    assert "main thread" in note["timeout_note"], note


def test_no_test_calls_an_async_tool_without_awaiting_it():
    """The test suite is not exempt from the await rule either.

    `tool_provenance` and `tool_build` both hopped off the event loop, and two tests
    went on comparing a *coroutine object* to a dict, and `pytest.raises` went on
    seeing no exception at all because one was never raised yet. Both tests were green
    and both were meaningless — the same shape as the closure mismatch, one level up.
    A coroutine that is never awaited cannot fail a test, so the suite is scanned for
    the two shapes that discard one: a bare expression statement, and an assignment.
    """
    import inspect

    async_tools = {name for name in dir(m)
                   if name.startswith("tool_") and inspect.iscoroutinefunction(getattr(m, name))}

    def called_tool(call) -> str | None:
        f = call.func
        if isinstance(f, ast.Attribute) and f.attr in async_tools:
            return f.attr
        if isinstance(f, ast.Name) and f.id in async_tools:
            return f.id
        return None

    offenders = []
    for path in sorted((Path(m.__file__).resolve().parents[1] / "tests").glob("test_*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            value = None
            if isinstance(node, ast.Expr):
                value = node.value
            elif isinstance(node, ast.Assign):
                value = node.value
            if isinstance(value, ast.Call):
                name = called_tool(value)
                if name:
                    offenders.append(f"{path.name}:{node.lineno} discards {name}()")
    assert not offenders, (
        "an async tool was called without being awaited, so the assertion that follows "
        "compares against a coroutine and cannot fail: " + "; ".join(offenders))


# --------------------------------------------------------------------------- #
# HTTP transport binding guard
# --------------------------------------------------------------------------- #
def test_loopback_classifier():
    """The trust boundary is the loopback address, not a hard-coded list."""
    assert m._is_loopback("127.0.0.1")
    assert m._is_loopback("127.1.2.3")        # the whole 127/8 block is loopback
    assert m._is_loopback("::1")
    assert m._is_loopback("localhost")
    assert not m._is_loopback("0.0.0.0")      # "all interfaces" is not loopback
    assert not m._is_loopback("192.168.1.5")
    assert not m._is_loopback("10.0.0.1")
    # a name that does not resolve must fail closed, not look loopback
    assert not m._is_loopback("does-not-exist.invalid")


def test_http_transport_refuses_a_non_loopback_bind_without_expose(capsys, monkeypatch):
    """An unauthenticated HTTP MCP surface must not silently bind a public address."""
    monkeypatch.setattr(m, "set_project", lambda _p: None)

    rc = m.main(["--transport", "streamable-http", "--host", "0.0.0.0"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "refusing" in err and "0.0.0.0" in err


def test_http_transport_loopback_bind_is_not_refused_by_the_guard(monkeypatch):
    """The default loopback bind is the safe path and must sail through the guard."""
    monkeypatch.setattr(m, "set_project", lambda _p: None)

    # loopback is allowed; main() proceeds past the guard to build_server and then
    # server.run. Stub both so we can assert we reached them rather than returning
    # the refusal code 2 — and without starting a real server.
    seen = {}

    class _Fake:
        def run(self, *a, **kw):
            seen["ran"] = True

    monkeypatch.setattr(m, "build_server", lambda **kw: _Fake())

    rc = m.main(["--transport", "sse", "--host", "127.0.0.1"])
    assert rc == 0
    assert seen.get("ran") is True
