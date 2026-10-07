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

A backend is a function ``(ExecRequest, policy) -> ExecResult``. Nothing else in
the engine knows how a command ran, so a Docker backend (M8) is an addition to
:data:`BACKENDS`, not a change to the pipeline.

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
import pty
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

    @property
    def expected(self) -> bool:
        return self.exit_code in set(self.request.expect_exit)

    @property
    def ok(self) -> bool:
        return not self.refused and not self.timed_out and self.expected

    def to_dict(self) -> dict:
        return {
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


# --------------------------------------------------------------------------- #
# the environment
# --------------------------------------------------------------------------- #
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
    raise SpecError(
        f"unknown exec backend {name!r}; known: local, bubblewrap "
        "(docker arrives with the environment lab in M8)")


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


def _launch_argv(backend: str, req: ExecRequest, cwd: Path) -> list[str]:
    if backend == "bubblewrap":
        return _bwrap_argv(req, cwd)
    return _host_argv(req)


def _env_for(req: ExecRequest, cwd: Path, backend: str) -> dict[str, str]:
    env = dict(BASE_ENV)
    env.update(req.env)                  # what the spec declared it needs
    env["VIDKIT_SANDBOX"] = backend
    if backend == "bubblewrap":
        env["HOME"] = BASE_ENV["HOME"]
        env["PWD"] = "/work"
    else:
        env["HOME"] = str(cwd)
        env["PWD"] = str(cwd)
    return env


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
        cwd=str(cwd) if backend != "bubblewrap" else None,
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
    yield ExecResult(
        request=req, exit_code=rc, stdout=text, stderr="",
        seconds=time.monotonic() - started, truncated=truncated,
        timed_out=timed_out, backend=backend,
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
    """
    ok, detail = bwrap_available()
    return [
        {"name": "local", "available": True,
         "detail": "runs unconfined on the host"},
        {"name": "bubblewrap", "available": ok, "detail": detail},
    ]

