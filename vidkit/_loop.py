"""Doing the engine's blocking work without stopping the server that asked for it.

The engine is synchronous, deliberately. A capture is Playwright's *sync* API, a
render is ``subprocess.run`` over ffmpeg, a container probe is a blocking read,
and a session is a long-lived object graph held in memory. Rewriting any of it to
be awaitable, so that the MCP layer could call it, would mean a second
implementation of everything — and the second one is the one nobody tests.

An MCP tool, though, is invoked by FastMCP **on its event loop**. Two things
cannot happen there, and both of them did:

* Playwright's sync API refuses outright —
  ``It looks like you are using Playwright Sync API inside the asyncio loop.`` —
  so every browser tool failed always, with a message naming Playwright rather
  than the seam.
* Anything merely blocking stopped the whole server for its duration: every other
  client, every keepalive, for as long as an ffmpeg render takes.

So there are two jobs here, and they are different jobs.

**A session-bound worker thread.** Playwright's sync objects are bound to the
thread that created them: the thread that opened a page has to be the thread that
later clicks it. A pool would work by luck and break under load, so each session
owns one thread, started lazily on first use.

**A plain off-loop hop.** Work with no thread affinity — a render, a docker probe,
a report read — only needs to not happen on the loop.

Both fast-path through when there is no loop, which is how the CLI, the pipeline's
own stages and the tests keep calling the engine directly with no thread at all.
"""

from __future__ import annotations

import asyncio
import queue
import threading
from concurrent.futures import Future
from typing import Any, Callable, TypeVar

try:  # anyio ships with mcp; the engine's own extras do not need it
    from anyio.to_thread import run_sync as _run_sync
except Exception:  # pragma: no cover - only reachable without anyio installed
    _run_sync = None  # type: ignore[assignment]

T = TypeVar("T")

#: How long to wait for a worker thread to finish when a session closes. A render
#: already in flight can outlast this; the caller is then told, rather than hung.
JOIN_TIMEOUT = 10.0


class Worker:
    """One thread for one session, and whatever blocking work belongs to it.

    Jobs arrive on a :class:`queue.Queue`, which is thread-safe from either side,
    so a caller may be an event loop or an ordinary stack. Results come back as
    :class:`concurrent.futures.Future`, likewise safe to wait on from anywhere —
    deliberately *not* an asyncio future, because one worker thread has to be able
    to serve a client that runs no loop at all.
    """

    def __init__(self, name: str = "vidkit-worker") -> None:
        self._name = name
        self._thread: threading.Thread | None = None
        self._jobs: "queue.Queue[Any] | None" = None
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        """The thread's name, which is how a hung worker is identified."""
        return self._name

    @property
    def alive(self) -> bool:
        t = self._thread
        return t is not None and t.is_alive()

    def submit(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> "Future[T]":
        """Queue ``fn(*args, **kwargs)`` and return a future for its result.

        The callable runs on the worker thread and nowhere else, which is what
        makes a page opened by one call clickable by the next.
        """
        fut: "Future[T]" = Future()
        with self._lock:
            if not self.alive:
                self._jobs = queue.Queue()
                self._thread = threading.Thread(
                    target=self._serve, name=self._name, daemon=True)
                self._thread.start()
            jobs = self._jobs
        assert jobs is not None
        jobs.put((lambda: fn(*args, **kwargs), fut))
        return fut

    def _serve(self) -> None:
        """The worker's whole life: one job, then the next, until the sentinel."""
        jobs = self._jobs
        assert jobs is not None
        while True:
            item = jobs.get()
            if item is None:
                return
            fn, fut = item
            if not fut.set_running_or_notify_cancel():
                continue
            try:
                value = fn()
            except BaseException as exc:  # noqa: BLE001 - carried to the caller
                fut.set_exception(exc)
            else:
                fut.set_result(value)

    def stop(self) -> bool:
        """Ask the thread to finish, and wait for it. Safe to call twice."""
        with self._lock:
            thread, jobs = self._thread, self._jobs
            self._thread, self._jobs = None, None
        if thread is None or not thread.is_alive():
            return False
        if jobs is not None:
            jobs.put(None)
        if threading.current_thread() is thread:
            # Called *from* the worker — a session closing itself. Joining here
            # would be the thread waiting for its own death; the sentinel is
            # already queued, so it exits as soon as this job returns.
            return True
        thread.join(timeout=JOIN_TIMEOUT)
        return not thread.is_alive()


# --------------------------------------------------------------------------- #
# crossing the boundary
# --------------------------------------------------------------------------- #
# There is no way to escape the loop *from* the loop: a synchronous function that
# blocks the loop thread has stopped the very thing that would run the work it is
# waiting for. So the direction of the fix is forced, and it is worth saying out
# loud, because the alternative looks reasonable and deadlocks under load.
#
#   * A tool the protocol can reach is declared ``async`` and hops *out* with
#     :func:`offload`. That is the only door an MCP client has.
#   * A function that drives a session's browser runs on that session's own thread
#     with :func:`session`, and does not care whether its caller was a loop, an
#     anyio worker or a plain stack.
#   * Code with no loop at all — the CLI, the pipeline's stages, the tests — calls
#     the engine directly, and every one of these fast-paths through to a plain
#     call.
# --------------------------------------------------------------------------- #
def in_loop() -> bool:
    """Whether this call is already inside a running event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


async def offload(fn: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """Await a blocking ``fn(*args, **kwargs)``, run on a thread that is not the loop.

    What every registered MCP tool body should be. It has no thread affinity of its
    own — a render, a container probe, a report read — and only needs to not happen
    on the loop.
    """
    if _run_sync is None:  # pragma: no cover - mcp always brings anyio
        raise RuntimeError(
            "this tool would block the event loop, but anyio is not installed — "
            "`pip install anyio`")
    return await _run_sync(lambda: fn(*args, **kwargs))


def _worker_of(obj: Any) -> Worker | None:
    """The worker an object owns, if it has been given one."""
    return getattr(obj, "worker", None)


def session(obj: Any, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run ``fn`` for ``obj`` on the thread that owns its page, and wait.

    Thread affinity is not about the event loop: Playwright's page has to be
    clicked by the thread that made it, whoever is asking. So this goes through the
    worker whenever there is one, loop or no loop.
    """
    worker = _worker_of(obj)
    if worker is None:
        return fn(*args, **kwargs)
    return worker.submit(fn, *args, **kwargs).result()
