"""Run a declared command in a declared sandbox, and keep the evidence (R-E1…R-E5).

Why this module exists
----------------------
A screencast about software shows a product *and* the work done with it. The work
happens in a terminal, and a terminal that was drawn rather than typed is a
plausible terminal — which is precisely the fabrication invariant I7 forbids. So
vidkit has to be able to run a real command and film the real result.

The owner's instinct was "give vidkit shell access". That is not the primitive.
Shell access is unbounded, unauditable, and invisible to ``verify``. The primitive
is a **declared, bounded, auditable execution environment**: every command is
written down in the spec, every boundary (working directory, environment,
timeout, output caps, network) is declared before it runs, and the outcome is
recorded so a later reader can check it.

The trust boundary is therefore a *property of the spec*, and the spec is what
``verify`` reads. That is the whole design.

Backends
--------
* ``local`` — no isolation. Runs on the host, in a declared directory. It is the
  honest name for what it is, and it is what makes this usable on a machine with
  no container runtime. Declaring it is a statement the spec makes about itself.
* ``bubblewrap`` — Linux namespaces via ``bwrap(1)``. No daemon, no image, no
  root. The default when ``bwrap`` is present.
* ``docker`` — the command runs *inside a container* built from a declared
  image, inside a declared environment lifecycle. The unit of isolation is the
  image, which is the point: a video about a Postgres migration should be filmed
  against a real Postgres, and the image is what says which one.

A backend is a function ``(ExecRequest, policy) -> ExecResult``. Nothing else in
the engine knows how a command ran, so the Docker backend is an addition to
:data:`BACKENDS`, not a change to the pipeline.

Docker's "available" has three meanings, and collapsing them is how this goes
wrong
----------------------------------------------------------------------------
* *the client is installed* — ``shutil.which("docker")``. Cheap, and useless on
  its own: Docker Desktop is installed on millions of machines whose daemon is
  not running.
* *the daemon answers* — ``docker info``, measured at 56–84 ms.
* *a container can run* — ``docker run --rm hello-world``, measured at
  435–459 ms, and it needs the image present or a network to pull it.

Per the M7 rule (D41) a capability gate has to *demonstrate* the capability, so
:func:`docker_available` runs the container and ``doctor`` reports all three
rungs separately rather than inventing one boolean.

Two things worth stating plainly
---------------------------------
* **Network is off unless it is declared.** The sandbox is built network-less
  first and the flag is what opens it, so an author who forgets gets the safe
  behaviour rather than the unsafe one.
* **No shell.** A command is a list of arguments (``shlex.split`` of the spec
  string at load time). Nothing here interpolates, expands, or evaluates. There
  is no shell metacharacter to get wrong because there is no shell.
"""

from __future__ import annotations

import errno
import fcntl
import os
import posixpath
import pty
import re
import select
import shlex
import shutil
import signal
import struct
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Iterator, Sequence

from .errors import SpecError, ToolError

#: The environment a command actually sees. Everything else is dropped, so a
#: build cannot leak an unrelated credential into a command that is about to be
#: filmed — a recorded environment is a published environment.
BASE_ENV: dict[str, str] = {
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "HOME": "/home/sandbox",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "TERM": "xterm-256color",
    "COLUMNS": "100",
    "LINES": "30",
    "PS1": "$ ",
    "SHELL": "/bin/sh",
}

#: Directories a sandboxed command may read (bubblewrap only). Read-only binds.
READ_ROOTS = ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc")

#: A hard ceiling on how much of one stream is kept. A command that prints a
#: gigabyte is a command that fills a disk, so the cap is not politeness.
MAX_CAPTURE_BYTES = 256 * 1024

#: How long the sandbox capability probe may take. It binds the whole of ``/``
#: read-only and runs ``/bin/true``; measured at ~14 ms, so this is ~100x headroom
#: for a loaded machine, and still short enough to sit in front of ``doctor``.
PROBE_TIMEOUT = 1.5

#: The mount layout the probe builds, so that a probe which passes proves the
#: *engine's* sandbox works and not merely that some other bwrap invocation does.
#: Kept identical in spirit to :func:`_bwrap_argv`, and pinned by a test.
PROBE_ARGV = ["/bin/true"]

#: The image every Docker probe runs. Deliberately the *smallest* thing that is
#: certainly runnable rather than something the engine would use in a build: the
#: probe answers "can a container start on this host", and a bigger image would
#: answer it more slowly while adding a second reason to fail.
DOCKER_PROBE_IMAGE = "hello-world"

#: A container round trip costs ~450 ms measured, so the probe's ceiling is
#: generous where bwrap's 1.5 s is tight.
DOCKER_PROBE_TIMEOUT = 15.0

#: How long ``docker info`` may take to say whether the daemon is answering.
DOCKER_INFO_TIMEOUT = 5.0

#: A container is stopped with ``docker stop`` first and only then removed. This
#: is how long ``stop`` may take before the engine stops asking.
DOCKER_STOP_TIMEOUT = 15.0

#: Every container the engine creates is named with this prefix, so a leaked one
#: is identifiable as vidkit's and can be reaped without guessing.
DOCKER_PREFIX = "vidkit-"

#: The mount point inside a container that the project directory is bound to.
#: Containers do not have the host's paths, so a declared ``cwd`` is relative to
#: this — which is why a docker step's cwd is resolved on both sides.
DOCKER_WORKDIR = "/work"

#: Labels every container carries. A leaked container can be found by them, and
#: a reader can tell what story it belonged to without reading the spec again.
DOCKER_LABELS = {
    "vidkit.role": "exec",
}

#: The backends that actually confine a command — as opposed to `local`, which runs
#: it on the machine with the spec author's own privileges.
#:
#: This lives here, next to `BASE_ENV` and the argv builders, because it is a claim
#: about what the runtime *does*, not about what a spec may write. `verify` reads it
#: rather than spelling "bubblewrap" into a check, so adding a backend cannot turn a
#: correct build into a reported lie.
CONFINING_BACKENDS = frozenset({"bubblewrap", "docker"})

#: How long the declared readiness command must keep succeeding, uninterrupted.
#:
#: One success is a sample, not a demonstration. Postgres is the proof: its entry
#: point runs a temporary server on the real socket during initdb, and
#: `pg_isready` answers `0` against it — measured at t≈1.30s, before that bootstrap
#: server was stopped at t≈1.45s and the real one took over at t≈1.84s. A gate that
#: trusts the first success hands the next command a database that is already
#: shutting down, which is exactly what happened the first time this example was
#: built: every `docker exec` died with "the database system is shutting down"
#: while the environment had just been reported `ready`.
#:
#: So readiness is not "it answered once", it is "it answered and *kept* answering".
#: A duration rather than a count, because a count can be satisfied by two samples
#: that straddle the gap; three quarters of a second cannot be answered by a server
#: that is on its way out.
READY_HOLD = 0.75


