# PLAN.md — what we are doing right now

> **This file describes only *now* and *next*.** It is rewritten as work progresses.
> For the phase-wise plan see [ROADMAP.md](FEATURE-ROADMAP.md). For what already happened see
> [HISTORY.md](HISTORY.md). For why, see [DECISIONS.md](DECISIONS.md).
>
> Last updated: **2026-10-06**.

---

## Current phase: M0 — Extract & baseline → **COMPLETE**

**Goal:** make the repo prove its own standalone-ness, and put it under version control.

Exit criterion ([FEATURE-ROADMAP.md](FEATURE-ROADMAP.md) §M0):

> A fresh clone → `pip install -e ".[dev]"` → `pytest` green →
> `vidkit build examples/hello-world/video.yaml` succeeds with **only** `ffmpeg` +
> `rsvg-convert`; `grep` shows no host terms.

**Status: the engine half is met and independently verified, and M0 is now fully closed** —
the repo is published and CI is green on the remote.

Exit criterion ([FEATURE-ROADMAP.md](FEATURE-ROADMAP.md) §M0):

> A fresh clone → `pip install -e ".[dev]"` → `pytest` green →
> `vidkit build examples/hello-world/video.yaml` succeeds with **only** `ffmpeg` +
> `rsvg-convert`; `grep` shows no host terms.

