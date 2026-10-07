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
