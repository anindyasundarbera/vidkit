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

## M2 — Provider & data hardening — **COMPLETE**

Exit criterion ([FEATURE-ROADMAP.md](FEATURE-ROADMAP.md) §5):

> `vidkit build --only panels,clips,render` works from persisted data, **offline**.

**Met, and the interesting half is what it refuses.** M1 made a build aimable; M2 makes its
data trustworthy, and makes an offline re-render the *default* rather than an option to
remember.

### Verified evidence

| Claim | How it was checked | Result |
|---|---|---|
| Offline re-render works | `build --only panels,clips,render` on hello-world | exit **0** in **99.20 s**, logging `datasets: reusing snapshot` |
| …and does not touch the source | a probe provider that *appends to a file* when it runs | file unchanged across the panels build (CI step) |
| A snapshot for another window is refused | `--only panels --timeframe 2026-02-01..2026-02-28` | exit **2**, `snapshot is stale` naming both windows |
| A missing snapshot is refused, not refetched | deleted `_build/data/` | exit **2**, naming the data dir; source still untouched |
| `--refresh` is the way out | `--only panels --refresh` | source asked again, panel re-rendered |
| Secrets are masked | `doctor` on a spec with a declared variable | prints `NAME  set (37 chars)`, never the value |
| …including in provider error text | `redact("upstream refused token <value>")` | `upstream refused token ***` |
| A missing secret fails loudly | empty exported variable | `missing_required()` non-empty; `doctor` exits non-zero |
| Degradation is a fact, not a hunch | `guard.require_live_data: true` + a fallback | `facts.degraded` non-empty; `all datasets live` fails |
| Suite is green and still cheap | `python3 -m pytest tests -q` | **124 passed in 0.70 s** (P6 holds) |
| CI asserts all of it | extracted every `run:` block and executed it | all pass locally |

Design consequences recorded as **D20–D22**.

---

## Current phase: M3 — Capture v2  *(P0)*

**Purpose.** Record real product *behaviour*, not just real product screens. This is the last
capability that only ever existed in an ad-hoc script, and it is P0 because M5–M10 all assume
capture is real.

**Requirements.** R-C3 (downloads), R-C4 (artifact rendering), R-C5 (element waits),
R-C6 (take selection), R-C7 (auth), R-C8 (deterministic rendering).

**Exit criterion.**

> A spec can capture a real downloaded file and film it, with no bespoke script.

### Ordered work

1. **`wait_for` action (R-C5).** Smallest and most load-bearing: a capture that races the UI
   is the root cause of most flaky recordings. `wait_for_selector` with an optional timeout,
   and a refusal that names the selector.
2. **`download` action (R-C3).** `click` → `expect_download` → save the real bytes to
   `_capture/artifacts/`, and record the path so a later shot can show it. The bytes are the
   evidence — never a mocked filename.
3. **`content`/`artifact` capture (R-C4).** Render the saved bytes in a page and screenshot
   them. That is how a generated PDF, CSV or image becomes a shot.
4. **Assertions before the shot (R-C1, already done) extended to the new actions.** Every new
   action must be able to carry the same `assert` the URL capture has.
5. **Take selection (R-C6).** `take: 2` or a predicate, so a recorded flow can be re-run and a
   better take kept without re-authoring.
6. **Auth/session (R-C7).** Reuse a stored `storage_state`, and refuse to record a login form
   unless the spec says the login *is* the story.
7. **Deterministic rendering (R-C8).** Freeze the clock, the locale, the viewport and
   `prefers-reduced-motion` so two captures of the same flow are byte-comparable.
8. **Capture guide.** Document each action with its refusals; a capture action that cannot
   fail honestly is not finished.

### Tasks

| # | Task | Status | Depends on |
|---|---|---|---|
| 1 | `wait_for` action + tests | `[ ]` | — |
| 2 | `download` action → real bytes in `_capture/artifacts/` | `[ ]` | 1 |
| 3 | `content`/`artifact` capture that shoots the saved bytes | `[ ]` | 2 |
| 4 | `assert` support on every new action | `[ ]` | 2, 3 |
| 5 | Take selection | `[ ]` | 2 |
| 6 | Auth/session reuse | `[ ]` | 1 |
| 7 | Determinism: frozen clock/locale/viewport/reduced-motion | `[ ]` | — |
| 8 | `docs/authoring/capture-guide.md` | `[ ]` | 1–7 |
| 9 | Branch `phase/m3-capture-v2` → commits → PR → merge | `[ ]` | 8 |

**Evidence requirement.** 2 and 3 must be demonstrated against a **local HTTP server** the
test starts itself — no external network, and no browser needed for the parts that can be
unit-tested with a fake page object. Playwright is absent on this machine, so every path that
needs it is written to a narrow seam and unit-tested through a fake; the CI runner installs it.

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

None blocking M3. The next genuinely open questions belong to M5 (job contract shape) and M9
(movie mode scope); the one item that needs an explicit go-ahead is the **public `v1.0.0`
tag at M6**.

Playwright is not installed on the development machine, so M3 is written against a narrow
seam and unit-tested with a fake page; the CI runner installs the real thing. Any capture
claim that cannot be demonstrated locally is marked as such until CI proves it.
