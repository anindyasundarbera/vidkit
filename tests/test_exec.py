"""Tests for the declared-execution contract (R-E1…R-E5).

Split deliberately in two. The **policy** half — what a spec may declare, what
gets refused before a camera rolls, how a result is judged — is pure Python and
runs everywhere, including the lean CI job that installs no ffmpeg. The
**sandbox** half actually starts a process, so it is marked ``needs_render``:
the sandbox needs the same host plumbing a render does, and a unit test that
hangs is worse than one that skips.

The one test that matters most is
:func:`test_run_is_handed_a_real_terminal_not_a_pipe`. The whole reason this
module shells out to a PTY is that a program changes what it prints when it
notices it is not on one, and a recording of the wrong transcript would be a
fabricated screen — invariant I7.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from vidkit import exec as ex
from vidkit import spec as sp
from vidkit.errors import SpecError, ToolError
from vidkit.secrets import Secrets


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _yaml(tmp_path: Path, *, steps: list | None = None,
          policy: dict | None = None, guard: dict | None = None,
          shots: list | None = None) -> Path:
    """A spec on disk. Built as a mapping and dumped as YAML so the test reads like
    the spec an author would write, rather than like the loader's internals."""
    import yaml

    if shots is None:
        shots = ([{"exec": steps[0]["label"]}] if steps else [{"still": "s.svg"}])
    body: dict = {
        "project": {"title": "T", "slug": "t", "output": "t.mp4",
                    "min_seconds": 1, "max_seconds": 30},
        "narration": {"inline": {0: "hi"}},
    }
    if steps is not None:
        block: dict = {"steps": steps}
        block.update(policy or {})
        body["exec"] = block
    if guard:
        body["guard"] = guard
    body["scenes"] = [{"n": 0, "shots": shots}]
    (tmp_path / "s.svg").write_text("<svg/>", encoding="utf-8")
    p = tmp_path / "video.yaml"
    p.write_text(yaml.safe_dump(body, sort_keys=False), encoding="utf-8")
    return p


# --------------------------------------------------------------------------- #
# the spec surface (R-E1)
# --------------------------------------------------------------------------- #
def test_exec_defaults_are_stated_not_implied(tmp_path):
    spec = sp.load_spec(_yaml(tmp_path, steps=[{"label": "run it", "cmd": ["echo", "hi"]}]))
    step = spec.exec[0]
    assert (step.label, step.cmd, step.cwd) == ("run it", ["echo", "hi"], ".")
    assert step.shell == []                      # a list command declares no shell
    assert (step.backend, step.timeout) == ("bubblewrap", 60.0)
    assert step.network is False and step.expect_exit == [0]
    assert step.reads == [] and step.env == {} and step.at is None
    assert (step.cols, step.rows) == (100, 30)


def test_a_string_command_declares_a_shell_and_a_list_does_not(tmp_path):
    """The difference is the whole point of the two forms: one says out loud that
    it is a shell script, the other is an argv. Neither is a surprise at runtime."""
    spec = sp.load_spec(_yaml(tmp_path, steps=[
        {"label": "script", "cmd": "npm test && echo done"},
        {"label": "argv", "cmd": ["npm", "test"]},
    ]))
    script, argv = spec.exec
    assert script.shell == ["/bin/sh", "-c"]
    assert script.cmd == ["npm test && echo done"]
    assert argv.shell == [] and argv.cmd == ["npm", "test"]


def test_a_shell_field_is_refused_because_it_hides_the_decision(tmp_path):
    """`shell:` would let a spec pick an interpreter without saying whether the
    command is a script. The two `cmd` forms already say it, so a third spelling
    is a way to be unclear about what runs."""
    with pytest.raises(SpecError, match="`shell:` is not a spec field"):
        sp.load_spec(_yaml(tmp_path, steps=[
            {"label": "x", "cmd": "echo hi", "shell": "/bin/bash"}]))


def test_an_empty_command_is_refused(tmp_path):
    for cmd in ("", "   ", []):
        with pytest.raises(SpecError, match="`cmd`"):
            sp.load_spec(_yaml(tmp_path, steps=[{"label": "x", "cmd": cmd}]))


def test_a_command_must_be_a_string_or_a_list(tmp_path):
    with pytest.raises(SpecError, match="must be a string"):
        sp.load_spec(_yaml(tmp_path, steps=[{"label": "x", "cmd": {"run": "ls"}}]))


def test_a_step_needs_a_label_and_a_command(tmp_path):
    with pytest.raises(SpecError, match="needs a `label`"):
        sp.load_spec(_yaml(tmp_path, shots=[{"still": "s.svg"}],
                           steps=[{"cmd": "ls"}]))
    with pytest.raises(SpecError, match="needs a `cmd`"):
        sp.load_spec(_yaml(tmp_path, shots=[{"still": "s.svg"}],
                           steps=[{"label": "x"}]))


