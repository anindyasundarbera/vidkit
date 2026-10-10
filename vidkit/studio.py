"""Studio sessions, takes and budgets — the state a director holds between calls.

Why this module exists
----------------------
Every other part of vidkit is a **verb**: load a spec, render it, check it. An
agent handed *(story, timeframe, environment)* and asked for a demo does not
work in verbs. It works in a **sitting** — open the set, bring the database up,
try the capture, look at what came back, try it again, keep the good one, render
the film, read the report. Between those calls it has to *remember* things, and
the things it remembers have to be checkable rather than asserted.

So a :class:`Session` is a durable JSON record of one sitting: what it is about,
where it is working inside the project, which takes have been tried, which one was
kept and why. The record is deliberately **data** — nothing in it is a handle to a
browser or a container. Those already have owners:

* the sandbox and its containers belong to :mod:`vidkit.exec`, which *measures*
  what became of them, and ``docker`` itself is the register of what is running;
* browsers belong to Playwright, and are opened for one call at a time.

That split is why ``status`` can tell the truth after a process restart: it asks
the owners, it does not consult its own memory of what it once did. A container
that died while nobody was looking reads ``alive: false``, because the answer came
from ``docker ps`` and not from a field this module wrote.

The live half
-------------
Some things *cannot* be data. A browser a caller opened in one call has to still be
there in the next one, and a :class:`~vidkit.context.Context` holds the secrets, the
provider module and the measured facts a *sitting* accumulates. Those live in
:attr:`Session._live`, which is process-local, never serialised, and deliberately
absent from :meth:`Session.to_dict`. The rule that keeps this honest is that
``_live`` may only hold things that are **reconstructible or explicitly open**: a
missing context is rebuilt from the spec, a missing browser is reported as not
open, and neither is ever silently faked. What ``status`` reports about the
durable record is exactly what survived a restart.

Takes
------
A take is a **name convention backed by real bytes** (R-C6): ``capture.name`` for
the first attempt, ``capture.name.take2`` for the second, and so on. What was
missing is the *record* — which takes exist, which one the film actually used,
and how they differ. ``take_record`` writes that down by hashing the file, and
``take_select`` copies the chosen take over the base name (reusing the capture
stage's own rule, so a build cannot tell the difference).

**This module never draws a take.** Selecting is not editing: it promotes bytes
that a real capture produced, and records the hash of what it promoted. There is
no operation here that changes a picture to make it look better than it was (I7).

Budgets
-------
Borrowed as a *concept* from OpenMontage (see ``docs/plan/OPENMONTAGE.md``): a
session declares what it may spend and refuses when it runs out, rather than
discovering the ceiling by hitting it. Wall-clock and container counts are
**measured** against what the work actually did; token budget is recorded but not
enforced, because vidkit cannot see a client's token meter and a number it cannot
measure is not a number it should pretend to police.

The wall-clock budget is a *session* deadline, not a per-call alarm. The MCP
tools already bound one call with ``SIGALRM`` (``mcp_server._deadline``); a session
outlives any one call, so its budget is recorded as a start time and checked by
arithmetic.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import _loop
from . import capture as _capture
from .errors import SpecError, ToolError

#: Directory name, beside the output, where a project keeps its studio state.
STATE_DIR = ".vidkit"

#: A session id is used in filenames and container names, so it is restricted to
#: characters that are safe in both. Generated ids satisfy this by construction;
#: a caller-supplied one is checked, because a session named ``../../etc`` would
#: otherwise choose where the record is written.
_SESSION_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")


# --------------------------------------------------------------------------- #
# budgets
# --------------------------------------------------------------------------- #
@dataclass
class Budget:
    """What a sitting declared it may spend, and what it has spent.

    ``spent_seconds`` is **not** an estimate and **not** a tally of the calls a
    session made — it is derived from the timestamps the session recorded, so it
    survives a process restart and cannot drift from the record. ``containers``
    is the *peak* number of sandboxes held at once, which is the number that
    matters for a laptop (see :meth:`check`).
    """

    max_seconds: float = 0.0             # 0 = no declared ceiling
    max_containers: int = 0              # 0 = no declared ceiling
    max_tokens: int = 0                  # recorded, not enforced — see the module docstring
    tokens: int = 0                      # as reported by the client, if it says
    spent_seconds: float = 0.0
    containers: int = 0

    @property
    def seconds_left(self) -> float | None:
        return None if self.max_seconds <= 0 else self.max_seconds - self.spent_seconds

    @property
    def exhausted(self) -> bool:
        left = self.seconds_left
        return left is not None and left <= 0

    def to_dict(self) -> dict:
        left = self.seconds_left
        out: dict = {
            "max_seconds": self.max_seconds,
            "max_containers": self.max_containers,
            "max_tokens": self.max_tokens,
            "tokens": self.tokens,
            "spent_seconds": round(self.spent_seconds, 3),
            "containers": self.containers,
            # `null` rather than a sentinel number: "no ceiling declared" and
            # "no time left" are different states and must not both be spelled 0.
            "seconds_left": None if left is None else round(left, 3),
            "exhausted": self.exhausted,
        }
        return out

    def check(self, *, seconds: float = 0.0, containers: int = 0) -> str:
        """Refuse a call that would exceed the budget. Returns the reason, or ``""``.

        ``containers`` is the number of environments that would be **held at
        once** by this call, not the number it starts: the ceiling exists to stop
        a session piling up sandboxes on one machine, and one that started twelve
        databases one after another and closed each has spent nothing.

        A call that cannot say how long it will take passes no ``seconds`` — a step
        runs until it is done, and estimating it would be a guess dressed as a
        budget. Such a call is still refused once the clock is *already* past the
        ceiling, because that is not an estimate: the session has spent its
        allowance and the next thing it does spends more of it. Without this branch
        the seconds ceiling could never fire on the calls that actually cost time,
        which would make it a ceiling in name only.
        """
        left = self.seconds_left
        if left is not None and left <= 0:
            return (f"session budget: the {self.max_seconds:.0f}s budget is spent "
                    f"({self.spent_seconds:.0f}s used) — close the session or open "
                    "a new one with a larger budget")
        if left is not None and seconds and seconds > left:
            return (f"session budget: {seconds:.0f}s requested but only {left:.0f}s "
                    f"of the {self.max_seconds:.0f}s budget is left")
        if self.max_containers and containers > self.max_containers:
            return (f"session budget: {containers} environment(s) would be up at once "
                    f"but the budget allows {self.max_containers}")
        return ""

    def note_spend(self, seconds: float, *, containers: int | None = None) -> None:
        self.spent_seconds += max(0.0, seconds)
        if containers is not None:
            self.containers = max(self.containers, containers)


# --------------------------------------------------------------------------- #
# takes
# --------------------------------------------------------------------------- #
@dataclass
class Take:
    """One recorded attempt at a capture, and the hash of the bytes it produced.

    The hash is the whole point. ``take_list`` can say "these are the takes"; only
    a hash lets a caller answer "did the product change between them?" without
    inventing an answer, and only a hash makes ``take_select`` auditable after the
    fact.
    """

    capture: str
    take: int
    path: str
    digest: str = ""
    bytes: int = 0
    at: str = ""
    note: str = ""
    created: float = 0.0

    def to_dict(self) -> dict:
        return {
            "capture": self.capture,
            "take": self.take,
            "path": self.path,
            "digest": self.digest,
            "bytes": self.bytes,
            "at": self.at,
            "note": self.note,
            "created": self.created,
        }


def _digest(path: Path) -> str:
    """The content hash of a file, or ``""`` when it is not there."""
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    return hashlib.sha256(data).hexdigest()[:16]


def take_path(out_dir: Path, name: str, take: int) -> Path:
    """Where take ``take`` of capture ``name`` lives — the same rule ``capture`` uses."""
    return out_dir / "_capture" / f"{_capture.take_name(name, take)}.png"


# --------------------------------------------------------------------------- #
# the session
# --------------------------------------------------------------------------- #
def new_id(prefix: str = "s") -> str:
    """A session id: short, sortable-ish, and safe in a filename."""
    return f"{prefix}{int(time.time()):x}{uuid.uuid4().hex[:6]}"


@dataclass
class Session:
    """One sitting: what it is about, what it tried, what it kept.

    Serialised whole to ``<out>/.vidkit/sessions/<id>.json`` after every mutation,
    so the record and the work cannot diverge if the process dies mid-sitting.
    """

    id: str
    spec: str = ""                       # resolved spec path
    root: str = ""                       # the story folder
    out_dir: str = ""                    # where the render is written
    story: str = ""
    title: str = ""
    environment: str = ""                # the env an env_up started, if any
    budgets: Budget = field(default_factory=Budget)
    takes: list[Take] = field(default_factory=list)
    #: environments this sitting started, oldest first (see :class:`EnvRef`).
    environment_refs: list[EnvRef] = field(default_factory=list)
    #: ``"{capture}/{take}"`` of every take ever promoted, oldest first. A list
    #: rather than a single value: a session that changed its mind twice should
    #: show both decisions, not just the last one.
    selections: list[str] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    opened: float = field(default_factory=time.time)
    closed: float | None = None

    #: Live objects this process owns for the session — a browser, its context and
    #: page. **Not** serialised: a `Page` is not JSON, and a session read back from
    #: disk after a restart genuinely has no browser, which is what `browser_act`
    #: says rather than pretending otherwise.
    _live: dict = field(default_factory=dict, repr=False, compare=False)

    #: Where this record was found, when it was loaded through a :class:`Registry`.
    #: Not serialised: it describes the *record's* location, not the sitting, and a
    #: record that named its own directory would be wrong the moment it was copied.
    _record_dir: str = field(default="", repr=False, compare=False)

    #: The thread that owns this session's browser. Not serialised, and not created
    #: until something needs it, because Playwright's sync objects belong to the
    #: thread that made them — see :mod:`vidkit._loop`.
    worker: "_loop.Worker | None" = field(default=None, repr=False, compare=False)

    # -- lifecycle -------------------------------------------------------- #
    @property
    def open(self) -> bool:
        return self.closed is None

    def close(self, reason: str = "") -> None:
        if self.closed is None:
            self.closed = time.time()
            self.events.append({"at": time.time(), "kind": "close",
                                "detail": reason})

    # -- the record ------------------------------------------------------- #
    def elapsed(self) -> float:
        end = self.closed if self.closed is not None else time.time()
        return max(0.0, end - self.opened)

    def sync_run_seconds(self, seconds: float = 0.0) -> None:
        """Add work that `elapsed` cannot see, before the next budget read."""
        self.budgets.spent_seconds += max(0.0, seconds)

    def sync_budget(self, containers: int = 0) -> None:
        """Bring the measured spend up to date. Called before every read.

        A high-water mark, not an assignment: the clock and a single long command
        are both real spend, and taking the larger keeps one from erasing the
        other.
        """
        self.budgets.spent_seconds = max(self.budgets.spent_seconds, self.elapsed())
        if containers:
            self.budgets.containers = max(self.budgets.containers, containers)

    def event(self, kind: str, detail: str = "", **extra) -> None:
        """Append one thing that happened. The session's own timeline."""
        self.events.append({"at": time.time(), "kind": kind, "detail": detail,
                            **extra})

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "open": self.open,
            "spec": self.spec,
            "root": self.root,
            "out_dir": self.out_dir,
            "story": self.story,
            "title": self.title,
            "environment": self.environment,
            "budgets": self.budgets.to_dict(),
            "takes": [t.to_dict() for t in self.takes],
            "environments": [e.to_dict() for e in self.environment_refs],
            "selections": list(self.selections),
            "opened": self.opened,
            "closed": self.closed,
            "elapsed": round(self.elapsed(), 3),
            "events": list(self.events),
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "Session":
        b = raw.get("budgets") or {}
        sess = cls(
            id=str(raw.get("id", "")),
            spec=str(raw.get("spec", "")),
            root=str(raw.get("root", "")),
            out_dir=str(raw.get("out_dir", "")),
            story=str(raw.get("story", "")),
            title=str(raw.get("title", "")),
            environment=str(raw.get("environment", "")),
            budgets=Budget(
                max_seconds=float(b.get("max_seconds", 0.0)),
                max_containers=int(b.get("max_containers", 0)),
                max_tokens=int(b.get("max_tokens", 0)),
                tokens=int(b.get("tokens", 0)),
                spent_seconds=float(b.get("spent_seconds", 0.0)),
                containers=int(b.get("containers", 0)),
            ),
            takes=[Take(**{k: v for k, v in t.items() if k in Take.__dataclass_fields__})
                   for t in (raw.get("takes") or [])],
            environment_refs=[
                EnvRef(**{k: v for k, v in e.items() if k in EnvRef.__dataclass_fields__})
                for e in (raw.get("environments") or [])],
            selections=[str(s) for s in (raw.get("selections") or [])],
            events=list(raw.get("events") or []),
            opened=float(raw.get("opened", time.time())),
            closed=None if raw.get("closed") is None else float(raw["closed"]),
        )
        return sess


