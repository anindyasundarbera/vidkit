# PLAN.md — what we are doing right now

> **This file describes only *now* and *next*.** It is rewritten as work progresses.
> For the phase-wise plan see [FEATURE-ROADMAP.md](FEATURE-ROADMAP.md). For what already
> happened see [HISTORY.md](HISTORY.md). For why, see [DECISIONS.md](DECISIONS.md).
>
> Last updated: **2026-10-07** (M7 merged; M8 next).

---

## Where we are

One branch, one PR, one merge per phase. **M0–M7 are merged to `main`, which is `40cf724`.
Nothing is in flight.**

| Phase | What it made true | Landed |
|---|---|---|
| **M0** Extract & baseline | A fresh clone installs, tests, and builds `hello-world` with only `ffmpeg` + `rsvg-convert`; no host terms in the engine. | `bbd1e40` |
| **M1** Story & timeframe | vidkit can be *aimed*: a story identity and a resolved window of time, independently checked by `verify`. | `aa3eb5d` |
| **M2** Provider & data hardening | An offline re-render from persisted snapshots is the default, not an option. | `21a96d4` |
| **M3** Capture v2 | Assert-before-shot, action DSL, takes. | `a824e09` |
| **M4** Presentation v2 | 11 panel kinds, overlays, transitions, still fitting. | `4ffff5c` |
| **M5** Agent surface | The job contract: `--json`, `--progress`, `run ACTION`, four MCP tools, a timeout guard. | `7c548de` |
| **M6** Hardening & v1.0 | Provenance as a first-class action; portability; `1.0.0`. | `6987090` |
| **M7** Executor & sandbox | A spec can declare commands that run in a real PTY inside a declared sandbox, and the film is proven to contain the recording. | `40cf724` |

Full evidence for each is in [HISTORY.md](HISTORY.md); each phase's reasoning is in
[DECISIONS.md](DECISIONS.md) (D1–D41).

### M7 in one paragraph

`vidkit/exec.py` and `vidkit/terminal.py` (26 modules), a tenth pipeline stage `exec`
between `capture` and `narration`, three new `verify` checks, four new guards, a fourth CI
job, and a permanent example `examples/terminal-demo/`. **467 tests pass** on a full
toolchain and **428 pass / 39 skip** on a lean one. Its first CI run failed three of five
jobs, and the fix produced **D41**, which is the most reusable thing the phase left behind:

> **When a capability gate decides whether an honest build is possible, it must
> demonstrate the capability, not observe a precondition of it.**

`shutil.which("bwrap")` observes a precondition. Running one confined command demonstrates
the capability. That is why availability is now a ~14 ms probe, and why `doctor` tells a
Ubuntu 24.04 user the truth *before* a build instead of letting them meet a
`Permission denied` afterwards.

---

## The one thing that still needs the owner

> **Push the `v1.0.0` tag.**

The version is `1.0.0` in all three places (`pyproject.toml`, `vidkit/__init__.py`,
`CHANGELOG.md`). Pushing a tag is the point at which the release becomes a claim to the
world rather than a commit on a branch, and it is the owner's to make. Nothing downstream is
blocked by waiting: M8 and M9 read the *code*, not the tag.

A second owner call sits behind it: **the M7 work is in `CHANGELOG.md` under
`## [Unreleased]`.** If the owner would rather cut `1.1.0`, that is a one-line change;
folding it back into `1.0.0` would mean the tag and the release notes disagree, which is the
one thing a CHANGELOG exists to prevent.

PyPI publication stays **deferred** ([FEATURE-ROADMAP.md](FEATURE-ROADMAP.md) §9) — tagging
and publishing are different visible acts and only the first was asked for.

---

## Next: M8 — Docker & environment lab  *(P1)*

Branch **`phase/m8-docker-lab`** off `40cf724`. See
[FEATURE-ROADMAP.md](FEATURE-ROADMAP.md) §11. **Purpose:** film a real environment — a
service starting, a dependency installing, a container's logs — not a description of one.

### The shape, before any code

M7 built the trust boundary; M8 spends it. Everything here is a *demonstrated capability*
(D41), and everything is a *declaration* added to the spec language, never a flag added to
the runner (D33). Concretely:

1. **A `docker` backend for `exec`.** It slots in beside `bwrap` and `local` behind the same
   `ExecRequest`/`ExecResult` pair, so the pipeline, the frame renderer, and the three exec
   checks do not change at all. If they do change, the M7 abstraction was wrong and that is
   the finding — not something to work around.
2. **A probed Docker capability** — `docker run --rm hello-world`, never `which docker`.
   This is D41 applied to a daemon. `doctor` and `backends_report()` must say which Docker
   is present and whether it *answers* before a build starts.
3. **An environment lifecycle in the spec** — bring up, run, always tear down. Teardown must
   be unconditional: it runs on success, on a failed check, on an interrupt, and after a
   crash in a stage that never started a container. A leaked container is a host-side bug in
   a tool that otherwise only writes files. The teardown path needs tests that
   *deliberately* crash a stage mid-lifecycle.
4. **Container logs and service health as panel data**, so "the service came up" is
   *measured* rather than narrated — the same move M7 made for terminal frames.
5. **Real versions into provenance** — image **digests**, not image tags. A tag is a name
   that can move; a film that cites one cannot be re-explained next month.

### The risks, named now

- **This is the first phase where a bug can affect the host rather than the output.** The
  mitigations are not negotiable and are listed in §11: never mount the Docker socket into
  the sandbox, run unprivileged, hard timeout, forced teardown on every exit path.
- **Docker is not bubblewrap.** `bwrap` is a syscall that either works or does not. Docker is
  a daemon with its own state, its own failure modes, and a startup cost, so "available" has
  at least three distinct meanings — client installed, daemon reachable, image present.
  Collapsing them into one boolean is how this phase goes wrong.
- **The probe is expensive.** Unlike `bwrap`'s measured ~14 ms, a `docker run` costs seconds.
  It cannot sit on the `doctor` happy path unmemoised: decide the caching policy
  deliberately and write the reason down.
- **CI.** GitHub's runners have Docker, so the probe is possible — but it is the slowest job
  yet, and the lean-`PATH` suite must keep skipping every test that needs it. A third marker
  is likely required and must be applied **independently** of the other two (defect G).
- **The runner image is moving.** GitHub announced `ubuntu-latest` migrates to Ubuntu 26
  beginning **2026-10-19**. Every runner fact M7 recorded is a statement about Ubuntu 24.04;
  do not assume the Docker story survives the move.

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
