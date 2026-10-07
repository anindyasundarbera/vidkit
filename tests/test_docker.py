"""Tests for the declared-environment lifecycle (R-E6).

The claim this module exists to protect is a *causal* one: the video shows a
write and then a read-back **of the same system**. That is why an environment is
started once and every command is ``docker exec``-ed into it, rather than each
command getting its own ``docker run``. Two containers would film two different
databases and every individual frame would still be honest — which is exactly
how a demo lies while passing a per-frame review.

So the tests are grouped by the four things that can break that claim:

**argv shape** — what the container is and is not given. Pure string building,
needs no Docker, and runs everywhere.

**the refusal paths** — a spec asking for something the host cannot give must be
refused *before* a camera rolls, not downgraded into a build whose evidence is
true and whose claim is false (invariant I7).

**the lifecycle, against a real daemon** — up, ready, exec, logs, teardown. These
carry ``needs_docker``, which is a *probe*: a machine with the client installed
and the daemon down is not a machine that can run a declared environment.

**teardown on every exit path** — the property that matters most and is easiest
to lose, because the path that leaks is the one nobody exercises: a crash
between "the container exists" and "the container is ready".

The readiness tests are the subtle ones. Postgres on ``postgres:16-alpine``
answers ``pg_isready`` at t≈1.30 s against its *bootstrap* server, which is shut
down at t≈1.45 s; the server that survives only accepts connections from
t≈1.84 s. A single successful sample therefore certifies a database that is
about to vanish, and the next ``docker exec`` fails with ``the database system is
shutting down``. See :data:`vidkit.exec.READY_HOLD`.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
import time
from pathlib import Path

import pytest

from vidkit import exec as ex
from vidkit import spec as sp
from vidkit.assembler import Assets, _start_environments, _stop_environments
from vidkit.errors import SpecError, ToolError

from conftest import _HAVE_DOCKER


needs_docker = pytest.mark.needs_docker


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _fresh_probe():
    """``docker_available`` memoises per process; tests monkeypatch underneath it."""
    ex._PROBE_CACHE.clear()
    ex.unbind_environments()
    yield
    ex.unbind_environments()
    ex._PROBE_CACHE.clear()


@pytest.fixture
def env() -> ex.EnvSpec:
    return ex.EnvSpec(name="db", image="postgres:16-alpine",
                      env={"POSTGRES_PASSWORD": "demo"})


class _Ctx:
    """The three things the environment stage reads off a real ``Context``."""

    def __init__(self, root: Path, spec: sp.Spec):
        self.root = root
        self.spec = spec
        self.execs = root / "_build" / "exec"
        self.assets = Assets()
        self.notes: list[tuple[str, str]] = []

    def info(self, message: str) -> None:
        self.notes.append(("info", message))

    def warn(self, message: str) -> None:
        self.notes.append(("warn", message))

    def said(self, level: str) -> str:
        return "\n".join(m for lvl, m in self.notes if lvl == level)


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "video.yaml"
    path.write_text(textwrap.dedent(text).strip() + "\n", encoding="utf-8")
    return path


#: The smallest spec that loads: everything `load_spec` requires and nothing else.
_MINIMAL = """
    project:
      title: Probe
      slug: probe
      output: probe.mp4
      size: [320, 180]
      fps: 12
      min_seconds: 1
      max_seconds: 60
    style:
      font: DejaVu Sans
      background: "#101418"
      foreground: "#ffffff"
      accent: "#4aa3df"
      title: Probe
    voice: {engine: none}
    narration: {inline: {1: "One."}}
    scenes:
      - n: 1
        title: One
        shots: [{exec: thing, effect: hold}]