def test_two_steps_may_not_share_a_label(tmp_path):
    """A shot names a step by label. Two steps with one label would make a shot
    ambiguous, and the ambiguity would resolve silently to whichever came first."""
    with pytest.raises(SpecError, match="same label"):
        sp.load_spec(_yaml(tmp_path, steps=[{"label": "run", "cmd": "a"},
                                            {"label": "run", "cmd": "b"}]))


def test_an_unknown_backend_is_refused_at_load_time(tmp_path):
    with pytest.raises(SpecError, match="unknown backend 'chroot'"):
        sp.load_spec(_yaml(tmp_path, steps=[
            {"label": "x", "cmd": "ls", "backend": "chroot"}]))


def test_a_shot_may_not_name_a_step_that_was_never_declared(tmp_path):
    with pytest.raises(SpecError, match="not declared"):
        sp.load_spec(_yaml(tmp_path, steps=[{"label": "one", "cmd": "a"}],
                           shots=[{"exec": "two"}]))


def test_an_exec_shot_with_no_exec_block_is_refused(tmp_path):
    path = _yaml(tmp_path, steps=None, shots=[{"exec": "run it"}])
    with pytest.raises(SpecError, match="declares no `exec:` steps"):
        sp.load_spec(path)


def test_the_policy_is_parsed_and_defaults_to_no_network(tmp_path):
    """Two layers, and this pins the safe default of the outer one: a command
    asking for the network is not enough, the spec has to have allowed it."""
    spec = sp.load_spec(_yaml(tmp_path, steps=[{"label": "a", "cmd": "ls"}]))
    assert spec.exec_policy.allow_network is False
    assert spec.exec_policy.max_timeout == 300.0

    opened = sp.load_spec(_yaml(tmp_path, steps=[{"label": "a", "cmd": "ls"}],
                                policy={"allow_network": True, "max_timeout": 120}))
    assert opened.exec_policy.allow_network is True
    assert opened.exec_policy.max_timeout == 120.0


def test_expect_exit_accepts_a_bare_int_or_a_list(tmp_path):
    spec = sp.load_spec(_yaml(tmp_path, steps=[
        {"label": "a", "cmd": "ls", "expect_exit": 1},
        {"label": "b", "cmd": "ls", "expect_exit": [0, 1]},
    ]))
    assert spec.exec[0].expect_exit == [1]
    assert spec.exec[1].expect_exit == [0, 1]


def test_reads_accepts_a_bare_string(tmp_path):
    spec = sp.load_spec(_yaml(tmp_path, steps=[
        {"label": "a", "cmd": "ls", "reads": "/srv/data"}]))
    assert spec.exec[0].reads == ["/srv/data"]


def test_a_timeout_beyond_the_policy_ceiling_is_refused(tmp_path):
    with pytest.raises(SpecError, match="exceeds the spec's"):
        sp.load_spec(_yaml(tmp_path, steps=[{"label": "a", "cmd": "ls", "timeout": 600}]))


# --------------------------------------------------------------------------- #
# what the guard promises (R-E5)
# --------------------------------------------------------------------------- #
def test_a_build_claims_the_sandbox_by_default(tmp_path):
    """Honest by default. A spec that runs commands says they were contained
    unless it explicitly says otherwise, so the interesting claim takes an act of
    writing rather than an omission."""
    spec = sp.load_spec(_yaml(tmp_path, steps=[{"label": "a", "cmd": "ls"}]))
    assert spec.guard.require_sandbox is True
    assert spec.guard.require_exec_success is True


def test_a_spec_that_runs_unconfined_must_say_so(tmp_path):
    spec = sp.load_spec(_yaml(tmp_path, steps=[{"label": "a", "cmd": "ls"}],
                              guard={"require_sandbox": False}))
    assert spec.guard.require_sandbox is False


# --------------------------------------------------------------------------- #
# check_policy: refusals before the camera rolls
# --------------------------------------------------------------------------- #
def _requests(tmp_path, steps) -> list:
    """Build ``ExecRequest``s without going through a spec file.

    Most ``check_policy`` refusals are also load-time refusals, so the loader
    would raise before the function under test ever ran — you cannot ask a
    policy checker about a spec the loader already rejected. Going through
    ``Exec`` keeps each reason testable on its own.
    """
    spec = sp.load_spec(_yaml(tmp_path, shots=[{"still": "s.svg"}]))
    reqs = []
    for s in steps:
        reqs.append(sp.Exec(label=s["label"], cmd=_cmd_of(s), cwd=s.get("cwd", "."),
                            backend=s.get("backend", "bubblewrap"),
                            timeout=s.get("timeout", 60.0),
                            network=s.get("network", False)))
    return reqs, spec