# --------------------------------------------------------------------------- #
# the registry
# --------------------------------------------------------------------------- #
class Registry:
    """Sessions on disk, in one project.

    Deliberately a directory of JSON files rather than a database. The record has
    to be readable by a human debugging a failed shoot, greppable by CI, and
    diffable in a pull request; a single sqlite blob is none of those, and there
    is no concurrency here to justify one.
    """

    def __init__(self, out_dir: Path | str) -> None:
        self.out_dir = Path(out_dir).resolve()
        self.dir = self.out_dir / STATE_DIR / "sessions"

    # -- paths ------------------------------------------------------------ #
    def path(self, session_id: str) -> Path:
        if not _SESSION_ID_RE.match(session_id):
            raise ToolError(
                f"session id {session_id!r} is not usable — ids are lower-case "
                "letters, digits, dot, dash and underscore, up to 64 characters")
        return self.dir / f"{session_id}.json"

    # -- reads ------------------------------------------------------------ #
    def ids(self) -> list[str]:
        if not self.dir.exists():
            return []
        return sorted(p.stem for p in self.dir.glob("*.json"))

    def load(self, session_id: str) -> Session:
        p = self.path(session_id)
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise ToolError(
                f"no session {session_id!r} in {self.dir} — call session_open "
                "first, or session_list to see what is there") from None
        except (OSError, ValueError) as exc:
            raise ToolError(f"session {session_id!r} could not be read: {exc}") from exc
        sess = Session.from_dict(raw)
        # `self.dir`, not `self.out_dir`: `record_dir` exists to be *different* from
        # `out_dir` — one is where the film goes, the other is where this session's own
        # record was written. Pointing both at the project root tells a client nothing
        # it did not already have.
        sess._record_dir = str(self.dir)
        return sess

    def all(self, *, include_closed: bool = True) -> list[Session]:
        out: list[Session] = []
        for sid in self.ids():
            try:
                s = self.load(sid)
            except ToolError:
                continue          # a corrupt record is skipped, not fatal to the list
            if include_closed or s.open:
                out.append(s)
        return sorted(out, key=lambda s: s.opened)

    # -- writes ----------------------------------------------------------- #
    def save(self, session: Session) -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        p = self.path(session.id)
        # Write beside and rename, so a crash mid-write leaves the previous
        # record intact rather than a half-file that reads as a corrupt session.
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(session.to_dict(), indent=1), encoding="utf-8")
        os.replace(tmp, p)
        return p


