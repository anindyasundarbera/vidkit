# AGENTS.md — the contract for working in this repository

> **Read this file first, every session.** It is the durable operating contract for
> `vidkit`. It survives context compaction; the conversation does not.
>
> **Repo:** <https://github.com/anindyasundarbera/vidkit> (public, MIT) · default branch `main`
> · first commit `87b7435`. CI (`.github/workflows/ci.yml`) runs the unit suite on Python
> 3.10/3.12 and builds `examples/hello-world` end to end.
>
> For *what to build next* read [docs/plan/PLAN.md](docs/plan/PLAN.md).
> For *what already happened* read [docs/plan/HISTORY.md](docs/plan/HISTORY.md).
> For *the phase-wise plan* read [docs/plan/FEATURE-ROADMAP.md](docs/plan/FEATURE-ROADMAP.md).
> For *why we chose what we chose* read [docs/plan/DECISIONS.md](docs/plan/DECISIONS.md).

---

## 1. What this project is

`vidkit` turns a small declarative **spec** (`video.yaml`) plus an optional **provider**
module into a **narrated, captioned `.mp4`** and a machine-readable **`verify.json`**.

The user's stated goal, verbatim in intent:

> Turn vidkit into a capable **presentation studio** for software demos — with **Playwright**,
> a **sandboxed terminal**, and **Docker** access — exposed as a **standalone MCP server**,
> drivable by an external capable agent. It must also be versatile enough to produce
> **movies**, not only product demos.

The north star, from [ROADMAP.md](ROADMAP.md) §1.1:

> An agent is handed **(story, timeframe, environment)** and returns a **narrated,
> captioned demo video** plus a **verification report** — with no human editing of scripts
> or specs.

### 1.1 The one thing that makes vidkit worth existing

**Honest by construction.** Every visual is sourced from something real — a live capture of a
running product, a chart drawn from a provider's measured data, or a declared graphic asset.
Nothing is fabricated. `verify.py` then *reopens the render* and proves the claims hold
(runtime window, banned/required phrases, caption readability, audio presence, live-capture
presence). This is the differentiator. **Never weaken it to make a build pass.**

---

## 2. Non-negotiable invariants

Violating any of these is a bug, regardless of what it makes easier.

| # | Invariant | Enforced by |
|---|---|---|
| I1 | The engine is **host-agnostic**. No product name, URL, port, or dataset id appears in `vidkit/vidkit/*.py` outside comments. | CI grep; [ROADMAP.md](ROADMAP.md) §3.2 |
| I2 | **A failed assertion aborts the build** — captures assert *before* screenshotting. | `capture.py` |
| I3 | Captions are **token-for-token faithful** to the script. No word dropped or reordered. | `narration.py::build_srt(strict=True)` |
| I4 | Captions are **≤ 2 lines, ≤ 42 characters per line**. | `narration.py` + `verify.py` |
| I5 | **Measured audio is the master clock.** Clip lengths derive from real per-scene durations, never from estimates, when audio exists. | `tts.py`, `assembler.py` |
| I6 | A **silent cut must be declared** (`guard.require_audio: false`), never accidental. | `verify.py` |
| I7 | **Nothing fabricated is rendered.** Not a mock UI, not an invented number, not a restaged take. | `verify.py`, review |
| I8 | Specs are **plain data**. A spec never executes arbitrary code; only the named provider is imported. | `spec.py` |
| I9 | The **story lives in the consumer's repo**, never bundled into vidkit. Integration is **MCP-only, never vendored**. | [ROADMAP.md](ROADMAP.md) decision of record |
| I10 | Provider **datasets are snapshotted** to `data/*.json`, so panels re-render without re-fetching. | `assembler.py` |

---

## 3. Repository map