**Met on a clean runner, not just locally.** Published to
<https://github.com/anindyasundarbera/vidkit> (public), first commit `87b7435`; GitHub Actions
run [`37513459095`](https://github.com/anindyasundarbera/vidkit/actions/runs/37513459095) is
green across `pytest (3.10)`, `pytest (3.12)`, and `build hello-world end to end`. See
[HISTORY.md](HISTORY.md) for the full record.

### Verified evidence

| Claim | How it was checked | Result |
|---|---|---|
| hello-world builds offline | `vidkit build examples/hello-world/video.yaml` | **ALL PASS** — 8 panels, 12 stills, 87.20 s, no browser/network/TTS |
| `doctor` passes | `vidkit doctor examples/hello-world/video.yaml` | exit 0, 8 scenes, 8 charts, all 8 panel kinds |
| `plan` is accurate | `vidkit plan examples/hello-world/video.yaml` | 217 words, window 60–120 s |
| Suite is green | `python3 -m pytest tests -q` | **44 passed** |
| Engine is host-free | `grep -rniE "oneaquahealth\|oah_\|fhir" vidkit/*.py tests/*.py examples/` | **0 hits** |
| Wheel is complete | `pip wheel . --no-deps` then inspect | ships `vidkit/py.typed` + `dist-info/licenses/LICENSE` |
| CI assertion script works | rendered the `run:` block from `ci.yml` and executed it | `ALL PASS`, exit 0 |

---

## Task board

Legend: `[x]` done+verified · `[~]` in progress · `[ ]` not started · `[!]` blocked · `[-]` deferred

### M0.1 — hello-world fixture  *(critical path)*

| # | Task | Status | Depends on |
|---|---|---|---|
| 1 | `examples/hello-world/assets/00-title.svg` — title card at 1920×1080 | `[x]` | — |
| 2 | `examples/hello-world/assets/07-end.svg` — end card at 1920×1080 | `[x]` | — |
| 3 | `examples/hello-world/provider.py` — all 8 datasets, measured from disk | `[x]` | — |
| 4 | `examples/hello-world/narration.md` — 8 scenes, bold spoken lines | `[x]` | — |
| 5 | **`examples/hello-world/video.yaml`** — the spec itself | `[x]` | 1–4 |
| 6 | `vidkit build examples/hello-world/video.yaml` → mp4 + srt + all checks PASS | `[x]` | 5 |
| 7 | `vidkit doctor examples/hello-world/video.yaml` → exit 0 | `[x]` | 5 |

**Task 5 detail (as built).** Eight charts, one per dataset the provider returns, covering
all 8 panel kinds:

| dataset | panel kind | scene |
|---|---|---|
| `overview` | `stat_cards` | 1 |
| `notes` | `text_panel` | 2 |
| `size_profile` | `line_series` | 3 |
| `biggest` | `bar_profile` | 3 |
| `pipeline` | `strip` | 4 |
| `facts` | `kv_table` | 5 |
| `cli` | `endpoints` | 6 |
| `terminal` | `terminal` | 6 |

Scenes 0 and 7 are static stills. `voice.engine: none` (offline), `guard.require_audio: false`
(declared silent cut), `guard.require_live_mode: false`. Runtime window 60–120 s brackets the
measured silent-cut duration (217 spoken words at `_FALLBACK_WPS = 2.5` → **87.20 s** actual).

### M0.2 — repo hygiene

| # | Task | Status | Depends on |
|---|---|---|---|
| 8 | `LICENSE` (MIT) | `[x]` | — |
| 9 | `CHANGELOG.md` with a `0.1.0` entry | `[x]` | — |
| 10 | `.github/workflows/ci.yml` — pytest + hello-world build | `[x]` | 6 |
| 11 | Add `py.typed` and ship it as package data | `[x]` | — |

> CI deliberately runs **only** `pytest` + the hello-world build. No linter is configured in
> `pyproject.toml`, so the workflow does not invent one — adding `ruff` is M6 work.

### M0.3 — correctness review

| # | Task | Status | Depends on |
|---|---|---|---|
| 12 | **`default_spec()` ordering** — resolved by construction: oneaquahealth removed, so hello-world is the only example and the default is unambiguous. `test_default_spec_picks_examples_deterministically` pins the *behaviour* (alphabetical first), not a filename. | `[x]` | 5 |
| 13 | Tests for `guard.require_audio` (declared silent cut vs. undeclared) | `[x]` | — |
| 14 | Remove host references from engine comments/docstrings and from tests/docs | `[x]` | — |
| 15 | Re-run `pytest tests -q` → **44 passed** | `[x]` | 12, 13 |

### M0.4 — publish — **COMPLETE 2026-10-06**

| # | Task | Status | Depends on |
|---|---|---|---|
| 16 | Create the GitHub repo — `anindyasundarbera/vidkit`, **public** | `[x]` | Q5 answer |
| 17 | `git remote add origin …` (via `gh repo create --source=. --remote=origin`) | `[x]` | 16 |
| 18 | `git add -A` and create the **first commit** on `main` — 54 files | `[x]` | 1–15, Q6 answer |
| 19 | Commit trailer `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>` | `[x]` | 18 |
| 20 | `git push -u origin main` — **`87b7435`** | `[x]` | 18 |

**Q6 resolved → gitignore.** `*.mp4` and `*.srt` were added to the generated-output block in
`.gitignore`. This was checked rather than assumed: both are only ever *written*
(`assembler.py:301,305`) and never read as input, they are reproducible, and CI regenerates
and asserts them on every push. The staged tree is 54 files with no artefacts or caches.

**CI confirmed green on the remote** — run [`37513459095`](https://github.com/anindyasundarbera/vidkit/actions/runs/37513459095):

| Job | Result | Time |
|---|---|---|
| `pytest (3.10)` | ✅ success | 19s |
| `pytest (3.12)` | ✅ success | 16s |
| `build hello-world end to end` | ✅ success | 1m33s |

The `build-example` job is the meaningful one: a clean Ubuntu runner with only `ffmpeg` and
`librsvg2-bin` runs `vidkit doctor` → `plan` → `build examples/hello-world/video.yaml` →
asserts `verify.json` is `"ok": true`. That is the first independent proof the engine works on
a machine with no prior state.

**Blocked / deferred in M0:** none. M0 is closed.

---

## Next phase: M1 — Story & timeframe contract

**The functional gap that blocks the whole premise.** vidkit has no representation of a
*story* and no concept of a *timeframe*. Windows are hard-coded in provider URL strings.
Until this lands, an agent cannot be handed `(story, timeframe, environment)` — which is the
north star.

Both design questions are now **answered** ([DECISIONS.md](DECISIONS.md) D1, D3): story
identity is **folders + optional `story.yaml`**; timeframe accepts **both** `{days, as_of}`
and `{start, end}`, resolving to one `{start, end}`.

Ordered, because each depends on the last:

1. `timeframe` in the spec (both forms) → expose as `ctx.timeframe`; record the resolved
   window in the provenance manifest.
2. Thread `ctx.timeframe` into `provider.datasets(ctx)`.
3. `story` identity + optional manifest, validated at load (one code path).
4. **R-F7** verify check: the window stated in narration/captions matches the spec timeframe.
5. `vidkit init <dir>` scaffold producing a runnable story.
6. `vidkit plan` prints the resolved timeframe.

**Exit:** two builds of one story with different timeframes produce different, correctly
labelled videos; a mismatched narration window **fails `verify`**.

---

## Deliberately not doing yet

| Deferred | Why | Decision |
|---|---|---|
| Sandboxed terminal + Docker executor | Needs the story/timeframe contract to exist first, or it is sandboxing a pipeline that cannot yet be aimed. | [DECISIONS.md](DECISIONS.md) D13 |
| Movie/narrative mode | Same reason; and it is additive, not a rescue. | [DECISIONS.md](DECISIONS.md) D14 |
| Adopting any OpenMontage code | AGPL-3.0 boundary — see [OPENMONTAGE.md](OPENMONTAGE.md). Concepts only. | [DECISIONS.md](DECISIONS.md) D9 |
| More panel kinds | No gap: all 8 built-in kinds exist and are exercised by `test_every_builtin_panel_renders` **and** by the hello-world build. | — |

---

## Answered questions (previously open)

| # | Question | Answer |
|---|---|---|
| Q1 | Where does this repo ultimately live? | **GitHub** — create `vidkit` under the owner's account. |
| Q2 | Is `examples/oneaquahealth/` staying or moving out? | **Moves out.** Removed from this repo 2026-10-06 and **backed up** to `~/Projects/oneaquahealth-story-backup/` — with zero commits, deletion would have been irreversible. |
| Q3 | Story manifest shape (D1)? | **Both** — folder convention + optional `story.yaml`. |
| Q4 | Timeframe shape (D3)? | **Both** — `{days, as_of}` and `{start, end}`. |
| Q5 | **Repo owner and visibility?** | **`anindyasundarbera/vidkit`, public.** Created 2026-10-06 → <https://github.com/anindyasundarbera/vidkit> |
| Q6 | **Commit the rendered example output?** | **Gitignore.** `*.mp4` and `*.srt` added to `.gitignore`; both are write-only outputs and CI regenerates them. |

## Still-open questions for the owner

None. The next open questions belong to M1 and are listed in its section.