def _cmd_of(step) -> list[str]:
    raw = step.get("cmd", "ls")
    return ["/bin/sh", "-c", raw] if isinstance(raw, str) else list(raw)


def test_check_policy_passes_a_command_that_can_run(tmp_path):
    reqs, spec = _requests(tmp_path, [{"label": "ok", "cmd": ["ls"]}])
    assert ex.check_policy(reqs, root=spec.root, allow_network=False) == []


def test_check_policy_names_the_command_it_is_complaining_about(tmp_path):
    """A build with eight commands must say *which* one is wrong. The label is
    the only handle the author has."""
    reqs, spec = _requests(tmp_path, [{"label": "npm test", "cmd": ["ls"],
                                       "cwd": "nowhere"}])
    problems = ex.check_policy(reqs, root=spec.root, allow_network=False)
    assert len(problems) == 1 and problems[0].startswith("npm test:")


def test_check_policy_refuses_a_missing_working_directory(tmp_path):
    reqs, spec = _requests(tmp_path, [{"label": "a", "cmd": "ls",
                                       "cwd": "no/such/dir"}])
    assert "working directory does not exist" in ex.check_policy(
        reqs, root=spec.root, allow_network=False)[0]


def test_check_policy_accepts_a_directory_that_exists(tmp_path):
    (tmp_path / "sub").mkdir()
    reqs, spec = _requests(tmp_path, [{"label": "a", "cmd": "ls", "cwd": "sub"}])
    assert ex.check_policy(reqs, root=spec.root, allow_network=False) == []


def test_check_policy_refuses_network_the_spec_never_allowed(tmp_path):
    """The refusal has to explain *why* it is a refusal, not just that it is one,
    or the author widens the wrong thing."""
    reqs, spec = _requests(tmp_path, [{"label": "curl", "cmd": ["curl", "https://x"],
                                       "network": True}])
    problems = ex.check_policy(reqs, root=spec.root, allow_network=False)
    assert len(problems) == 1
    assert "allow_network" in problems[0] and "network: true" in problems[0]


def test_check_policy_allows_the_network_once_the_spec_widens_it(tmp_path):
    reqs, spec = _requests(tmp_path, [{"label": "curl", "cmd": ["curl", "https://x"],
                                       "network": True}])
    assert ex.check_policy(reqs, root=spec.root, allow_network=True) == []


def test_check_policy_refuses_a_backend_this_host_does_not_have(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    reqs, spec = _requests(tmp_path, [{"label": "a", "cmd": "ls"}])
    problems = ex.check_policy(reqs, root=spec.root, allow_network=False)
    assert len(problems) == 1 and "bwrap(1) is not on PATH" in problems[0]
    assert "backend: local" in problems[0]


def test_check_policy_reports_every_bad_command_not_just_the_first(tmp_path):
    reqs, spec = _requests(tmp_path, [{"label": "a", "cmd": "ls", "cwd": "no"},
                                      {"label": "b", "cmd": "ls", "cwd": "no"}])
    assert len(ex.check_policy(reqs, root=spec.root, allow_network=False)) == 2


def test_check_policy_rejects_a_nonpositive_timeout(tmp_path):
    spec = sp.load_spec(_yaml(tmp_path, shots=[{"still": "s.svg"}]))
    req = sp.Exec(label="a", cmd=["ls"], timeout=0.0)
    assert "timeout must be > 0" in ex.check_policy([req], root=spec.root,
                                                     allow_network=False)[0]


def test_check_policy_rejects_an_empty_command_or_expectation():
    req = sp.Exec(label="a", cmd=[], expect_exit=[])
    problems = ex.check_policy([req], root=Path("/"), allow_network=False)
    assert any("no command declared" in p for p in problems)
    assert any("at least one exit code" in p for p in problems)


# --------------------------------------------------------------------------- #
# resolve_backend: a missing backend is a refusal, never a silent downgrade
# --------------------------------------------------------------------------- #
def test_resolve_backend_keeps_local_and_bubblewrap():
    assert ex.resolve_backend("local") == "local"
    if shutil.which("bwrap"):
        assert ex.resolve_backend("bubblewrap") == "bubblewrap"


def test_resolve_backend_refuses_a_backend_that_is_not_installed(monkeypatch):
    """The dangerous failure is not `docker is missing`, it is `docker is missing
    so we quietly ran it on the host`. The result would be true and the claim
    would be false."""
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(ToolError, match="bwrap\\(1\\) is not on PATH"):
        ex.resolve_backend("bubblewrap")


def test_resolve_backend_refuses_a_name_it_has_never_heard_of():
    with pytest.raises(SpecError, match="unknown exec backend"):
        ex.resolve_backend("namespace")


def test_backends_report_says_what_this_host_can_do():
    report = ex.backends_report()
    names = {b["name"] for b in report}
    # docker is mentioned as a known-but-absent backend, not by backends_report:
    # it arrives with the environment lab
    assert names == {"local", "bubblewrap"}
    assert all("available" in b and "detail" in b for b in report)


# --------------------------------------------------------------------------- #
# ExecResult.ok: success is measured against what was declared
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "kwargs, ok",
    [
        ({}, True),                                        # exit 0, as declared
        ({"exit_code": 1, "expect_exit": [1]}, True),      # a failing test is the point
        ({"exit_code": 1}, False),                         # not declared
        ({"timed_out": True}, False),
        ({"refused": "backend missing"}, False),
    ],
)
def test_ok_is_not_merely_exit_zero(kwargs, ok):
    """`ok` is a judgement against what the spec declared, not a comparison with
    zero. A video about a failing test declares `expect_exit: [1]`, and that run is
    a success."""
    fields = dict({"exit_code": 0}, **kwargs)
    req = sp.Exec(label="a", cmd=["x"], expect_exit=fields.pop("expect_exit", [0]))
    assert ex.ExecResult(request=_as_request(req), **fields).ok is ok


