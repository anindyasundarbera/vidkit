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

---

## 2026-10-07 — M3: Capture v2 — **COMPLETE**

**Goal.** Make real product *behaviour* recordable, not just real product *screens*. The exit
criterion: a spec can capture a real downloaded file and film it, with no bespoke script.

Branch `phase/m3-capture-v2` → PR → merged to `main`. Requirements R-C3…R-C8.

### What was built

| Area | Change |
|---|---|
| Spec | `Action` gained `timeout`, `state`, `save_as`, `assert_`; new `action` kinds `wait_for` and `download`; `Capture` gained `artifact`, `storage_state`, `allow_login`, `deterministic`, `take`, and a now-optional `url` |
| Spec validation | `_validate_captures()` — duplicate names, `take < 1`, `url`/`artifact` exclusivity, an `artifact:` no `download` produces, a missing `storage_state`, a `save_as` containing a path separator, and a password-shaped fill with no declared session |
| Capture | rewritten: `freeze_script`, `wait_for`, `apply`, `download`, `artifact_name` (traversal defence), `sniff`, `artifact_page`, `_body_for`, `_parse_row`, `rasterize_pdf` (pdftoppm → gs → refuse), `artifact_source`, `shoot_artifact`, `take_name`/`choose_take`, `digest`, `capture_one`, `capture_all` |
| Ordering | artifact captures run **after** every URL capture, so a producer always precedes its consumer |
| Context / CLI | `Context.capture_artifacts`; a new `vidkit auth` subcommand that records a Playwright storage state by hand, with `_warn_if_secret` and a repo-relative hint |
| Scaffold | `vidkit init` now writes `.auth/` into the story's `.gitignore` |
| Assembler | `Assets.artifacts` records what each capture filmed |
| Verify | new check `filmed artifacts are real files`, emitted only for a spec that declares an artifact |
| Fixture | `examples/capture-kit/` — a stdlib-only server whose table fills after first paint, with a real CSV and a real one-page PDF download, plus a 5-capture spec and a 3-scene narration |
| Tests | `tests/test_capture.py`, **74 tests**; suite **198 passed in 1.71 s** (P6 holds) |
| CI | a third job, `capture-probe`: installs poppler + Chromium, films the kit, asserts the artifacts are real, and asserts a deliberately-wrong assertion fails the build |

### Exit criterion — proven against a real Chromium

Playwright was installed into a scratch virtualenv (`/tmp/venv-pw`) so this was verified by
actually driving a browser, not by a fake page object.

| Claim | Evidence |
|---|---|
| The whole flow records | `vidkit build examples/capture-kit/video.yaml` → exit 0, `capture-kit.mp4` 227 374 B |
| A real download is real bytes | `_capture/artifacts/usage.csv` 158 B, header + exactly 5 rows |
| A downloaded PDF is a real PDF | `summary.pdf` 1104 B starting `%PDF-`; `pdftotext` shows the real summary |
| An artifact is filmed as itself | `csv_page.png` 66 496 B; `pdf_page.png` **1275×1650**, the PDF's own text rasterised |
| A wrong state stops the build | a spec asserting `#summary contains 'nine hundred rows'` → exit 1, `… (saw '5 rows · 7016 visits · 395 signups')` |
| The suite is green | `python3 -m pytest tests -q` → **198 passed in 1.71 s** |
| CI asserts all of it | every `capture-probe` `run:` block extracted and executed locally: `CAPTURE OK` |

### Defects found and fixed while building it

1. **8 failures in the new test file itself, found on its first run.** A `_page()` helper
   signature, a `shoot_artifact` arity, a `rasterize_pdf` test monkeypatching `shutil.which`
   when the code branches on `pdftoppm`, and a `capture_all(object())` that passed an object
   where a real spec was needed. All fixed; and the rasteriser now has an explicit
   ghostscript-fallback test rather than an assumed one.
2. **The fixture's HTML constant used `{{`/`}}` escaping with no `f` prefix**, so the browser
   received a literal `${{r.day}}` and raised `Uncaught SyntaxError: Unexpected token '.'`;
   the table never filled. Found **only** by running a real browser — the fake-page unit tests
   could not see it.
3. **The fixture's `load()` removed an element that was already gone**, so the second *Apply*
   click threw `TypeError: Cannot read properties of null` and silently left `#summary` at its
   first value. Also invisible to unit tests.

Defects 2 and 3 are the argument for the new CI job, restated as evidence: unit tests with a
fake page object were **green** while the real page was broken twice.

### Documentation

`docs/capture/capture-guide.md` rewritten (119 → 292 lines): the full capture field table, the
action table with `wait_for` and `download`, per-action `assert`, the downloads and artifacts
guarantees, signing in without filming a login, the determinism table, takes, browser
discovery, resolution, reliability tactics, debugging, and the worked example. Also updated:
`spec-reference.md` (`captures[]` rewritten), `cli-reference.md` (`vidkit auth`),
`verification.md` (the new check), `troubleshooting.md` (six new failure rows and three
scenarios), `concepts.md` (a new principle, "an artifact is filmed as itself, or not at all"),
`architecture.md`, `pipeline.md` (the capture stage and its guarantees), `mcp-server.md`,
`recipes.md` (two new recipes), `modules.yaml`, `README.md`, and `CHANGELOG.md`.

### Decisions taken

**D23** an artifact is filmed as itself, or not at all. **D24** a take is named, and promoting
one is explicit. **D25** a login form is filmed only on purpose.

---

## 2026-10-07 — M4: Presentation v2 — **COMPLETE**

**Goal.** Stop the output from looking wrong. M3 fixed what the camera *points at*; M4 fixes
what the audience *sees*. Requirements R-D1…R-D6.

Branch `phase/m4-presentation-v2` → PR → merged to `main`.

### What was built