def open_session(out_dir: Path | str, *, spec: str = "", story: str = "",
                 title: str = "", session_id: str = "",
                 max_seconds: float = 0.0, max_containers: int = 0,
                 max_tokens: int = 0) -> Session:
    """Begin a sitting and write its record."""
    reg = Registry(out_dir)
    sid = session_id or new_id()
    p = reg.path(sid)               # validates the id even when it was generated
    if p.exists():
        raise ToolError(
            f"session {sid!r} already exists — sessions are never resumed under the "
            "same id, because the record of a sitting that was interrupted still has "
            "to be readable as what it was")
    sess = Session(
        id=sid, spec=str(spec), root=str(Path(spec).parent) if spec else "",
        out_dir=str(Path(out_dir).resolve()), story=str(story), title=str(title),
        budgets=Budget(max_seconds=max(0.0, max_seconds),
                       max_containers=max(0, max_containers),
                       max_tokens=max(0, max_tokens)),
    )
    # The *sessions* directory, not the project root — see the note in `Registry.load`.
    sess._record_dir = str(reg.dir)
    sess.event("open", story or title or spec)
    reg.save(sess)
    return hold(sess)


# --------------------------------------------------------------------------- #
# takes, as operations on a session
# --------------------------------------------------------------------------- #
def record_take(session: Session, capture_name: str, take: int = 1,
                note: str = "") -> Take:
    """Note what a capture produced, and hash the bytes.

    Refuses when the file is not there: a take recorded for a capture that never
    ran is exactly the fabricated-fact failure this toolkit is built to prevent.
    """
    if take < 1:
        raise ToolError("a take number starts at 1")
    p = take_path(Path(session.out_dir), capture_name, take)
    if not p.is_file():
        raise SpecError(
            f"take {take} of {capture_name!r} was not recorded because there is no "
            f"{p} — run the capture first, or name the take that exists "
            "(session_takes lists what is there)")
    entry = Take(capture=capture_name, take=take,
                 path=str(p.relative_to(Path(session.out_dir))
                          if p.is_relative_to(Path(session.out_dir)) else p),
                 digest=_digest(p), bytes=p.stat().st_size,
                 at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                 note=note, created=time.time())
    session.takes = [t for t in session.takes
                     if not (t.capture == capture_name and t.take == take)]
    session.takes.append(entry)
    session.event("take", f"{capture_name} take {take}", digest=entry.digest)
    return entry


def _scan_takes(session: Session, capture_name: str = "") -> list[Take]:
    """Every take file that is actually on disk, whether or not it was recorded.

    Scanned rather than read from the record on purpose: the record can be
    incomplete (a capture run outside a session, a record written by an older
    build), and "which takes exist" is a question about the filesystem. The
    record then supplies the *notes*, which are the part only a caller knows.
    """
    captures = Path(session.out_dir) / "_capture"
    if not captures.is_dir():
        return []
    known = {(t.capture, t.take): t for t in session.takes}
    base: dict[str, list[tuple[int, Path]]] = {}
    for p in captures.glob("*.png"):
        stem, take = p.stem, 1
        m = re.match(r"^(.*)\.take(\d+)$", stem)
        if m:
            stem, take = m.group(1), int(m.group(2))
        base.setdefault(stem, []).append((take, p))
    out: list[Take] = []
    for stem, entries in sorted(base.items()):
        if capture_name and stem != capture_name:
            continue
        for take, p in sorted(entries):
            prev = known.get((stem, take))
            out.append(Take(
                capture=stem, take=take,
                path=str(p.relative_to(Path(session.out_dir))),
                digest=_digest(p), bytes=p.stat().st_size,
                at=prev.at if prev else "", note=prev.note if prev else "",
                created=prev.created if prev else p.stat().st_mtime))
    return out


def list_takes(session: Session, capture_name: str = "") -> dict:
    """What takes exist, and which of them the film is currently built from."""
    takes = _scan_takes(session, capture_name)
    kept = set(session.selections)
    rows = []
    for t in takes:
        row = t.to_dict()
        row["selected"] = f"{t.capture}/{t.take}" in kept
        rows.append(row)
    return {"session": session.id, "takes": rows, "selections": list(session.selections)}


def select_take(session: Session, capture_name: str, take: int) -> dict:
    """Promote one take so a build uses it. Never draws a new picture.

    The promotion itself is the capture stage's own rule
    (:func:`vidkit.capture.choose_take`), reused rather than reimplemented, so a
    film assembled from a selected take is built by exactly the code path that
    builds one from a first take.
    """
    out_dir = Path(session.out_dir)
    src = take_path(out_dir, capture_name, take)
    if not src.is_file():
        raise SpecError(
            f"take {take} of {capture_name!r} does not exist ({src}); "
            "session_takes lists the takes that do")
    base = out_dir / "_capture" / f"{capture_name}.png"
    before = _digest(base)
    _capture.choose_take(base, take, name=capture_name)
    after = _digest(base)
    if take > 1 and before == after:
        # `choose_take` copies the take over the base name. If the bytes did not
        # change, the promotion did not happen, and a build would film the *old*
        # take while the record claimed the new one — the exact
        # recorded-a-fact-that-is-not-true failure this toolkit refuses. Only
        # reachable when the two takes are byte-identical, which is itself worth
        # knowing: it means the retry changed nothing.
        raise ToolError(
            f"take {take} of {capture_name!r} is byte-identical to the take already "
            "in use, so promoting it would change nothing — the retry produced the "
            "same screen. Keep the current take, or capture again.")
    marker = f"{capture_name}/{take}"
    session.selections.append(marker)
    # The live context already exists if this session has been used; keep it in step,
    # or a build in this same process would render the take the sitting just replaced.
    live = session._live.get("ctx")
    if live is not None:
        live.selections.add(marker)
    session.event("select", marker, digest=after)
    return {"ok": True, "selected": marker, "path": str(base), "digest": after,
            "selections": list(session.selections)}