def _as_request(step) -> ex.ExecRequest:
    return ex.ExecRequest(cmd=list(step.cmd), shell=list(step.shell), cwd=step.cwd,
                          timeout=step.timeout, backend=step.backend,
                          expect_exit=list(step.expect_exit), label=step.label)


def test_a_refusal_reports_itself_as_the_exit_code_of_a_command_that_cannot_start():
    """126 is what a shell uses for "found it, could not run it". Reusing it means
    a refusal reads as a normal failure to anything downstream that only looks at
    the code."""
    result = ex.ExecResult(request=ex.ExecRequest(cmd=["nope"], label="a"),
                           exit_code=126, refused="nothing to run")
    assert result.exit_code == 126 and not result.ok
    assert result.to_dict()["refused"] == "nothing to run"


def test_the_result_record_keeps_the_whole_story():
    """A verdict cannot be re-examined. The record has to carry the boundary it
    ran under as well, because that is what makes the claim checkable later."""
    result = ex.ExecResult(
        request=ex.ExecRequest(cmd=["ls"], label="list", cwd="sub", timeout=5.0,
                               backend="bubblewrap", network=False),
        exit_code=0, stdout="ok\n", seconds=1.2345, backend="bubblewrap")
    d = result.to_dict()
    assert d["label"] == "list" and d["cmd"] == ["ls"] and d["cwd"] == "sub"
    assert d["backend"] == "bubblewrap" and d["network"] is False
    assert d["expected"] is True and d["seconds"] == 1.234
    assert d["stdout_bytes"] == 3


# --------------------------------------------------------------------------- #
# redact_bytes: length-preserving, or the recording shears
# --------------------------------------------------------------------------- #
def test_redaction_masks_a_secret_that_was_printed_back():
    """The realistic leak: a command echoes a token, or a failing curl prints its
    own URL. A recorded terminal is a published terminal."""
    s = Secrets()
    s.declare("TOKEN")
    s.values = {"TOKEN": "s3cr3t-value"}
    raw = b"Authorization: Bearer s3cr3t-value\r\n"
    out = s.redact_bytes(raw)
    assert b"s3cr3t-value" not in out
    assert b"****" in out and b"Authorization" in out


def test_redaction_preserves_the_length_byte_for_byte():
    """This is not tidiness. A cast is a stream of timed cursor movements; making
    it shorter moves every escape sequence that follows, and the replay then draws
    a screen nobody saw."""
    s = Secrets()
    s.declare("TOKEN")
    s.values = {"TOKEN": "abc"}
    raw = b"x\x1b[31mabc\x1b[0m\x1b[1;5Ht"
    assert len(s.redact_bytes(raw)) == len(raw)


def test_redaction_copes_with_a_multibyte_secret():
    s = Secrets()
    s.declare("TOKEN")
    s.values = {"TOKEN": "clé-ü"}
    raw = "clé-ü ok".encode("utf-8")
    out = s.redact_bytes(raw)
    assert len(out) == len(raw)
    assert "clé-ü".encode("utf-8") not in out


def test_redaction_leaves_ordinary_output_alone():
    s = Secrets()
    s.declare("TOKEN")
    s.values = {"TOKEN": "abc"}
    assert s.redact_bytes(b"all tests passed\r\n") == b"all tests passed\r\n"
    assert s.redact_bytes(b"") == b""