```
vidkit/
├─ AGENTS.md              ← you are here (agent contract)
├─ README.md              user-facing overview
├─ ROADMAP.md             requirements R-A1…R-H9, milestones M0–M6  ← governing document
├─ CHANGELOG.md           release notes
├─ LICENSE                MIT
├─ pyproject.toml         packaging, extras, console scripts
├─ vidkit/                the engine (23 modules)
│    assembler.py         the 9-stage pipeline + Context/Assets wiring
│    spec.py              dataclasses + loader + cross-reference validation
│    context.py           Context/Assets: the paths every stage shares
│    provider.py          provider plugin loading (datasets/panels/stills/register)
│    capture.py           Playwright capture, action DSL, assert-before-shot
│    panels.py            11 built-in panel kinds + register()
│    svg.py               SVG primitives + the default Theme/PanelDoc
│    narration.py         scene-script parsing, caption wrapping, SRT building
│    overlay.py           banner/image graphics drawn over a shot
│    tts.py               per-scene piper WAVs; silent fallback
│    ffmpeg.py            duration/volume/concat/xfade/still_to_clip/overlay_clip/mux
│    timeframe.py         the resolved window (days/as_of or start/end)
│    secrets.py           declared secrets + redaction
│    snapshot.py          dataset snapshots, freshness, degraded replay
│    scaffold.py          `vidkit new` project skeleton
│    verify.py            the acceptance checks → Report
│    reports.py           report rendering helpers (shared by CLI and MCP)
│    job.py               the {action, story, out} job contract -> one manifest
│    cli.py               doctor/plan/build/tts/capture/auth/init/run/verify/docs
│    mcp_server.py        MCP tools (14) + resources (3) + transports
│    errors.py            VidkitError / SpecError / ToolError / ProviderError
│    __init__.py          version + public exports
│    __main__.py          python -m vidkit
├─ tests/
│    test_core.py         panels, spec, captions, report — pure Python
│    test_job.py          the job contract: manifest shape, refusals, progress
│    test_cli.py          --json / --progress / run: exit codes and pipeability
│    test_mcp.py          the MCP surface
│    test_timeframe.py    the window contract (R-F)
│    test_providers.py    snapshots, fallbacks, stage selection (R-B)
│    test_capture.py      the capture DSL, action semantics (R-C)
│    test_ffmpeg.py       filter graphs + real pixels read back
│    test_presentation.py fit/overlay/transition contracts (R-D)
├─ examples/
│    hello-world/         offline CI fixture (no browser, no voice, no network)
│    capture-kit/         a local fixture server the capture probe films
├─ docs/
│    modules.yaml         machine-readable doc route table (agents resolve by stem)
│    README.md            doc router
│    foundations/         concepts, pipeline, architecture
│    authoring/           spec-reference, provider-guide, panels-reference, narration-and-captions
│    capture/             capture-guide
│    verification/        verification
│    operations/          cli-reference, mcp-server, troubleshooting, extracting-to-new-repo
│    guides/              recipes
│    plan/                PLAN.md, HISTORY.md, ROADMAP.md, DECISIONS.md, OPENMONTAGE.md
└─ .github/workflows/     CI (lint + pytest + hello-world build)
```

---

## 4. How to work in this repo

### 4.1 Environment

`python3` (not `python`) is what exists here. `ffmpeg`, `rsvg-convert`, and `git` are present.
`playwright`/`piper` are **optional** extras and are not required for the core test suite.

```bash
pip install -e ".[dev]"          # core + pytest
pytest tests -q                  # 337 tests, ~50 s; no external tools needed
```

### 4.2 Commands that must keep working

```bash
pytest tests -q                                            # 337 passed
python3 -m vidkit doctor  examples/hello-world/video.yaml  # exit 0
python3 -m vidkit plan    examples/hello-world/video.yaml  # scene plan + estimate
python3 -m vidkit build   examples/hello-world/video.yaml  # mp4 + srt + verify.json
python3 -m vidkit --json run plan --story examples/hello-world   # the agent surface
python3 -m vidkit docs --index                             # JSON route table
```

### 4.3 When you change code

1. **Read the invariant table (§2) before proposing a design.** If a design breaks an
   invariant, say so and propose an alternative instead.
2. Make surgical, complete changes. Do not refactor unrelated code.
3. **Run `pytest tests -q`.** It is fast — there is no excuse not to.
4. If you touched the pipeline, **build the hello-world fixture**:
   `vidkit build examples/hello-world/video.yaml`. It must produce an `.mp4`, a
   `narration.srt`, and a `verify.json` with **all checks passing**, using only `ffmpeg`
   and `rsvg-convert`.
5. Update the spec/panel/CLI docs that your change invalidates — see [docs/modules.yaml](docs/modules.yaml).
6. **Record the work** in [docs/plan/HISTORY.md](docs/plan/HISTORY.md) and tick
   [docs/plan/PLAN.md](docs/plan/PLAN.md).

### 4.4 Gotchas that have already bitten us

- **`default_spec()` ordering.** `mcp_server.py::default_spec()` picks the alphabetically
  first `examples/*/video.yaml`. This **used to be** a live hazard: adding `hello-world`
  silently changed the default from `oneaquahealth`. It is now **resolved by construction** —
  `examples/oneaquahealth/` was removed, so `hello-world` is the only example and the default
  is unambiguous. `test_default_spec_picks_examples_deterministically` pins the *behaviour*
  (alphabetical first) rather than a filename, so it stays meaningful if a second example
  is ever added.
