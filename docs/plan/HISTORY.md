# HISTORY.md — what we have done

> **Append-only.** Never rewrite the past. Newest entry at the bottom.
> Each entry carries a date and the evidence that supports it.
> For what is happening *now*, see [PLAN.md](PLAN.md).

---

## 2026-10-04 — Engine audit (pre-existing work, recorded here for completeness)

The engine, tests, and docs set were already on disk when this session began. What was
verified at that time, and is the baseline the rest of this document builds on:

| Claim | Evidence |
|---|---|
| Engine is host-free | `grep -rniE "oneaquahealth\|oah_\|yam-\|fhir\|8080\|8090"` → 0 hits across `vidkit/`, `tests/`, `examples/` (the 2 historical comment mentions are gone) |
| No timeframe concept exists | `grep -rniE "timeframe\|date_range\|window\|since\|days" vidkit/vidkit/*.py` → nothing structural |
| MCP server and docs were never in git | `git log --all --oneline -- vidkit/docs vidkit/vidkit/mcp_server.py` → empty (repo has no commits at all) |

The root [ROADMAP.md](../../ROADMAP.md) §3 records this audit. Its "current state" table is
**now stale** — it claims `mcp_server.py`, `docs/`, and `reports.py` are absent. All three
exist. The roadmap's §4 milestones remain the governing plan and were not invalidated.

---

## 2026-10-06 — Session: understanding vidkit

**Goal:** understand the project well enough to answer a strategy question about it.

Read all 17 modules, `README.md`, `ROADMAP.md`, `docs/modules.yaml`, the doc set, and both
example/test trees. Verified the toolchain and ran the suite.

**Evidence:**

```bash
python3 -m pytest tests -q     # 39 passed (24 core + 15 MCP) in 0.53s
which python3 ffmpeg rsvg-convert git
#   /usr/bin/python3  /snap/bin/ffmpeg  /usr/bin/rsvg-convert  /usr/bin/git
git log --oneline              # fatal: your current branch 'main' does not have any commits yet
```

**Key facts established:**

- `python`, not `python3`, does not exist on this machine. **Use `python3`.**
- The repo has **zero commits**; `git status --short` shows 8 untracked top-level entries.
- No git remote is configured.
- 10 MCP tools (`vidkit_doctor/plan/build/tts/capture/verify/verify_report/panel_kinds/docs/docs_index`),
  3 resources (`vidkit://docs/index`, `vidkit://docs/modules`, `vidkit://docs/{name}`).
- 8 panel kinds, 9 pipeline stages, 15 docs in 6 doc modules.

---

## 2026-10-06 — Research: OpenMontage, and whether to integrate it

**Question asked by the owner:** *"Can vidkit implement or integrate OpenMontage to increase
its capability? Or is OpenMontage alone sufficient?"*

Researched `calesthio/OpenMontage` from primary sources — GitHub code search, `gh api`, raw
file fetches, and an independent deep-dive sub-agent whose report corroborated every finding.

**Full record, with citations: [OPENMONTAGE.md](OPENMONTAGE.md). Verdict summary:**

- **Not integrable as a library.** No MCP server (code search for MCP returned 0 hits; its
  own MCP issue is still open), no `console_scripts` entry points, no public Python API.
- **Zero Docker / sandbox / terminal-execution infrastructure.** 0 code hits for
  docker/sandbox/container. The owner's sandbox goal is **greenfield either way** — it is not
  a reason to adopt OpenMontage, and not a reason to reject it.
- **Licence is AGPL-3.0.** Importing or vendoring makes vidkit a derivative work. Safe
  separation is subprocess invocation of an unmodified install.
- **Its architecture forbids programmatic orchestration** by design ("Rule Zero": *the agent
  IS the control plane*). Adopting that would destroy vidkit's differentiator.

**Recommendation delivered:** borrow **concepts** only (capability envelope, selector
pattern, pipeline-as-data YAML, JSON-Schema artifacts, cost governance) and **zero code**.
Keep vidkit's honest-by-construction engine as the core. Recorded as
[DECISIONS.md](DECISIONS.md) D9.

---

## 2026-10-06 — M0 started: hello-world fixture

**Why M0 and not the sandbox:** the owner was unavailable to answer the "which direction
first" routing question. M0 is the ROADMAP's own documented prerequisite, is purely
additive, and is the only phase that protects existing work from loss. It also happens to be
the phase whose exit criterion the user's own roadmap already fixed.