def test_redaction_masks_the_longest_secret_first():
    """Two values where one contains the other: masking the short one first
    would leave the second half of the long one visible."""
    s = Secrets()
    s.needs = {}
    s.values = {"A": "token", "B": "token-extra"}
    assert s.redact_bytes(b"[token-extra]") == b"[***********]"


# --------------------------------------------------------------------------- #
# _exec_span: how long each recorded frame is held
# --------------------------------------------------------------------------- #
def _span_ctx(tmp_path, fps: int = 30):
    spec = sp.load_spec(_yaml(tmp_path, steps=[{"label": "a", "cmd": "ls"}]))
    spec.project.fps = fps
    from vidkit.context import Context
    ctx = Context(spec=spec, root=spec.root, out_dir=tmp_path / "_out")
    ctx.ensure_dirs()
    return ctx


def _frames(*times):
    from vidkit.assembler import Assets
    a = Assets()
    a.exec_frames["a"] = [(t, Path(f"f{i}.png")) for i, t in enumerate(times)]
    return a


def test_span_needs_two_frames_or_the_shot_is_a_still(tmp_path):
    from vidkit.assembler import _exec_span
    ctx = _span_ctx(tmp_path)
    assert _exec_span(ctx, _frames(0.0), sp.Shot(kind="exec", ref="a"), 5.0) is None
    assert _exec_span(ctx, _frames(), sp.Shot(kind="exec", ref="a"), 5.0) is None


def test_interior_frames_keep_their_measured_pace(tmp_path):
    """A command that paused for two seconds paused for two seconds. Re-timing it
    to look brisk would be the recording lying about how long the work took."""
    from vidkit.assembler import _exec_span
    ctx = _span_ctx(tmp_path)
    paths, held, speed = _exec_span(
        ctx, _frames(0.0, 2.0, 2.5, 3.0), sp.Shot(kind="exec", ref="a"), 10.0)
    assert [round(h, 2) for h in held[:3]] == [2.0, 0.5, 0.5]
    assert speed == 1.0 and len(paths) == 4
    assert sum(held) == pytest.approx(10.0, abs=1e-6)


def test_the_final_frame_takes_whatever_time_is_left(tmp_path):
    """The common case: a command prints its result and exits, so its final screen
    has a measured span of exactly zero. A shot that held it for zero seconds would
    end on a frame nobody could read."""
    from vidkit.assembler import _exec_span
    ctx = _span_ctx(tmp_path)
    paths, held, speed = _exec_span(
        ctx, _frames(0.0, 0.5, 0.9), sp.Shot(kind="exec", ref="a"), 6.0)
    assert held[-1] > 4.0, f"the last frame was held for {held[-1]}s"
    assert sum(held) == pytest.approx(6.0, abs=1e-6)


def test_at_chooses_the_moment_the_shot_is_about(tmp_path):
    """`at:` is how a spec films a step of a long command rather than its end."""
    from vidkit.assembler import _exec_span
    ctx = _span_ctx(tmp_path)
    paths, held, _ = _exec_span(
        ctx, _frames(0.0, 1.0, 2.0, 3.0, 4.0), sp.Shot(kind="exec", ref="a", at=2.0), 8.0)
    assert [p.name for p in paths] == ["f0.png", "f1.png", "f2.png"]
    assert sum(held) == pytest.approx(8.0, abs=1e-6)


def test_at_before_the_first_moment_still_shows_something(tmp_path):
    from vidkit.assembler import _exec_span
    ctx = _span_ctx(tmp_path)
    paths, held, _ = _exec_span(
        ctx, _frames(1.0, 2.0), sp.Shot(kind="exec", ref="a", at=0.2), 4.0)
    assert [p.name for p in paths] == ["f0.png"]
    assert sum(held) == pytest.approx(4.0, abs=1e-6)


def test_no_frame_is_ever_held_for_zero_seconds(tmp_path):
    from vidkit.assembler import _exec_span
    ctx = _span_ctx(tmp_path)
    for seconds in (0.5, 1.0, 6.0):
        _, held, _ = _exec_span(
            ctx, _frames(0.0, 0.5, 5.0), sp.Shot(kind="exec", ref="a"), seconds)
        assert min(held) >= 1.0 / 30, f"a frame vanished from a {seconds}s shot"


def test_a_recording_that_overruns_its_take_is_compressed_and_says_so(tmp_path, capsys):
    """Honest re-timing. A screencast at 2x is fine as long as the build says 2x;
    quietly claiming a four-second build took half a second is not."""
    from vidkit.assembler import _exec_span
    ctx = _span_ctx(tmp_path)
    paths, held, speed = _exec_span(
        ctx, _frames(0.0, 2.0, 4.0, 6.0), sp.Shot(kind="exec", ref="a"), 1.0)
    assert speed > 1.0
    assert sum(held) == pytest.approx(1.0, abs=1e-6)
    out = capsys.readouterr().out
    assert "WARN" in out and "playing at" in out and "exec a" in out


