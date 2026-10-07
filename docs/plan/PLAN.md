# PLAN.md — what we are doing right now

> **This file describes only *now* and *next*.** It is rewritten as work progresses.
> For the phase-wise plan see [FEATURE-ROADMAP.md](FEATURE-ROADMAP.md). For what already
> happened see [HISTORY.md](HISTORY.md). For why, see [DECISIONS.md](DECISIONS.md).
>
> Last updated: **2026-10-07** (M5 complete; M6 next).

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

## Completed: M4 — Presentation v2  *(P0/P1)*

**Purpose.** Stop the output from looking wrong. M3 fixed what the camera *points at*; M4
fixes what the audience *sees*.

**Requirements.** R-D3 (date-proportional axis), R-D4 (overlays), **R-D5 (aspect-preserving
crop — this is a bug fix)**, R-D1/D2 (panels), R-D6 (transitions).

**Exit criterion.**

> Full-page captures are never stretched; a time series is spaced by real dates; an overlay
> renders.

### What was built

1. **`fit: cover|contain` (R-D5).** `still_to_clip` no longer emits a bare `scale=W:H`.
   `cover` scales up and centre-crops the overflow; `contain` scales down and letterboxes
   with a flat colour; the `zoom` branch fits into the enlarged box *before* `zoompan`. A
   new check, `frames are the declared size`, reads the geometry back off the produced file.
2. **Date-proportional axis (R-D3).** `parse_x`/`axis_positions` in `panels.py`; a date label
   the engine cannot read unambiguously (`"3"`, `"March"`) is deliberately left categorical.
3. **`overlay:` (R-D4).** A whole engine, not just a spec field: `vidkit/overlay.py`,
   `Ffmpeg.overlay_clip`, `assembler._overlay_graphic`, and the compositing step inside
   `_build_clips`. An overlay never replaces a shot.
4. **Three panel kinds (R-D1/D2).** `progress`, `comparison`, `quote` — registry now 11.
5. **Transitions (R-D6).** `cut|fade|wipe|slide` at `concat`, built as an `xfade` chain.
   `_clip_plan` lays the run out before rendering and the *outgoing* take of each junction
   carries the extra time, so the runtime is unchanged and narration stays the master clock.
6. **Guides.** spec-reference, panels-reference, pipeline, concepts, architecture,
   verification, README, ROADMAP, CHANGELOG.

### Tasks

| # | Task | Status | Depends on |
|---|---|---|---|
| 1 | `still_to_clip` aspect-preserving scale/crop + tests | `[x]` | — |
| 2 | Date-proportional x-axis | `[x]` | — |
| 3 | Overlay/lower-third compositing | `[x]` | 1 |
| 4 | Additional panel kinds | `[x]` | — |
| 5 | Transitions at `concat` | `[x]` | 1 |
| 6 | Docs: spec-reference, panels, pipeline | `[x]` | 1–5 |
| 7 | Branch `phase/m4-presentation-v2` → commits → PR → merge | `[~]` | 6 |

### Verified evidence

| Claim | How it was checked | Result |
|---|---|---|
| A still is fitted, not stretched | real render of a 1280×3000 page into 640×360, pixels read back | `cover` fills and crops; `contain` letterboxes; the frame is `640×360` in both |
| A geometry claim is read off the file | `frames are the declared size` against a deliberately wrong-sized film | correct film passes, `320x180` fails naming the real size |
| A dated x axis follows elapsed time | `axis_positions` over a 3-month and a 1-month gap | the 3-month gap is 3× as wide |
| An ambiguous label is not a date | `parse_x("3")`, `parse_x("March")` | `None` — spacing stays categorical |
| An overlay is drawn over the shot | real render, `640×360` clip + banner, pixels at row 40 and row 310 | shot still visible above, banner present below |
| A declared overlay always appears | `overlay.fade` set far beyond the clip length | clamped; the banner is still on screen |
| An overlay is not a substitute for a shot | spec load with `overlay:` and `shots: []` | refused: `scene 0 has no shots` |
| A transition never changes the runtime | real render, `fade`/`wipe`/`slide`, track duration vs measured narration | `4.00 s` vs `4.00 s` for all three |
| A fade is a genuine dissolve | pixels across the seam at t = 2.0…2.6 | `(253,0,0) → (253,0,0) → (167,0,83) → (0,0,254)` |
| A wipe is a boundary, not a blend | pixels left and right at t = 2.3 | red left, blue right, same frame |
| A hard cut leaves no seam | the same instant with `transition: cut` | one colour across the whole frame |
| Overlays and transitions survive a resume | `--from concat` on an overlaid, dissolving spec | same duration, banner still present, `clips/base/` ignored |
| Suite is green and still cheap | `python3 -m pytest tests -q` | **278 passed in 37.56 s** |

Branch `phase/m4-presentation-v2` → PR → merged to `main`. Design consequences: **D26–D28**.

---

## M5 — Agent surface — **COMPLETE**

Exit criterion ([FEATURE-ROADMAP.md](FEATURE-ROADMAP.md) §8):

> An MCP client can `init → build → verify` a story purely from tool calls; the same is
> possible from a shell with `--json`.

**Met, from a shell, in one session.** `--json doctor` (no story needed) → `--json run init`
→ `--json run plan` → `--json --progress run build` → `--json run verify`; exit codes
`0 0 0 0 0`, 23 log lines on stderr and pure JSON on stdout throughout. 14 MCP tools.

### Verified evidence

| Claim | How it was checked | Result |
|---|---|---|
| The whole loop is driveable without prose | the five `--json` calls above, chained | `0 0 0 0 0`; the scaffolded story builds and verifies unedited |
| stdout stays parseable under `--progress` | stdout piped to `json.load`, stderr to a file | JSON parsed; 23 log lines separated |
| `doctor` works before a story exists | `--json doctor` in a story-less directory | `ok: true` |
| A refusal is data | `run_job("plan", story="does-not-exist")` | `ok: false` + `failure.kind`/`hint` |
| A refusal still names the window | `timeframe="7d"` against a spec pinning another window | `ok: false`, `timeframe.days == 7` |
| A timeout returns a manifest | `tool_run("build", timeout=0.05)` | `ok: false`, `"did not finish within"` |
| Suite is green | `python3 -m pytest tests -q` | **337 passed in 48.04 s** |

Branch `phase/m5-agent-surface` → PR → merged to `main`. Design consequences: **D29–D30**.

---

## Next: M6 — Hardening & v1.0  *(P0/P1)*

See [FEATURE-ROADMAP.md](FEATURE-ROADMAP.md) §9. A provenance manifest (dataset source, spec
hash, tool versions, build time), a portability pass, `CHANGELOG` release notes, optional
PyPI.

**The one item that needs the owner.** The public **`v1.0.0` tag** is a visible release and
is the only remaining decision in the roadmap that a human owns. It will be raised — with
the evidence the exit criterion asks for — before it is pushed. Everything else in M6 and
after is authorised by [FEATURE-ROADMAP.md](FEATURE-ROADMAP.md).