**Created:**

| File | What it is |
|---|---|
| `examples/hello-world/assets/00-title.svg` | Title card, 1920×1080, headless-safe fonts |
| `examples/hello-world/assets/07-end.svg` | End card, 1920×1080 |
| `examples/hello-world/provider.py` | Offline provider — **measures** the repo rather than hard-coding |
| `examples/hello-world/narration.md` | 8 scenes, 217 spoken words, bold lines only |

`provider.py` derives every figure from files on disk: module count, non-comment LOC per
module, `len(STAGES)`, `len(kinds())`, test count, the real environment (`sys.platform`,
`shutil.which` for ffmpeg/rsvg-convert), and the spec's own sha256. The video claims nothing
that was not counted. This is the [I7 invariant](../../AGENTS.md) applied to the fixture itself.

Assets were first drawn at 1280×720 and **corrected to 1920×1080**, because `PanelDoc` is
constructed with `spec.project.width/height` and the built-in panel renderers place elements
at 1920×1080 coordinates. Mixed canvas sizes would have stretched the still cards.

**Engine changes (2 files):**

- `vidkit/spec.py` — added `Guard.require_audio: bool = True` and its parse line
  (`guard.require_audio=bool(g.get("require_audio", True))`).
- `vidkit/verify.py` — two changes:
  1. a silent cut is now a **PASS** when `guard.require_audio is False` (declared), and still
     a **FAIL** otherwise;
  2. the *speech rate plausible* check is **skipped** (PASS, "silent cut") when no narration
     track was muxed, because there is nothing to measure.

**Rationale:** invariant I6 says a silent cut must be *declared*, never accidental. Before
this change, a spec that deliberately shipped a silent cut — like the offline CI fixture —
could not pass `verify` at all. The change sharpens the invariant rather than weakening it:
silence still fails unless the spec says so in writing.

**Not yet verified at this point:** the hello-world build has never been run. The
`spec.py`/`verify.py` edits have not been re-tested against the suite.

---

## 2026-10-06 — Owner answers Q1–Q4; M0 completed and verified

**The owner answered the four blocking questions** recorded in the previous entry, which
unblocked the rest of M0:

| # | Question | Answer |
|---|---|---|
| Q1 | Where does this repo live? | **GitHub** — create the repo. |
| Q2 | Is `examples/oneaquahealth/` staying or moving out? | **Remove it** from this repo. |
| Q3 | Story manifest shape (D1)? | **Both** — folder convention *and* `story.yaml`. |
| Q4 | Timeframe shape (D3)? | **Both** — `{days, as_of}` *and* `{start, end}`. |

Q1 was already half-answered by reconnaissance: `gh auth status` reports an authenticated
account with `repo` scope over SSH, and `gh repo view <owner>/vidkit` returns **not found** —
the repo does not exist yet, so creating it is a real action, not a no-op.

**Safety note.** `examples/oneaquahealth/` was removed, but the repo has **zero commits**, so
the deletion was irreversible. The nine files (6 source + 5 assets, one shared) were copied to
`~/Projects/oneaquahealth-story-backup/` **before** removal and verified present afterwards.
Deleting it here also settles the `default_spec()` hazard that had been flagged in
`AGENTS.md` §4.4 — with one example left, the MCP default is unambiguous.

**hello-world built and verified.** `examples/hello-world/video.yaml` was written and run:

```bash
vidkit doctor examples/hello-world/video.yaml   # exit 0 — 8 scenes, 8 charts, 8 panel kinds
vidkit plan   examples/hello-world/video.yaml   # 217 words, est. 1.30 min, window 60–120 s
vidkit build  examples/hello-world/video.yaml   # ALL PASS — 87.20 s, 8 panels, 12 stills
```

Artifacts: `hello-world.mp4` (1.5 MB) and `narration.srt` (2,111 B), report at
`examples/hello-world/_build/verify.json` with all nine checks passing and captions reporting
"all cues ok".

**Note on the timing discrepancy — this is not a bug.** `plan` predicted 78 s; the build
measured 87.20 s. They use two intentionally different constants: `WORDS_PER_SECOND = 2.78`
in `reports.py` is the *estimate* shown by `plan`, while `_FALLBACK_WPS = 2.5` in `tts.py` is
the silent-cut fallback that actually drives the clip length. 217 / 2.5 ≈ 86.8 s. Both are
correct for their purpose.