- **`_validate()` and providers.** A `still`/`capture`/`chart` reference may be unresolved
  *only if* `provider:` is declared. Without a provider, every reference must exist.
- **Panel canvas is the project size.** `PanelDoc` is constructed with
  `spec.project.width/height`, so panel coordinates assume **1920×1080** defaults. Still-card
  SVGs must match the project canvas or they will be scaled/stretched.
- **`project.min_seconds < max_seconds`** is enforced at load time.
- **Narration headers are regex-matched**: `^##\s*Scene\s+(\d+)\b.*?·\s*(\d+:\d+)\s*[–-]\s*(\d+:\d+)\s*$`.
  An en-dash `–`, not a hyphen, separates the times. Spoken lines must be `**bold**`;
  `[bracketed]` lines are stage directions and are ignored.
- **stdout corrupts JSON-RPC.** The MCP server wraps printing stages in `stdout_to_stderr()`.
  Any new printing code path must be wrapped too.
- **`_FALLBACK_WPS = 2.5`** in `tts.py` disagrees with the CLI `plan` estimator (`words/2.78`).
  A known, documented minor inconsistency.
- **This repo has a `build/` directory and `vidkit.egg-info/`** from an editable install.
  They are gitignored scratch; do not commit them.

---

## 5. Document maintenance rules

These documents are only worth having if they stay true. ROADMAP.md §3 went stale and
misled us once already — do not repeat that.

| Document | Rule |
|---|---|
| [AGENTS.md](AGENTS.md) | Update when invariants, the repo map, or the commands change. Rare. |
| [docs/plan/PLAN.md](docs/plan/PLAN.md) | **Rewrite** as work progresses. Only ever describes *now* and *next*. Keep it short. |
| [docs/plan/HISTORY.md](docs/plan/HISTORY.md) | **Append-only.** Never rewrite the past. Every entry carries a date and evidence. |
| [docs/plan/FEATURE-ROADMAP.md](docs/plan/FEATURE-ROADMAP.md) | Update when a phase lands or scope changes. Supersedes root `ROADMAP.md` milestones. |
| [docs/plan/DECISIONS.md](docs/plan/DECISIONS.md) | **Append-only.** One entry per decision, with alternatives and consequences. |
| [docs/plan/OPENMONTAGE.md](docs/plan/OPENMONTAGE.md) | Frozen research record. Re-verify before acting on it if older than ~1 month. |

### 5.1 Evidence rule

Every claim in these documents must be **verifiable from the repo**. State the command and
the observed result, not a recollection. ROADMAP.md §3 is the model: it lists the exact
`grep`/`pytest` commands behind each row. Recollections are how the "37 tests / mcp_server
verified" fiction got into the notes.

### 5.2 Status markers

Use exactly these, so they are greppable:

- `[x]` done and verified
- `[~]` in progress
- `[ ]` not started
- `[!]` blocked — the entry must say by what
- `[-]` deliberately deferred — the entry must name the decision entry that deferred it

---

## 6. Current position (snapshot)

> Snapshot taken 2026-10-06. If this disagrees with [docs/plan/PLAN.md](docs/plan/PLAN.md),
> trust PLAN.md.

- **Repo state:** public on GitHub (`anindyasundarbera/vidkit`), default branch `main`,
  CI green. M0–M3 are merged; M4 is the active phase.
- **Tests:** `python3 -m pytest tests -q` → **337 passed**, no external tools required.
- **Engine:** host-free. 9 stages, 23 modules, 11 panel kinds, 14 MCP tools.
- **Active phase:** **M4 — Presentation v2** ([docs/plan/FEATURE-ROADMAP.md](docs/plan/FEATURE-ROADMAP.md)).
  If this line disagrees with [docs/plan/PLAN.md](docs/plan/PLAN.md), trust PLAN.md.
- **Biggest remaining gap:** there is still no **executor/sandbox** and no **Docker lab**,
  so the studio cannot yet drive a real terminal on behalf of an agent. That is M7/M8.
- **The one item needing an owner decision:** the public `v1.0.0` tag at M6.

---

## 7. How to talk to the user

- The user is the project owner and is technically deep. Be direct and concrete.
- **Do not ask for permission to do the work that PLAN.md already authorises.** Just do it,
  then report what changed and what the evidence is.
- **Do ask** when a decision would change architecture, licensing, or scope — those go in
  DECISIONS.md and the user owns them.
- When you disagree with a plan item, say so plainly, with the invariant or evidence behind
  the objection, and propose the alternative. Do not silently comply and do not silently
  deviate.
