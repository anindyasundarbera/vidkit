# PLAN.md — what we are doing right now

> **This file describes only *now* and *next*.** It is rewritten as work progresses.
> For the phase-wise plan see [FEATURE-ROADMAP.md](FEATURE-ROADMAP.md). For what already
> happened see [HISTORY.md](HISTORY.md). For why, see [DECISIONS.md](DECISIONS.md).
>
> Last updated: **2026-10-06**.

---

## M0 — Extract & baseline — **COMPLETE**

Exit criterion ([FEATURE-ROADMAP.md](FEATURE-ROADMAP.md) §3):

> A fresh clone → `pip install -e ".[dev]"` → `pytest` green →
> `vidkit build examples/hello-world/video.yaml` succeeds with **only** `ffmpeg` +
> `rsvg-convert`; `grep` shows no host terms.

**Met on a clean runner, not just locally.** Published to
<https://github.com/anindyasundarbera/vidkit> (public), commits `87b7435` + `bbd1e40`. Full
record in [HISTORY.md](HISTORY.md).

---

## M1 — Story & timeframe contract — **COMPLETE**

Exit criterion ([FEATURE-ROADMAP.md](FEATURE-ROADMAP.md) §4):

> Two builds of one story with different timeframes produce different, correctly labelled
> videos. A story whose narration window disagrees with its spec **fails `verify`**.

**Met, and both halves are now CI steps rather than claims.** `vidkit` can be *aimed*: it has
a story identity and a resolved window of time, and `verify` independently checks the video
against that window.

### Verified evidence

| Claim | How it was checked | Result |
|---|---|---|
| Two windows → two correctly-labelled videos | build, then re-build with `--timeframe 2026-08-01..2026-09-30` | banner + `plan` print the new window; both videos build |
| A disagreeing narration fails `verify` | edited one date in `narration.md`, re-ran `verify` | exit **2**, single failure `timeframe consistent with spec` |
| Restoring it passes again | re-ran `verify` | `ALL PASS` |
| The check is *true*, not merely green | read the pass line | `[PASS] timeframe consistent with spec — matches 2026-09-07 to 2026-10-06 (30 days)` |
| `vidkit init` is not a lie | scaffolded into `_scaffold/`, built it | exit **0**; `[PASS] runtime within window — 14.00s within [8, 30]` |
| Suite is green and still cheap | `python3 -m pytest tests -q` | **84 passed in 1.51 s** (P6 holds) |
| CI asserts all three | rendered and executed the new `run:` blocks | pass locally; green on the remote |

Branch `phase/m1-story-timeframe` → PR → merged to `main` (one PR per phase, for
traceability). Design consequences recorded as D17–D19.

---

## Current phase: M2 — Provider & data hardening  *(P1)*

**Purpose.** Make what a provider *says* good enough to hand to an agent. M1 made the request
aimable; M2 makes the answer trustworthy, and makes a build resumable without a network.

**Requirements.** R-B3 (dataset snapshots), R-B4 (secret contract), R-B5 (deterministic
fallback). R-B1 (plugin loading) and R-B2 (timeframe threading) are already done — R-B2 landed
in M1.

**Exit criterion.**

> `vidkit build --only panels,clips,render` works from persisted data, **offline**.

### Ordered work

1. **Snapshot guarantee (R-B3).** Datasets are already written to `data/*.json`; the work is to
   make that a *guarantee* rather than a side effect — record enough alongside each snapshot
   (dataset name, provider, resolved timeframe, a content hash) that a resumed build can prove
   it is re-rendering from the data that matches the current spec, and **refuse** a stale
   snapshot instead of silently mixing windows.
2. **`--only` and `--from` actually honour it.** Confirm the stage list is validated
   (`STAGES` order), that a skipped stage's outputs are *checked for existence* rather than
   assumed, and that skipping `data` does not silently reach the network.
3. **Secret/env contract (R-B4).** Providers declare what they need; the engine resolves from
   the environment, never logs a value, never writes to the source system. A missing declared
   secret must fail loudly at `doctor`, not mid-build.