**Tests repointed and extended: 39 → 44 passing.**

| Change | File |
|---|---|
| `EXAMPLE` constant repointed to `hello-world`; plan/doctor assertions now check slug, 8 scenes, word count, and required phrases | `tests/test_mcp.py` |
| `test_docs_index_tool_lists_modules` now requires the `plan` module | `tests/test_mcp.py` |
| **New** `test_docs_tool_exposes_plan_docs` — asserts all 5 plan docs resolve by bare stem **and** module-qualified path, and that `FEATURE-ROADMAP` exists in `_doc_routes()` | `tests/test_mcp.py` |
| **New** `test_default_spec_picks_examples_deterministically` — pins the *behaviour* (alphabetical first), not a filename | `tests/test_mcp.py` |
| **New** `test_require_audio_defaults_to_true`, `test_require_audio_can_be_declared_off`, `test_verify_passes_declared_silent_cut_but_fails_undeclared` | `tests/test_core.py` |
| Host-story strings in fixtures genericised (`FHIR`→`gateway`, `Yamuna`→`map`, etc.) | `tests/test_core.py` |

The silent-cut test drives `verify_output` with a real `Context` and empty assets, asserting
the **exact** check name `"audio present"` flips between ok and not-ok as `require_audio`
changes — so the invariant is tested at the level it is enforced.

**Hygiene files created:**

| File | Notes |
|---|---|
| `LICENSE` | MIT. Was declared in `pyproject.toml` but the file was missing. |
| `CHANGELOG.md` | Keep a Changelog, `0.1.0` + `Unreleased`. |
| `vidkit/py.typed` | Empty marker; wired into package data. |
| `.github/workflows/ci.yml` | Jobs `test` (3.10/3.12) and `build-example` (ffmpeg + librsvg2-bin → doctor/plan/build → assert `verify.json`) |

`pyproject.toml` gained `[tool.setuptools] license-files = ["LICENSE"]` and
`[package-data] vidkit = ["py.typed"]`.

**Independent verification of the deliverables (not just "it ran once"):**

```bash
python3 -m pytest tests -q                       # 44 passed
python3 -m pip wheel . --no-deps -w /tmp/wt      # succeeds
# wheel contains vidkit/py.typed and dist-info/licenses/LICENSE
# the ci.yml "Assert verification passed" run-block was rendered from YAML and executed → ALL PASS, exit 0
grep -rniE "oneaqua|oah|yamuna|fhir" vidkit/*.py tests/*.py examples/   # 0 hits
```

The `ci.yml` check mattered because YAML strips the indentation of a block scalar while the
embedded heredoc does **not** strip its own — rendering and executing the step proved the
script survives the round-trip with its `<<'PY'` terminator intact.

**Docs updated to match reality** (all previously stale): root `ROADMAP.md` §3 gained a
current-baseline table and its M0 checklist is now marked complete; `DECISIONS.md` D1/D3 were
resolved to "both" and their index rows flipped to DECIDED; `PLAN.md` carries verified
evidence instead of intentions; `AGENTS.md` lost its stale example-tree and `default_spec`
notes. `docs/README.md` and `docs/modules.yaml` were **already correct** — verified, not
rewritten.

**Still open at end of session:** the GitHub repo itself (owner + visibility unconfirmed) and
whether rendered `hello-world.mp4`/`narration.srt` should be committed or gitignored. No git
commit has been made.

---

## 2026-10-06 — Repo published; M0 fully closed

**Owner answered the last two questions.** Q5: repo on `anindyasundarbera`, **public**. Q6:
**gitignore** the rendered `.mp4`/`.narration.srt`.

**Rendered-output policy settled in `.gitignore`.** Added `*.mp4` and `*.srt` to the generated
render-output block. Verified this is safe rather than a guess: both are always *outputs* —
`assembler.py:305` writes `spec.project.output` into `ctx.out_dir` and `assembler.py:301` sets
`assets.srt = ctx.out_dir / "narration.srt"`; nothing anywhere reads an `.mp4` or `.srt` as
input. They are reproducible, and CI regenerates and asserts them on every push.

