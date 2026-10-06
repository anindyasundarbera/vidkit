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