@dataclass
class ExecRequest:
    """One declared command: what to run, and where.

    ``cmd`` is a list, never a string — there is no path through this module that
    hands anything to a shell. ``shell`` is the argv of the *interpreter* to run
    it under (default ``/bin/sh``), because a shell script is a legitimate thing
    to film; the point is that the engine chose it, not that the spec typed it.
    """

    cmd: list[str]
    cwd: str = "."
    #: The argv of the *interpreter* to run ``cmd`` under. Empty means "run
    #: ``cmd`` directly, as an argv". The spec writes a string and this becomes
    #: ``["/bin/sh", "-c"]``; the spec writes a list and this stays empty. The
    #: convenient form announces that it is a shell script, and the safe form is
    #: the default one.
    shell: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    timeout: float = 60.0
    backend: str = "bubblewrap"
    network: bool = False
    reads: list[str] = field(default_factory=list)    # extra read-only binds
    expect_exit: list[int] = field(default_factory=lambda: [0])
    label: str = ""

    def argv(self) -> list[str]:
        """The concrete argv: the declared interpreter (if any), then the command."""
        return [*self.shell, *self.cmd]

    def to_dict(self) -> dict:
        return {
            "cmd": list(self.cmd),
            "shell": list(self.shell),
            "cwd": self.cwd,
            "env": dict(self.env),
            "timeout": self.timeout,
            "backend": self.backend,
            "network": self.network,
            "reads": list(self.reads),
            "expect_exit": list(self.expect_exit),
            "label": self.label,
        }


@dataclass
class ExecResult:
    """What actually happened, in full.

    ``ok`` is deliberately *not* ``exit_code == 0``. A spec may declare that a
    non-zero exit is the point (a failing test that the video is about), so
    success is judged against ``expect_exit``. ``ok`` is that judgement; the raw
    exit code stays available, and so does everything else, because a record
    that keeps only the verdict cannot be re-examined.
    """

    request: ExecRequest
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    seconds: float = 0.0
    truncated: dict[str, bool] = field(default_factory=dict)
    timed_out: bool = False
    refused: str = ""                     # a policy refusal: nothing was executed
    backend: str = ""
    #: Set only by the docker backend: the image the command ran inside, and the
    #: digest of what that image actually was when it ran. ``verify`` checks the
    #: second, because a tag is a name that can move.
    image: str = ""
    image_digest: str = ""

    @property
    def expected(self) -> bool:
        return self.exit_code in set(self.request.expect_exit)

    @property
    def ok(self) -> bool:
        return not self.refused and not self.timed_out and self.expected

    def to_dict(self) -> dict:
        out = {
            "label": self.request.label,
            "cmd": list(self.request.cmd),
            "backend": self.backend,
            "cwd": self.request.cwd,
            "network": self.request.network,
            "timeout": self.request.timeout,
            "expect_exit": list(self.request.expect_exit),
            "exit_code": self.exit_code,
            "expected": self.expected,
            "timed_out": self.timed_out,
            "refused": self.refused,
            "seconds": round(self.seconds, 3),
            "truncated": dict(self.truncated),
            "stdout_bytes": len(self.stdout.encode("utf-8")),
            "stderr_bytes": len(self.stderr.encode("utf-8")),
        }
        if self.image:
            # Only present when a container actually ran. The image is part of
            # what the command *was*, so a record that omits it cannot be
            # re-examined later.
            out["image"] = self.image
            out["image_digest"] = self.image_digest
        return out


# --------------------------------------------------------------------------- #
# the environment (R-E6)
# --------------------------------------------------------------------------- #
@dataclass
class EnvSpec:
    """A declared container environment: one image, one lifecycle.

    Named in the spec as ``environment:`` and referenced by an exec step with
    ``backend: docker``. The unit of reuse is deliberate — the same database is
    started once and several commands run against it, because that is what a
    software demo actually does, and starting one per command would film a
    different system from the one being demonstrated.
    """

    name: str
    image: str
    #: The container's entrypoint override. Empty means "whatever the image
    #: declares", which is usually what an author wants.
    command: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    #: Ports published to the host, as ``"5432:5432"``. Empty means none: the
    #: network *inside* the container is enough to run a neighbouring command
    #: against it, and publishing a port opens it to the host, which a spec
    #: should have to ask for.
    ports: list[str] = field(default_factory=list)
    #: ``HOST:CONTAINER`` pairs bound read-only. The project directory at
    #: :data:`DOCKER_WORKDIR` is bound by the *backend*, never by the spec, so a
    #: spec cannot forget to give its commands their files.
    volumes: list[str] = field(default_factory=list)
    #: How long ``docker run -d`` may take to return a container id. Pulling an
    #: image over a slow link is legitimately slow, so this is generous.
    timeout: float = 120.0
    #: Readiness gate: a container that is *up* is not a service that is *ready*,
    #: so a spec may declare the command that proves the service answers. Empty
    #: means the gate is the container's own health, or its having started.
    ready: list[str] = field(default_factory=list)
    ready_timeout: float = 60.0
    network: bool = False

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "image": self.image,
            "command": list(self.command),
            "env": dict(self.env),
            "ports": list(self.ports),
            "volumes": list(self.volumes),
            "timeout": self.timeout,
            "ready": list(self.ready),
            "ready_timeout": self.ready_timeout,
            "network": self.network,
        }


@dataclass
class EnvState:
    """What became of the environment: measured, not narrated.

    ``teardown`` is always attempted and always recorded. A build that failed
    halfway through is exactly the build most likely to leave a container
    behind, so "it was removed" is a fact ``verify`` can check rather than a
    promise the code made to itself.
    """

    spec: EnvSpec
    container_id: str = ""
    container_name: str = ""
    #: The digest of the image that actually ran. A tag is a name that can move;
    #: the digest is what the video was filmed against.
    image_digest: str = ""
    started: bool = False
    up: bool = False
    up_error: str = ""
    ready: bool = False
    ready_detail: str = ""
    #: What ``docker logs`` captured, as a panel can be drawn from it. Kept as
    #: measured text plus where it was written, never as a summary.
    logs: str = ""
    log_path: Path | None = None
    health: dict = field(default_factory=dict)
    teardown: dict = field(default_factory=dict)
    seconds: float = 0.0

    def to_dict(self) -> dict:
        return {
            **self.spec.to_dict(),
            "container_id": self.container_id[:12] if self.container_id else "",
            "container_name": self.container_name,
            "image_digest": self.image_digest,
            "started": self.started,
            "up": self.up,
            "up_error": self.up_error,
            "ready": self.ready,
            "ready_detail": self.ready_detail,
            "health": dict(self.health),
            "teardown": dict(self.teardown),
            "seconds": round(self.seconds, 3),
        }