def test_a_recording_that_fits_is_not_reported_as_re_timed(tmp_path, capsys):
    from vidkit.assembler import _exec_span
    ctx = _span_ctx(tmp_path)
    _, _, speed = _exec_span(
        ctx, _frames(0.0, 0.5, 1.0), sp.Shot(kind="exec", ref="a"), 30.0)
    assert speed == 1.0
    assert "WARN" not in capsys.readouterr().out


def test_the_frames_are_index_aligned_with_their_durations(tmp_path):
    """The bug this pins: the older form returned `paths` and `held` with different
    lengths, so ffmpeg was handed a duration for a frame that did not exist."""
    from vidkit.assembler import _exec_span
    ctx = _span_ctx(tmp_path)
    paths, held, _ = _exec_span(
        ctx, _frames(0.0, 1.0, 2.0), sp.Shot(kind="exec", ref="a"), 5.0)
    assert len(paths) == len(held)


# --------------------------------------------------------------------------- #
# the sandbox itself: these start a process, so they need the render toolchain
# --------------------------------------------------------------------------- #
pytestmark_render = pytest.mark.needs_render

_HAVE_BWRAP = shutil.which("bwrap") is not None


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "work"
    root.mkdir(exist_ok=True)
    return root


@pytest.mark.needs_render
def test_run_records_what_the_command_printed(tmp_path):
    root = _root(tmp_path)
    req = ex.ExecRequest(cmd=["/bin/echo", "measured"], backend="local")
    result = ex.run(req, root=root)
    assert result.ok, result.refused
    assert "measured" in result.stdout
    assert result.exit_code == 0 and result.seconds > 0


@pytest.mark.needs_render
def test_run_is_handed_a_real_terminal_not_a_pipe(tmp_path):
    """The reason this module uses a PTY at all. `tty` exits 1 on a pipe and 0 on a
    terminal, so this assertion is the difference between filming a terminal and
    filming a transcript no terminal ever displayed."""
    root = _root(tmp_path)
    result = ex.run(ex.ExecRequest(cmd=["/bin/sh", "-c", "tty >/dev/null"],
                                   backend="local"), root=root)
    assert result.exit_code == 0, (
        "the command did not see a terminal — the recording would show output the "
        "program would never have printed to a real one")


@pytest.mark.needs_render
def test_run_reports_the_exit_code_a_spec_declared_as_expected(tmp_path):
    root = _root(tmp_path)
    req = ex.ExecRequest(cmd=["/bin/sh", "-c", "exit 3"], backend="local",
                         label="fails on purpose", expect_exit=[3])
    result = ex.run(req, root=root)
    assert result.exit_code == 3 and result.expected and result.ok


@pytest.mark.needs_render
def test_run_kills_the_whole_process_group_on_timeout(tmp_path):
    """`sleep 30` under a 1.5s timeout must be *gone*, not merely abandoned. A live
    orphan holding a port is how a build leaves a machine in a state no one meant."""
    root = _root(tmp_path)
    marker = root / "still-here"
    req = ex.ExecRequest(
        cmd=["/bin/sh", "-c", f"sleep 2; touch {marker}"],
        backend="local", timeout=1.5)
    result = ex.run(req, root=root)
    assert result.timed_out and not result.ok
    import time as _t
    _t.sleep(1.5)
    assert not marker.exists(), "the process group survived the timeout"


@pytest.mark.needs_render
def test_stream_reaches_a_killed_command_but_run_still_returns_a_result(tmp_path):
    root = _root(tmp_path)
    req = ex.ExecRequest(cmd=["/bin/sh", "-c", "echo half; exit 9"], backend="local",
                         expect_exit=[9])
    chunks: list[bytes] = []
    result = ex.run(req, root=root, on_chunk=chunks.append)
    assert result.exit_code == 9 and result.ok
    assert b"half" in b"".join(chunks)


@pytest.mark.needs_render
def test_run_refuses_a_missing_working_directory_without_running_anything(tmp_path):
    root = _root(tmp_path)
    result = ex.run(ex.ExecRequest(cmd=["/bin/echo", "no"], cwd="gone",
                                   backend="local"), root=root)
    assert not result.ok and "does not exist" in result.refused
    assert result.stdout == ""