def takes_summary(session: Session) -> dict:
    """A compact view for a status call: what exists, what was kept."""
    takes = _scan_takes(session)
    by_capture: dict[str, list[int]] = {}
    for t in takes:
        by_capture.setdefault(t.capture, []).append(t.take)
    return {
        "captures": {k: sorted(v) for k, v in sorted(by_capture.items())},
        "count": len(takes),
        "selections": list(session.selections),
    }


# --------------------------------------------------------------------------- #
# environments, outside a build
# --------------------------------------------------------------------------- #
@dataclass
class EnvRef:
    """The session's memory of one sandbox it started.

    Deliberately *thinner* than :class:`vidkit.exec.EnvState`: it holds only what
    is needed to find the container again and to hand a caller something to read.
    What became of it — health, logs, teardown — is asked of Docker when it is
    asked for, never replayed from here. A session that cached "ready: true" from
    ten minutes ago would be reporting a memory, not a running service.

    ``to_state`` rebuilds the runtime's own object from these fields, so a session
    can go on using one engine instead of growing a second implementation of the
    same lifecycle. ``container_id`` is kept in full: :meth:`EnvState.to_dict`
    truncates it for display, and a truncated id cannot be stopped.
    """

    name: str
    container_name: str = ""
    container_id: str = ""
    image: str = ""
    image_digest: str = ""
    started: float = 0.0
    stopped: float | None = None
    ready: bool = False
    ready_detail: str = ""
    up_error: str = ""
    health: dict = field(default_factory=dict)
    teardown: dict = field(default_factory=dict)

    def to_state(self, state=None):
        """The runtime :class:`~vidkit.exec.EnvState` this record stands for.

        ``state`` (an ``EnvSpec``) is required to build a fresh one; it is passed
        in rather than stored because the environment's declaration belongs to the
        spec, which may have been edited since the container was created — in
        which case the *spec's* version is the one a new call should use.
        """
        from . import exec as _exec

        return _exec.EnvState(
            spec=state, container_id=self.container_id,
            container_name=self.container_name, image_digest=self.image_digest,
            started=bool(self.started), up=not self.up_error,
            up_error=self.up_error, ready=self.ready,
            ready_detail=self.ready_detail, health=dict(self.health),
            teardown=dict(self.teardown),
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "container_name": self.container_name,
            "container_id": self.container_id[:12] if self.container_id else "",
            "image": self.image,
            "image_digest": self.image_digest,
            "started": self.started,
            "stopped": self.stopped,
            "ready": self.ready,
            "ready_detail": self.ready_detail,
            "up_error": self.up_error,
            "health": dict(self.health),
            "teardown": dict(self.teardown),
        }


def env_spec(spec, name: str):
    """The runtime ``EnvSpec`` for a declared environment, or a refusal naming it."""
    from .assembler import _env_spec

    env = spec.environment(name)
    if env is None:
        declared = ", ".join(e.name for e in spec.environments) or "none"
        raise SpecError(
            f"the spec declares no environment {name!r} (declared: {declared}) — an "
            "environment is the `environment:` block a `backend: docker` step runs in")
    return _env_spec(env)


def start_environment(session: Session, spec, name: str) -> EnvRef:
    """Bring a declared environment up for this session, and prove it is up.

    The **stamp** is the session id, which is what makes the container
    attributable: ``docker ps`` on a machine that has run vidkit shows
    ``vidkit-studio-<session>`` rather than an anonymous hash, and a leak can be
    traced back to the sitting that made it.

    A session may hold one container per environment. Starting an environment it
    already has up is refused rather than duplicated — a second container under
    the same name cannot exist anyway, and two under different names is how a
    machine ends up running four copies of Postgres.
    """
    from . import exec as _exec

    existing = [e for e in session.environment_refs
                if e.name == name and e.stopped is None]
    if existing:
        raise ToolError(
            f"environment {name!r} is already up for this session "
            f"(container {existing[0].container_name or 'unknown'}); call env_down "
            "first, or session_status to see what is running")

    env = env_spec(spec, name)
    if session.budgets.max_containers:
        held = len(live_refs(session)) + 1
        why = session.budgets.check(containers=held)
        if why:
            raise ToolError(why)

    state = _exec.environment_up(env, root=Path(session.root or "."),
                                 stamp=session.id)
    ref = EnvRef(
        name=name, container_name=state.container_name,
        container_id=state.container_id, image=state.spec.image,
        image_digest=state.image_digest, started=time.time(),
        ready=state.ready, ready_detail=state.ready_detail,
        up_error=state.up_error, teardown=dict(state.teardown))
    session.environment_refs.append(ref)
    if state.up and not state.ready and not state.up_error:
        session.event("env_up", f"{name} up but not ready: {state.ready_detail}")
    else:
        session.event("env_up", f"{name} {'ready' if state.ready else state.up_error or 'not up'}")
    session.sync_budget(containers=len(live_refs(session)))
    return ref


def live_refs(session: Session) -> list[EnvRef]:
    """The session's environments that ought to still be running."""
    return [e for e in session.environment_refs if e.stopped is None]


def stop_environment(session: Session, name: str = "") -> list[EnvRef]:
    """Take down what this session holds. Idempotent, and always recorded.

    Stops them **all** unless one is named: a session ending should not be able to
    leave a database behind because the caller forgot which one it started. The
    teardown verdict comes from Docker and is stored verbatim — including the
    failures, which are the interesting ones.
    """
    from . import exec as _exec

    targets = [e for e in live_refs(session)
               if not name or e.name == name]
    if name and not targets:
        raise ToolError(f"this session has no environment {name!r} still up")
    for ref in targets:
        state = ref.to_state(env_spec_for_ref(session, ref))
        state.teardown.clear()          # `environment_down` is idempotent by this key
        _exec.environment_down(state)
        ref.teardown = dict(state.teardown)
        ref.stopped = time.time()
        session.event("env_down", f"{ref.name}: "
                      + " ".join(f"{k}={v}" for k, v in ref.teardown.items()))
    session.sync_budget()
    return targets


def env_spec_for_ref(session: Session, ref: EnvRef):
    """The ``EnvSpec`` for a record, taken from the session's own spec file."""
    spec = load_spec(session)
    return env_spec(spec, ref.name)


def load_spec(session: Session):
    """The parsed spec a session is working against, as it is *right now*.

    Re-read from disk on every call rather than held on the session. A session
    lives for minutes and the spec may be edited in between — and a session
    acting on a stale in-memory copy would build something other than what the
    file says. ``Spec`` is cheap and this is not a hot path.
    """
    from .spec import load_spec as _load

    path = Path(session.spec)
    if not path.is_file():
        raise SpecError(
            f"the spec this session was opened against is gone: {path} — a session "
            "records where its story lives, and it cannot build from a file that "
            "is no longer there")
    return _load(path)


