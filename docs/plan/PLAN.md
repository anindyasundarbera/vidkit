# PLAN.md — what we are doing right now

> **This file describes only *now* and *next*.** It is rewritten as work progresses.
> For the phase-wise plan see [FEATURE-ROADMAP.md](FEATURE-ROADMAP.md). For what already
> happened see [HISTORY.md](HISTORY.md). For why, see [DECISIONS.md](DECISIONS.md).
>
> Last updated: **2026-10-08** (M7 complete; M8 next).

---

## Where we are

One branch, one PR, one merge per phase. **M0–M6 are on `main`; M7 is on
`phase/m7-executor-sandbox`.**

| Phase | What it made true | Landed |
|---|---|---|
| **M0** Extract & baseline | A fresh clone installs, tests, and builds `hello-world` with only `ffmpeg` + `rsvg-convert`; no host terms in the engine. | `bbd1e40` |
| **M1** Story & timeframe | vidkit can be *aimed*: a story identity and a resolved window of time, independently checked by `verify`. | `aa3eb5d` |
| **M2** Provider & data hardening | An offline re-render from persisted snapshots is the default, not an option. | `21a96d4` |
| **M3** Capture v2 | Assert-before-shot, action DSL, takes. | `a824e09` |
| **M4** Presentation v2 | 11 panel kinds, overlays, transitions, still fitting. | `4ffff5c` |
| **M5** Agent surface | The job contract: `--json`, `--progress`, `run ACTION`, four MCP tools, a timeout guard. | `7c548de` |
| **M6** Hardening & v1.0 | Provenance as a first-class action; portability; `1.0.0`. | `6987090` |
| **M7** Executor & sandbox | A spec can declare commands that run in a real PTY inside a declared sandbox, and the film is proven to contain the recording. | branch |

Full evidence for each is in [HISTORY.md](HISTORY.md); each phase's reasoning is in
[DECISIONS.md](DECISIONS.md) (D1–D40).

### M7 in one paragraph

`vidkit/exec.py` and `vidkit/terminal.py` (26 modules), a tenth pipeline stage `exec`
between `capture` and `narration`, three new `verify` checks, four new guards, a fourth CI
job, and a permanent example `examples/terminal-demo/`. **460 tests pass** on a full
toolchain and **425 pass / 35 skip** on a lean one. Six defects were found during the phase
— three of them only by rendering and then matching the finished film's pixels back to the
recorded frames (MAE 1.7–3.3). The three that the unit tests could not have caught are the
reason M7 ends with a *watching* step, not a *reading* step.

---

## The one thing that still needs the owner

> **Push the `v1.0.0` tag.**

The version is `1.0.0` in all three places (`pyproject.toml`, `vidkit/__init__.py`,
`CHANGELOG.md`). Pushing a tag is the point at which the release becomes a claim to the
world rather than a commit on a branch, and it is the owner's to make. Nothing downstream is
blocked by waiting: M7 and M8 read the *code*, not the tag.

A second owner call is queued behind M7's merge: **the M7 work currently sits in
`CHANGELOG.md` under `## [Unreleased]`.** If the owner would rather cut `1.1.0` at merge
time, that is a one-line change; folding it back into `1.0.0` would mean the tag and the
release notes disagree, which is the one thing the CHANGELOG exists to prevent.

PyPI publication stays **deferred** ([FEATURE-ROADMAP.md](FEATURE-ROADMAP.md) §9) — tagging
and publishing are different visible acts and only the first was asked for.

---

## Next: M8 — Docker & environment lab  *(P1)*

See [FEATURE-ROADMAP.md](FEATURE-ROADMAP.md) §11. **Purpose:** film a real environment — a
service starting, a dependency installing, a container's logs — not a description of one.

### The shape, before any code

M7 built the trust boundary; M8 spends it. Everything here is a *declaration* added to the
spec language, never a flag added to the runner (D33). Concretely:

1. **A `docker` backend for `exec`.** It slots in beside `bwrap` and `local` behind the same
   `ExecRequest`/`ExecResult` pair, so the pipeline, the frame renderer, and the three exec
   checks do not change at all. If they do change, the M7 abstraction was wrong and that is
   the finding — not something to work around.
2. **An environment lifecycle in the spec** — bring up, run, always tear down. Teardown must
   be unconditional: it runs on success, on a failed check, on an interrupt, and after a
   crash in a stage that never started a container. A leaked container is a host-side bug in
   a tool that otherwise only writes files.
3. **Container logs and service health as panel data**, so "the service came up" is
   *measured* rather than narrated.
4. **Real versions into provenance** — image digests, not image tags. A tag is a name that
   can move; a film that cites one cannot be re-explained next month.

### The risks, named now

- **This is the first phase where a bug can affect the host rather than the output.** The
  mitigations are not negotiable and are listed in §11: never mount the Docker socket into
  the sandbox, run unprivileged, hard timeout, forced teardown on every exit path.
- **`docker` is not `bwrap`.** `bwrap` is a syscall; Docker is a daemon with its own state,
  its own failure modes, and a startup cost. `backends_report()` and `doctor` must say which
  Docker is present and whether the daemon answers *before* a build starts, for the same
  reason `check_policy()` does.
- **CI.** GitHub's runners have Docker, so the probe is possible — but it is the slowest job
  yet, and the lean-`PATH` suite must keep skipping every test that needs it.

### Exit

> A spec can bring up a declared environment, film real activity inside it, tear it down
> unconditionally, and prove the environment's identity in `verify.json`.

---

## After M8

**M9 — Movie mode** (§12): richer still kinds, audio beds with ducking, multi-track audio,
shot timing, narrative shape. Constraint **P5**: it reuses the same stages — *at most* the
ten that exist after M7. If it needs an eleventh, the design is wrong and gets rethought
before it is built.

**M10 — Studio surface v2** (§13): stateless verbs become a session an agent can hold open
and try several takes against.

One branch, one PR, one merge each — as M0–M7 were done.
