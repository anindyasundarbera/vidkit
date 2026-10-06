# PLAN.md — what we are doing right now

> **This file describes only *now* and *next*.** It is rewritten as work progresses.
> For the phase-wise plan see [FEATURE-ROADMAP.md](FEATURE-ROADMAP.md). For what already
> happened see [HISTORY.md](HISTORY.md). For why, see [DECISIONS.md](DECISIONS.md).
>
> Last updated: **2026-10-07**.

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

## M3 — Capture v2 — **COMPLETE**

Exit criterion ([FEATURE-ROADMAP.md](FEATURE-ROADMAP.md) §6):

> A spec can capture a real downloaded file and film it, with no bespoke script.

**Met, against a real Chromium, not a fake page object.** Every claim below was produced by
running the actual browser; the unit tests exist to keep it that way, not to stand in for it.

### Verified evidence

| Claim | How it was checked | Result |
|---|---|---|
| A real page can be driven and proven | `vidkit build examples/capture-kit/video.yaml` against a real Chromium | exit **0**; `[PASS] all live captures present — 5 captures` |
| A real download is real bytes | `wc -c`, `head` | `usage.csv` **158 B**, header + exactly 5 data rows |
| A downloaded PDF is a real PDF | `file`/magic + `pdftotext` | `%PDF-`, 1104 B, one page of real summary text |
| An artifact is filmed as itself | sniff + rasterise | `csv_page.png` 66 496 B; `pdf_page.png` **1275×1650**, the PDF's own text |
| …and refuses when it cannot | `pdftoppm`/`gs` monkeypatched to fail | `cannot show a.pdf: pdftoppm failed …`, then `gs failed` |
| A wrong assertion stops the build | a spec asserting `#summary contains 'nine hundred rows'` | exit **1**, `… (saw '5 rows · 7016 visits · 395 signups')` |
| Determinism is real | freeze script injected before the page runs | clock, locale, timezone, reduced-motion, `Math.random` all pinned |
| The suite is green and still cheap | `python3 -m pytest tests -q` | **198 passed in 1.71 s** (P6 holds) |
| CI asserts all of it, with a browser | extracted the `capture-probe` `run:` blocks and executed them | serve OK, film OK, refusal OK, `CAPTURE OK` |

**Two real bugs were found only because the browser was real**, after the unit tests were
green: the fixture's HTML constant had doubled braces without an `f` prefix, so the page
raised `Uncaught SyntaxError`; and its `load()` removed an element that was already gone, so
the second *Apply* click silently left `#summary` at its first value. Both would have shipped
on unit tests alone. That is the argument for the CI job, restated as evidence.

Branch `phase/m3-capture-v2` → PR → merged to `main`. Design consequences recorded as
**D23–D25**.

---

## Current phase: M4 — Presentation v2  *(P0/P1)*

**Purpose.** Stop the output from looking wrong. M3 fixed what the camera *points at*; M4
fixes what the audience *sees*.

**Requirements.** R-D3 (date-proportional axis), R-D4 (overlays), **R-D5 (aspect-preserving
crop — this is a bug fix)**, R-D1/D2 (panels), R-D6 (transitions).

**Exit criterion.**

> Full-page captures are never stretched; a time series is spaced by real dates; an overlay
> renders.

### Ordered work

1. **`still_to_clip` must preserve aspect (R-D5).** It currently emits a bare `scale=W:H`,
   which **stretches** a full-page capture to 16:9. A distorted screenshot misrepresents the
   product, so this is a truthfulness bug, not a polish item — and it is first because every
   other M4 change is measured against it.
2. **Date-proportional axis (R-D3).** A time series must be spaced by real dates, not by
   index, so a gap in the data reads as a gap.
3. **Overlays / lower-thirds (R-D4).** A compositing seam so a title, a callout, or a
   branding strip can sit over a shot without being baked into the capture.
4. **More panel kinds (R-D1/D2).** Grow the registry where a real story needs it; no
   speculative kinds.
5. **Transitions (R-D6).** Cut, fade, and a wipe, applied at `concat` — deterministic, and
   never a substitute for a real state change.
6. **Guides.** Update `docs/authoring/spec-reference.md`, the panels reference, and the
   pipeline stage map for the new fields and stages.

### Tasks

| # | Task | Status | Depends on |
|---|---|---|---|
| 1 | `still_to_clip` aspect-preserving scale/crop + tests | `[ ]` | — |
| 2 | Date-proportional x-axis | `[ ]` | — |
| 3 | Overlay/lower-third compositing | `[ ]` | 1 |
| 4 | Additional panel kinds | `[ ]` | — |
| 5 | Transitions at `concat` | `[ ]` | 1 |
| 6 | Docs: spec-reference, panels, pipeline | `[ ]` | 1–5 |
| 7 | Branch `phase/m4-presentation-v2` → commits → PR → merge | `[ ]` | 6 |

**Evidence requirement.** Every aspect-ratio and transition claim must be checked by
**probing the produced video** (`ffmpeg`-derived frame geometry), not by reading the filter
string. A filter that *looks* right is not evidence.