4. **Deterministic fallback (R-B5).** A model-dependent dataset that is unavailable must
   produce a *declared* degradation — never a stuck "loading" frame, never an invented number.
   This is D16 applied to the data path.
5. **Provider guide (R-H5 partial).** Document the seam: what a provider may return, what the
   engine validates, what happens when it lies.

### Tasks

| # | Task | Status | Depends on |
|---|---|---|---|
| 1 | Snapshot metadata + staleness refusal (R-B3) | `[ ]` | — |
| 2 | `--only/--from` re-render offline test — the M2 exit criterion | `[ ]` | 1 |
| 3 | Secret/env declaration + resolution + `doctor` check (R-B4) | `[ ]` | — |
| 4 | Declared-degradation fallback for unavailable datasets (R-B5) | `[ ]` | — |
| 5 | `docs/authoring/providers.md` — the provider guide (R-H5) | `[ ]` | 1–4 |
| 6 | Tests for 1–4, keeping the suite sub-second | `[ ]` | 1–4 |
| 7 | Branch `phase/m2-provider-hardening` → commits → PR → merge | `[ ]` | 6 |

**Evidence requirement.** 2 and 4 must be *demonstrated* (a real offline re-render; a real
missing-secret failure), not asserted — same bar as M1.

---

## After M2 — the rest of the sequence

One branch, one PR, one merge per phase; `FEATURE-ROADMAP.md` §5–§14 is the authority for
scope and exit criteria.

| Phase | Purpose | Exit in one line |
|---|---|---|
| M3 Capture v2 | record real *behaviour*, not just screens | a spec captures a real download and films it |
| M4 Presentation v2 | stop the output looking wrong | full-page captures never stretched (the `still_to_clip` aspect bug) |
| M5 Agent surface | make it drivable | `init → build → verify` from tool calls and from `--json` |
| M6 Hardening & v1.0 | ship it | tagged `v1.0.0` — **flag to the owner before tagging** |
| M7 Executor & sandbox | terminal, files, isolation | a recorded real terminal session, never animated |
| M8 Docker & environment lab | real containers on camera | a container is started, filmed, and torn down |
| M9 Movie mode | narrative, not just demo | additive; no tenth stage |
| M10 Studio surface v2 | session-oriented MCP tools | an agent holds a session, not a job |

---

## Deliberately not doing yet

| Deferred | Why | Decision |
|---|---|---|
| Sandboxed terminal + Docker executor | Needs a story and a window to exist first; M1/M2 supply them. | [DECISIONS.md](DECISIONS.md) D13 |
| Movie/narrative mode | Additive, not a rescue — and only meaningful once capture is real (M3/M7). | [DECISIONS.md](DECISIONS.md) D14 |
| Adopting any OpenMontage code | AGPL-3.0 boundary — concepts only, no code reuse, no vendoring. | [DECISIONS.md](DECISIONS.md) D9 |
| A linter (`ruff`) | Belongs with "ship it", not with feature work. | M6 |

---

## Answered questions (previously open)

| # | Question | Answer |
|---|---|---|
| Q1 | Where does this repo ultimately live? | **GitHub** — `anindyasundarbera/vidkit`. |
| Q2 | Is `examples/oneaquahealth/` staying or moving out? | **Moves out.** Removed 2026-10-06, backed up to `~/Projects/oneaquahealth-story-backup/`. |
| Q3 | Story manifest shape (D1)? | **Both** — folder convention + optional `story.yaml`. |
| Q4 | Timeframe shape (D3)? | **Both** — `{days, as_of}` and `{start, end}`. |
| Q5 | Repo owner and visibility? | **`anindyasundarbera/vidkit`, public** (created 2026-10-06). |
| Q6 | Commit the rendered example output? | **Gitignore.** `*.mp4`/`*.srt` are write-only and rebuilt in CI. |
| Q7 | Traceability of the phase plan? | **One branch + PR + merge per phase** (`phase/mN-<slug>`). |

## Still-open questions for the owner

None blocking M2. The next genuinely open questions belong to M5 (job contract shape) and M9
(movie mode scope); the one item that needs an explicit go-ahead is the **public `v1.0.0`
tag at M6**.