**Genericization finished.** The sweep of illustrative snippets that still carried host
flavour: `spec-reference.md` (`oah_trend` → the real built-in `line_series`),
`provider-guide.md` (`oah_trend` → `myapp_trend`, an explicitly user-owned kind, and
`_trend`/`_sparkline` aligned), `narration-and-captions.md` ("FHIR server" → "an upstream
API"), `cli-reference.md` (`OAH_GATEWAY` → `MYAPP_API_URL`). Note the first attempt invented a
kind `sparkline` that does not exist in `_REGISTRY`; caught and corrected to a real kind
before committing, because a doc code-block that a reader would copy must actually run.

`extracting-to-new-repo.md` was reframed from a forward-looking checklist into a status
document: a banner states the extraction has happened, steps 1–6 are marked done, the
post-extraction checklist is ticked (44 tests, 0 broken links, LICENSE, CI), step 2 records
the example removal + backup, and step 7 plus "Known couplings" are marked as the remaining
**OAH-side** work.

**Published.**

```bash
gh repo create anindyasundarbera/vidkit --public --source=. --remote=origin
# → https://github.com/anindyasundarbera/vidkit
git add -A                       # 54 files (rendered outputs correctly ignored)
git commit -m "Initial import of vidkit as a standalone project"
git push -u origin main          # 87b7435
```

**CI verified green on GitHub, not just locally** — run `37513459095`:

| Job | Result |
|---|---|
| `pytest (3.10)` | ✅ 19s |
| `pytest (3.12)` | ✅ 16s |
| `build hello-world end to end` | ✅ 1m33s |

The third job is the one that matters: a bare Ubuntu runner installs only `ffmpeg` and
`librsvg2-bin`, then runs `vidkit doctor` → `vidkit plan` → `vidkit build examples/hello-world/video.yaml`
→ asserts `verify.json` reports `"ok": true`. This is the first **independent** confirmation
that the engine works on a machine that has never seen this repo. Local execution of the same
script had only proven the script; this proves the product.

Working tree clean, `main` tracking `origin/main`, remote tree carries all 54 files.
`/tmp/1791*.txt` OpenMontage research scratch removed.

**M0 is complete. All 13 session todos are done.**

---

## 2026-10-06 — M1: the story & timeframe contract

**Branch:** `phase/m1-story-timeframe` → PR #1 → `main`, merge commit **`aa3eb5d`** (CI green).

The blocker is closed. vidkit can now be *aimed*: a story has an identity, and a build has a
window of time it is about — a window that `verify` independently checks the video against.

### What was built

**`vidkit/timeframe.py` (new).** The whole contract in one module. A frozen `Timeframe`
(`start`, `end`, `as_of`, `source` ∈ `override|spec|story`, `floating`) with `days`
(inclusive), `label()`, `prose()`, `as_prompt()`, `matches()`. It accepts both spellings the
owner asked for — `{days, as_of}` and `{start, end}` — plus `weeks`/`months`/`years`, the
shorthand strings (`28d`, `4w`, `6m`, `2026-09-09..2026-10-06`,
`9 September 2026 to 6 October 2026`) and a bare date. It also reads windows *back out* of
prose (`find_window_claims`) and compares them (`timeframe_matches`).

**Story identity (D1, option C).** `Story` + `load_story` in `spec.py`. A story is a folder;
`story.yaml` is optional and, when present, validated strictly. When it is absent the identity
is synthesised from the folder name — deliberately *one* code path, because D1's rejected
alternative was exactly the "two code paths that rot" hazard.

**`vidkit/scaffold.py` (new) + `vidkit init <dir>`.** Writes a four-file runnable story —
`story.yaml`, `video.yaml`, `narration.md`, `provider.py` — that builds and verifies clean
with no edits. Refuses to overwrite anything that exists.

**Precedence, recorded rather than inferred.** `override > video.yaml > story.yaml`. The
winner is on `spec.timeframe.source` and printed by `plan`, `doctor`, and the build banner, so
a `--timeframe` run never leaves you guessing which window you got.

**R-F7 in `verify.py`.** The narration and captions are read for statements about time and
compared with the resolved window. Narration silent about time passes with a note; narration
that disagrees fails, naming both windows.

**Two distinct failure points, deliberately split.** Narration that states a window the spec
cannot *guarantee* (dates while the window floats) is refused at **load**, before any
expensive rendering. Narration that merely *disagrees* fails at **verify**. Both are errors —
the split just means each is caught by whichever stage can prove it.

### Evidence, not assertion

The exit criteria are now CI steps, so they cannot rot:

| CI step | Asserts |
|---|---|
| `Second build with a different window` | one story, two windows → two correctly-labelled videos |
| `Reject a narration window that disagrees with the spec` | exits 2, and the timeframe check is the **only** failure |
| `Scaffold a story and verify it` | `vidkit init` → `plan` shows the resolved window → `build` exits 0 |

Locally: full build `ALL PASS` including
`[PASS] timeframe consistent with spec — matches 2026-10-07 to 2026-10-06 (30 days)`;
`--timeframe 2026-08-01..2026-09-30` exits **2** with the single failing check
`timeframe consistent with spec`; editing one date in `narration.md` and re-running `verify`
exits **2**; restoring it returns to `ALL PASS`; `vidkit build _scaffold/video.yaml` exits 0
with `[PASS] runtime within window — 14.00s within [8, 30]`.

Tests went from 44 to **84**, still in **~1.5 s** (P6 holds).

### Defects found and fixed while building it

M1 was not just additive; writing the tests surfaced four real bugs.

1. **The `verify`-alone verdict disagreed with the build verdict.** `cli.py`'s standalone
   `verify` set `assets.audio_track` unconditionally, so re-verifying a *silent cut* reported
   `[FAIL] audio present` where the build it was re-verifying had said PASS. A render must not
   have two verdicts. Now `wav if wav.exists() else None`. **Pre-existing**, found by M1.
2. **`parse_timeframe` crashed on `default_as_of`.** `'str' object has no attribute
   'toordinal'` — the fallback date was never coerced. Any relative window without an `as_of`
   reached this.
3. **A lone `start:` in a timeframe silently produced a one-day window.** A half-written range
   rendered a one-day video. Now refused: `start and end must be given together`.
4. **`days: 0` and `days: "soon"` produced the wrong error / a raw `ValueError`.** `days: 0`
   claimed the key was missing (because `if raw.get("days")` is falsy for `0`), and a
   non-numeric value escaped as an unhandled `int()` error. Both now name the field and the
   reason. Fixed by a `_present()` helper that distinguishes *absent* from *falsy* — the same
   bug class as (3).

A fifth, caught before committing: the scaffold's narration headers used ASCII `-`/`.` and
its runtime window was guessed from `tf.days`, so the scaffold failed its own parser and its
own runtime check. Now it emits real `—`/`·`/`–` and sizes the window from the narration's own
word count at 2.5 words/sec — the same constant the silent-cut path actually uses.

### The MCP surface got the same contract

`vidkit build` accepts `from_stage` and `refresh`, refuses `only` and `from_stage` together,
and the tool description names both. An agent that can select stages must also be able to say
"do not trust what is on disk" — otherwise R-B3 only holds for humans.

### Evidence in CI, not in a claim

Two new steps, both of which *prove* something rather than assert it:

- **Re-render offline, and refuse a stale snapshot.** The probe uses a provider that
  **appends to a canary file** every time it runs. A log line saying `reusing snapshot` is a
  claim; an unchanged file is a fact. Four cases: `--only panels` re-renders without touching
  the source, a stale window is refused *by name* before the source is touched, `--refresh`
  asks again, and a deleted snapshot is refused by path without a silent refetch.
- **A missing secret fails loudly, a present one is never printed.** Covers the two halves
  that matter: an exported-but-**empty** variable is not "set", and the value is masked in a
  provider's own exception text — the leak path that actually happens.

### Documentation

New `docs/authoring/stories-and-timeframes.md` (registered in `docs/modules.yaml`), and
updates to `spec-reference.md`, `narration-and-captions.md`, `concepts.md`, `cli-reference.md`,
`verification.md`. The `timeframe` key, the precedence rules, and the three things narration
may say about time are all documented where an author or an agent will look for them.

---

## 2026-10-06 — M2: provider, secret and snapshot hardening

**Branch:** `phase/m2-provider-hardening` → PR → `main`.

M1 made a build *aimable*. M2 makes its **data** trustworthy, which is what has to be true
before an agent is allowed to drive the provider seam.

### The four things that changed

**1. A snapshot records the request it answers (R-B3).** `_build/data/_snapshot.json` holds
`{provider, provider_sha256, timeframe}` beside a hash per dataset. A stage about to reuse
on-disk datasets compares its own request against that record and refuses when it differs:

```
datasets for "biggest" were fetched with a different timeframe
  recorded: 2026-08-01 to 2026-09-30 (61 days)
  wanted:   2026-09-07 to 2026-10-06 (30 days)
re-run with --refresh, or build without --only so the data stage runs.
```

The key is deliberately narrow. Provider identity, provider *source* hash, and the resolved
window. A chart title is not part of it — a cosmetic edit must never refetch a source.

**2. Secrets are declared and masked (R-B4).** A need is declared in the spec's
`provider.secrets` (so `doctor` and `plan` work without importing provider code) *and* the
module's `secrets()`; the two are merged. Resolution is from the environment only. An empty
string counts as **unset**. `Secrets.redact()` masks by longest value first and is applied to
provider *exception text* as well as engine messages. `doctor` prints a masked inventory and
exits non-zero on a missing required variable:

```
secrets:
  ACME_TOKEN       set (43 chars)
  ACME_BASE_URL    NOT SET — required
```

`provider.write_back: true` is now refused at load time — the engine never writes to a source
system.

**3. Degradation is declared, recorded, and only fatal by request (R-B5).** A provider may
raise `SourceUnavailable` and return a value it *declared* via `fallback_for(name, ctx)` or
`fallbacks(ctx)`. If it does not, the build fails. A fallback *used* is recorded in
`ctx.degraded`, which reaches `verify.json` as `facts.degraded`; `guard.require_live_data: true`
turns any degradation into a verify failure. The default is `false`, because hello-world's
provider *synthesizes* its series and is authored, not degraded.

**4. Stages are resumable.** `--from STAGE` selects a suffix; `--refresh` re-adds the `data`
stage; the two are mutually exclusive with `--only`.

### Evidence, not assertion

| Probe | Result |
|---|---|
| `python3 -m pytest tests -q` | **124 passed in 0.70 s** (was 84; **+40** in `tests/test_providers.py`) |
| `python3 -m vidkit build examples/hello-world/video.yaml --only panels,clips,render` | exits 0 in **99.20 s**, logging `[vidkit] datasets: reusing snapshot` — the offline exit criterion |
| same, after editing the spec's window | exits **2**, refusing with the sentence above |
| same, with `_build/data/` deleted | exits **2**, naming the data dir — never silently refetching |
| same, with `--refresh` | refetches, then renders |
| `python3 -m vidkit doctor examples/hello-world/video.yaml` | prints the masked secrets section |
| the new CI steps, extracted and executed locally | `OFFLINE RE-RENDER OK`, `STALE SNAPSHOT REFUSED`, `MISSING SNAPSHOT REFUSED`, `REFRESH OK`, `SECRET CONTRACT OK` |

### Defects found and fixed while building it

1. **`load_datasets` fell back to a built-in sample.** A chart whose dataset was absent
   rendered a *plausible* chart from canned numbers. That is exactly the fabrication D16
   forbids, hiding behind a green build. It now raises a `SpecError` naming the missing file.
2. **`Spec.provider` was a bare `str`.** It could not carry `secrets` or `write_back` without
   the spec growing parallel top-level keys. Now a `ProviderSpec`, with `provider_name` kept
   as the derived display string so no call site had to guess.
3. **A provider exception's text reached the log unredacted.** With secrets in scope this is a
   leak path: a `401` message that echoes the token it sent. `collect_datasets` now redacts.
4. **`{}` for `provider:` was treated as a named module.** An empty mapping produced a
   provider literally named `""`.

### Documentation

`docs/authoring/provider-guide.md` now documents the seam as a *contract* — `secrets()`,
`fallbacks`, secrets and redaction, when the source is down, and datasets/snapshots/staleness.
Also updated: `spec-reference.md` (the long-form `provider:` block, `require_live_data`),
`cli-reference.md` (`--from`, `--refresh`, the staleness rule, exit code 2),
`verification.md` (`all datasets live`), `concepts.md` (the state map and the boot sequence).

### Decisions taken

**D20** secrets are declared, environment-resolved, and masked everywhere. **D21** a snapshot
records the request it answers, not just the data. **D22** degradation is declared in advance,
recorded, and only fatal by request.