def environments_in_use() -> list[dict]:
    """Every vidkit sandbox running on this host, whoever started it.

    Asked of the host rather than of a session, because the question a reader has
    when a build misbehaves is "what is *actually* up right now?", and the answer
    must not depend on which JSON file they happen to be looking at.
    """
    from . import exec as _exec

    try:
        return _exec.environments_running()
    except Exception as exc:                      # noqa: BLE001 - docker may be absent
        return [{"error": f"docker could not be asked: {exc}"}]


def environment_status(session: Session, name: str = "") -> dict:
    """What is running, what is not, and whether the session is over budget.

    Two halves, and they answer different questions. ``live`` is the host's own
    answer (via ``docker ps``); ``held`` is this session's record of what it
    started. When a session holds something that is not live, that is a container
    that **died** — which is the single most useful thing this call can tell a
    caller, and it cannot be derived from either half alone.
    """
    held = [e.to_dict() for e in live_refs(session)]
    live = environments_in_use()
    live_names = {row.get("name") for row in live}
    for row in held:
        row["alive"] = bool(row["container_name"]) and row["container_name"] in live_names
    if name:
        held = [r for r in held if r["name"] == name] or held
    session.sync_budget(containers=len(live_refs(session)))
    return {
        "session": session.id,
        "held": held,
        "live": live,
        "budgets": session.budgets.to_dict(),
        "note": ("`alive: false` means the container this session started is no "
                 "longer running — the service died, or something else removed it"),
    }


# --------------------------------------------------------------------------- #
# running a command in a session, outside a build
# --------------------------------------------------------------------------- #
# A session's whole reason to exist is that a caller can *act* between the stages
# of a build: bring a database up, film a page, run a probe, look at the answer,
# and only then assemble. The build pipeline can already do all of that, but only
# as one indivisible arc. These are the same operations, one at a time, recorded
# as they happen.
#
# Nothing here is a second implementation of anything. The request is translated
# by ``assembler._exec_request``, the command runs under ``exec.run``, the page is
# driven by ``capture``'s own action applier, and the environment lifecycle is
# ``exec.environment_up``/``environment_down``. What the session adds is the
# *record*: which session asked, what it cost, and what it produced.
# --------------------------------------------------------------------------- #
def run_step(session: Session, spec, label: str, *, on_chunk=None) -> dict:
    """Run one **declared** ``exec:`` step and record the result.

    Only a declared step. A tool that runs an arbitrary command handed to it over
    the wire is a remote shell, and the engine exists to film commands the *spec*
    authored. A caller that wants something new runs it by editing the spec, which
    is the same rule the build obeys — and which keeps the spec the single account
    of what the video shows.
    """
    from . import exec as _exec
    from .assembler import _exec_request

    step = spec.exec_step(label)
    if step is None:
        declared = ", ".join(s.label for s in spec.exec) or "none"
        raise SpecError(
            f"the spec declares no exec step {label!r} (declared: {declared}) — a "
            "session runs the commands the spec authored, not commands handed to it")
    why = session.budgets.check()
    if why:
        raise ToolError(why)

    root = Path(session.root or ".")
    req = _exec_request(step, _Contextish(spec, Path(session.out_dir)))
    started = time.time()
    result = _exec.run(req, root=root, on_chunk=on_chunk)
    spent = time.time() - started
    row = result.to_dict()
    row["session"] = session.id
    session.events.append({"kind": "exec", "at": round(time.time(), 3),
                           "detail": f"{label}: exit {result.exit_code}",
                           "label": label, "ok": result.ok,
                           "seconds": round(spent, 3)})
    session.sync_run_seconds(spent)
    return row


class _Contextish:
    """The sliver of ``Context`` that ``assembler._exec_request`` actually reads.

    That translator touches ``spec`` and nothing else today; it takes a ``Context``
    because everything in ``assembler`` does. Rather than start a whole second
    pipeline to run one command, this stands in — and being one attribute wide, it
    is also the honest documentation of how little the translator needs.
    """

    __slots__ = ("spec", "out_dir")

    def __init__(self, spec, out_dir: Path) -> None:
        self.spec = spec
        self.out_dir = out_dir


def environment_exec(session: Session, spec, label: str, *, on_chunk=None) -> dict:
    """Run a ``backend: docker`` step inside the session's own container.

    The build reaches the container through the module-level
    ``exec._ENV_FOR_RUN``/``_CONTAINER_FOR_RUN`` maps, which ``environment_up``
    populates and ``environment_down`` clears — so a session that brought an
    environment up and then ran a step is using exactly the path the pipeline
    uses. The refusal when nothing is up is deliberate: silently starting a
    container would hide which lifecycle the video was filmed against.
    """
    from . import exec as _exec

    step = spec.exec_step(label)
    if step is None:
        raise SpecError(f"the spec declares no exec step {label!r}")
    env_name = getattr(step, "environment", "") or ""
    if not env_name:
        raise ToolError(
            f"step {label!r} does not run in an environment, so there is nothing to "
            "start — call session_exec for it")
    ref = next((e for e in live_refs(session) if e.name == env_name), None)
    if ref is None or not ref.container_id:
        raise ToolError(
            f"step {label!r} runs in environment {env_name!r}, which is not up for "
            "this session — call env_up first (env_status lists what is running)")
    _exec.bind_step(label, ref.to_state(env_spec(spec, env_name)))
    return run_step(session, spec, label, on_chunk=on_chunk)


# --------------------------------------------------------------------------- #
# driving a browser, outside a build
# --------------------------------------------------------------------------- #
def _vp(session: Session, spec, viewport: list[int] | tuple[int, int] | None):
    if viewport and len(viewport) == 2:
        return int(viewport[0]), int(viewport[1])
    return tuple(spec.project.size)