@pytest.mark.skipif(not (_HAVE_BWRAP), reason="bwrap(1) not installed")
@pytest.mark.needs_render
def test_bwrap_sandbox_cannot_write_outside_the_declared_directory(tmp_path):
    """Read is granted from the system roots; *write* is granted only to the bound
    working directory. The asymmetry is the point: a command may read a library and
    may not edit the repository it was run from.

    The host path is not mounted at all, so the shell's own error is whichever of
    "no such file or directory" or "directory nonexistent" applies — what matters
    is that the sandbox gave it nowhere to write, not how it worded the refusal.
    """
    root = _root(tmp_path)
    outside = root.parent / "untouchable"
    outside.write_text("original", encoding="utf-8")
    req = ex.ExecRequest(
        cmd=["/bin/sh", "-c", f"echo changed > {outside}; echo status=$?"],
        backend="bubblewrap")
    result = ex.run(req, root=root)
    assert outside.read_text(encoding="utf-8") == "original"
    assert "status=0" not in result.stdout, (
        f"the sandbox let the command write outside its working directory: "
        f"{result.stdout!r}")


@pytest.mark.skipif(not (_HAVE_BWRAP), reason="bwrap(1) not installed")
@pytest.mark.needs_render
def test_bwrap_sandbox_cannot_write_to_the_read_only_system_roots(tmp_path):
    """The other half of the asymmetry: a path that *is* visible is still
    read-only, so the refusal there is a permission failure rather than a missing
    directory."""
    root = _root(tmp_path)
    target = "/usr/share/vidkit-should-not-exist"
    result = ex.run(ex.ExecRequest(
        cmd=["/bin/sh", "-c", f"echo changed > {target}; echo status=$?"],
        backend="bubblewrap"), root=root)
    assert "status=0" not in result.stdout
    assert not Path(target).exists()


@pytest.mark.skipif(not _HAVE_BWRAP, reason="bwrap(1) not installed")
@pytest.mark.needs_render
def test_the_sandbox_has_no_network_unless_the_command_declared_it(tmp_path):
    """Built network-less first and opened by the flag, so an author who forgets
    gets the safe behaviour rather than the unsafe one."""
    root = _root(tmp_path)
    probe = ("python3 -c \"import socket,sys;"
             "socket.create_connection(('1.1.1.1',53),0.4);print('REACHED')\" "
             "2>/dev/null || echo BLOCKED")
    off = ex.run(ex.ExecRequest(cmd=["/bin/sh", "-c", probe],
                                backend="bubblewrap"), root=root)
    assert "BLOCKED" in off.stdout and "REACHED" not in off.stdout

    on = ex.run(ex.ExecRequest(cmd=["/bin/sh", "-c", probe], network=True,
                               backend="bubblewrap"), root=root)
    assert "REACHED" in on.stdout, (
        "the sandbox did not come back with the network it was told to open; "
        f"got {on.stdout!r} (refused={on.refused!r})")


@pytest.mark.skipif(not _HAVE_BWRAP, reason="bwrap(1) not installed")
@pytest.mark.needs_render
def test_the_sandbox_runs_the_command_in_the_declared_directory(tmp_path):
    root = _root(tmp_path)
    (root / "sub").mkdir(exist_ok=True)
    result = ex.run(ex.ExecRequest(cmd=["/bin/sh", "-c", "pwd"], cwd="sub",
                                   backend="bubblewrap"), root=root)
    assert result.stdout.strip() == "/work"
    assert result.ok


@pytest.mark.skipif(not _HAVE_BWRAP, reason="bwrap(1) not installed")
@pytest.mark.needs_render
def test_a_sandboxed_command_may_write_inside_the_bound_directory(tmp_path):
    root = _root(tmp_path)
    result = ex.run(ex.ExecRequest(cmd=["/bin/sh", "-c", "echo hi > made.txt"],
                                   backend="bubblewrap"), root=root)
    assert result.exit_code == 0, result.refused
    assert (root / "made.txt").read_text(encoding="utf-8").strip() == "hi"


@pytest.mark.skipif(not _HAVE_BWRAP, reason="bwrap(1) not installed")
@pytest.mark.needs_render
def test_the_environment_a_command_sees_is_the_declared_one(tmp_path, monkeypatch):
    """A recorded environment is a published environment, so the sandbox gets the
    declared environment rather than the builder's."""
    monkeypatch.setenv("VIDKIT_LEAKY_SECRET", "should-not-appear")
    root = _root(tmp_path)
    result = ex.run(ex.ExecRequest(
        cmd=["/bin/sh", "-c", "echo [${VIDKIT_LEAKY_SECRET-unset}]"],
        backend="bubblewrap"), root=root)
    assert "should-not-appear" not in result.stdout
    assert "[unset]" in result.stdout