# --------------------------------------------------------------------------- #
# can this host actually sandbox? (defect G)

#
# The question "is bwrap available?" has two answers and only one of them is the
# one anybody means. `shutil.which("bwrap")` answers "is the file there". What a
# spec declaring `backend: bubblewrap` is asking is "will the sandbox actually
# confine the command". On Ubuntu 24.04 those answers differ: bubblewrap is
# installed and every invocation fails, because
# /proc/sys/kernel/apparmor_restrict_unprivileged_userns is 1, so the kernel
# refuses the user namespace bwrap needs to exist at all.
#
# That made three things lie at once: `doctor` said the environment was ready,
# `resolve_backend` accepted a spec it could not honour, and CI's own
# "the sandbox is really there" gate passed on a host where the sandbox could
# not start. So availability is now *demonstrated* — the probe runs the engine's
# own sandbox around /bin/true — and the proof costs ~14 ms.
#
# The probe is memoised because it runs at load time, once per process, and the
# answer cannot change within a process. Nothing here caches across processes;
# a host that gains the capability mid-session is a restart away.
# --------------------------------------------------------------------------- #
_PROBE_CACHE: dict[str, tuple[bool, str]] = {}


def _bwrap_probe_argv() -> list[str]:
    """The engine's sandbox, around a command that does nothing.

    Deliberately built through the *same* helpers a real request uses. A probe
    that invented its own argv would answer a question about itself.
    """
    req = ExecRequest(cmd=list(PROBE_ARGV), backend="bubblewrap")
    argv = _bwrap_argv(req, Path("/"))
    # No host PATH lookup for the binary itself: `shutil.which` already told us
    # where it is, and re-deriving it here is what would let the probe drift.
    return argv


def bwrap_available(*, refresh: bool = False) -> tuple[bool, str]:
    """Can this host run the sandbox, and if not, why not — as a sentence.

    The second element is written to be shown to a person, because "available:
    False" on its own sends an author looking for a missing binary that is
    sitting right there on PATH.
    """
    if not refresh and "bubblewrap" in _PROBE_CACHE:
        return _PROBE_CACHE["bubblewrap"]

    binary = shutil.which("bwrap")
    if binary is None:
        verdict = (False, "bwrap(1) is not on PATH")
        _PROBE_CACHE["bubblewrap"] = verdict
        return verdict

    argv = _bwrap_probe_argv()
    argv[0] = binary
    try:
        proc = subprocess.run(
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=PROBE_TIMEOUT)
    except subprocess.TimeoutExpired:
        verdict = (False, f"{binary} did not return within {PROBE_TIMEOUT}s")
    except OSError as exc:
        verdict = (False, f"{binary} could not be started: {exc}")
    else:
        if proc.returncode == 0:
            verdict = (True, f"{binary} ran a confined command")
        else:
            why = proc.stderr.decode("utf-8", "replace").strip().splitlines()
            verdict = (False, _explain_bwrap_failure(why[-1] if why else ""))

    _PROBE_CACHE["bubblewrap"] = verdict
    return verdict


def _explain_bwrap_failure(line: str) -> str:
    """Turn bwrap's kernel-level complaint into something an author can act on.

    Ubuntu 24.04 ships an AppArmor rule that denies unprivileged user namespaces,
    which is the single most common reason a *correctly installed* bubblewrap
    cannot run. Detecting it by its symptom rather than by reading the sysctl
    keeps this correct on hosts where the sysctl is unreadable.
    """
    text = line or "bwrap exited non-zero"
    if "uid map" in text or "RTM_NEWADDR" in text or "Operation not permitted" in text:
        return (
            f"{text} — the kernel is refusing unprivileged user namespaces, which "
            "on Ubuntu 24.04 is the AppArmor restriction. Lift it with "
            "`sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0`, "
            "or declare `backend: local` to run unconfined on purpose."
        )
    return text


def resolve_backend(name: str) -> str:
    """The backend actually used, or a refusal explaining why the named one cannot run.

    A spec that asks for ``docker`` and silently gets ``local`` produces evidence
    that is true and a claim that is false. So a backend that cannot run is a
    refusal, and it says what is wrong — including when the binary is present and
    the kernel will not let it work, which is the case this used to get wrong.
    """
    if name == "local":
        return "local"
    if name == "bubblewrap":
        ok, detail = bwrap_available()
        if not ok:
            raise ToolError(
                f"the spec declares `backend: bubblewrap`, but the sandbox cannot "
                f"run on this host: {detail}. Fix the environment, or declare "
                "`backend: local` to say honestly that the command runs "
                "unconfined here.")
        return "bubblewrap"
    if name == "docker":
        ok, detail = docker_available()
        if not ok:
            raise ToolError(
                f"the spec declares `backend: docker`, but a container cannot run "
                f"on this host: {detail}. Fix the environment, or declare "
                "`backend: local` to say honestly that the command runs "
                "unconfined here.")
        return "docker"
    raise SpecError(
        f"unknown exec backend {name!r}; known: local, bubblewrap, docker")


def _bwrap_argv(req: ExecRequest, cwd: Path) -> list[str]:
    """Build the ``bwrap`` argv: the sandbox, then the command.

    Read is granted from :data:`READ_ROOTS` plus whatever the spec declared;
    *write* is granted only to ``/work``, which is the declared working directory
    bound into the sandbox. That asymmetry is the point: a command may read a
    system library and may not edit the repository it was run from.
    """
    argv = [
        "bwrap",
        "--unshare-all",
        # A fresh process table and user namespace, so nothing in the sandbox can
        # signal, attach to, or look at anything on the host.
        "--die-with-parent",
        "--new-session",
        "--setenv", "HOME", BASE_ENV["HOME"],
        "--proc", "/proc",
        "--dev", "/dev",
        "--tmpfs", "/tmp",
        "--dir", "/work",
        "--chdir", "/work",
    ]
    if req.network:
        # `--unshare-all` already took the network away; this is the exact and
        # only place it comes back, and the spec had to say so to get here.
        argv += ["--share-net"]
    for root in (*READ_ROOTS, *req.reads):
        p = Path(root)
        if p.exists():
            argv += ["--ro-bind", str(p), str(p)]
    argv += ["--bind", str(cwd), "/work"]
    return [*argv, *req.argv()]


def _host_argv(req: ExecRequest) -> list[str]:
    return list(req.argv())