def browser_open(session: Session, spec, url: str = "", *,
                 viewport=None, storage_state: str = ""):
    """Start a browser this session owns, and hand back the live objects.

    A long-lived page is the difference between "the tool photographed a URL" and
    "an agent drove an application". The same deterministic init script, locale,
    timezone and reduced-motion settings the capture stage uses are applied here,
    so a picture taken through this door is the same picture the build would film
    — a second, laxer path would make the video's frames unreproducible by the
    only code that is supposed to be able to reproduce them.
    """
    from playwright.sync_api import sync_playwright

    if not _capture._playwright_available():
        raise ToolError(
            "playwright is not installed, so no browser can be driven — "
            "`pip install playwright` and `playwright install chromium`")
    if session._live.get("browser") is not None:
        where = session._live.get("url")
        at = f" at {where!r}" if where else ""
        raise ToolError(
            f"this session already has a browser open{at}; "
            "call browser_close first — one session, one page")
    why = session.budgets.check()
    if why:
        raise ToolError(why)

    p = sync_playwright().start()
    context = None
    try:
        chrome = _capture._find_chrome()
        browser = p.chromium.launch(headless=True, executable_path=chrome,
                                    args=["--no-sandbox", "--hide-scrollbars"])
        ctx_kwargs = {}
        if storage_state:
            ctx_kwargs["storage_state"] = str(Path(session.root) / storage_state)
        w, h = _vp(session, spec, viewport)
        context = browser.new_context(
            viewport={"width": w, "height": h},
            device_scale_factor=2.0,
            locale=_capture.FROZEN_LOCALE,
            timezone_id=_capture.FROZEN_TZ,
            reduced_motion="reduce",
            color_scheme="light",
            **ctx_kwargs,
        )
        page = context.new_page()
        page.add_init_script(_capture.freeze_script())
        if url:
            page.goto(url, wait_until="networkidle", timeout=60000)
    except Exception:
        if context is not None:
            with contextlib.suppress(Exception):
                context.close()
        with contextlib.suppress(Exception):
            p.stop()
        raise
    session._live.update({"pw": p, "browser": browser, "context": context,
                          "page": page, "url": url})
    session.event("browser", f"open {url or '(blank)'}")
    return browser, context, page


def browser_close(session: Session) -> dict:
    """Shut the session's browser down, and say what was on screen when it went."""
    if session._live.get("browser") is None:
        return {"ok": True, "closed": False, "note": "no browser was open"}
    url = session._live.get("url", "")
    for key in ("page", "context", "browser"):
        with contextlib.suppress(Exception):
            obj = session._live.get(key)
            if obj is not None:
                obj.close()
        session._live[key] = None
    with contextlib.suppress(Exception):
        session._live["pw"].stop()
    session._live["pw"] = None
    session._live["url"] = ""
    session.event("browser", f"close {url or '(blank)'}")
    return {"ok": True, "closed": True, "was": url}


def browser_act(session: Session, actions: list[dict], *, spec=None) -> dict:
    """Drive the open page: the capture DSL, one step at a time.

    Returns *what the page said* after each step, not just that it worked. An
    agent that clicks a button needs to read the result of the click, and a tool
    that returns only ``ok: true`` makes it guess. Text is read from the selector
    an action named when there is one, and the page title otherwise.
    """
    from .spec import Action, _action  # the loader's own translator

    if session._live.get("page") is None:
        raise ToolError(
            "no browser is open for this session — call browser_open first")
    page = session._live["page"]
    steps: list[dict] = []
    for i, raw in enumerate(actions):
        action = raw if isinstance(raw, Action) else _action(raw, f"action {i + 1}")
        row: dict = {"index": i, "kind": action.kind}
        try:
            if action.kind == "wait_for":
                _capture.wait_for(page, action)
            elif action.kind == "download":
                from pathlib import Path as _P
                art = _capture.download(
                    page, action,
                    artifacts_dir=_P(session.out_dir) / "_capture" / "artifacts")
                row["artifact"] = art.name if hasattr(art, "name") else str(art)
            else:
                _capture.apply(page, action)
            row["ok"] = True
        except ToolError as exc:
            row["ok"] = False
            row["error"] = str(exc)
            steps.append(row)
            session.event("browser", f"action {i}: {exc}")
            return {"ok": False, "steps": steps, "stopped_at": i,
                    "note": "the action that failed is the last one listed"}
        sel = action.selector
        if sel:
            with contextlib.suppress(Exception):
                row["text"] = (page.inner_text(sel) or "")[:400]
        if not row.get("text"):
            with contextlib.suppress(Exception):
                row["title"] = page.title()
        steps.append(row)
    session.event("browser", f"{len(steps)} action(s)")
    return {"ok": True, "steps": steps}


def _screenshot_with_retry(page, dest: Path, *, full_page: bool,
                           attempts: int = 3, pause: float = 0.5) -> None:
    """Photograph ``page`` to ``dest``, retrying a transient compositor failure.

    Chromium can intermittently fail a screenshot with ``Unable to capture
    screenshot`` while its font loader is handing off to the compositor — the
    page has loaded and the fonts are loaded, but the frame is not yet
    compositable. A single attempt turns that into a hard failure for a shot
    whose *content* is fine. Re-attempting captures the same real page, so it is
    a retry of the measurement, not a restaging; the last attempt's error is
    raised if it never succeeds.
    """
    last: Exception | None = None
    for _ in range(attempts):
        try:
            page.screenshot(path=str(dest), full_page=full_page)
            return
        except Exception as exc:  # pragma: no cover - only under the transient race
            last = exc
            time.sleep(pause)
    raise last  # type: ignore[misc]


def browser_shot(session: Session, name: str, *, take: int = 1,
                 full_page: bool = False, note: str = "") -> dict:
    """Photograph the open page into ``_capture/`` — and record what was shot.

    Deliberately writes through the capture stage's own naming rule
    (:func:`vidkit.capture.take_name`) so a screenshot taken here is
    indistinguishable from one the pipeline would have taken, and a take selected
    here is a take the build can use.
    """
    if session._live.get("page") is None:
        raise ToolError("no browser is open for this session — call browser_open first")
    out_dir = Path(session.out_dir)
    dest = take_path(out_dir, name, take)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _screenshot_with_retry(session._live["page"], dest, full_page=full_page)
    row = record_take(session, name, take, note=note or "session_browser_shot")
    # Deliberately *not* promoted. `capture_one` promotes because a spec's `take:`
    # is a declared intent; ad-hoc shooting has no such declaration, and the whole
    # reason to shoot three takes is to then choose between them. Promoting here
    # would mean the last shot silently became the film's frame — the "which take
    # is in the video?" question answered by an accident of ordering.
    return {**row.to_dict(), "selected": f"{name}/{take}" in set(session.selections),
            "promoted": False,
            "note": f"{row.note} — call session_take_select to film from this take"}


# --------------------------------------------------------------------------- #
# a session's whole state, in one call
# --------------------------------------------------------------------------- #
def status(session: Session) -> dict:
    """Everything a caller needs to decide what to do next, in one answer.

    A session is long-lived and a client may come back to it after a compaction,
    a restart, or an hour of doing something else. So the status is *complete*
    rather than cheap: the record, the takes that exist, the environments that
    were started, what is on disk, and the next step if one is obvious. A caller
    that has to make three calls to find out where it is will eventually make two
    and guess.
    """
    session.sync_budget(containers=len(live_refs(session)))
    takes = _scan_takes(session)
    picked = set(session.selections)
    out_dir = Path(session.out_dir)
    artifacts = {
        "output": next((str(p) for p in sorted(out_dir.glob("*.mp4"))), None),
        "srt": next((str(p) for p in sorted(out_dir.glob("*.srt"))), None),
        "verify": str(report_path(session)) if report_path(session).is_file() else None,
    }
    holds = len(live_refs(session))
    return {
        **session.to_dict(),
        # Two directories, named separately, because they are two different pieces of
        # knowledge: `out_dir` is where the *files* go, `record_dir` is where this
        # session's own record was written. A client that kept only the session id
        # needs the second to find it again.
        "record_dir": str(_registry_root(session)),
        "takes_existing": len(takes),
        "unrecorded_takes": [f"{t.capture}/{t.take}" for t in takes
                             if (t.capture, t.take) not in
                             {(r.capture, r.take) for r in session.takes}],
        "environments_live": holds,
        "artifacts": artifacts,
        "next": _next_step(session, takes, picked, artifacts),
    }