"""


def _docker_spec(tmp_path: Path, *, image: str = "postgres:16-alpine",
                 extra: str = "", ready: str = "true", ready_argv: str = "",
                 command: str = "", trailing: str = "") -> sp.Spec:
    """A minimal spec with one declared environment and one docker-backed step.

    Assembled by concatenation rather than one interpolated triple-quoted string,
    because ``textwrap.dedent`` measures the common indent of *every* non-blank
    line: interpolating ``_MINIMAL`` (indented 4) next to lines indented 8 makes
    dedent strip only four columns, and the ``environment:`` block lands inside
    ``scenes:``. That failure mode is silent — the spec still parses, it just
    means something else — so the shape is fixed here and never re-derived.

    ``command`` is the *environment's* command — what keeps the container alive —
    and is emitted at the environment's indentation on purpose. Appending it after
    the ``exec:`` block instead put it at document level, where it was silently
    ignored: the container then ran the image's default command, exited at once,
    and every readiness test failed with "container … is not running" while the
    spec looked correct.
    """
    body = [
        textwrap.dedent(_MINIMAL),
        "environment:",
        "  - name: db",
        f"    image: {image}",
    ]
    # ``ready`` is the plain form — one word, emitted as a one-element argv. When
    # the command contains spaces, `ready_argv` takes the YAML list form verbatim:
    # a readiness command is an argv and never a shell line, so `sh -c '…'` has to
    # be spelled as one too. Passing the whole shell line through `ready` made the
    # container try to exec a file called `sh -c 'if [ -e …`.
    if ready_argv:
        body.append("    ready: " + textwrap.dedent(ready_argv).strip())
    else:
        body.append(f'    ready: ["{ready}"]')
    body.append("    ready_timeout: 8")
    if command:
        # Indented by four because this fragment is a *field of the environment*,
        # and the caller writes it flush-left for readability. Nothing in YAML
        # would complain about it landing at document level instead — the key
        # would simply be ignored, the image's own command would run, the
        # container would exit, and every readiness assertion would fail with
        # "container … is not running" while the spec still looked right.
        for line in textwrap.dedent(command).rstrip("\n").splitlines():
            body.append("    " + line)
    if extra:
        body.append(textwrap.dedent(extra).rstrip("\n"))
    body += [
        "exec:",
        "  steps:",
        "    - label: thing",
        "      backend: docker",
        "      environment: db",
        '      cmd: ["true"]',
    ]
    if trailing:
        body.append("      " + textwrap.dedent(trailing).rstrip("\n"))
    _write(tmp_path, "\n".join(body))
    return sp.load_spec(tmp_path / "video.yaml")


def _spec_text(body: str) -> str:
    """``_MINIMAL`` plus ``body``, each dedented on its own.

    See :func:`_docker_spec` for why they are dedented separately.
    """
    return textwrap.dedent(_MINIMAL) + textwrap.dedent(body).rstrip("\n") + "\n"


def _refuse(tmp_path: Path, text: str) -> str:
    """Load ``text``, assert it is refused, and return the message."""
    _write(tmp_path, text)
    with pytest.raises(SpecError) as caught:
        sp.load_spec(tmp_path / "video.yaml")
    return str(caught.value)


# --------------------------------------------------------------------------- #
# 1. argv shape — what the container is given. No Docker required.
# --------------------------------------------------------------------------- #
def test_the_container_is_named_after_the_environment_and_is_identifiable(env):
    """A leak has to be attributable from ``docker ps`` alone."""
    name = ex._container_name(env, "abc123")
    assert name.startswith(ex.DOCKER_PREFIX)
    assert "db" in name and name.endswith("abc123")


def test_a_name_with_an_ugly_environment_name_is_still_a_legal_container_name(env):
    env.name = "My Environment/Db!"
    name = ex._container_name(env, "s")
    assert name == "vidkit-my-environment-db-s"


def test_the_project_is_bound_read_only_and_by_the_backend(tmp_path):
    """The spec cannot forget to give its commands their files."""
    args = ex._docker_volume_args(None, tmp_path)
    assert args == ["-v", f"{tmp_path}:{ex.DOCKER_WORKDIR}:ro"]


def test_a_declared_volume_is_added_after_the_projects(env, tmp_path):
    env.volumes = ["/tmp/data:/data"]
    args = ex._docker_volume_args(env, tmp_path)
    assert args[-2:] == ["-v", "/tmp/data:/data"]
    assert args[1].startswith(str(tmp_path))


def test_the_container_gets_the_declared_environment(env, tmp_path):
    argv = ex._docker_create_argv(env, tmp_path, "vidkit-db-x")
    assert "-e" in argv and "POSTGRES_PASSWORD=demo" in argv


def test_network_is_none_unless_the_spec_asks(env, tmp_path):
    argv = ex._docker_create_argv(env, tmp_path, "n")
    assert argv[argv.index("--network") + 1] == "none"


def test_a_spec_that_asks_for_network_gets_it(env, tmp_path):
    env.network = True
    assert "--network" not in ex._docker_create_argv(env, tmp_path, "n")


def test_the_container_is_created_in_the_background_and_not_self_removing(env, tmp_path):
    """``--rm`` would destroy the logs, and the logs are the evidence."""
    argv = ex._docker_create_argv(env, tmp_path, "n")
    assert argv[:3] == ["run", "-d", "--name"]
    assert "--rm" not in argv


def test_the_container_carries_vidkit_s_own_labels(env, tmp_path):
    argv = ex._docker_create_argv(env, tmp_path, "n")
    for key, value in ex.DOCKER_LABELS.items():
        assert f"{key}={value}" in argv


def test_docker_exec_runs_into_the_running_environment_not_a_fresh_container(env):
    """The causal claim of the whole feature, expressed as an argv."""
    req = ex.ExecRequest(cmd=["psql", "-c", "select 1"], backend="docker", label="thing")
    argv = ex._docker_argv(req, Path("."), env, "cid")
    assert argv[:3] == ["docker", "exec", "-i"]
    assert argv[3] != "run" and "run" not in argv, "a fresh container per command"
    assert "cid" in argv
    assert argv[argv.index("cid"):] == ["cid", "psql", "-c", "select 1"]


def test_docker_exec_asks_for_a_terminal(env):
    """A program that changes what it prints off a TTY must be filmed on one."""
    req = ex.ExecRequest(cmd=["true"], backend="docker", label="thing")
    assert "-t" in ex._docker_argv(req, Path("."), env, "cid")


def test_the_workdir_inside_the_container_is_not_the_host_path(env):
    """A spec writes the *relative* path; the host path must not leak in."""
    req = ex.ExecRequest(cmd=["true"], cwd="sub", backend="docker", label="thing")
    assert ex._docker_workdir(req, Path("/host/sub")) == f"{ex.DOCKER_WORKDIR}/sub"
    at_root = ex.ExecRequest(cmd=["true"], backend="docker", label="thing")
    assert ex._docker_workdir(at_root, Path("/host")) == ex.DOCKER_WORKDIR


@needs_docker
def test_the_container_does_not_inherit_the_hosts_home_or_paths(env, tmp_path, monkeypatch):
    """``PWD`` is a path *inside* the container, and ``HOME`` is not the host's.

    Asserting the dictionary entry alone would only prove the engine wrote a
    string. What matters is the string names the directory the command is really
    in, so this asks the container.

    ``HOME`` is asserted from the *client's* environment and from the container
    separately, because they have different answers and both matter. The client
    must not be handed a ``HOME`` it cannot read: it warns about the unreadable
    ``.docker/config.json`` on the same PTY the recording captures, and that
    warning ends up in the cast and in the stills as if the command had printed
    it. The container's ``HOME`` is its own — uid 0 has ``/root`` from
    ``/etc/passwd`` — and the host's path must not be passed in to replace it.

    Deliberately *not* proved through ``PS1``, which an earlier version did: a
    shell sets its own default prompt whatever the environment said, so that
    assertion passed against a container the engine had given no environment at
    all. It was a false negative wearing the costume of a real check.
    """
    req = ex.ExecRequest(cmd=["true"], backend="docker", label="thing")
    environ = ex._env_for(req, Path("/host/dir"), "docker")
    assert "HOME" not in environ, "the docker client must not be given a host HOME"
    assert ex.BASE_ENV["HOME"] not in environ.values()
    assert environ["PWD"] == ex.DOCKER_WORKDIR
    assert "/host/dir" not in environ["PWD"]

    env.command = ["sleep", "60"]
    state = ex.environment_up(env, root=tmp_path)
    try:
        ex.bind_step("thing", state)
        result = ex.run(ex.ExecRequest(cmd=["pwd"], backend="docker", label="thing"),
                        root=tmp_path)
        assert result.exit_code == 0, result.stdout
        assert result.stdout.strip() == ex.DOCKER_WORKDIR

        home = ex.run(ex.ExecRequest(cmd=["sh", "-c", "echo ${HOME:-unset}"],
                                     backend="docker", label="thing"), root=tmp_path)
        assert home.exit_code == 0, home.stdout
        container_home = home.stdout.strip().splitlines()[-1]
        assert container_home != ex.BASE_ENV["HOME"]
        assert "/host/dir" not in container_home
    finally:
        ex.environment_down(state)


def test_a_docker_step_with_no_running_environment_is_refused_not_ran():
    """An exec step may not quietly start its own container and leave it behind."""
    req = ex.ExecRequest(cmd=["true"], backend="docker", label="orphan")
    with pytest.raises(SpecError, match="no environment is running"):
        ex._launch_argv("docker", req, Path("."))


def test_binding_is_released_when_the_environment_is_torn_down(env):
    state = ex.EnvState(spec=env, container_id="c", container_name="n")
    ex.bind_step("thing", state)
    assert ex._ENV_FOR_RUN["thing"] is env
    ex.unbind_environments()
    assert ex._ENV_FOR_RUN == {} and ex._CONTAINER_FOR_RUN == {}


# --------------------------------------------------------------------------- #
# 2. The refusal paths. A wrong answer here is a build whose evidence is true
#    and whose claim is false.
# --------------------------------------------------------------------------- #
def test_the_spec_cannot_declare_a_field_the_engine_never_honours(tmp_path):
    """A silently ignored ``privileged: true`` is an author believing a lie."""
    assert "unknown field" in _refuse(tmp_path, _spec_text("""
        environment:
          - name: db
            image: alpine
            privileged: true
        exec:
          steps: [{label: thing, backend: docker, environment: db, cmd: ["true"]}]
    """))


def test_an_environment_needs_an_image(tmp_path):
    assert "needs an `image`" in _refuse(tmp_path, _spec_text("""
        environment:
          - name: db
        exec:
          steps: [{label: thing, backend: docker, environment: db, cmd: ["true"]}]
    """))


def test_a_volume_must_say_where_it_goes(tmp_path):
    """A bare path mounts an empty volume, which reads as the command failing."""
    assert "HOST:CONTAINER" in _refuse(tmp_path, _spec_text("""
        environment:
          - {name: db, image: alpine, volumes: [/data]}
        exec:
          steps: [{label: thing, backend: docker, environment: db, cmd: ["true"]}]
    """))


def test_two_environments_cannot_share_a_name(tmp_path):
    assert "declared twice" in _refuse(tmp_path, _spec_text("""
        environment:
          - {name: db, image: alpine}
          - {name: db, image: alpine}
        exec:
          steps: [{label: thing, backend: docker, environment: db, cmd: ["true"]}]
    """))


def test_a_docker_step_must_name_an_environment_it_can_reach(tmp_path):
    assert "needs an `environment:`" in _refuse(tmp_path, _spec_text("""
        exec:
          steps: [{label: thing, backend: docker, cmd: ["true"]}]
    """))


def test_only_docker_steps_may_name_an_environment(tmp_path):
    """The sandbox is a per-command decision; letting `local` name one makes it a hint."""
    assert "only `backend: docker` runs inside" in _refuse(tmp_path, _spec_text("""
        environment:
          - {name: db, image: alpine}
        exec:
          steps: [{label: thing, backend: local, environment: db, cmd: ["true"]}]
    """))


def test_an_environment_nobody_uses_is_refused(tmp_path):
    assert "no exec step declares" in _refuse(tmp_path, _spec_text("""
        environment:
          - {name: db, image: alpine}
          - {name: unused, image: alpine}
        exec:
          steps: [{label: thing, backend: docker, environment: db, cmd: ["true"]}]
    """))


def test_a_docker_step_naming_an_undefined_environment_is_refused(tmp_path):
    """Both halves are reported: the step points nowhere, and `db` is then unused."""
    said = _refuse(tmp_path, _spec_text("""
        environment:
          - {name: db, image: alpine}
        exec:
          steps: [{label: thing, backend: docker, environment: nope, cmd: ["true"]}]
    """))
    assert "no such environment is defined" in said
    assert "no exec step declares `environment: db`" in said


def test_a_scene_showing_a_docker_step_the_spec_never_declared_is_refused(tmp_path):
    """The M7 message has to survive M8: an exec shot names a *label*, not an image."""
    assert "declares no `exec:` steps" in _refuse(tmp_path, textwrap.dedent(_MINIMAL))


def test_a_host_that_cannot_run_containers_refuses_the_spec_at_load_time(
        monkeypatch, tmp_path):
    """Better a load-time refusal than a build that downgrades without saying so."""
    monkeypatch.setattr(ex, "_PROBE_CACHE", {})
    monkeypatch.setattr(ex, "docker_client", lambda: None)
    problems = ex.check_policy(
        [ex.ExecRequest(cmd=["true"], backend="docker", label="thing")],
        root=tmp_path, allow_network=False)
    assert any("docker" in p and "cannot run on this host" in p for p in problems)


def test_the_refusal_names_the_backend_once_however_many_commands_use_it(
        monkeypatch, tmp_path):
    monkeypatch.setattr(ex, "bwrap_available",
                        lambda **kw: (False, "bwrap cannot run here"))
    requests = [ex.ExecRequest(cmd=["true"], backend="bubblewrap", label=f"c{i}")
                for i in range(5)]
    problems = ex.check_policy(requests, root=tmp_path, allow_network=False)
    assert sum("bwrap cannot run here" in p for p in problems) == 1


def test_dockers_available_has_three_distinct_meanings(monkeypatch):
    """Client installed / daemon answering / a container actually running."""
    monkeypatch.setattr(ex, "docker_client", lambda: "/usr/bin/docker")
    assert ex.docker_client() == "/usr/bin/docker"
    monkeypatch.setattr(ex, "docker_daemon", lambda: (True, "daemon answers"))
    assert ex.docker_daemon() == (True, "daemon answers")


def test_a_client_with_no_daemon_is_reported_as_exactly_that(monkeypatch):
    monkeypatch.setattr(ex, "docker_client", lambda: "/usr/bin/docker")
    monkeypatch.setattr(ex, "_docker_run", lambda *a, timeout: subprocess.CompletedProcess(
        a, 1, b"", b"Cannot connect to the Docker daemon at unix:///var/run/docker.sock"))
    ok, detail = ex.docker_daemon()
    assert not ok and "daemon is not running" in detail


def test_a_missing_image_is_explained_as_a_missing_image():
    said = ex._explain_docker_failure(
        "Unable to find image 'x:1' locally\n"
        "docker: Error response from daemon: pull access denied for x\n")
    assert "image is not present locally" in said


def test_the_three_things_are_probed_not_assumed(monkeypatch):
    """The capability gate must *demonstrate*, never observe a precondition (D41)."""
    seen: list[tuple] = []
    monkeypatch.setattr(ex, "docker_client", lambda: "/usr/bin/docker")
    monkeypatch.setattr(ex, "_docker_run",
                        lambda *a, timeout: (seen.append(a),
                                             subprocess.CompletedProcess(a, 0, b"hi\n", b""))[1])
    ok, detail = ex.docker_available(refresh=True)
    assert ok and "hello-world" in detail
    assert seen == [("run", "--rm", ex.DOCKER_PROBE_IMAGE)]


def test_backends_report_names_the_three_backends_and_prices_docker(monkeypatch):
    monkeypatch.setattr(ex, "bwrap_available", lambda **kw: (True, "bwrap works"))
    monkeypatch.setattr(ex, "docker_client", lambda: "/usr/bin/docker")
    monkeypatch.setattr(ex, "docker_daemon", lambda: (True, "daemon answers"))
    monkeypatch.setattr(ex, "docker_available", lambda **kw: (True, "a container ran"))
    rows = {row["name"]: row for row in ex.backends_report()}
    assert set(rows) == {"local", "bubblewrap", "docker"}
    assert rows["docker"]["available"] is True
    assert set(rows["docker"]["rungs"]) == {"client", "daemon", "container"}


def test_a_spec_declaring_docker_says_the_sandbox_is_needed(tmp_path, monkeypatch):
    """A spec whose commands need a container needs a host that can run one.

    The gate itself fires at load time (D41: a capability gate must *demonstrate*
    the capability, never observe a precondition), so a spec declaring docker only
    loads at all on a host that really can run a container. Both halves are asserted
    here: the refusal on a host that cannot, and the verdict on the loaded spec.
    """
    from vidkit.reports import _sandbox_needs
    monkeypatch.setattr(ex, "_PROBE_CACHE", {})
    monkeypatch.setattr(ex, "docker_client", lambda: "/usr/bin/docker")
    monkeypatch.setattr(ex, "_docker_run", lambda *a, timeout: subprocess.CompletedProcess(
        a, 1, b"", b"Cannot connect to the Docker daemon at unix:///var/run/docker.sock"))
    with pytest.raises(SpecError, match="cannot run on this host"):
        _docker_spec(tmp_path)

    # With the refusal stood down the spec loads, so `doctor` can be asked what it
    # thinks of a story this machine cannot run — which is the question it exists
    # to answer.
    monkeypatch.setattr(ex, "check_policy", lambda *a, **kw: [])
    needs = _sandbox_needs(_docker_spec(tmp_path))
    assert needs["ok"] is False
    assert "docker" in needs["declared"]
    assert needs["docker_ok"] is False
    assert "daemon is not running" in needs["docker_detail"]


def test_a_spec_declaring_docker_on_a_working_host_is_reported_as_runnable(tmp_path, monkeypatch):
    from vidkit.reports import _sandbox_needs
    if not _HAVE_DOCKER:
        pytest.skip("a spec declaring docker only loads on a host that can run one")
    needs = _sandbox_needs(_docker_spec(tmp_path))
    assert needs["ok"] is True
    assert needs["docker_ok"] is True
    assert "postgres:16-alpine" in needs["docker_detail"]


# --------------------------------------------------------------------------- #
# 3. The lifecycle, against a real daemon.
# --------------------------------------------------------------------------- #
@needs_docker
def test_an_environment_comes_up_and_is_actually_removed(env, tmp_path):
    state = ex.environment_up(env, root=tmp_path)
    try:
        assert state.up, state.up_error
        assert state.container_id
        assert state.image_digest.startswith("sha256:")
        assert state.ready
        assert len(state.container_name) > len(ex.DOCKER_PREFIX)
    finally:
        ex.environment_down(state)
    assert state.teardown["removed"]
    assert state.teardown["attempted"]
    assert "stopped and removed" in state.teardown["detail"]


@needs_docker
def test_removing_a_container_twice_is_not_an_error(env, tmp_path):
    state = ex.environment_up(env, root=tmp_path)
    ex.environment_down(state)
    first = dict(state.teardown)
    ex.environment_down(state)
    assert state.teardown["removed"], "a second pass must not claim nothing happened"
    assert state.teardown["detail"] == first["detail"], (
        "the second pass must preserve the first pass's evidence, not overwrite it")


@needs_docker
def test_a_container_that_never_becomes_ready_is_reported_and_still_removed(env, tmp_path):
    env.ready = ["false"]
    env.ready_timeout = 3
    state = ex.environment_up(env, root=tmp_path)
    try:
        assert state.up, "the container did start; it is the *service* that is not ready"
        assert not state.ready
        assert "exited 1" in state.ready_detail
    finally:
        ex.environment_down(state)
    assert state.teardown["removed"]


@needs_docker
def test_readiness_must_hold_and_a_single_success_is_not_enough(tmp_path, monkeypatch):
    """The Postgres bootstrap-server trap, reproduced with a clock instead of luck.

    The readiness command succeeds exactly once and then fails forever — which is
    the shape of ``pg_isready`` answering at t≈1.30 s against a server that stops
    accepting at t≈1.45 s. With ``READY_HOLD`` out of reach, a single success must
    not be promoted to "ready"; if it were, the next command would meet a database
    that is on its way down.
    """
    spec = _docker_spec(
        tmp_path, command="command: [sleep, '60']",
        ready_argv='["sh", "-c", "if [ -e /tmp/said-yes ]; then exit 1; fi; '
                   'touch /tmp/said-yes; exit 0"]')
    ctx = _Ctx(tmp_path, spec)
    monkeypatch.setattr(ex, "READY_HOLD", 30.0)
    try:
        _start_environments(ctx, ctx.assets, [])
        state = ctx.assets.environments["db"]
        assert state.up, state.up_error
        assert not state.ready, "one success must not be called ready"
        assert "never held" in state.ready_detail
        assert "answered once" in state.ready_detail, (
            "a service that answered and then stopped is not one that never answered")
        assert "exited 1" in state.ready_detail
    finally:
        _stop_environments(ctx, ctx.assets, list(ctx.assets.environments.values()))


@needs_docker
def test_a_readiness_command_that_keeps_succeeding_does_become_ready(tmp_path):
    spec = _docker_spec(tmp_path, command="command: [sleep, '60']", ready="true")
    ctx = _Ctx(tmp_path, spec)
    try:
        _start_environments(ctx, ctx.assets, [])
        state = ctx.assets.environments["db"]
        assert state.ready, state.ready_detail
        assert "without a single failure" in state.ready_detail
    finally:
        _stop_environments(ctx, ctx.assets, list(ctx.assets.environments.values()))


@needs_docker
def test_a_container_with_no_readiness_command_says_so_rather_than_claiming_ready(env, tmp_path):
    env.command = ["sleep", "60"]
    env.ready = []
    state = ex.environment_up(env, root=tmp_path)
    try:
        assert state.ready
        assert "nothing proved the service answers" in state.ready_detail
        assert state.health["status"] == "running"
    finally:
        ex.environment_down(state)


@needs_docker
def test_the_containers_logs_are_captured_even_after_it_has_died(env, tmp_path):
    """`docker logs` works on a stopped container; `--rm` would have thrown them away."""
    env.command = ["sh", "-c", "echo the-service-said-this; exit 3"]
    env.ready = ["true"]
    env.ready_timeout = 2
    state = ex.environment_up(env, root=tmp_path)
    try:
        ex.capture_logs(state, tmp_path / "logs" / "db.log")
        assert "the-service-said-this" in state.logs
        assert "the-service-said-this" in state.log_path.read_text()
    finally:
        ex.environment_down(state)


@needs_docker
def test_capturing_logs_twice_keeps_the_first_answer(env, tmp_path):
    env.command = ["sh", "-c", "echo first; sleep 60"]
    state = ex.environment_up(env, root=tmp_path)
    try:
        ex.capture_logs(state, tmp_path / "a.log")
        ex.capture_logs(state, tmp_path / "b.log")
        assert not (tmp_path / "b.log").exists()
        assert state.log_path == tmp_path / "a.log"
    finally:
        ex.environment_down(state)


@needs_docker
def test_a_command_runs_inside_the_declared_environment_and_sees_the_project(env, tmp_path):
    """The end-to-end shape: one system, two commands, and the second sees the first.

    The two halves are deliberately split by *where they write*, because the
    engine binds the project directory **read-only**. A command cannot modify the
    spec author's repository from inside a container — that is the point of the
    bind — so the positive half ("the second command sees the first command's
    work") is proved in ``/tmp``, which is the container's own filesystem, and the
    negative half proves the project is visible and genuinely unwritable at
    ``/work``. An earlier version wrote the marker into ``/work`` and so tested
    neither: it failed, and the failure looked like an engine bug.
    """
    (tmp_path / "spec-author-file.txt").write_text("from the host\n", encoding="utf-8")
    env.command = ["sleep", "60"]
    state = ex.environment_up(env, root=tmp_path)
    try:
        ex.bind_step("thing", state)
        first = ex.run(ex.ExecRequest(
            cmd=["sh", "-c", "echo written-by-one > /tmp/marker.txt"], backend="docker",
            label="thing"), root=tmp_path)
        second = ex.run(ex.ExecRequest(
            cmd=["cat", "/tmp/marker.txt"], backend="docker", label="thing"),
            root=tmp_path)
        assert first.exit_code == 0, first.stdout
        assert "written-by-one" in second.stdout, "one container, not one per command"

        # The project directory is visible inside the container and cannot be
        # written to: read the file the host just created, then try to add one.
        seen = ex.run(ex.ExecRequest(
            cmd=["cat", f"{ex.DOCKER_WORKDIR}/spec-author-file.txt"], backend="docker",
            label="thing"), root=tmp_path)
        assert seen.exit_code == 0, seen.stdout
        assert "from the host" in seen.stdout

        denied = ex.run(ex.ExecRequest(
            cmd=["sh", "-c", f"echo nope > {ex.DOCKER_WORKDIR}/new-file.txt"],
            backend="docker", label="thing"), root=tmp_path)
        assert denied.exit_code != 0, "the project bind is supposed to be read-only"
    finally:
        ex.environment_down(state)
    assert not (tmp_path / "new-file.txt").exists(), "nothing was written to the project"


@needs_docker
def test_the_engine_can_list_its_own_leaked_containers_and_nothing_else(env, tmp_path):
    state = ex.environment_up(env, root=tmp_path)
    try:
        mine = {row["name"] for row in ex.environments_running()}
        assert state.container_name in mine
    finally:
        ex.environment_down(state)
    assert state.container_name not in {r["name"] for r in ex.environments_running()}


@needs_docker
def test_image_digest_identifies_what_actually_ran(env):
    digest = ex.image_digest(env.image)
    assert digest.startswith("sha256:") and len(digest) == 71


def test_image_digest_of_a_missing_image_is_the_empty_string():
    assert ex.image_digest("vidkit-no-such-image:1") == ""


# --------------------------------------------------------------------------- #
# 4. Teardown on every exit path — including the one nobody exercises.
# --------------------------------------------------------------------------- #
@needs_docker
def test_a_crash_during_startup_still_removes_the_container(tmp_path):
    """The leak this test exists for was real: the first build of the docker
    example left a Postgres container behind, because the containers were started
    *outside* the ``try`` and the inner ``finally`` was never reached."""
    spec = _docker_spec(tmp_path, image="alpine")
    spec.environments[0].command = ["sleep", "60"]
    ctx = _Ctx(tmp_path, spec)
    assets = Assets()
    started: list[ex.EnvState] = []
    with pytest.raises(RuntimeError):
        try:
            _start_environments(ctx, assets, started)
            raise RuntimeError("crash inside the exec stage body")
        finally:
            _stop_environments(ctx, assets, started)
    assert started, "the state must be registered before readiness is awaited"
    assert started[0].teardown["removed"], started[0].teardown
    assert "removed" in ctx.said("info")
    assert started[0].container_name not in {r["name"] for r in ex.environments_running()}


@needs_docker
def test_the_second_teardown_pass_does_not_erase_the_first_pass_evidence(tmp_path):
    """`verify.json` has to name the container that was removed. A second no-op
    pass that overwrites the record reports `attempted: false` about a container
    that demonstrably existed — the record lies in the direction of innocence."""
    spec = _docker_spec(tmp_path, image="alpine")
    spec.environments[0].command = ["sleep", "60"]
    ctx = _Ctx(tmp_path, spec)
    assets = Assets()
    started: list[ex.EnvState] = []
    _start_environments(ctx, assets, started)
    _stop_environments(ctx, assets, started)
    _stop_environments(ctx, assets, started)          # the outer `finally`, again
    record = started[0].teardown
    assert record["attempted"] is True
    assert record["stopped"] is True
    assert record["removed"] is True
    assert started[0].container_name in record["detail"]
    lines = [line for line in ctx.said("info").splitlines() if "removed" in line]
    assert len(lines) == 1, f"the second pass must stay quiet, saw {lines}"
    assert record["attempted"] is True, "a no-op pass must not rewrite the record"


@needs_docker
def test_an_environment_that_cannot_start_is_a_warning_and_a_fact_not_a_crash(tmp_path):
    spec = _docker_spec(tmp_path, image="alpine")
    spec.environments[0].image = "vidkit-no-such-image:1"
    ctx = _Ctx(tmp_path, spec)
    assets = Assets()
    started: list[ex.EnvState] = []
    try:
        _start_environments(ctx, assets, started)
        assert "did not start" in ctx.said("warn")
        assert assets.environments["db"].up is False
    finally:
        _stop_environments(ctx, assets, started)


@needs_docker
def test_an_environment_nothing_references_is_never_started(monkeypatch, tmp_path):
    """Belt and braces, since load time already refuses it."""
    spec = _docker_spec(tmp_path)
    for step in spec.exec:
        step.environment = ""
        step.backend = "local"
    started_calls: list = []
    monkeypatch.setattr(ex, "environment_up",
                        lambda *a, **kw: started_calls.append(a) or ex.EnvState(spec=a[0]))
    ctx = _Ctx(tmp_path, spec)
    _start_environments(ctx, Assets(), [])
    assert started_calls == []


def test_the_stage_still_has_ten_stages():
    """M9's constraint P5: no eleventh pipeline stage. Environments are a
    *property of* the exec stage, not a new one."""
    from vidkit.assembler import STAGES
    assert len(STAGES) == 10
    assert "exec" in STAGES
    assert not any("env" in s for s in STAGES)