# --------------------------------------------------------------------------- #
# docker: three questions, three costs
# --------------------------------------------------------------------------- #
# Docker's "available" collapses three different questions, and each one costs
# about an order of magnitude more to answer than the last:
#
#   is the client installed?   `which docker`                  ~1 ms
#   does the daemon answer?    `docker info`                   ~60 ms
#   can a container run?       `docker run --rm hello-world`   ~450 ms
#
# The M7 rule (D41) says a capability gate must *demonstrate* the capability, so
# `docker_available` runs the container. But `doctor` cannot spend 450 ms on its
# happy path for every invocation, so the memo below is a deliberate trade —
# and unlike bwrap's, it is documented here rather than inherited:
#
#   * doctor and the pipeline both ask the same question in one process, and the
#     answer cannot change within a process, so probing twice is waste;
#   * a *test* that wants a different answer calls refresh=True, which is why
#     `tests/test_exec.py` holds an autouse fixture that clears the memo;
#   * nothing is cached across processes. A host whose daemon starts mid-session
#     is a restart away, which is honest and cheap.
#
# The probe runs `hello-world` rather than a busybox trick because its failure
# modes are legible to a person: "no such image" and "cannot connect to the
# daemon" are the two things that actually go wrong.
def docker_client() -> str | None:
    """Where ``docker(1)`` is, or ``None``. The cheapest of the three answers."""
    return shutil.which("docker")