def _registry_root(session: Session) -> Path:
    """Where a session's record was found.

    ``Session`` carries its record's directory in ``_record_dir`` when it was loaded
    through a :class:`Registry`; a session built in memory has only its output
    directory to point at.
    """
    return Path(getattr(session, "_record_dir", None) or session.out_dir)


def _next_step(session: Session, takes, picked: set, artifacts: dict) -> str:
    """The one thing a caller most likely wants to do, said plainly.

    Advisory, and phrased as advice. It is derived only from what is in the
    record and on disk — never from a guess about what the caller meant.
    """
    if not session.open:
        return "this session is closed; open a new one to carry on"
    if live_refs(session) and not artifacts["output"]:
        return "an environment is up — run session_exec, or env_down when done"
    if takes and not picked:
        return ("takes exist but none is selected — session_take_select to choose the "
                "one the film should use")
    if artifacts["output"] and artifacts["verify"]:
        return "a render and a report exist — read the report before believing the video"
    if artifacts["output"]:
        return "a render exists but has not been verified"
    return "nothing rendered yet — run the build with vidkit_run"


# --------------------------------------------------------------------------- #
# the session, doing the pipeline's work one stage at a time
# --------------------------------------------------------------------------- #
# Everything below assumes the *same* live Python objects. A `Context` holds the
# secrets, the provider module and the paths; a `Page` cannot be written to JSON;
# a browser that a caller started must be driven later, by another call. So they
# live on the session in this process (``Session._live``), and every function here
# says out loud when they are missing instead of silently starting a second copy.
# --------------------------------------------------------------------------- #
def session_context(session: Session):
    """The live :class:`~vidkit.context.Context` for this session, or a refusal.

    Built once per session and kept. Rebuilding it would re-read the spec and
    re-announce the story on every call, and — worse — would give the pipeline a
    *different* object graph from the one the session's own browser belongs to,
    which is how two halves of one sitting start disagreeing about the spec.
    """
    from .assembler import make_context

    live = session._live.get("ctx")
    if live is not None:
        return live
    if not session.spec:
        raise SpecError(
            "this session was opened without a spec, so there is nothing to plan or "
            "build — open one with a spec to carry a story through")
    ctx = make_context(session.spec, out_dir=Path(session.out_dir))
    # The sitting's promotions travel *into* the pipeline. Without this the render
    # stage would re-shoot every capture and overwrite the take the client chose,
    # and the film would contain a moment nobody picked while the record named one
    # they did. Selections live in the durable record, so they survive a restart
    # exactly as the takes themselves do.
    ctx.selections = set(session.selections)
    session._live["ctx"] = ctx
    return ctx


def session_assets(session: Session):
    """The live :class:`~vidkit.assembler.Assets` for this session.

    ``Assets`` is where measured facts accumulate across stages: captures, stills,
    panels, scene audio, the environments that were brought up. Created once and
    carried forward, so ``session_capture`` → ``session_build`` is one sitting's
    work rather than two unrelated ones.
    """
    from .assembler import Assets

    live = session._live.get("assets")
    if live is not None:
        return live
    ctx = session_context(session)
    assets = Assets()
    # `ctx` is the *last* field of `Assets`, not the first, so it must be named —
    # `Assets(ctx)` silently made `stills` hold a Context and the first stage that
    # touched a still died with "'Context' object has no attribute 'update'".
    assets.ctx = ctx
    session._live["assets"] = assets
    return assets


def capture_run(session: Session, names: list[str] | None = None) -> dict:
    """Run the spec's captures, recording each take as it lands.

    ``names`` narrows the run to particular captures; with none, all of them run,
    exactly as the pipeline's own capture stage would. The per-capture results —
    and the *refusals* — come back whole, because a capture whose assertion failed
    is the most interesting line in the answer.
    """
    from . import capture as _cap

    ctx = session_context(session)
    wanted = [c for c in ctx.spec.captures if not names or c.name in names]
    if not wanted:
        declared = ", ".join(c.name for c in ctx.spec.captures) or "none"
        raise SpecError(
            f"the spec declares no capture among {names!r} (declared: {declared})")
    if not _cap._playwright_available():
        raise ToolError(
            "playwright is not installed, so nothing can be captured — "
            "`pip install playwright` then `playwright install chromium`")
    chrome = _cap._find_chrome()
    rows, failures = [], 0
    for cap in wanted:
        why = session.budgets.check()
        if why:
            raise ToolError(why)
        try:
            res = _cap.capture_one(ctx, cap, chrome)
        except (ToolError, SpecError) as exc:
            # A refusal is data. The build aborts on one (I2); a session reports it
            # and lets the caller decide, which is the whole difference between an
            # agent driving and a pipeline running.
            failures += 1
            rows.append({"capture": cap.name, "take": cap.take, "ok": False,
                         "refused": str(exc)})
            session.event("capture", f"{cap.name}: refused", ok=False)
            continue
        row = res.to_dict() if hasattr(res, "to_dict") else dict(res.__dict__)
        row["ok"] = bool(getattr(res, "ok", True))
        row["take"] = cap.take
        rows.append(row)
        session.event("capture", f"{cap.name} take {cap.take}", ok=row["ok"])
        try:
            record_take(session, cap.name, cap.take, note=f"capture {cap.url}")
        except (ToolError, SpecError):
            pass          # an artifact-only capture writes no PNG; not an error
    return {"session": session.id, "captures": rows, "ran": len(rows),
            "refused": failures}


def build(session: Session, *, only: list[str] | None = None,
          from_stage: str | None = None) -> dict:
    """Run the pipeline inside this session, and keep everything it measured.

    Deliberately the *same* ``run`` the CLI and the job contract call. A second
    assembly path would be a second thing to keep honest, and the verification
    story (I7) only holds if there is exactly one code path that turns a spec into
    a film.
    """
    from .assembler import run

    ctx = session_context(session)
    assets = session_assets(session)
    started = time.time()
    try:
        # The spec *path*, not the context, because `run` is the CLI's entry
        # point and owns the one wiring of Context/Assets there is; the
        # session's live pair is handed in so this is the same sitting's graph.
        run(session.spec, only=only, from_stage=from_stage,
            ctx=ctx, assets=assets)
    finally:
        session.sync_run_seconds(time.time() - started)
    report = assets.report.to_dict() if getattr(assets, "report", None) else None
    ok = bool(report and report.get("ok"))
    session.event("build", "pipeline", ok=ok,
                  seconds=round(time.time() - started, 3))
    save(session)
    return {
        "session": session.id,
        "output": str(assets.output) if assets.output else None,
        "srt": str(assets.srt) if assets.srt else None,
        "report": report,
        # `ok` is read off the report the pipeline itself returned, never
        # recomputed here: a build that rendered is not the same as a build that
        # passed, and only `verify` gets to say which one happened.
        "ok": ok,
        "seconds": round(time.time() - started, 3),
    }