@pytest.mark.skipif(not _HAVE_BWRAP, reason="bwrap(1) not installed")
@pytest.mark.needs_render
def test_a_declared_read_root_is_visible_inside_the_sandbox(tmp_path):
    root = _root(tmp_path)
    extra = tmp_path / "extra"
    extra.mkdir()
    (extra / "data.txt").write_text("readable", encoding="utf-8")
    result = ex.run(ex.ExecRequest(cmd=["/bin/cat", str(extra / "data.txt")],
                                   reads=[str(extra)], backend="bubblewrap"), root=root)
    assert "readable" in result.stdout and result.ok


# --------------------------------------------------------------------------- #
# what the report attests, in verify.json
#
# A verify.json that is silent about something is not the same as a verify.json
# that is not about it. These pin the two places where an exec attestation could
# be told apart from "this check never applied" only by a human reading the
# source — which is exactly the state the file exists to avoid.
# --------------------------------------------------------------------------- #
def _exec_verified(tmp_path, steps, *, playback=None, frames=None, casts=None):
    """Run ``verify_output`` over hand-built exec assets, with no render."""
    from vidkit.assembler import Assets, _exec_request, make_context
    from vidkit.verify import verify_output

    spec = sp.load_spec(_yaml(tmp_path, steps=steps))
    ctx = make_context(tmp_path / "video.yaml", tmp_path / "out")
    ctx.spec = spec
    assets = Assets()
    for step in spec.exec:
        assets.exec_results[step.label] = ex.ExecResult(
            request=_exec_request(step, ctx), exit_code=0, stdout="ran\n",
            backend=step.backend)
    for label, name in (casts or {}).items():
        assets.exec_casts[label] = Path(name)
    assets.exec_playback.update(playback or {})
    assets.exec_take_frames.update(frames or {})
    return verify_output(ctx, assets, {0: "hello"})


def test_a_check_that_passed_is_still_written_down(tmp_path):
    """Defect E. `every declared command ran` used to appear only when it *failed*,
    so a green verify.json said nothing at all about whether the commands ran —
    a passing report and an inapplicable check looked identical. An attestation
    that exists only as an absence attests to nothing."""
    steps = [{"label": "a", "cmd": "ls"}, {"label": "b", "cmd": "true"}]
    rep = _exec_verified(tmp_path, steps)
    ran = next(c for c in rep.checks if c.name == "every declared command ran")
    assert ran.ok is True
    assert "2 command(s), all recorded" in ran.detail


def test_a_command_in_the_spec_that_never_recorded_is_an_actual_failure(tmp_path):
    """The other half of defect E: now that the check always exists, it must also
    be able to fail. A declared command with no result is the one thing this
    check is for."""
    steps = [{"label": "a", "cmd": "ls"}, {"label": "b", "cmd": "true"}]
    from vidkit.assembler import Assets, _exec_request, make_context
    from vidkit.verify import verify_output

    spec = sp.load_spec(_yaml(tmp_path, steps=steps))
    ctx = make_context(tmp_path / "video.yaml", tmp_path / "out")
    ctx.spec = spec
    assets = Assets()
    assets.exec_results["a"] = ex.ExecResult(
        request=_exec_request(spec.exec[0], ctx), exit_code=0, backend="bubblewrap")
    rep = verify_output(ctx, assets, {0: "hello"})
    ran = next(c for c in rep.checks if c.name == "every declared command ran")
    assert ran.ok is False
    assert "['b']" in ran.detail


def test_the_report_says_which_recordings_were_shown_as_a_moving_take(tmp_path):
    """Defect F. `playback` was `None` both for a recording replayed at 1.0x as a
    single held screen and for one never shown as a take at all — the reader could
    not tell "played at its real pace" from "there was no playback here"."""
    steps = [{"label": "a", "cmd": "ls"}, {"label": "b", "cmd": "true"}]
    rep = _exec_verified(tmp_path, steps, playback={"a": 1.0},
                         frames={"a": 3}, casts={"a": "a.cast"})
    facts = {f["label"]: f for f in rep.facts["exec"]}
    assert facts["a"]["frames"] == 3 and facts["a"]["playback"] == 1.0
    assert facts["b"]["frames"] is None and facts["b"]["playback"] is None


def test_a_recording_shown_as_one_screen_does_not_claim_a_playback_speed(tmp_path):
    """The distinction the fact exists to make. One screen is not a take played
    slowly — it is a take that was never a take, and the report says so by leaving
    both fields null rather than by reporting a speed it did not measure."""
    steps = [{"label": "a", "cmd": "ls"}]
    rep = _exec_verified(tmp_path, steps, casts={"a": "a.cast"})
    fact = rep.facts["exec"][0]
    assert fact["cast"] == "a.cast"
    assert fact["frames"] is None and fact["playback"] is None