def _docker_run(*args: str, timeout: float) -> subprocess.CompletedProcess:
    """Run ``docker`` with no shell, bounded, and with stdout/stderr captured.

    Every Docker call in this module goes through here, so there is exactly one
    place where a Docker command can be built and exactly one timeout policy.
    """
    binary = docker_client() or "docker"
    return subprocess.run(
        [binary, *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, timeout=timeout)


def docker_daemon() -> tuple[bool, str]:
    """Does the daemon answer? ``docker info`` is the smallest such question.

    Deliberately *not* memoised on its own: it is cheap enough to sit in front of
    ``doctor``, and a stale "the daemon is down" is worse than 60 ms.
    """
    if docker_client() is None:
        return False, "docker(1) is not on PATH"
    try:
        proc = _docker_run("info", "--format", "{{.ServerVersion}}",
                            timeout=DOCKER_INFO_TIMEOUT)
    except subprocess.TimeoutExpired:
        return False, f"`docker info` did not return within {DOCKER_INFO_TIMEOUT:g}s"
    except OSError as exc:
        return False, f"docker could not be started: {exc}"
    if proc.returncode == 0:
        version = proc.stdout.decode("utf-8", "replace").strip()
        return True, f"daemon answers (server {version or 'unknown'})"
    return False, _explain_docker_failure(proc.stderr.decode("utf-8", "replace"))


def _explain_docker_failure(text: str) -> str:
    """Turn Docker's stderr into a sentence about *this machine*.

    The two failures that actually happen are a daemon that is not running and a
    user who is not in the socket's group. They look nothing alike and send an
    author in opposite directions, so they are separated here rather than
    reported as "docker failed".
    """
    blob = (text or "").strip()
    low = blob.lower()
    if "cannot connect to the docker daemon" in low or "is the docker daemon running" in low:
        return ("the Docker daemon is not running — start it "
                "(`sudo systemctl start docker`, or launch Docker Desktop)")
    if "permission denied" in low and "docker.sock" in low:
        return ("this user cannot reach /var/run/docker.sock — add yourself to the "
                "`docker` group and log back in")
    if "no such image" in low or "pull access denied" in low or "not found" in low:
        return f"the image is not present locally: {blob.splitlines()[-1] if blob else 'unknown'}"
    return blob.splitlines()[-1] if blob else "docker exited non-zero"


def docker_available(*, refresh: bool = False) -> tuple[bool, str]:
    """Can this host run a container, and if not, why not — as a sentence.

    The demonstration, not the precondition: it runs the engine's own probe
    container. A host with a client and no daemon answers *False* here, which is
    the answer a spec declaring ``backend: docker`` needs.
    """
    if not refresh and "docker" in _PROBE_CACHE:
        return _PROBE_CACHE["docker"]

    if docker_client() is None:
        verdict = (False, "docker(1) is not on PATH")
        _PROBE_CACHE["docker"] = verdict
        return verdict

    try:
        proc = _docker_run("run", "--rm", DOCKER_PROBE_IMAGE,
                            timeout=DOCKER_PROBE_TIMEOUT)
    except subprocess.TimeoutExpired:
        verdict = (False, f"a container did not return within {DOCKER_PROBE_TIMEOUT:g}s")
    except OSError as exc:
        verdict = (False, f"docker could not be started: {exc}")
    else:
        if proc.returncode == 0:
            verdict = (True, f"`docker run --rm {DOCKER_PROBE_IMAGE}` succeeded")
        else:
            verdict = (False, _explain_docker_failure(
                proc.stderr.decode("utf-8", "replace")))

    _PROBE_CACHE["docker"] = verdict
    return verdict


def _docker_volume_args(env: EnvSpec | None, root: Path) -> list[str]:
    """The binds a container gets: the spec's, plus the project directory.

    The project bind is added here and not read from the spec on purpose. A spec
    that forgot it would produce a container with no files in it, and the author
    would be told their command failed rather than that their spec was thin.
    """
    args: list[str] = []
    if root.is_dir():
        args += ["-v", f"{root}:{DOCKER_WORKDIR}:ro"]
    for spec_volume in (env.volumes if env else ()):
        args += ["-v", spec_volume]
    return args


def _docker_argv(req: ExecRequest, cwd: Path, env: EnvSpec, container: str, *,
                 tty: bool = True) -> list[str]:
    """Build ``docker exec``: into the *running* declared environment, in ``cwd``.

    Two shapes are possible and this is deliberately the second. The first —
    ``docker run`` a fresh container per command — is simpler, and it is wrong:
    it films a *different* system for each command, so a demonstration of "write
    a row, then read it back" would show a write to one database and a read from
    another. A demo has to happen to one system, so the environment is started
    once and the commands are executed *into* it.

    ``tty`` allocates a PTY inside the container **and** makes Docker demand one
    on its own stdin — ``docker exec -t`` with stdin at ``/dev/null`` fails with
    ``cannot attach stdin to a TTY-enabled container``, exit 125. The filmed path
    runs under a real PTY and wants it; the internal readiness probe does not, and
    asking for it there turned every readiness gate into "exited 125" (defect O).
    """
    workdir = _docker_workdir(req, cwd)
    argv = ["docker", "exec"]
    if tty:
        argv += ["-i"]
    argv += ["-w", workdir]
    for name, value in _env_for(req, cwd, "docker").items():
        argv += ["-e", f"{name}={value}"]
    for name, value in env.env.items():
        argv += ["-e", f"{name}={value}"]
    # A PTY inside the container, so a program that asks whether stdout is a
    # terminal gets the same answer it would on the host. `-t` is what allocates
    # it; without it a progress bar is one line here and animated there.
    if tty:
        argv += ["-t"]
    argv.append(container)
    return [*argv, *req.argv()]


def _docker_workdir(req: ExecRequest, cwd: Path) -> str:
    """Where inside the container the command runs.

    The host path and the container path are different, and a spec writes the
    *relative* one. Resolving it here means `cwd: subdir` means the same thing in
    a container as it does on the host. The join is normalised, so the default
    ``cwd: .`` becomes the workdir itself rather than ``/work/.`` — both are
    legal, but only one of them reads as a path a person meant to write.
    """
    if os.path.isabs(req.cwd):
        return req.cwd
    joined = posixpath.normpath(posixpath.join(DOCKER_WORKDIR, req.cwd))
    return joined if joined.startswith(DOCKER_WORKDIR) else DOCKER_WORKDIR


def _launch_argv(backend: str, req: ExecRequest, cwd: Path, *,
                 tty: bool = True) -> list[str]:
    """The argv of ``req`` under ``backend`` — **including** the binary to run.

    ``tty`` says whether the caller has a terminal to offer. The filmed path does;
    the internal readiness probe runs with stdin at ``/dev/null`` and must say no,
    or Docker refuses the whole call (see :func:`_docker_argv`).
    """
    if backend == "bubblewrap":
        return _bwrap_argv(req, cwd)
    if backend == "docker":
        env = _ENV_FOR_RUN.get(req.label)
        container = _CONTAINER_FOR_RUN.get(req.label)
        if env is None or container is None:
            raise SpecError(
                f"exec {req.label or ' '.join(req.cmd)!r} declares `backend: docker` "
                "but no environment is running for it — an exec step cannot start "
                "its own container without leaving it behind")
        return _docker_argv(req, cwd, env, container, tty=tty)
    return _host_argv(req)


#: Which environment and container a docker command runs into, keyed by the
#: command's label. Populated by :func:`_bind_state` while a build is running and
#: cleared when the environment is torn down. A dict and not an argument because
#: ``stream``'s signature is shared by every backend, and widening it for one of
#: them would make the other two carry a field that means nothing to them.
_ENV_FOR_RUN: dict[str, EnvSpec] = {}
_CONTAINER_FOR_RUN: dict[str, str] = {}


def _env_for(req: ExecRequest, cwd: Path, backend: str) -> dict[str, str]:
    env = dict(BASE_ENV)
    env.update(req.env)                  # what the spec declared it needs
    env["VIDKIT_SANDBOX"] = backend
    if backend == "bubblewrap":
        env["HOME"] = BASE_ENV["HOME"]
        env["PWD"] = "/work"
    elif backend == "docker":
        # The container is not this machine, and this dictionary is used twice:
        # it is handed to `Popen` for the `docker` *client*, and every entry is
        # emitted as `-e` for the container. `HOME` is removed rather than
        # pointed somewhere else, because a client whose `HOME` names a
        # directory it cannot read prints `WARNING: Error loading config file`
        # onto the very same PTY that is being filmed — measured landing in the
        # recorded cast, the rasterised stills and `verify.json`, where it reads
        # as output of the command. Unset, the client is silent; inside the
        # container uid 0 still has `/root` from `/etc/passwd`, so nothing is
        # taken away from the command.
        env.pop("HOME", None)
        env["PWD"] = _docker_workdir(req, cwd)
    else:
        env["HOME"] = str(cwd)
        env["PWD"] = str(cwd)
    return env


# --------------------------------------------------------------------------- #
# the environment lifecycle (R-E6)
# --------------------------------------------------------------------------- #
def _container_name(env: EnvSpec, stamp: str) -> str:
    """A name that says whose container it is, so a leak is identifiable.

    ``docker ps`` on a machine that has run vidkit must not show a wall of
    anonymous ``thirsty_einstein`` containers with no way to tell which build
    abandoned them.
    """
    safe = re.sub(r"[^a-z0-9_.-]+", "-", env.name.lower()).strip("-.") or "env"
    return f"{DOCKER_PREFIX}{safe}-{stamp}"


def environment_up(env: EnvSpec, *, root: Path, stamp: str = "") -> EnvState:
    """Bring a declared environment up, and prove it came up.

    ``docker run -d`` returning an id is not the service being ready — a database
    that has printed ``database system is ready`` and one that is still
    initialising both look like a running container. So this waits on the
    container's own health when the image declares one, and on the spec's
    ``ready`` command when one is declared, and it records which of those
    answered rather than asserting that something did.
    """
    state = EnvState(spec=env)
    started = time.monotonic()
    stamp = stamp or f"{os.getpid():x}{int(time.time()) % 100000:05x}"
    state.container_name = _container_name(env, stamp)

    ok, detail = docker_available()
    if not ok:
        state.up_error = f"the docker backend cannot run on this host: {detail}"
        state.seconds = time.monotonic() - started
        return state

    argv = _docker_create_argv(env, root, state.container_name)
    state.started = True
    try:
        proc = _docker_run(*argv, timeout=env.timeout)
    except subprocess.TimeoutExpired:
        state.up_error = (f"`docker run` did not return within {env.timeout:g}s — "
                          "the image may be being pulled")
        state.seconds = time.monotonic() - started
        return state
    except OSError as exc:
        state.up_error = f"docker could not be started: {exc}"
        state.seconds = time.monotonic() - started
        return state

    if proc.returncode != 0:
        state.up_error = _explain_docker_failure(proc.stderr.decode("utf-8", "replace"))
        # `docker run -d` only *creates* the container when creation succeeded but
        # starting the process failed — the common case for a bad image command.
        # The daemon has already made it and it now owns the name, so it has to be
        # cleaned up rather than left as a stopped container nobody knows about.
        # This can only be decided by *looking*, because the two cases hand back
        # the same non-zero exit code.
        state.container_id = _find_by_name(state.container_name)
        if state.container_id:
            state.up_error += " — the container was created but not started"
        state.seconds = time.monotonic() - started
        return state

    state.container_id = proc.stdout.decode("utf-8", "replace").strip().splitlines()[-1]
    state.up = True
    state.image_digest = image_digest(env.image)
    bind_step(state.spec.name, state)
    _await_ready(state, root)
    state.seconds = time.monotonic() - started
    return state


def _find_by_name(name: str) -> str:
    """The id of a container already called ``name``, running or not, else ``""``.

    ``docker ps -a`` rather than ``docker ps``: a *stopped* container still owns
    its name, so a search that only looked at running ones would miss the case
    that makes the next ``docker run --name`` fail.
    """
    if not name:
        return ""
    try:
        proc = _docker_run("ps", "-a", "--filter", f"name=^{name}$",
                           "--format", "{{.ID}}", timeout=DOCKER_INFO_TIMEOUT)
    except (subprocess.TimeoutExpired, OSError):
        return ""
    if proc.returncode != 0:
        return ""
    ids = proc.stdout.decode("utf-8", "replace").strip().splitlines()
    return ids[0].strip() if ids else ""


def _docker_create_argv(env: EnvSpec, root: Path, name: str) -> list[str]:
    """``docker run -d`` for a declared environment.

    ``--rm`` is deliberately absent. A container that removed itself on exit
    would be gone before the logs could be read, and the logs are evidence. The
    engine removes it in :func:`environment_down`, on every exit path.
    """
    argv = ["run", "-d", "--name", name]
    for key, value in DOCKER_LABELS.items():
        argv += ["--label", f"{key}={value}"]
    for key, value in env.env.items():
        argv += ["-e", f"{key}={value}"]
    for port in env.ports:
        argv += ["-p", port]
    argv += _docker_volume_args(env, root)
    if not env.network:
        # The default is *no* network, so a demo that quietly reaches out is a
        # deliberate act in the spec rather than a default nobody looked at.
        argv += ["--network", "none"]
    argv.append(env.image)
    argv += list(env.command)
    return argv


def bind_step(label: str, state: EnvState) -> None:
    """Declare that the exec step ``label`` runs inside ``state``'s container.

    Keyed by the *command label*, because that is what the runner looks up when a
    labelled step streams. A step's label is unique across the spec (refused at
    load time), so this cannot be ambiguous even when two environments declare
    commands that do the same thing.
    """
    _ENV_FOR_RUN[label] = state.spec
    _CONTAINER_FOR_RUN[label] = state.container_id or state.container_name


def unbind_environments() -> None:
    """Forget every binding. Called on teardown, so a later build cannot inherit one."""
    _ENV_FOR_RUN.clear()
    _CONTAINER_FOR_RUN.clear()


def _await_ready(state: EnvState, root: Path) -> None:
    """Wait for the service behind the container to answer, and record what said so."""
    if not state.container_id:
        state.ready_detail = "the container did not start, so readiness was not tested"
        state.health = {"status": "not-started"}
        return
    deadline = time.monotonic() + state.spec.ready_timeout
    health = ""
    ready_since: float | None = None
    last_ready_code = 0
    last_ready_out = ""
    # Remembered across the whole wait, not just the latest try. `ready_since` is
    # reset by any failure — that is what the hold means — but a *single* success
    # then a failure is a different fact from never having answered at all, and
    # only keeping the last result would report the second while it happened. That
    # is exactly the Postgres bootstrap-server shape, so erasing it would erase the
    # evidence on the one case the whole readiness contract exists for (defect U).
    answered_at: float | None = None
    answered_out = ""
    while time.monotonic() < deadline:
        health = container_health(state.container_id)
        if state.spec.ready:
            code, out = _docker_probe_command(state, state.spec.ready, root)
            last_ready_code, last_ready_out = code, out
            if code == 0:
                # See READY_HOLD: the Postgres bootstrap server answers `ready`
                # while it is shutting down, so one success proves nothing.
                answered_at = answered_at or time.monotonic()
                answered_out = out or answered_out
                ready_since = ready_since or time.monotonic()
                held = time.monotonic() - ready_since
                if held >= READY_HOLD:
                    state.ready = True
                    state.ready_detail = (
                        f"`docker exec` of the declared readiness command answered "
                        f"for {held:.2f}s without a single failure: "
                        f"{out.strip().splitlines()[-1] if out.strip() else '(no output)'}")
                    state.health = {"status": health or "running"}
                    return
            else:
                ready_since = None
                state.ready_detail = (f"the readiness command exited {code}: "
                                      f"{(out.strip().splitlines() or [''])[-1]}")
        elif health in ("", "running"):
            state.ready = True
            state.ready_detail = ("the container reports `running`; no readiness "
                                  "command was declared, so nothing proved the "
                                  "service answers")
            state.health = {"status": health or "running"}
            return
        elif health == "healthy":
            state.ready = True
            state.ready_detail = "the image's own HEALTHCHECK reports `healthy`"
            state.health = {"status": health}
            return
        elif health in ("unhealthy", "exited", "dead"):
            state.ready_detail = f"the container reports `{health}`"
            state.health = {"status": health}
            return
        time.sleep(0.25)
    if answered_at is not None and not state.ready:
        # Honest about the near-miss: the service answered, but never once for long
        # enough to be called up — which is a different fact from never answering.
        state.ready_detail = (
            f"the readiness command answered once, then stopped holding: it never "
            f"held for {READY_HOLD:g}s; its last try exited {last_ready_code}"
            + (f": {(last_ready_out.strip().splitlines() or [''])[-1]}"
               if last_ready_out.strip() else ""))
    else:
        state.ready_detail = state.ready_detail or (
            f"nothing became ready within {state.spec.ready_timeout:g}s")
    state.health = {"status": health or "unknown"}


def _docker_probe_command(state: EnvState, cmd: list[str], root: Path) -> tuple[int, str]:
    """Run the spec's readiness command inside the container. Returns ``(code, output)``.

    Deliberately built by :func:`_docker_argv`, the same builder the steps use, so
    the readiness probe runs *exactly* as the commands it gates — same declared
    environment, same working directory. A probe that ran differently could certify
    a service the build cannot actually reach, which is worse than not probing at all.

    It is then executed by :func:`_launch_argv`, not by handing the builder's output
    to :func:`_docker_run`. That distinction is the whole of defect S: the builders
    answer "what is the argv **of** the command" and so name the binary themselves,
    while ``_docker_run`` prefixes the binary — so ``_docker_run(*_docker_argv(…))``
    executed ``docker docker exec -w /work …``, and Docker reported its own
    ``unknown shorthand flag: 'w' in -w`` (exit 125). That is why no readiness gate
    ever once passed. Going through ``_launch_argv`` means there is one definition
    of "how a command enters a container" rather than two that could drift.
    """
    req = ExecRequest(cmd=list(cmd), backend="docker", label=state.spec.name,
                      expect_exit=[0], timeout=min(30.0, state.spec.ready_timeout))
    bind_step(req.label, state)       # `_launch_argv` resolves the container by label
    try:
        proc = subprocess.run(
            _launch_argv("docker", req, Path("."), tty=False),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=req.timeout)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return 124, str(exc)
    return proc.returncode, (proc.stdout + proc.stderr).decode("utf-8", "replace")


def container_health(container_id: str) -> str:
    """The container's health status, or ``""`` if the image declares none."""
    try:
        proc = _docker_run("inspect", "--format", "{{.State.Health.Status}}",
                           container_id, timeout=DOCKER_INFO_TIMEOUT)
    except (subprocess.TimeoutExpired, OSError):
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.decode("utf-8", "replace").strip()


def container_logs(container_id: str, *, tail: int = 500) -> str:
    """The container's own log output — the evidence that a service came up.

    ``docker logs`` prints the *container's* stdout/stderr, which is where a
    server says whether it started. That makes it measured fact, not narration,
    which is what lets a panel show it (invariant I7).
    """
    try:
        proc = _docker_run("logs", "--tail", str(tail), container_id,
                           timeout=DOCKER_INFO_TIMEOUT)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return f"(logs unavailable: {exc})"
    # `docker logs` writes the container's stderr to *its* stderr, so both
    # streams are the container's output and both belong in the transcript.
    return (proc.stdout + proc.stderr).decode("utf-8", "replace")


def image_digest(image: str) -> str:
    """The image's content digest, or ``""``. A tag is a name; this is the thing.

    Recorded so a later reader can tell whether the video was filmed against the
    image the README names *today* or one that has since been republished under
    the same tag.
    """
    if not image:
        return ""
    try:
        proc = _docker_run("image", "inspect", "--format", "{{.Id}}", image,
                           timeout=DOCKER_INFO_TIMEOUT)
    except (subprocess.TimeoutExpired, OSError):
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.decode("utf-8", "replace").strip()


def capture_logs(state: EnvState, path: Path) -> str:
    """Write the container's logs to ``path`` and return them. Measured, once.

    Called from `_stop_environments` rather than from the happy path, because
    logs have to be read while the container still exists and there are exit paths
    that never reach the code after the exec loop. Writing them here means a build
    that died halfway through still has the service's output on disk — often the
    only evidence of *why* it died.
    """
    if state.log_path is not None:
        return state.logs         # already measured; teardown can run twice
    text = container_logs(state.container_id) if state.container_id else state.up_error
    state.logs = text
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(text, encoding="utf-8")
    except OSError:
        state.log_path = None
    else:
        state.log_path = path
    return text


def environment_down(state: EnvState) -> EnvState:
    """Stop and remove the container. **Always** called, on every exit path.

    This is the one function in the module that must not be able to fail
    silently. A leaked container is a bug that affects the *host* rather than the
    output, so the three steps — capture the logs, stop, remove — are each
    attempted, each recorded, and the verdict is `removed` only when the
    container is actually gone. A `--rm` container would have made this
    simpler and would have thrown away the logs.
    """
    result: dict = {"attempted": False, "stopped": False, "removed": False,
                    "detail": ""}
    if state.teardown.get("removed"):
        # A second pass is expected — the stage's outer `finally` runs this again to
        # cover a crash during startup — and it must not touch the first pass's
        # record. That record is the evidence: which container was removed, by which
        # pass, and whether the removal actually happened. Overwriting it with
        # "already removed" would leave `verify.json` reporting that nothing was
        # attempted while a container demonstrably existed.
        #
        # Returned *unchanged*, not with `attempted` set again. The caller reads
        # `attempted` to decide whether this pass did anything, so a no-op pass that
        # reported `attempted: true` would be announced as a second removal — and a
        # build that removed one container would appear to have removed two.
        return state
    state.teardown = result
    if not state.up and not state.container_id and not state.container_name:
        result["detail"] = "nothing was started, so nothing had to be removed"
        result["removed"] = True
        return state

    result["attempted"] = True
    target = state.container_id or state.container_name
    problems: list[str] = []
    try:
        stop = _docker_run("stop", "-t", "5", target, timeout=DOCKER_STOP_TIMEOUT)
        result["stopped"] = stop.returncode == 0
        if stop.returncode != 0:
            problems.append(_explain_docker_failure(stop.stderr.decode("utf-8", "replace")))
    except (subprocess.TimeoutExpired, OSError) as exc:
        problems.append(f"`docker stop` failed: {exc}")

    try:
        rm = _docker_run("rm", "-f", target, timeout=DOCKER_STOP_TIMEOUT)
        result["removed"] = rm.returncode == 0
        if rm.returncode != 0:
            problems.append(f"`docker rm` failed: "
                            f"{_explain_docker_failure(rm.stderr.decode('utf-8', 'replace'))}")
    except (subprocess.TimeoutExpired, OSError) as exc:
        problems.append(f"`docker rm` failed: {exc}")

    result["detail"] = "; ".join(problems) if problems else (
        f"container {state.container_name} stopped and removed")
    return state


def environments_running() -> list[dict]:
    """Every *live* container this engine is responsible for, by its label.

    Used by the tests and by a future `vidkit doctor` to notice a leak. It is
    scoped to vidkit's own label rather than to every container on the machine,
    because a tool that lists containers it did not create is a tool that will
    eventually remove one it did not create.
    """
    if docker_client() is None:
        return []
    try:
        proc = _docker_run("ps", "--filter", "label=vidkit.role=exec",
                           "--format", "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}",
                           timeout=DOCKER_INFO_TIMEOUT)
    except (subprocess.TimeoutExpired, OSError):
        return []
    if proc.returncode != 0:
        return []
    rows = []
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        parts = line.split("\t")
        if len(parts) == 4:
            rows.append({"id": parts[0], "name": parts[1], "image": parts[2],
                         "status": parts[3]})
    return rows


# --------------------------------------------------------------------------- #
# PTY recording
# --------------------------------------------------------------------------- #
def _set_winsize(fd: int, cols: int, rows: int) -> None:
    fcntl.ioctl(fd, 0x5414,  # TIOCSWINSZ
                struct.pack("HHHH", rows, cols, 0, 0))


def stream(req: ExecRequest, *, cwd: Path, backend: str, cols: int, rows: int,
           env: dict[str, str] | None = None) -> Iterator[bytes | ExecResult]:
    """Run ``req`` under a **PTY** and yield its output as it arrives.

    A PTY is not a nicety. A program notices whether its output is a terminal and
    changes what it prints — a progress bar collapses to one line, colours vanish,
    and prompts are suppressed. Recording a pipe produces a transcript that no
    terminal ever displayed, so the video would show something that was not what
    happened. Recording a terminal is the only way to film one.

    Yields raw ``bytes`` chunks, then exactly one :class:`ExecResult` last. The
    consumer must drain the iterator.
    """
    master, slave = pty.openpty()
    _set_winsize(slave, cols, rows)
    argv = _launch_argv(backend, req, Path(cwd))
    started = time.monotonic()
    proc = subprocess.Popen(
        argv,
        # `bwrap` chdirs itself into the sandbox, and `docker exec -w` chdirs
        # inside the container — in neither case does the *host* cwd apply, and
        # passing one would be a path that means nothing.
        cwd=str(cwd) if backend not in ("bubblewrap", "docker") else None,
        env=env if env is not None else _env_for(req, Path(cwd), backend),
        stdin=slave, stdout=slave, stderr=slave,
        close_fds=True,
        start_new_session=True,
    )
    os.close(slave)

    chunks: list[bytes] = []
    truncated = {"stdout": False, "stderr": False}
    total = 0
    timed_out = False
    deadline = started + req.timeout
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            ready, _, _ = select.select([master], [], [], min(remaining, 0.25))
            if ready:
                try:
                    data = os.read(master, 65536)
                except OSError as exc:              # EIO = the slave side closed
                    if exc.errno == errno.EIO:
                        break
                    raise
                if not data:
                    break
                total += len(data)
                if total <= MAX_CAPTURE_BYTES:
                    chunks.append(data)
                else:
                    truncated["stdout"] = True
                yield data
            elif proc.poll() is not None:
                # the child is gone and the buffer is drained
                try:
                    data = os.read(master, 65536)
                except OSError:
                    data = b""
                if not data:
                    break
                chunks.append(data)
                yield data
    finally:
        if timed_out:
            _kill(proc)
        os.close(master)
        rc = proc.wait()

    text = b"".join(chunks).decode("utf-8", "replace")
    in_container = _ENV_FOR_RUN.get(req.label) if backend == "docker" else None
    yield ExecResult(
        request=req, exit_code=rc, stdout=text, stderr="",
        seconds=time.monotonic() - started, truncated=truncated,
        timed_out=timed_out, backend=backend,
        image=in_container.image if in_container else "",
        image_digest=image_digest(in_container.image) if in_container else "",
    )


def _kill(proc: subprocess.Popen) -> None:
    """End the whole process group, then insist.

    ``start_new_session=True`` put the child in its own group, so ``killpg``
    reaches the command *and anything it spawned*. Killing only the direct child
    is how a timeout leaves an orphan holding a port.
    """
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            try:
                proc.send_signal(sig)
            except ProcessLookupError:
                return
        try:
            proc.wait(timeout=3.0)
            return
        except subprocess.TimeoutExpired:
            continue


def run(req: ExecRequest, *, root: Path, on_chunk: Callable[[bytes], None] | None = None,
        cols: int = 100, rows: int = 30) -> ExecResult:
    """Run one declared command and return the single :class:`ExecResult`.

    This is the synchronous face of :func:`stream`, and it is what the pipeline
    calls when nobody wants to watch: it drains the same PTY, offers every chunk
    to ``on_chunk``, and hands back the outcome. Having one implementation means
    the recorded stream and the returned result cannot disagree.
    """
    cwd, refusal = _resolve_cwd(req, root)
    if refusal:
        return ExecResult(request=req, exit_code=126, refused=refusal,
                          backend=req.backend)
    try:
        backend = resolve_backend(req.backend)
    except (SpecError, ToolError) as exc:
        return ExecResult(request=req, exit_code=126, refused=str(exc),
                          backend=req.backend)
    env = _env_for(req, cwd, backend)
    result: ExecResult | None = None
    for item in stream(req, cwd=cwd, backend=backend, cols=cols, rows=rows, env=env):
        if isinstance(item, ExecResult):
            result = item
        elif on_chunk is not None:
            on_chunk(item)
    assert result is not None                 # stream always ends with one
    return result


def _resolve_cwd(req: ExecRequest, root: Path) -> tuple[Path, str]:
    """The directory to run in, or a refusal naming what is wrong with it."""
    if os.path.isabs(req.cwd):
        candidate = Path(req.cwd)
    else:
        candidate = (root / req.cwd)
    try:
        candidate = candidate.resolve()
    except OSError:
        return root, f"working directory does not exist: {req.cwd}"
    if not candidate.is_dir():
        return root, f"working directory does not exist: {req.cwd}"
    return candidate, ""


def check_policy(requests: Sequence[ExecRequest], *, root: Path,
                 allow_network: bool) -> list[str]:
    """Refuse a spec whose commands could not run as declared. Returns reasons.

    Load-time is the right place for this: an author should learn from ``vidkit
    plan`` that a working directory is missing or a backend is unavailable, not
    from a stack trace halfway through a render.
    """
    problems: list[str] = []
    # A backend that cannot run is a fact about the *host*, not about the command
    # that happened to name it, so it is reported once however many commands
    # declare it. Repeating "bwrap cannot run" per command buries the other
    # refusals and reads as though three separate things were wrong.
    backend_problem: dict[str, str] = {}
    for req in requests:
        where = req.label or " ".join(req.cmd) or "(empty command)"
        if not req.cmd:
            problems.append(f"{where}: no command declared")
        if req.timeout <= 0:
            problems.append(f"{where}: timeout must be > 0 (got {req.timeout})")
        if not req.expect_exit:
            problems.append(f"{where}: expect_exit must name at least one exit code")
        if req.backend == "docker":
            pass                 # resolved inside the container, checked by _validate_exec
        else:
            _, refusal = _resolve_cwd(req, root)
            if refusal:
                problems.append(f"{where}: {refusal}")
        if req.network and not allow_network:
            problems.append(
                f"{where}: the command declares `network: true` but the spec's "
                "`exec.allow_network` is false — a command that reaches the "
                "network is a promise about a machine, so widen the spec "
                "deliberately rather than by accident")
        if req.backend in backend_problem:
            continue
        try:
            resolve_backend(req.backend)
        except (SpecError, ToolError) as exc:
            names = sorted({r.backend for r in requests if r.backend == req.backend})
            backend_problem[req.backend] = (
                f"backend {', '.join(names)}: {exc}")
    return problems + list(backend_problem.values())


def backends_report() -> list[dict]:
    """Which backends this host can actually *use*, for ``doctor`` and provenance.

    ``available`` means "a command declared with this backend will run confined",
    which is the only reading anyone has ever wanted from it. The bubblewrap row
    costs one ~14 ms probe; the local row is a fact about the design.

    Docker gets *three* rows' worth of information in one, because its
    "available" collapses three questions with three different costs (see the
    module docstring). ``rungs`` carries each answer separately, so a reader can
    tell "Docker is not installed" from "Docker is installed and the daemon is
    down" — which send an author to completely different places.
    """
    ok, detail = bwrap_available()
    docker_ok, docker_detail = docker_available()
    return [
        {"name": "local", "available": True,
         "detail": "runs unconfined on the host"},
        {"name": "bubblewrap", "available": ok, "detail": detail},
        {"name": "docker", "available": docker_ok, "detail": docker_detail,
         "rungs": docker_rungs()},
    ]


def docker_rungs() -> dict[str, dict]:
    """The three Docker questions, each answered and priced.

    Reported separately rather than folded into a verdict because the *action*
    differs: a missing client is an install, a dead daemon is a service to start,
    and an absent image is a pull. One boolean sends all three to the same
    unhelpful sentence.
    """
    client = docker_client()
    client_row = {"ok": client is not None,
                  "detail": client or "docker(1) is not on PATH"}
    if client is None:
        dead = {"ok": False, "detail": "not asked — the client is missing"}
        return {"client": client_row, "daemon": dead, "container": dead}
    daemon_ok, daemon_detail = docker_daemon()
    ok, detail = docker_available()
    return {
        "client": client_row,
        "daemon": {"ok": daemon_ok, "detail": daemon_detail},
        "container": {"ok": ok, "detail": detail},
    }