def report_path(session: Session) -> Path:
    """Where this session's ``verify.json`` is, whichever build wrote it.

    The path is a *fact about the pipeline*, not a preference of this module:
    ``assembler.run`` writes the report into ``ctx.build`` (``<out>/_build``) beside
    the tracks it describes, not into the output directory beside the film. Both
    candidates are checked rather than assumed, because the output directory is
    where a reader looks first and a build by an older version may have left one
    there.
    """
    out = Path(session.out_dir)
    for candidate in (out / "_build" / "verify.json", out / "verify.json"):
        if candidate.is_file():
            return candidate
    return out / "_build" / "verify.json"


def read_report(session: Session) -> dict:
    """The report for this session's render — read from the report file itself.

    Read from ``verify.json`` rather than from the in-memory ``Assets``, because
    the file is what a reviewer will open, and a tool that answered from memory
    could disagree with the artifact beside it.
    """
    path = report_path(session)
    if not path.is_file():
        raise ToolError(
            f"there is no report at {path} — run the build (vidkit_run or "
            "session_build), which writes one, before asking what it proved")
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ToolError(f"the report at {path} could not be read: {exc}") from exc
    checks = report.get("checks") or []
    failed = [c for c in checks if not c.get("ok", True)]
    return {"session": session.id, "path": str(path), "ok": report.get("ok"),
            "checks": len(checks), "failed": failed, "report": report}


def close_session(session: Session, reason: str = "") -> dict:
    """End a sitting: stop its browser, take its containers down, write the record.

    Ordered browser → containers → record, and every step attempted even if an
    earlier one failed. A session that cannot shut down cleanly is the one most
    likely to leave a database running, so the teardown is exactly where a
    `try`/`finally` belongs rather than a happy path.
    """
    problems: list[str] = []
    try:
        browser_close(session)
    except Exception as exc:                       # noqa: BLE001 - reported, not raised
        problems.append(f"browser: {exc}")
    try:
        for ref in stop_environment(session):
            if not ref.teardown.get("removed"):
                problems.append(
                    f"environment {ref.name!r} was not removed ({ref.teardown})")
    except Exception as exc:                       # noqa: BLE001
        problems.append(f"environments: {exc}")
    session.close(reason)
    session.sync_budget()
    session.event("close", " ".join(problems) if problems else reason)
    try:
        save(session)
    finally:
        # Even if the record could not be written, this process is no longer holding
        # a sitting. A registry that still lists a shut-down session is a lie, and it
        # is the lie a client retries against.
        forget(session)
    # Last, and after every call that might have used it: the worker owns the page,
    # and a page cannot be closed from a thread that does not own it.
    if session.worker is not None:
        session.worker.stop()
        session.worker = None
    return {"session": session.id, "closed": True, "elapsed": round(session.elapsed(), 3),
            "problems": problems,
            "note": ("a build may leave a container behind; `problems` says whether "
                     "this one did")}


# --------------------------------------------------------------------------- #
# the live sessions, for as long as the process lives
# --------------------------------------------------------------------------- #
#: Sessions this process is holding live objects for — a page, a container, a
#: `Context`. Module-level and deliberate: a sitting is a *running thing*, not a
#: record, and the tools are reached one call at a time with nothing but an id to
#: identify it by. Reading it back from disk on every call would rebuild the record
#: and lose the browser, which is exactly the bug this table exists to fix.
_LIVE: dict[str, Session] = {}


def _live_key(session_id: str, out_dir: Path | str | None) -> str:
    """A session id means different things in different projects."""
    return f"{Path(out_dir or '').expanduser().resolve()}::{session_id}"


def hold(session: Session) -> Session:
    """Adopt a session into this process, giving it a browser thread."""
    if session.worker is None:
        session.worker = _loop.Worker(name=f"vidkit-{session.id}")
    _LIVE[_live_key(session.id, session.out_dir)] = session
    return session


def held(session_id: str, out_dir: Path | str | None = None) -> Session | None:
    """The live session with this id, if this process is the one that opened it.

    With an output directory the answer is exact. Without one, an id that names
    exactly one held session is unambiguous — that is the common case for a client
    that stored the id and nothing else. An id held in *two* projects is not
    decidable here and this returns ``None`` rather than guessing: the caller falls
    back to the record on disk, which is the only thing it asked for, and the tool
    says which project it needs.
    """
    if out_dir:
        return _LIVE.get(_live_key(session_id, out_dir))
    matches = [s for s in _LIVE.values() if s.id == session_id]
    return matches[0] if len(matches) == 1 else None


def forget(session: Session) -> None:
    """Drop a session from this process. Idempotent, and safe for a stranger."""
    _LIVE.pop(_live_key(session.id, session.out_dir), None)


def live_sessions() -> list[Session]:
    """Every session this process is holding, for a status line or a teardown."""
    return list(_LIVE.values())


def live_ids() -> list[str]:
    """The ids of the held sessions — what a client sees, not the internal key."""
    return [s.id for s in _LIVE.values()]


# --------------------------------------------------------------------------- #
# the registry, as the tools see it
# --------------------------------------------------------------------------- #
def default_out_dir(spec_path: Path | str | None) -> Path:
    """Where a session's state lives: beside the spec, like the render itself."""
    if spec_path:
        return Path(spec_path).expanduser().resolve().parent
    return Path.cwd()


def save(session: Session) -> Path:
    """Persist a session. Called after every mutation, from one place."""
    session.sync_budget(containers=len(live_refs(session)))
    return Registry(session.out_dir).save(session)


def list_sessions(out_dir: Path | str, *, include_closed: bool = True) -> dict:
    """Every session in a project, newest last, with enough to choose between them."""
    reg = Registry(out_dir)
    rows = []
    for s in reg.all(include_closed=include_closed):
        rows.append({
            "id": s.id, "open": s.open, "story": s.story or s.title,
            "spec": s.spec, "opened": s.opened, "closed": s.closed,
            "elapsed": round(s.elapsed(), 3), "takes": len(s.takes),
            "environments": len(live_refs(s)), "selections": len(s.selections),
        })
    return {"out_dir": str(Path(out_dir).resolve()),
            "state_dir": str(Path(out_dir).resolve() / STATE_DIR),
            "sessions_dir": str(reg.dir),
            "sessions": rows, "count": len(rows)}


def with_spec(session: Session, spec=None):
    """The spec the session was opened against, or the one handed in.

    A tool that takes an optional ``spec`` means "act on this project instead", and
    that is a different session from the one on disk — so the session's own path
    wins unless there is not one. Said here, once, rather than in five tools.
    """
    if session.spec:
        return load_spec(session)
    if spec is None:
        raise SpecError(
            "this session has no spec and none was given, so there is nothing to "
            "act on")
    return spec