| Area | Change |
|---|---|
| FFmpeg | `_PAD_COLOR`; `FITS`; `fit_filters()`; `still_to_clip(..., fit=)` with `cover` (scale-up + centre-crop), `contain` (scale-down + letterbox) and a `zoom` branch that fits into the enlarged box *before* `zoompan`; `clip_geometry`, `still_geometry`, `frame_rgb`; `TRANSITIONS`; `concat_with_transitions()` (a linear `xfade` chain); `overlay_clip()` |
| Overlay | **new module `vidkit/overlay.py`** — `banner_size`, `banner_svg` (a translucent, never-full-width panel), `svg_size` |
| Spec | `Shot.fit`; `Overlay` + `_overlay()` validation with the `overlay image not found: <src>` refusal; `Scene.overlay`; `Project.transition` / `transition_seconds` with refusals for an unknown name and for a duration outside 0.05–2.0 |
| Assembler | new `_clip_plan(ctx, assets)` — the whole run laid out as `(scene, idx, shot, seconds)` **before** anything renders, because a dissolve overlaps two takes; `_build_clips` composites the overlay and pads the **outgoing** take of each junction; `_concat` picks the xfade chain |
| Panels | `_DATE_FORMATS`, `parse_x`, `axis_positions`; `render_line_series` interpolates in real time; `options.x_axis: index` opts out; three new kinds — `render_progress`, `render_comparison`, `render_quote` — registry now **11** |
| Verify | new check `frames are the declared size` (fact `video_size`) |
| Fixture | `examples/capture-kit/video.yaml` marks its `csv_page`/`pdf_page` shots `fit: contain`, because for those the whole document body is the claim |
| Tests | new `tests/test_ffmpeg.py` (18, filter graphs **and** pixels read back), new `tests/test_presentation.py` (60), `tests/conftest.py` (pytest's `basetemp` moved out of `/tmp`), `test_core.py` panel test widened to 11 kinds — suite **278 passed in 37.56 s** |

### Exit criterion — read back off the pixels, not the filter string

A filter that *looks* right is not evidence, so every visual claim here was measured off a
real render at 320×180:

- A two-scene `fade`, both scenes 2.0 s of measured narration, produces a track of
  **`(320, 180)` and `4.00 s`** — exactly the narration. Across t = 2.0 → 2.6 s the seam goes
  `(253,0,0) → (253,0,0) → (167,0,83) → (0,0,254)`: a genuine dissolve.
- `wipe` at t = 2.3 shows red at x=20 and blue at x=300 **in the same frame**; `cut` at the
  same instant shows one colour across all of it. A boundary and a blend are different claims.
- A `640×360` clip with a `640×100` banner: row 40 is still the shot, row 310 is the banner.
  Setting `fade` far beyond the clip length still leaves the banner on screen, because the
  fade is clamped to a third of the scene.
- `--from concat` on an overlaid, dissolving spec yields the same duration and the same
  banner, because the pre-overlay takes live in `clips/base/` and the concat glob only sees
  `clips/scene-*.mp4`.
- `frames are the declared size` passes a correct film and fails a `320x180` one naming the
  real size.

### Defects found and fixed while building it

1. **The snap ffmpeg cannot write into `/tmp`.** Every real-render test failed for a reason
   that had nothing to do with the code. Fixed by `tests/conftest.py` redirecting pytest's
   `basetemp` to `<repo>/.pytest-tmp`.
2. **Padding the *incoming* clip made the next picture appear early** — measured: blue on
   screen at 1.9 s instead of 2.0 s. Found by a smoke build, fixed by padding the **outgoing**
   take, which is what keeps the runtime identical to the narration. Recorded as **D28**.
3. **My own `_dominant()` helper was wrong**, `max(("red", r), ("green", g), ("blue", b))[0]`
   — tuples compare by name first, so `("red", 0)` beat `("green", 126)` and every green pixel
   reported as red. Fixed to `max(..., key=lambda kv: kv[1])[0]`. A test helper that lies is
   worse than no test.
4. **Two overlay filter-string tests read `rec.cmds[0]`**, the wrong command; fixed to
   `rec.cmds[-1]`.
5. **One transition assertion asserted the wrong offset** (`2.000` where the rule gives
   `1.500`). The code was right and the expectation was wrong; corrected with the rule
   written out in the comment.

Defects 2–5 are the same lesson twice over: check whether the *test* or the *code* is wrong
before changing either.

### Documentation

`docs/authoring/spec-reference.md` (`fit:`, `overlay:`, `project.transition` /
`transition_seconds`, with a table of what each transition *claims*), `panels-reference.md`
(the date axis, `x_axis: index`, the three new kinds), `pipeline.md` (the clip plan, the
overlay composite, `xfade` at concat), `concepts.md` (a new principle — a graphic states a
fact and never substitutes for footage), `verification.md` (the new check row),
`architecture.md` (22 modules, the overlay module, the new ffmpeg surface), `README.md`,
`ROADMAP.md` (§3.3 gap rows struck, §3.4 ticked), `AGENTS.md` (repo map and the snapshot),
`CHANGELOG.md`, `PLAN.md`, `FEATURE-ROADMAP.md`.

### Decisions taken

**D26** an overlay is drawn over a shot, never instead of one. **D27** a still is fitted,
never stretched. **D28** a transition is a beat, and it never changes the runtime.

---

## 2026-10-07 — M5: the agent surface

**Phase.** M5 ([FEATURE-ROADMAP.md](FEATURE-ROADMAP.md) §8) — **complete**. Requirements
R-G1 (MCP), R-G2 (`--json`), R-G3 (job contract), R-G4 (`init`), R-G5 (progress/cancel),
R-G6 (structured errors).

### What was built

- **`vidkit/job.py` (new).** One call, `{action, story, out}`, returning one manifest whose
  base keys are always present: `action, ok, story, out, spec, timeframe, artifacts, report,
  timeline, failure, progress, vidkit`. Actions live in `ACTIONS` (`plan, build, capture,
  tts, verify, doctor, init`); `needs_spec("init"|"doctor")` is `False`, so a pre-flight check
  works before a story exists. `refused(...)` builds the same manifest for a call that never
  reached the pipeline — a timeout, say — so a caller's error handling needs no second branch.
- **Progress as data (R-G5).** `Progress` collects `{name, kind, ok, detail, seconds}` steps;
  `_LineTicker` + `reporting()` capture the pipeline's own stdout for the block and classify
  each `[vidkit] …` line as `stage` / `check` / `warn` / `log`. `on_progress` is the *only*
  way a run's log leaves `run_job` — so `--json` is pipeable by construction (D30).
- **CLI (R-G2).** `vidkit run ACTION`; `--json` and `--progress` on every command, accepted
  before *or* after the verb via a shared `parents=[common]` parser with
  `default=argparse.SUPPRESS`. `_COMMAND_ACTION` maps verb → action, so `--json` and `run`
  agree by construction. `_exit_code`: `0` done, `1` refused, `2` ran but did not verify.
- **MCP (R-G1).** `vidkit_run`, `vidkit_actions`, `vidkit_init`, `vidkit_capture_plan`
  (14 tools), a `vidkit://actions` resource, `progress=True` on `vidkit_run`/`vidkit_build`,
  and a bounded `timeout` so a runaway build refuses instead of hanging the client.
- **`doctor` (R-H2).** Declared **secrets** appear as a tool row — present or missing, never
  the value — and a missing required secret folds into the verdict.
- **Docs (R-G6).** New `docs/operations/job-contract.md` (manifest keys, failure vocabulary,
  exit codes, progress contract), routed through `docs/modules.yaml`; `cli-reference.md` and
  `mcp-server.md` brought up to date; `CHANGELOG.md`, `PLAN.md`, `FEATURE-ROADMAP.md` §8.

### Evidence

| Claim | How it was checked | Result |
|---|---|---|
| `init → build → verify` from a shell, no prose parsed | `--json run init` → `run plan` → `--json --progress run build` → `run verify` | exit codes `0 0 0 0 0`; the story `init` writes builds and verifies unedited |
| stdout stays pure under `--progress` | the same build, stdout piped to `json.load`, stderr to a file | JSON parsed; 23 log lines on stderr |
| `doctor` needs no story | `--json doctor` in a story-less directory | `ok: true`, `spec: null` |
| A refusal is data, not an exception | `run_job("plan", story="does-not-exist")` | `ok: false`, `failure.kind == "tool"`, a `hint` |
| A refusal still reports the window asked for | `run_job("plan", story=EXAMPLE, timeframe="7d")` on a spec that pins a different window | `ok: false` **and** `timeframe.source == "override"`, `days == 7` |
| The base keys are the contract | `BASE_KEYS <= set(manifest)` for a success and a refusal | holds |
| A manifest survives JSON | `json.loads(json.dumps(manifest))` | round-trips |
| A timeout returns a manifest, not a hang | `tool_run("build", timeout=0.05)` with `run_job` stubbed to sleep | `ok: false`, `failure.kind == "tool"`, `"did not finish within"` |
| `timeout=0` means unbounded | the same test with `timeout=0` | `ok: true` |
| Suite green | `python3 -m pytest tests -q` | **337 passed** |

### Defects found while building it — both by the shell walk, neither by a unit test

1. **`--json run init` ran a *build*.** `_job_kwargs` read `args.cmd` (`"run"`) where it meant
   the *action* (`args.action`), and `_json_main` hard-coded `"build"` for the `run` verb. The
   unit tests all called the verbs directly, so the one flag combination that carries an
   action of its own was the one combination untested. Fixed by `_action_for(args)`; pinned
   by `test_json_run_init_really_inits`.
2. **`verify` reported an empty `timeline`.** `_do_verify` built its `Assets` by hand and
   never re-read the per-scene spans, so a verify manifest listed `"timeline": []` — an
   account of a film it had not looked at. Fixed by reusing `_load_or_estimate`, the same
   helper the build uses, which is what makes the two accounts of a run agree; pinned by
   `test_verify_reports_the_spans_it_looked_at`.

The lesson from M3 repeats: a walk through the real exit criterion finds what a suite of
unit tests arranged around the code's own assumptions cannot.

### Documentation

`docs/operations/job-contract.md` (new), `cli-reference.md`, `mcp-server.md`,
`docs/modules.yaml`, `CHANGELOG.md`, `PLAN.md`, `FEATURE-ROADMAP.md` §8, `DECISIONS.md`.

### Decisions taken

**D29** a job answers with a manifest, and never raises for an expected refusal.
**D30** progress is the pipeline's own narration, delivered only through a hook.

### A third defect, found by CI rather than locally — the test environment

The first PR for M5 came back red on both `pytest` jobs and green on `build hello-world end
to end` and `film a real page and a real download`. Four tests failed:

| Test | Why |
|---|---|
| `test_verify_reports_the_spans_it_looked_at` | reaches the pipeline; there is no `rsvg-convert` on the `pytest` runner |
| `test_doctor_runs_without_a_story` | asserted `ok is True`; a lean machine is allowed to report a missing required tool |
| `test_json_doctor_needs_no_story` | asserted exit `0`; the same verdict |
| `test_json_matches_plain_run_for_every_read_only_action` | the same, via `doctor` |

None of these are wrong *assertions about the code*; they are assertions about *the machine
the test happens to run on*. The `pytest` job deliberately installs only `-e ".[dev]"` —
fast, and available everywhere — and the render job installs `ffmpeg` and `librsvg2-bin` and
does the building. Every test that reaches the pipeline has to say so.

Fixed by a `needs_render` marker, registered in `tests/conftest.py` and applied by
`pytest_collection_modifyitems` when `ffmpeg` or `rsvg-convert` is absent; by comparing the
two `doctor` paths to each other rather than to zero; and by asserting
`manifest["ok"] == manifest["doctor"]["ok"]`. Reproduced first with a lean `PATH` holding
every binary except `ffmpeg`, `ffprobe` and `rsvg-convert` — 4 failed, 318 passed — and then
fixed until the same command gave 321 passed, 16 skipped.

The lesson is the M5 lesson again, one level up: a green local suite can still be testing
the wrong machine. `AGENTS.md` §4.1 now states the two environments.

---

## 2026-10-07 — M6: hardening & v1.0

**Phase.** M6 ([FEATURE-ROADMAP.md](FEATURE-ROADMAP.md) §9) — **complete**. Requirements
R-F8 (provenance), R-H5 (fresh-clone walkthrough), R-H6 (portability), R-H8/R-H9 (release
metadata), plus the M0–M5 defect debt that had accumulated.

### What was built

- **`vidkit/provenance.py` (new) — R-F8.** `probe_tools()`, `spec_digest()`, `Tool`,
  `Provenance`, written to `OUT/_build/provenance.json` by **every rendering action**. The
  record names the spec and its SHA-256, the resolved window and its source, the provider and
  its digest, the dataset snapshots the run actually used, every tool that could have touched
  the render (present or not, with version), the vidkit version, the action, the stages that
  ran, and the wall-clock duration.
- **Provenance became a first-class action.** `ACTIONS` went 7 → **8** (`plan, build,
  capture, tts, verify, provenance, doctor, init`); `_STAGES` gained an explicit entry for
  every action (a defect, below); the CLI gained the `provenance` verb; `mcp_server` gained
  `vidkit_provenance`. So the same question — "which build is this and what made it?" — is
  answerable from the CLI, from `--json`, from `vidkit_run`, and from a dedicated MCP tool.
- **`verify` reads it, never writes it.** `verify.json` ends with a `facts["provenance"]`
  block carrying the build's identity — a **fact, not a check**, so a verify on a build with
  no record still runs every acceptance check and simply reports `provenance: null`.
- **R-H6, portability.** `capture._find_chrome()` was rewritten to search the real layout on
  all three platforms (`chrome-linux/chrome`, `chrome-mac` **and** `chrome-mac-arm64` under
  the Playwright cache, `chrome.exe` on `PATH`, and the `/Applications` bundles) instead of
  the Linux path only. Platform support is now *stated* rather than implied: a tiered table
  in `docs/operations/troubleshooting.md` says what is tested (Linux, all of CI), supported
  but untested (macOS), and best-effort (Windows) — including the one real degradation, that
  `signal.setitimer` does not exist on Windows, so the MCP run timeout is **not installed**
  there and a job is unbounded. That is named, not hidden.
- **R-H5, the walkthrough.** New `docs/guides/first-video.md`: a fresh clone to a verified
  `.mp4`, twice — once by CLI, once by MCP — using only the docs.
- **R-H8/H9, release.** `0.1.0` → **`1.0.0`** in `pyproject.toml` and `vidkit/__init__.py`;
  `CHANGELOG.md` `[1.0.0] - 2026-10-07`, with a duplicate `[Unreleased]` link block from the
  original 0.1.0 section deduplicated on the way through.
- **CI now asserts the contract, not just that the commands exit 0.** The JSON-walk step
  checks that `build.json` carries a provenance with `action == "build"` and
  `artifacts.provenance_json.ok`; that `verify.json`'s provenance agrees with the build's on
  `spec_sha256`; that `report.facts.provenance.spec_sha256` is present; and that
  `vidkit --json provenance` returns `schema == 1` with all five tools each carrying a
  `present` key.

### Evidence

| Claim | How it was checked | Result |
|---|---|---|
| A build writes a complete record | `vidkit run build` on a scaffolded story, then `json.load` on `_build/provenance.json` | `schema 1`, `action build`, 9 stages, 5 tools, `spec_sha256` matching `sha256sum video.yaml` |
| The record is never invented | `vidkit provenance` before any build | `ok: false`, `hint` "run build first" |
| Every surface agrees | the four readers of one build | identical `spec_sha256`, `built_at` |
| `verify` reports the build it looked at | `vidkit run verify`, read `report.facts.provenance` | `action: "build"`, same digest as the build |
| Provenance is a fact, not a check | a verify whose record was deleted | every check still runs; `provenance: null` |
| The action list is one list | `tool_actions() == actions_help()` | equal — `mcp_server` no longer keeps its own copy |
| `stages` is never *unknown* | `stages_for(a)` for all 8 actions | `[]` for the five non-rendering actions, not `null` |
| Suite green, full toolchain | `python3 -m pytest tests -q` | **359 passed** |
| Suite green, lean `PATH` | the same command with `/tmp/leanbin` (no `ffmpeg`, no `rsvg-convert`) | 337 passed, 22 skipped |
| hello-world still builds | `python3 -m vidkit build examples/hello-world/video.yaml` | `.mp4` + `.narration.srt` + `verify.json`, every check passing |
| The CI chain itself runs | the extracted JSON-walk step with `PATH=/tmp/cibin:$PATH` | `CI_CHAIN_OK` |

### Defects found while building it

1. **`tool_provenance` called `.to_dict()` on a dict.** The new MCP tool assumed the job layer
   returned a `Provenance` object; `run_job` had already serialised it. Every unit test around
   the *reader* passed while the *tool* was broken — the two were tested separately and never
   against each other. Fixed, and pinned by a test that drives the tool against a real build.
2. **`tool_actions` silently had no `stages`.** It built its own rows instead of asking the job
   layer, so the one surface an agent uses to *choose* an action was the one that could not say
   what the action would run. `tool_actions()` now delegates to `actions_help()`, and a test
   asserts the two are equal so they cannot drift again.
3. **`actions_help()` had no `stages` key at all.** An agent asking "which stages does
   verification run?" got a missing key, indistinguishable from "unknown". The *missing key*
   in `_STAGES` was the real bug: `[]` ("this action renders nothing") and absent ("nobody
   said") are different answers, and the code was giving the second one.
4. **`test_provenance_tool_reads_what_build_wrote` passed a spec *file* to a function that
   wanted a *story folder*.** The test built from `examples/hello-world/video.yaml` and then
   read provenance from `.../video.yaml/video.yaml`. Caught by running the full suite rather
   than the file I had been editing. The `hint` in the resulting `ToolError` said exactly
   which path was wrong, which is the job contract doing its work on its own author.
5. **`vidkit provenance SPEC` was advertised and dispatched nowhere.** The plain verb was in
   the usage block, in `--json`, in `ci-reference.md` and in `README.md` — and the parser had
   no handler for it, so `vidkit provenance video.yaml` fell through to `print_help()` and
   returned **`0`**: a success code for doing nothing. Found by running the extracted CI step
   against `/tmp/cibin` rather than by reading it, which is the only way this class of defect
   is ever found. Fixed with a real `_provenance()` and a `format_provenance()` renderer, and
   pinned by `test_every_advertised_verb_is_actually_dispatched`, which parses the usage block
   and asserts every verb in it has a dispatch branch.
6. **The CI step itself was wrong twice.** First it called `vidkit --json provenance
   --story …`, a flag the top-level verb does not take (it takes a positional spec) — the
   first run of the extracted step said `unrecognized arguments: --story`. Then it asserted
   `m['schema'] == 1` against the whole manifest, where `--json` returns the job manifest
   *wrapping* the record, exactly as `verify` does. Both were invisible while the assertion
   was only ever read.

Defects 1–3 share one shape: **a new surface tested only against its own assumptions**.
Defects 5–6 share another: **a command that was written down and never run**. The fix each
time was to drive the *other* surface — which is why the CI step now walks the whole chain
from the shell, through the shim a user would actually type.

### Documentation

`docs/verification/provenance.md` (new), `docs/guides/first-video.md` (new), both routed in
`docs/modules.yaml` (23 docs / 7 modules); `README.md`, `docs/README.md`,
`docs/foundations/architecture.md`, `docs/foundations/pipeline.md`,
`docs/operations/cli-reference.md`, `docs/operations/mcp-server.md`,
`docs/operations/troubleshooting.md`, `AGENTS.md`, `PLAN.md`, `FEATURE-ROADMAP.md`,
`DECISIONS.md`.

### Decisions taken

**D31** provenance is written by the build and only read by everything else.
**D32** platform support is stated, not implied.

### The framing, recorded because it will be asked again

`verify.json` answers **"is this honest?"** — it reopens the render and checks the claims.
`provenance.json` answers **"what is this?"** — it says what was built, from what, by what,
and when. They are two questions and two files. Folding provenance into the report would mean
a re-verify rewrites the build's identity, which is the drift the split exists to prevent.

---

## 2026-10-08 — M7 — Executor & sandbox

**Branch** `phase/m7-executor-sandbox`, off `main` at `6987090`. Merged by PR. Closes
[FEATURE-ROADMAP.md](FEATURE-ROADMAP.md) §10.

**What was built.** A spec can now declare commands to run and film. Two new modules —
`vidkit/exec.py` (26 modules total) — and the first new pipeline stage since M0, taking
`STAGES` from 9 to 10 (`exec` sits between `capture` and `narration`). The whole contract,
with its evidence:

| Claim | Evidence |
|---|---|
| The exec contract is tested | `python3 -m pytest tests/test_exec.py -q` → **68 passed** |
| The renderer is tested | `python3 -m pytest tests/test_terminal.py -q` → **33 passed in 0.20s** |
| Nothing else regressed | `python3 -m pytest tests -q` → **460 passed in 376.30s** (was 359) |
| Lean machines still work | lean `PATH` → **425 passed, 35 skipped in 2.51s** |
| A real recording builds and verifies | `python3 -m vidkit build examples/terminal-demo/video.yaml` → **ALL PASS**, 11 checks |
| The film really contains the recording | the finished `.mp4` sampled at 17 timestamps, each decoded to RGB and matched to its intended frame → **MAE 1.7–3.3**, i.e. pixel-accurate |
| The 4 recorded frames are distinct | `sha256sum` of each PNG differs |
| The sandbox is real | `bwrap --unshare-all` live: network off by default, `sleep 30` → `timed_out=True` at 1.5s with the process group killed |
| CI's exec job runs what it claims | every `run:` block extracted with PyYAML and executed locally → all exit 0 |

**The three defects that only a real render could find.** Each was invisible to the unit
tests, and each produced a *green* build. They are recorded because "a passing verify.json"
was, in all three cases, not evidence that the code worked.

| # | Symptom | Cause | Fix |
|---|---|---|---|
| A | Every exec shot rendered **one blank frame** | `_exec_frames` handed the concatenated raw payload *stream* to `terminal.replay()`, which parses *cast-file text*; `read_cast` returned `[]` | Split the API: `replay_events(events, …)` for the engine, `replay(cast_text)` for files |
| B | The **final** screen never appeared | `replay_events` samples on an interval, so the last screen regularly fell between samples | Append `(events[-1][0], screen)` when `moments[-1][0] < events[-1][0]` |
| C | The final frame was held for **exactly 0.0s** | A print-then-exit command's last frame has a measured span of zero | Interior frames keep their *measured* spans; the **last** frame takes whatever time remains |

Defect A deserves the note: the first fix attempt made `replay()` *sniff* its input format
and dispatch. It was reverted. A cast file carries its own timestamps, and recovering them
from a byte stream loses the measured pace — the film would have been re-timed by an
invisible amount to save one function signature.

**Two more defects, found while writing the tests.** Both are the same shape: **a claim that
could only be verified by a human reading the source**.

| # | Symptom | Cause | Fix |
|---|---|---|---|
| D | The actionable "you declared no `exec:` steps" message was unreachable | The scene-shot loop raised a vaguer error first; `_validate_exec`'s branch was dead | Moved the message into the loop; the dead branch is now a bare `return` |
| E | A **passing** `verify.json` could not attest that the commands ran | `every declared command ran` was added to the report only when it *failed* — indistinguishable from "not applicable" | Emitted whenever `declared` is non-empty, with `"N command(s), all recorded"` on success |

Defect E then exposed a sixth while the CI job was being written:

| # | Symptom | Cause | Fix |
|---|---|---|---|
| F | `playback: null` meant **two different things** | It was null both for a recording replayed as a single held screen *and* for one never shown as a take at all | `report.facts.exec` now also carries `frames`, so "shown as one screen" and "played at 1.0x" read differently |

**Defect F is the same error as E one level down.** E was an attestation that existed only as
an absence; F was a fact whose *null* covered a real distinction. Both make a report that
looks complete while withholding the one thing the reader needs.

**Test authoring.** `tests/test_terminal.py` (33) and `tests/test_exec.py` (68). Eleven
initial failures in `test_exec.py` were diagnosed as **nine test-authoring mistakes and two
genuine engine defects** (D and, separately, the `every declared command ran` check). The
mistakes are worth naming because they were all the same mistake in different clothes —
*testing a function through a path that never reaches it*:

- `check_policy` reports almost every refusal that the *loader* also reports, so a spec round
  trip raised before the function under test ran. Tests now build `Exec` objects directly.
- `argv()` lives on `ExecRequest`, not on the spec's `Exec`.
- A policy test using `max_timeout: 10` failed at load, because steps default to `timeout: 60`.

The parser was probed empirically before its tests were written, and two of the initial
expectations were wrong — both mine, not the engine's. `feed(b"first")` then `feed(b"\rlast")`
leaves `"lastt"`, not `"last"`: a carriage return does not erase a longer previous line
without an `\x1b[K`. Both behaviours are now pinned as-is, with the reason written down.

**One test that was itself dishonest.** The bwrap write-refusal test asserted a permission
error. It was not a permission error: the target path was outside the sandbox's mounts
entirely (tmpfs `/tmp` versus a repo-relative `.pytest-tmp`), so the shell reported
`Directory nonexistent` (exit 2). The test was rewritten to assert the *honest* claim — the
file is unchanged — and a second test was added targeting `/usr/share/…`, which **is**
mounted read-only, so the permission half is still pinned. **bwrap's refusal wording is not
stable and must not be asserted.**

**Documentation.** `docs/capture/exec-guide.md` (new, routed: 24 docs / 7 modules);
`docs/authoring/spec-reference.md` (the `exec` block and shots, four new guard rows);
`docs/verification/verification.md` (three new checks); `docs/modules.yaml`; `AGENTS.md`
(the two new modules, the 10 stages, §6 snapshot, and six new §4.4 gotchas); `CHANGELOG.md`;
`FEATURE-ROADMAP.md` §10. `pyte` was considered for the screen model and **deliberately not
taken** as a dependency.

**CI.** A fourth job, `exec-probe`, installs `bubblewrap` and asserts the recording is
really in the film. All of its `run:` blocks were extracted and executed locally before
being pushed, which is how defect F was found.

**Decisions taken.** **D33**–**D40**.
---

## M7 CI findings — a presence check is not a capability check (defect G)

**2026-10-08.** Context: M7, PR #7, first push.

The M7 branch passed locally and failed CI in three jobs at once. Root-causing them took
longer than writing the fixes, and the reason is worth recording: **they looked like one
failure and were three, and the third was in the workflow rather than the engine.**

### What was actually wrong

| # | Job | Symptom | Cause |
|---|---|---|---|
| 1 | `pytest (3.10)` and `pytest (3.12)` | the *same* 26 failures | the `needs_render` skip key was the wrong key. Those 26 tests need a **sandbox**, not a renderer, so a job that installs no ffmpeg skipped the wrong set — and would have skipped them in a job that installs one |
| 2 | `exec-probe` | the build succeeded, the film was made, and all three recorded commands exited 1 | `bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted` |
| 3 | `exec-probe` | the job's own "the sandbox really is here" gate **passed** on a runner where no sandbox could start | the gate asked where the file was rather than whether it ran |

**Reproduced byte-for-byte before any fix.** A directory holding symlinks to everything but
`bwrap` (`/tmp/lean7`) turned 26 failures up locally where CI saw 26:
`38 passed / 33 skipped` after the fix, `26 failed / 35 passed / 7 skipped` before.

### What the runner is

Established with a temporary diagnostic workflow (four commits, deleted before merge):

- `ubuntu-latest` is `ubuntu-24.04` image `20260927.320.1`, and it does **not** preinstall
  `bubblewrap`. An earlier note in `ci.yml` and `FEATURE-ROADMAP.md` claiming it did was
  simply wrong and has been corrected.
- `/proc/sys/kernel/apparmor_restrict_unprivileged_userns` is **`1`**. Consequently *every*
  rung of the ladder fails, including the bare `bwrap --dev /dev --ro-bind / / /bin/true`:
  `bwrap: setting up uid map: Permission denied`.
- `--unshare-user-try` does not help. Wrapping the whole thing in an outer
  `unshare --user --map-root-user` does not help.
- `sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0` **does** work
  (`before: 1` → `after: 0`), and the runner grants passwordless `sudo`.

This is a fact about the host, not a defect in vidkit. But it made a defect in vidkit
visible: `bwrap` being installed and `bwrap` being *usable* are different questions, and
vidkit was answering the first while acting on the second.

### The fourth bug, which nobody reported

While wiring the fix, `grep -rn backends_ vidkit/` returned **only the definitions**. The
docstring of `backends_report()` said "for doctor and provenance" and **no code called it**.
So `vidkit doctor` never mentioned the sandbox, and a spec declaring `backend: bubblewrap` on
Ubuntu 24.04 died mid-build with a `SpecError` instead of being refused up front. This is
defect G's other half, and it was invisible precisely because the function worked.

### Defect G — `available` meant "is the file there?"

Fixed in five places:

1. **`exec.py`** — `bwrap_available()` actually starts a sandbox around `/bin/true`, through
   the engine's *own* `_bwrap_argv`, so the probe answers a question about the engine and not
   about itself. Memoised in `_PROBE_CACHE` (a real probe costs **14.1 ms**; a whole-pipeline
   probe would cost ~2 s — this is why the probe tests one harmless command rather than the
   pipeline). `_explain_bwrap_failure()` recognises the AppArmor signature and names the
   sysctl. `resolve_backend()` consumes it, so the load-time refusal now distinguishes
   *missing* from *cannot start*.
2. **`reports.py`** — `doctor_report` gains a `backends` block that gates `ok`, and
   `format_doctor` prints a `sandbox` line. It is answered **with or without a spec**,
   because it is a fact about the host: `available` is the host question, `ok` is the spec
   question, and a `local`-only spec passes where the host itself cannot sandbox.
3. **`tests/conftest.py`** — a `needs_sandbox` marker, probed by the engine. The two markers
   are now applied **independently**: the old `pytest_collection_modifyitems` early-returned
   as soon as render tools were present, which is exactly the bug class it was written to
   prevent, one layer up.
4. **`tests/test_exec.py`** — the autouse `_fresh_probe` fixture, because `_PROBE_CACHE` is
   memoised and a test that patches `shutil.which` must invalidate it. The six PTY tests lost
   `needs_render`: they use `backend: local` and absolute binaries, so the marker was hiding
   them from the lean job for no reason. The old `skipif(not _HAVE_BWRAP)` guards — a
   *presence* check — are gone.
5. **`ci.yml`** — a `Let unprivileged user namespaces exist` step and a gate that calls
   `bwrap_available(refresh=True)` and fails honestly.

### Also fixed at the same time

`check_policy` reported the host's backend refusal **once per command**. Three commands on a
machine that cannot sandbox is one problem, and repeating it buried the real per-command
refusals under identical text. It is now stated once, last, as `backend bubblewrap: …`.

### Evidence

```
pytest tests/test_exec.py -q                 → 71 passed in 4.24s
env -i PATH=/tmp/lean7 … pytest             → 38 passed, 33 skipped   (was 26 failed)
     … and the 6 PTY tests PASSED, not skipped
env -i PATH=<bwrap + python3 only> …        → 71 passed   (the markers are independent)
python3 -m pytest tests -q                  → 463 passed in 382.10s
vidkit build examples/hello-world/video.yaml --out _hwcheck   → exit 0
examples/terminal-demo/_build/verify.json   → ok: true, 11 checks, all PASS
```

Decisions taken: **D41**. The diagnostic workflow was deleted before the merge.


---

## 2026-10-07 — M7 merged: the first honest capability gate

**PR [#7](https://github.com/anindyasundarbera/vidkit/pull/7)** →
`main` @ **`40cf724`** (merge commit, parents `6987090` + `dab77b0`).

The branch was pushed, failed CI on three of five jobs, was fixed, was force-pushed
(`--force-with-lease`) as `dab77b0`, and merged only after the re-run went green. The
diagnostic workflow that produced the runner facts below was added, used, and deleted —
its history was rebased away, so the merge commit has no trace of it. **This section is
the evidence of record.**

### The CI outcome, as observed

| Job | First run (`37578714492`) | After the fix (`37581822650`) |
|---|---|---|
| `pytest (3.10)` | **fail** — 26 tests | pass, 17 s |
| `pytest (3.12)` | **fail** — 26 tests | pass, 17 s |
| `exec-probe` ("run a real command and film it") | **fail** — 3 commands, all exit 1 | pass, 43 s |
| `capture-probe` ("film a real page and a real download") | pass | pass, 1 m 26 s |
| `build-example` ("build hello-world end to end") | pass | pass, 4 m 29 s |

### What the runner actually is

Established on the runner, not inferred:

| Claim | Evidence |
|---|---|
| `ubuntu-latest` resolves to `ubuntu-24.04`, image `20260927.320.1` | diagnostic workflow, `lsb_release -a` |
| Bubblewrap is **not** preinstalled | `which bwrap` → absent; the old `ci.yml` comment saying otherwise was wrong and is corrected |
| Unprivileged user namespaces are restricted | `/proc/sys/kernel/apparmor_restrict_unprivileged_userns = 1` |
| Every `bwrap` rung fails, including the minimal one | `bwrap --dev /dev --ro-bind / / /bin/true` → `setting up uid map: Permission denied`; `--unshare-all` → `loopback: Failed RTM_NEWADDR: Operation not permitted` |
| `--unshare-user-try` and an outer `unshare --user --map-root-user` do **not** help | diagnostic workflow, both attempted |
| `sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0` **does** help | diagnostic workflow; confirmed in the fixed `exec-probe`, which prints `before: 1` / `after: 0` |
| A real capability probe costs **~14.1 ms** | measured; a whole-pipeline probe would cost ~2 s, which is why `doctor` probes one harmless command |

### The fixed job, verbatim

```
before: 1
kernel.apparmor_restrict_unprivileged_userns = 0
after:  0
sandbox OK — {'name': 'bubblewrap', 'available': True,
              'detail': '/usr/bin/bwrap ran a confined command'}
  [PASS] commands ran sandboxed — 3 command(s) under bubblewrap
EXEC OK — 3 commands, all sandboxed, all replayed
```

### The general rule this produced

> **When a capability gate decides whether an honest build is possible, it must
> demonstrate the capability, not observe a precondition of it.**

`shutil.which("bwrap")` observes a precondition. Running one confined command demonstrates
the capability. The same rule will govern M8: Docker must be probed with
`docker run --rm hello-world`, never `which docker` — a daemon that is installed and not
answering is the identical bug in a new costume. Recorded as **D41**.

### Local verification at merge time

```
python3 -m pytest tests -q                                    → 467 passed in 377.47 s
env -i PATH=/tmp/lean7 … python3 -m pytest tests -q          → 428 passed, 39 skipped
env -i PATH=<bwrap + python3 only> … pytest tests/test_exec  → 73 passed
```

The third is the decisive one: it shows the two skip markers are genuinely independent,
where the old implementation early-returned as soon as render tools were present.

### Still owed to the owner

- **The `v1.0.0` tag has still not been pushed.** The code is `1.0.0` and merged; the tag is
  a separate visible act and remains the owner's to make.
- **M7 sits in `CHANGELOG.md` under `## [Unreleased]`.** Whether it becomes `1.1.0` at
  release is the owner's call; folding it into `1.0.0` would make the tag and the release
  notes disagree.

### A dated risk, from the run's own annotations

GitHub announced that **`ubuntu-latest` migrates to Ubuntu 26 beginning 2026-10-19**. Every
runner fact in the table above is a statement about Ubuntu 24.04. When the image moves, the
AppArmor restriction may change shape and the `sudo sysctl` step may become a no-op — or
unnecessary. The `exec-probe` step prints the sysctl value *before* and *after* for exactly
this reason: the log alone should say what happened.

---

## 2026-10-09 — M8: the environment lab (Docker as a first-class backend)

**Branch:** `phase/m8-docker-lab` off `7e46276` (PR #8's merge).
**Goal (FEATURE-ROADMAP §11):** a spec can declare a *service* — a container — and run
commands *inside* it, so a demo whose claim is "step 1 wrote a row and step 2 read it back"
is a claim about one real database. Plus the `env`/`ports`/`volumes`/`ready` contract, and
`doctor` reporting the three Docker questions separately.

### What landed

| Area | Change |
|---|---|
| `vidkit/exec.py` | `EnvSpec` / `EnvState`; `docker_client`, `docker_daemon`, `docker_available`, `docker_rungs`, `image_digest`, `_docker_argv`, `_docker_create_argv`, `_docker_run`, `_docker_workdir`, `_docker_volume_args`; `environment_up`, `_await_ready`, `_docker_probe_command`, `container_health`, `container_logs`, `capture_logs`, `environment_down`, `environments_running`; `bind_step` / `unbind_environments`; `_env_for`'s docker branch; `CONFINING_BACKENDS`; `READY_HOLD`, `DOCKER_*`, `PROBE_TIMEOUT` |
| `vidkit/spec.py` | `EXEC_BACKENDS` + `docker`; `Environment`; `Exec.environment`; `Spec.environments` / `Spec.environment()` / **`Spec.exec_environment(label)`**; `_environment()`; `_validate_exec()` environment checks |
| `vidkit/assembler.py` | `Assets.environments`; the `_exec_stage` split (`_start_environments` / `_run_exec_steps` / `_capture_environment_logs` / `_stop_environments`); `_env_spec`; `_env_of`; per-step `bind_step`; unconditional teardown |
| `vidkit/verify.py` | `_container_of(spec, assets, result)`; `facts.exec[].container`; the `facts.environments` block; `commands ran sandboxed` reads `exec_mod.CONFINING_BACKENDS` |
| `vidkit/reports.py` | the docker `doctor` row + `_image_list()`; `_backends_line()`; `_sandbox_needs(spec)` |
| `vidkit/provenance.py` | `commands` gained the image/digest and the environment each command ran in |
| `tests/` | **`test_docker.py`** (~50 tests); `conftest.py`'s third independent marker `needs_docker`; two `test_exec.py` tests pinning `exec_environment` |
| `examples/docker-demo/` | Postgres 16-alpine, written to and read back inside **one** container, torn down on every exit path |
| `.github/workflows/ci.yml` | the **`docker-probe`** job (the sixth) — capability ladder, engine gate, build, artifact assertions, leak check |
| docs | `exec-guide.md` **§10 Environments**; `spec-reference.md`'s `environment[]` section; `verification.md`'s two new fact blocks; `AGENTS.md`'s eleven new gotchas; this entry; **D42–D48** |

### The defect list — fourteen found

This phase's most valuable output is not the feature; it is the list of ways the feature was
wrong before it was right. Each was found by running the thing, not by reading it.

| # | What was wrong | How it was found | Fix |
|---|---|---|---|
| **H** | `AttributeError: 'EnvState' object has no attribute 'image'` in `_start_environments` | first end-to-end build | `state.spec.image` |
| **I** | Readiness was a **single sample**, and Postgres answers `pg_isready` against a *bootstrap* server ~150 ms before the real one is up | measured `pg_isready` / `SELECT 1` timings by hand | `READY_HOLD = 0.75 s` → **D43** |
| **J** | `verify`'s sandbox check hard-coded `bubblewrap` | the docker fixture failed its own check | `CONFINING_BACKENDS` in the engine → **D42** |
| **K** | A crash between `docker run` and `bind_step` **leaked a container**; teardown covered only the happy path | inspected `docker ps -a` after a refusal | nested `try/finally`; `started` recorded pre-readiness → **D45** |
| **L** | `_start_environments` ignored its own new `started` parameter | the teardown test | `state.__dict__.update(got.__dict__)` |
| **M** | The binding was keyed by *environment name*, so a step's declared `env:` was not what its container actually got, and the image never reached provenance | wiring `_write_provenance` | `bind_step(label, state)`, keyed by **command label** → **D46** |
| **N** | `Environment.logs_panel` and `Environment.at` were parsed, accepted and honoured **nowhere** | reading the dataclass against the stage | removed from the dataclass, the `known` set and the constructor |
| **S** | `backend: docker` ran **`docker docker exec …`** — the argv builder already began with `docker` and the runner prepended another | the docker suite: exit 125, `unknown shorthand flag: 'w'` | probe through `_launch_argv` → **D44** |
| **T** | The container **never received the declared environment** — `docker exec` does not inherit the client's, and only `req.env` was forwarded | `test_..._does_not_inherit_the_hosts_home_or_paths` | `_docker_argv` emits `-e` per `_env_for(...)` entry → **D47** |
| **U** | A **single** readiness failure both cleared `ready_since` *and* overwrote `ready_detail`, making the "answered but never held" branch unreachable | reasoning about the branch while writing its test | key the branch on `answered_at` → **D43** |
| **O** | `docker exec -t` needs a terminal on *Docker's* stdin (`_docker_run` passes `DEVNULL`) → every probe exit 125, `cannot attach stdin to a TTY-enabled container` | the docker suite | `tty=False` keyword on `_launch_argv`/`_docker_argv` |
| **P/Q/R** | Three **test-harness** faults: `textwrap.dedent` measured the common indent across *every* non-blank line and silently nested `environment:` inside `scenes:`; `narration.inline` must be a mapping, not a list; `cwd: "."` produced `/work/.` | the docker suite | fragments dedented and concatenated separately; a `_MINIMAL` template; `posixpath.normpath` + a `startswith` guard |

**Two of these were invisible to the unit tests by construction.** S was masked because the
filmed path uses `Popen` directly and only the *probe* went through the broken builder; O was
masked because the probe is the only place a TTY was requested on a non-terminal stdin. Both
were caught only by the end-to-end fixture — which is the argument for keeping one.

**Three of the fourteen were pre-existing M7 bugs that only a second backend could expose**
— **J** (a hard-coded backend name in the verifier), **S** (a builder whose output was
double-prefixed) and **T** (an environment contract that only worked because bubblewrap
happens to inherit its parent's). A one-backend design hides its own assumptions; the value
of adding a second was less the backend than the revelation.

**And two of the fourteen are the same class as M7's E and F — *a check that passes must be
written down*.** **N** accepted a field nobody read; **U** let a single failure erase the
evidence that the gate had *ever* answered. That rule was then applied deliberately to all
three of M8's new fact classes, which is why a passing build now records *why* it passed.

**A fifth issue, found in CI, not in the code:** `doctor` with **no spec** did not report the
sandbox at all, and on a sandbox-less host printed "bwrap cannot run" **once per command**.
Fixed, and pinned by tests.

### Evidence at the end of development

*(Superseded later in this phase by the two `exec_environment` tests, which raised the counts
to 520 / 75; the final figures are in the merge entry below.)*

```
python3 -m pytest tests -q                          → 518 passed in 470.54 s
env -i PATH=<lean> python3 -m pytest tests -q      → 445 passed, 73 skipped in 5.54 s
python3 -m pytest tests/test_docker.py -q          → 50 passed in 90.13 s
python3 -m pytest tests/test_exec.py tests/test_docker.py tests/test_core.py -q
                                                   → 156 passed in 100.17 s
vidkit build examples/docker-demo/video.yaml       → ok: true, 11/11 checks pass
docker ps -a --filter name=vidkit-                 → (empty)
```

The `docker-probe` job's extracted steps were run locally, and its verification step printed:

```
DOCKER OK — 3 commands in container vidkit-db-10e98a0eb4e, all sandboxed, service removed
```

`facts.environments[0]` from that build:

```json
{"name": "db", "image": "postgres:16-alpine",
 "image_digest": "sha256:721873c3…",
 "ready": true,
 "ready_detail": "`docker exec` of the declared readiness command answered for 0.98s
                  without a single failure: /var/run/postgresql:5432 - accepting connections",
 "seconds": 2.663,
 "teardown": {"attempted": true, "stopped": true, "removed": true,
              "detail": "container vidkit-db-10e98a0eb4e stopped and removed"}}
```

The image is recorded **by digest**, because a tag is a name that can move — the same rule as
D21's snapshot recording the request it answers.

### The CI job's capability ladder, and why it prints before it gates

`docker-probe` walks four rungs in order — install the client if absent, start the daemon if
down, relax the socket mode, then let the **engine** decide via `docker_rungs()` +
`docker_available(refresh=True)` — and it prints its own ladder *before* gating, because a red
job should say which rung broke rather than only that the gate closed. This is D48 applied to
CI: the failure names the missing rung.

### What this phase deliberately did **not** build

- **No `--rm`.** Containers are removed by the build, on every path, so "removed" is
  attributable to vidkit — and a crashed build leaves something to inspect. **D45.**
- **No `docker compose`, no Dockerfiles.** An `environment` is one image and one command.
  Anything more is a build system, and the story would move out of the spec.
- **No `ports:` publishing to the host.** Ports exist so a browser capture could later reach a
  service *inside* one network; publishing to the host would make the video depend on what
  else is bound on the machine.
- **No eleventh pipeline stage.** The environments are started, used and torn down inside the
  existing `exec` stage, per FEATURE-ROADMAP §12 constraint **P5**.

### Still owed to the owner

- **The `v1.0.0` tag has still not been pushed**, and M7+M8 now both sit under
  `## [Unreleased]`. Whether that becomes `1.1.0` is the owner's call.
- **Docker is not required to pass the suite.** `needs_docker` skips on a host without it, so
  the docker tests are evidence of correctness *where Docker exists*, not of portability.
- **`ubuntu-latest` moves to Ubuntu 26 on 2026-10-19.** The docker job's rungs are stated for
  the current image; the job prints them, so the log will say what changed.

---

## 2026-10-09 — M8 merged: a service can be declared, proven, filmed and removed

**PR [#9](https://github.com/anindyasundarbera/vidkit/pull/9)** →
`main` @ **`63ad046`** (merge commit, parents `7e46276` + `d2c1930`).

Unlike M7, this phase went green on its **first** CI run. Run
[`37593535531`](https://github.com/anindyasundarbera/vidkit/actions/runs/37593535531), all
**six** jobs passing:

| Job | Result |
|---|---|
| `pytest (3.10)` | pass, 1 m 43 s |
| `pytest (3.12)` | pass, 1 m 40 s |
| `build hello-world end to end` (`build-example`) | pass, 4 m 24 s |
| `film a real page and a real download` (`capture-probe`) | pass, 1 m 20 s |
| `run a real command and film it` (`exec-probe`) | pass, 59 s |
| **`run a real container, film it, and remove it` (`docker-probe`)** | **pass, 49 s — the new job** |

The new job is what M8 is for: it climbs a capability ladder, lets the **engine's own probe**
decide, builds `examples/docker-demo/` against a real `postgres:16-alpine`, and then asserts
the thing the phase claims — that three commands shared **one** container, that its readiness
**held**, that it was removed, and that the row written by command 1 appears in command 2's
own recording.

### The abstraction held

M8 added a backend and a resource lifecycle inside the **same ten stages** M7 left. No new
`ExecRequest` field; no widened `stream()` signature. That is the fact the phase was designed
to test, and P5 ("versatility without dilution") is now a *demonstrated* constraint rather
than an aspiration for M9 to inherit. The cost was paid in `exec.py` alone (+869 lines) — a
module that grew a lifecycle without growing a second vocabulary for it.

### Fourteen defects, and the two classes they fall into

Fourteen were found in total, across development, the end-to-end fixtures, and the CI
job's own dry run. They are worth grouping because the groups are what to watch for next:

**Class 1 — a gate that observes rather than demonstrates.** Defects **H** (an attribute
error that would have made bring-up fail silently), **I** (readiness sampled once), **O**
(`docker exec -t` demanding a TTY on *Docker's own* stdin, exit 125), **S** (`docker docker`
double prefix), **T** (the container never received `BASE_ENV`, and the client's `HOME`
leaked its config warning onto the filmed PTY). Each is a case of the code asking *"is the
tool here?"* or *"did anything happen?"* instead of *"did the thing the user is paying for
actually occur?"* **D41/D48** are the rules extracted from these.

**Class 2 — a check that passes must be written down.** **E** and **F** (from M7) were already
this class; **N** (fields parsed but honoured nowhere), **U** (a single readiness failure
erasing the "answered but never held" evidence) and **J** (the verifier's sandbox check naming
one backend) are M8's additions. The rule was then applied deliberately to all three of M8's
new fact classes — `environments`, the per-command `container` key, and the readiness *hold*
— so a passing build records *why* it passed, not merely that nothing complained.

Five more fit neither class cleanly: **K** (a leaked container, and a teardown contract that
covered only the happy path), **L** (`_start_environments` ignoring its own `started` list),
**M** (the binding keyed by environment name rather than command label) and **P/Q/R**
(test-design faults plus a `cwd` normalisation bug in `_docker_workdir`, fixed with
`posixpath.normpath`).

**Three of the fourteen were pre-existing M7 bugs that only a second backend could expose** —
**J**, **S** and **T**. A one-backend design hides its own assumptions; the value of adding
a second backend was less the backend than the revelation.

### The evidence, as observed

```
python3 -m pytest tests -q                      ->  520 passed in 467.70s
PATH=/tmp/leanbin python3 -m pytest tests -q   ->  445 passed, 75 skipped in 5.47s
```

The lean run is the portability claim: **75** tests skip on a host with neither a render
toolchain, a usable sandbox, nor Docker, and the remaining 445 pass in under six seconds. No
marker implies another; `needs_docker` is probed by *actually running a container*, so a host
with a Docker client that cannot confine anything skips the same tests a host with no client
skips — which is the correct answer and the one M7 got wrong.

The extracted `docker-probe` steps, run locally against this host's Docker:

```
rung client: ok  /usr/bin/docker
rung daemon: ok  daemon answers (server 29.7.2)
rung container: ok  `docker run --rm hello-world` succeeded
DOCKER OK — 3 commands in container vidkit-db-123f8c0efde, all sandboxed, service removed
no vidkit container remains
artifacts ok
```

`examples/docker-demo/_build/verify.json` carries `image_digest sha256:721873c3…` and a
`ready_detail` reading *"answered for 0.98s without a single failure: /var/run/postgresql:5432
- accepting connections"*. **Zero leaked containers.**

### What this phase deliberately did **not** build

- **No `--rm`.** Containers are removed by the build, on every path, so "removed" is
  attributable to vidkit — and a crashed build leaves something to inspect. **D45.**
- **No `docker compose`, no Dockerfiles.** An `environment` is one image and one command.
  Anything more is a build system, and the story would move out of the spec.
- **No `ports:` publishing to the host.** Ports exist so a browser capture could later reach a
  service *inside* one network; publishing to the host would make the video depend on what
  else is bound on the machine.
- **No eleventh pipeline stage.** Per FEATURE-ROADMAP §12 constraint **P5**.

### Still owed to the owner

- **The `v1.0.0` tag has still not been pushed**, and M7+M8 now both sit under
  `## [Unreleased]`. Whether that becomes `1.1.0` is the owner's call; folding them back into
  `1.0.0` would make the tag and the release notes disagree.
- **Docker is not required to pass the suite.** `needs_docker` skips on a host without it, so
  the docker tests are evidence of correctness *where Docker exists*, not of portability.
- **`ubuntu-latest` moves to Ubuntu 26 on 2026-10-19.** The docker job's rungs are stated for
  the current image; the job prints them, so the log will say what changed.
- **`doctor`'s happy path calls the full `docker_available()` probe** (~450–510 ms) rather
  than the cheap `docker_daemon()` (~60 ms) and deferring the container demonstration. The
  seam is recorded in **D48**; whether the wall time is worth the certainty is undecided.

### Next

**M9 — Movie mode** ([PLAN.md](PLAN.md), [FEATURE-ROADMAP.md](FEATURE-ROADMAP.md) §12). The
gap is three separable things: stills that do not move, audio that is narration or nothing,
and shot length that is arithmetic. All three land as **additions to the spec surface**
inside the same ten stages.

## 2026-10-10 — M9: movie mode — a film with no capture, no provider and no browser

**Branch** `phase/m9-movie-mode` off `9d3385b`. **Status: complete, verify green.**

The north star for this milestone was one sentence from [PLAN.md](PLAN.md): vidkit must be
"versatile enough to produce **movies**, not only product demos". A movie is not a demo with
different words. A demo is *about* something that happened — it films it and proves it. A film
may have nothing to film at all, and the honesty claim has to survive that. M9 is the milestone
that finds out whether it does.

### The four deliverables

1. **The camera moves.** A shot may declare `motion: {kind: zoom|pan, direction: …, amount: …}`,
   and the engine builds the ffmpeg expression. `motion:` and a non-`hold` `effect:` are
   refused together: they are the same statement made twice, and allowing both would make the
   report ambiguous about which one was the picture's actual transformation.
2. **The engine draws the picture (R-D9).** `card:` renders a title from the shot's own words —
   kicker, rule, wrapped body, optional scrim over a `backdrop:` resolved at load time. `solid:`
   is one flat field. Both are classified as **declared asset** in `verify.SHOT_SOURCES`,
   because that is what they are: pictures the author asked for by writing them down. **D50.**
3. **The clock is expressed.** `seconds:` on a scene and on a shot. When every length is
   declared, `facts.timing_source = "spec"` and the voice is cut to the spec; otherwise the
   measured voice remains the master clock. **D51** — and I5 is not weakened, because I5 forbids
   an *estimate* presented as a measurement, not a *decision* recorded as one.
4. **A music bed.** `score: {src, volume, duck_db, ramp, fade_in, fade_out}`, looped to the
   film's real length, ducked under the measured narration spans.

Plus `plan_shots(spec, audio)` as the single timing rule read by both the renderer and
`vidkit plan`, four new verify checks, and a seventh CI job (`movie-probe`).

### The fixture, and how it was proven

`examples/movie-demo/` has no `capture`, no provider and no browser. Five scenes, one drawn
card, one drawn field, declared artwork, a hand-declared zoom, a looping score.

```
$ vidkit build examples/movie-demo/video.yaml
16.01s within [15, 17]        ... ALL PASS
artwork: 6 shot(s) from declared asset (4 drawn by the engine)
motion: 4 of 5 declared move(s) change the picture; 1 over a field with nothing in it to reveal
```

`tests/test_movie.py` is **90 tests** and needs `ffmpeg` + `rsvg-convert` but no browser, no
network and no voice.

### Eight defects found and fixed

The milestone's whole subject is honesty, so it is worth naming what it caught — including in
its own claims.

1. **`_move_filters` built an expression ffmpeg folds to a constant.** `iw-iw/zoom*(1-p)`
   evaluates to one value; `(iw-iw/zoom)*(1-p)` travels. The parentheses are load-bearing, and
   a static picture renders with **no error at all**. Proven by measuring real frames: pans
   `left` 846→1072, `right` 1076→852, `up` 478→604, `down` 606→480; zooms mirror.
2. **`UnboundLocalError: '_spans'`.** A generator expression is its own scope, so an import
   made inside one is not visible to the loop body. Hoisted. **D52** is the generalisation:
   an absent measurement is not a negative measurement.
3. **`assets_of(ctx)` bound the wrong object**, so the artwork resolver read a path that did
   not exist and every card resolved over nothing but its backdrop.
4. **`plan_shots`/`_clip_plan` disagreed with `reports.plan_report`** — `vidkit plan` predicted
   lengths the renderer did not produce, because each had its own copy of the timing rule.
   There is now one rule with two readers. **D51.**
5. **A silent cut claimed ducking that never happened.** `mix.wav` measured flat at
   −20.7/−20.6/−20.0/−20.6/−20.4 dB, and the mix had taken the `_score_only` path, yet the
   report said `duck_seconds: 16.01`. `Ffmpeg.mix()` now **returns** a `MixResult` and verify
   reports what it did. **D52.**
6. **`narration_spans` published scene-wav durations as positions in a 16.01 s film.** With no
   concatenated track there are no offsets to seek to. Verify now publishes spans only when
   **every** scene has a real wav on disk, and `narration_estimate` otherwise. **D52.**
7. **`svg.document()` did not declare `xmlns:xlink`.** Every card with a `backdrop:` drew an
   empty frame, silently: `rsvg-convert` resolves an **absolute** `xlink:href` and renders
   nothing whatever for a relative one, without an error either way. Found because the
   backdrop test renders through the real rasteriser instead of asserting on the SVG string.
8. **A check that could not fail.** `camera moves are declared` compared a list against a
   filter of itself and always passed; its sentence was a restatement of the spec wearing the
   clothes of a result. Replaced with a pixel measurement (**D49**) — and that measurement
   immediately found a real defect **in the fixture**: scene 2 pans across a flat
   `solid: "navy"`, so its picture does not change by a single pixel. The fixture keeps that
   shot on purpose; it is the only one in the film whose `mae` is `0.0` while its declaration is
   non-empty, and therefore the only one that proves the report distinguishes a declaration
   from a measurement.

Defects 1–5 were found by building and looking at pixels; 6–8 by writing tests whose job was
to disagree with the report. **Three** of the eight are one class: a fact that had not been
established, in a report that presented it as measured. That class is now a decision, not a
habit — **D49** and **D52**.

The measurement defect 8 introduced is itself pinned by
`test_a_declared_camera_move_is_measured_not_restated`, which builds two clips by hand under
the exact names `_measure_move` derives — one over a flat `solid`, one over artwork with edges
in it — and asserts the flat one measures **exactly `0.0`**, that the artwork one's head and
tail frames differ, and that a **missing clip measures `None`, not `0.0`**. It failed six
distinct ways while being written (undefined `ff`, undefined `rsvg`, wrong clip names,
`len()` on a generator). That is the point: it can fail.

### The evidence, as observed

```bash
$ python3 -m pytest tests/test_movie.py -q
90 passed in 32.71s

$ python3 -m pytest tests -q                       # full
610 passed in 534.19s (0:08:54)

$ PATH=/tmp/leanbin python3 -m pytest tests -q     # no ffmpeg/rsvg/bwrap/docker
531 passed, 79 skipped in 5.62s

$ vidkit docs --index | python3 -c "import json,sys; print(len(json.load(sys.stdin)['docs']))"
49
```

`movie-probe` is the seventh CI job and asserts the **real** fact shapes (`artwork` is a list of
rows, `artwork_sources` a list, `motion` a list of rows — there is no `motion["moving"]`), that
the engine actually drew the cards, that at least four of five moves changed the picture, and
that a silent cut must **not** publish `narration_spans`.

### What this phase deliberately did **not** build

- **No transition library.** Cuts only. A crossfade is a compositor, and the film here is a
  proof, not a showcase.
- **No subtitle burn-in beyond the caption renderer M4 already had.** The SRT is the artifact;
  burning is one flag away when a consumer wants it.
- **No eleventh stage.** Per FEATURE-ROADMAP §12 constraint **P5**.
- **No `still:` motion over a provider panel.** The motion contract is on the shot, but only
  declared artwork and engine-drawn pictures are proven with it.

### Still owed to the owner

- **The `v1.0.0` tag has still not been pushed**, and M7, M8 and M9 all sit under
  `## [Unreleased]`. Whether that becomes `1.1.0` or `1.2.0` is the owner's call.
- **The `movie-probe` job is the slowest correctness gate at ~5.3 s of ffmpeg measurement** for
  the motion check. Acceptable for a fixture; worth revisiting if it ever guards a long film.
- **Nothing renders motion over a live capture.** `motion:` is proven on stills; a moving camera
  over a browser capture is implemented but untested, and the report would say so (`mae` would
  be measured, so it would not lie).

### Next

**M10** ([PLAN.md](PLAN.md), [FEATURE-ROADMAP.md](FEATURE-ROADMAP.md) §13). The gap M9 leaves is
composition across shots: M9 made a single shot able to move, be drawn and be timed; nothing yet
lets a film be *assembled* from shots that overlap, transition, or come from more than one take
of the same scene.

---

## 2026-10-10 — M9 merged: a film with no browser, and a check that can fail

**PR [#11](https://github.com/anindyasundarbera/vidkit/pull/11)** →
`main` @ **`1894ec9`** (merge commit, parents `9d3385b` + `010afde`).

Every job went green on the **first** CI run. Run
[`37607163740`](https://github.com/anindyasundarbera/vidkit/actions/runs/37607163740), all
**seven** jobs passing:

| Job | Result |
|---|---|
| `pytest (3.10)` | pass, 1 m 51 s |
| `pytest (3.12)` | pass, 1 m 42 s |
| `build hello-world end to end` (`build-example`) | pass, 3 m 11 s |
| `film a real page and a real download` (`capture-probe`) | pass, 1 m 19 s |
| `run a real command and film it` (`exec-probe`) | pass, 1 m 1 s |
| `run a real container, film it, and remove it` (`docker-probe`) | pass, 49 s |
| **`cut a film from declared artwork alone` (`movie-probe`)** | **pass, 46 s — the new job** |

The new job is the phase's claim stated as a gate: install **only** `ffmpeg` and
`librsvg2-bin`, build `examples/movie-demo/`, and then assert that every shot names a declared
asset, that the engine really drew some of them, that the clock came from the spec, and that a
silent cut publishes an estimate rather than claiming word positions it does not have. The two
tools it installs are the two the feature exists to need.

### The one thing that had to be *added* to the job

The job shipped with a motion assertion that was itself the M9 defect it was meant to catch: it
only asked whether a `motion:` row existed. A gate that restates the spec cannot fail. It now
reads `mae` off every row, requires at least three moves to have actually changed the picture,
requires the one move over a flat field to be exactly `0.0`, and requires changed + flat to
account for every row — so a measurement that silently stopped reading the picture would fail
the job on three separate counts.

This is the phase's own lesson applied to the phase's own CI, and it is the second time M9's
honesty class turned up *inside work that was written to enforce honesty*. D52 exists because of
it: **a check that cannot fail is worse than no check, because it reads as assurance.**

### The fixture defect was kept, deliberately

The new measurement found, on its first run, that scene 2 of `examples/movie-demo/video.yaml`
declares a pan over a flat `solid: "navy"` — a move over a field with nothing in it to reveal,
which measures exactly `0.0`. The options were to make the fixture work or to leave it failing.
It was left, and the spec now carries a comment explaining what it is for: it is the *evidence*
that the measurement reads the picture rather than the request. A fixture that always measures
"moved" cannot demonstrate that the check can report "did not move". The `movie-probe` job
asserts on that row by name.

### Eight defects, and the class three of them share

Five were found by measuring pixels; three by writing a test that was allowed to fail. The
class that matters is **a fact that was never established** — three of the eight:

- a check that compared a list against a filter of itself (`len(moved) == len([r for r in
  artwork if r.get("motion")])`, where `moved` *was* that filter);
- `narration_spans` publishing scene-wav durations as though they were positions in a 16.01 s
  film whose scenes' words would take 35.6 s;
- `duck_seconds` printed as a number the mix never produced whenever a silent cut took the
  score-only path.

Each read as assurance and none could fail. D49 and D52 are the two rules that came out of it:
**an absent measurement is not a negative measurement**, and **a check about what a picture did
decodes the picture**.

Two further defects were of a nastier mechanical kind, both silent: ffmpeg folds
`iw-iw/zoom*p` to a constant while `(iw-iw/zoom)*p` travels — **the parentheses are
load-bearing and a still picture renders with no error at all**; and `rsvg` resolves an
**absolute** `xlink:href` but renders an **empty frame** for a relative one, again with no
error. Both were found only because the output was measured, not because anything complained.

### The evidence, as observed

```bash
$ python3 -m pytest tests/test_movie.py -q
90 passed in 33.30s

$ python3 -m pytest tests -q                       # full
610 passed in 534.19s (0:08:54)

$ PATH=/tmp/leanbin python3 -m pytest tests -q     # no ffmpeg/rsvg/bwrap/docker
531 passed, 79 skipped in 5.62s

$ python3 -m vidkit build examples/movie-demo/video.yaml   # ffmpeg + rsvg only
# verify: all checks pass — 16.01 s
```

The `movie-probe` steps were re-extracted from the workflow and run locally before the PR was
opened (`MOVIE OK — 6 shot(s) from declared asset (4 drawn by the engine), 5 moving (4 changed
the picture, 1 over a flat field measured 0.0), 16.01s, score ducked=False`; `artifacts ok`).

### What this phase deliberately did **not** build

- **No transitions.** Cuts only. Composition across shots is M10's subject, not M9's.
- **No motion over a provider panel.** The contract is on the shot, but only declared artwork
  and engine-drawn pictures are proven with it.
- **No eleventh stage.** Per FEATURE-ROADMAP §12 constraint **P5**, and it held a second time.
- **No `1.1.0` bump.** The version stays `1.0.0` and the phase sits under `## [Unreleased]`.

### Still owed to the owner

- **The `v1.0.0` tag has still not been pushed**, and M7, M8 and M9 all sit under
  `## [Unreleased]`. Whether that becomes `1.1.0` or `1.2.0` is the owner's call.
- **A moving camera over a live capture is implemented but untested.** The report would not
  lie about it — `mae` is measured, so it would show whatever it measured — but no fixture
  covers it.
- **`doctor`'s happy path still calls the full `docker_available()` probe.** D48 records the
  question; the fast `docker_daemon()` path is the standing alternative.

### Next

**M10** ([PLAN.md](PLAN.md), [FEATURE-ROADMAP.md](FEATURE-ROADMAP.md) §13). The gap M9 leaves is
composition across shots: M9 made a single shot able to move, be drawn and be timed; nothing yet
lets a film be *assembled* from shots that overlap, transition, or come from more than one take
of the same scene.

## 2026-10-11 — M10: the studio surface — a session, a take, and a check that awaits

**Branch** `phase/m10-studio-session`, off `main` = `4819a62` (M9 + its bookkeeping merge).

### What was built

| File | What it is |
|---|---|
| `vidkit/studio.py` | ~1 420 lines. `Session` (spec, record dir, budget, selections), `Registry`, `Take`, `status(session) -> next_step`, take record/list/select, environment up/down/status over M8, live browser sessions. |
| `vidkit/_loop.py` | Rewritten from scratch: `Worker` (one daemon thread per live session), `offload(fn, *args)`, `session(sess)`. |
| `vidkit/mcp_server.py` | 15 tools → **34** (12 sync + 22 async), 3 resources → **7**. `_PROJECT` / `set_project()` / `_implicit_project()`, `--project`. One more deliberate sync tool: `tool_run`. |
| `vidkit/spec.py` | `_SPEC_KEYS` + `_check_spec_keys`; per-shot `transition:`; `_pointer_timeout`. |
| `vidkit/context.py` | `Context.selections`, `Context.selected_take(capture)`. |
| `vidkit/capture.py` | `capture_all` keeps a promoted take instead of re-shooting it. |
| `vidkit/ffmpeg.py` | `concat_with_transitions` — every input normalised with `settb=AVTB`. |
| `tests/test_studio.py` | **87 tests**, including the protocol-level exit proof. |
| `tests/test_mcp.py` | **35 tests**, including two structural AST scans. |
| `.github/workflows/ci.yml` | The **`studio-probe`** job — the seventh. |

### The three facts this phase is actually about

1. **FastMCP runs sync tools on the loop thread.** Not inferred — a probe printed the thread
   name from inside both a sync and an async tool body, and both said `MainThread`. Playwright's
   sync API therefore refused outright (`It looks like you are using Playwright Sync API inside
   the asyncio loop`), so **every browser and capture tool was dead over MCP, always, on every
   machine**, and no test saw it because the tests called the plain functions rather than the
   wire. `_loop.py` exists because of this sentence. (D55)
2. **`concat=n=2` gives its output the first input's timebase.** The first attempt at
   `transition:` produced `First input link main timebase (1/1000000) do not match the
   corresponding second input link xfade timebase (1/12800)` — from ffmpeg itself, naming the
   cause. **Any** hard cut preceding a dissolve aborted the render. Every input is normalised
   now, and the five junction mixes render at exactly `6.000 s`. (D58)
3. **A test that does not await an async tool cannot fail.** Making the tools async turned
   existing assertions into `assert dict == coroutine` — always `False`, never raising, always
   green. Two were found. The class is now pinned by an AST scan over every `tests/test_*.py`,
   alongside a second scan that pins every registration closure against the coroutine it wraps
   in **both** directions. (D57)

### The defects

**Nineteen real defects were found in M10's own new code**, none of them by reading:

| # | Defect | Fixed by |
|---|---|---|
| 1 | `Session.sync_budget(live_containers=…)` declared, all five call sites passed `containers=` | rename |
| 2 | A stray indentation swallowed the tail of `open_session` | reindent |
| 3 | `run(ctx, assets, …)` positional drift | signature |
| 4 | `Assets(ctx)` landing in the `stills` field | keyword |
| 5 | `Budget.check()`'s seconds branch unreachable | reorder |
| 6 | The driver escaped `capture.apply` for every action but three | `_driver_message`, `_patience` |
| 7 | `timeout:` silently dropped for pointer actions | `_pointer_timeout` |
| 8 | `session_open` dropped four parameters and returned success | D53 |
| 9 | `record_dir` returned the project root | `Registry.load` |
| 10 | (a) sync tools on the event loop; (b) no live-session registry, so every call after the first saw `{}` | `_loop.py`, `_LIVE` |
| 11 | `browser_open` raised **after** opening a real browser | D53 |
| 12 | `held(id)` could never match without an `out_dir` | match by held id |
| 13 | `close_session` called `forget()` after `save()` | `try/finally` |
| 14 | A resource awaited a **sync** tool; a closure assigned an async call without awaiting | structural scan |
| 15 | The loader dropped unknown top-level keys silently and asymmetrically | `_SPEC_KEYS` |
| 16 | **A selected take was destroyed by the build** | D54 |
| 17 | The CI probe compared a promoted take against itself — a check that could not fail | compare to take 2's pre-promotion digest |
| 18 | `tests/test_provenance.py` called `tool_provenance` un-awaited | `anyio.run` |
| 19 | `tests/test_providers.py` called `tool_build` un-awaited twice | `anyio.run(lambda: …)` |

Defects 15, 16, 17 and 19 were all of one family: **something was reported that had not been
established.** Defect 17 could not fail at all; defect 16 made a *record* true while the film
was false.

### Evidence

```
pytest tests -q                       -> 716 passed in 637.42s
PATH=/tmp/leanbin pytest tests -q     -> 615 passed, 101 skipped in 15.26s
tests/test_studio.py                  -> 87 passed
tests/test_mcp.py                     -> 35 passed
tests/test_presentation.py            -> 69 passed
tests/test_docker.py                  -> 50 passed in 90.13s
studio-probe (steps 06-09)            -> STUDIO OK — 9 checks, 3 takes, chose take 2,
                                         frame [252, 0, 0], 17346 bytes, record closed
```

The `studio-probe` step 09 claims are measurements, not restatements: it **decodes the delivered
`.mp4`'s middle frame** and asserts the kept take's page colour survived the render, and it
compares the promoted bytes to **take 2's own pre-promotion digest** with an inequality against
take 1's. `ffmpeg` writes outside `/tmp` on this host, so the probe runs under `$HOME`.

### Test-count and marker bookkeeping

`tests/` collects **620**. Nine `tests/test_studio.py` tests reach a real sandbox
(`exec.steps`) or a real Docker daemon (`backend: docker`) and had no marker — they passed
locally and failed in the lean run. All nine now carry `@needs_sandbox` or `@needs_docker`, and
`needs_playwright` is the **fourth** capability marker in `tests/conftest.py`.

### What this phase deliberately did **not** build

- **No compositor.** Picture-in-picture, masks and text over live motion remain unowned by any
  phase. A `transition:` is a filter; a compositor is not.
- **No eleventh stage.** Ten, as in M8 and M9 (FEATURE-ROADMAP §12 constraint **P5**).
- **No version bump.** Still `1.0.0`; M7–M10 sit under `## [Unreleased]`.

### Still owed to the owner

- **The `v1.0.0` tag has not been pushed**, and which version M7–M10 become (`1.1.0` or
  `1.2.0`) is the owner's call.
- **A moving camera over a live capture is implemented but untested** (carried from M9).
- **`doctor`'s happy path** still calls the full `docker_available()` probe (D48).
