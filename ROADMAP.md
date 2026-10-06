# vidkit — Requirements, Current State & Roadmap

**Status:** baseline complete · M0 published · updated 2026-10-06 · <https://github.com/anindyasundarbera/vidkit>
**Decision of record:**

1. vidkit is a **standalone project in its own repository**. No vidkit source lives inside
   OneAquaHealth.
2. Its job is to let an **agent** produce a demo video from a **given story** and a **given
   timeframe**.
3. OneAquaHealth (and any other product) consumes vidkit as an **external tool** — wired in
   **only via MCP**. The coupling is a URL/config reference, never a vendored copy.
4. The **OneAquaHealth story lives in the OneAquaHealth repo** (it is OAH's own data and
   assets), not inside vidkit. The copy that was in this repo has been **removed**; it is
   preserved locally at `~/Projects/oneaquahealth-story-backup/` pending its move into the
   OAH repo (R-H1). vidkit ships only the host-free `examples/hello-world`.

This document is the contract for that work: what is *required*, what *exists today* (each
claim verified on disk), the *gap*, and the *path* to close it.

---

## 1. Goal & scope

### 1.1 North star

> An agent is handed **(story, timeframe, environment)** and returns a **narrated, captioned
> demo video** plus a **verification report** — with no human editing of scripts or specs.

### 1.2 In scope

- The engine: spec → stills/captures/charts → per-scene narration → captioned `.mp4` + `verify.json`.
- The **agent surface**: a machine-drivable contract (MCP tools and/or a headless JSON CLI).
- Story/timeframe **contracts** so an agent can vary them without touching code.
- Standalone packaging, docs, tests, and CI for the new repo.

### 1.3 Out of scope (explicit non-goals)

- Being a general-purpose NLE (no timeline UI, no keyframe editing).
- Rendering anything that is **not** sourced from the target product, its data, or declared
  graphic assets — the "no fabricated UI" guarantee is a feature.
- Acting as the target application's data layer. vidkit *reads*; providers own the data.
- A hosted service. vidkit runs locally, offline-capable, with ffmpeg + rsvg-convert.
- Being vendored into a consuming repo. Consumers integrate by pointing at the standalone
  server (MCP) or the CLI; the story stays in the consumer's repo.

### 1.4 Decisions (all previously open items are now resolved)

| # | Decision | Resolution | Impact |
|---|---|---|---|
| D1 | What is a "story"? | **Decided: both** — a folder convention *plus* an optional `story.yaml` manifest | Shapes R-A1, R-G4 |
| D2 | How does the agent talk to it? | **Decided: MCP is the consumer integration**; keep a headless JSON CLI as the transport-independent fallback | Shapes R-G1/G2 |
| D3 | Timeframe forms | **Decided: both** — `{days, as_of}` and `{start, end}`; the resolved value is recorded in the provenance manifest | Shapes R-A3 |
| D4 | Where does the OAH example live? | **Decided: in the OneAquaHealth repo**, pointing at the standalone vidkit. Removed from here. | Shapes M0 |
| D5 | Where does a story live? | In the **consuming product's repo** (story = that product's data + assets + provider) | Shapes R-A1, M0 |
| D6 | How is vidkit pinned? | `uvx`/`pipx` from a tag vs. a pinned git ref; document both | Shapes R-H2, R-H9 |

Full rationale, alternatives considered, and status are in
[`docs/plan/DECISIONS.md`](docs/plan/DECISIONS.md).

---

## 2. Requirements

Priorities: **P0** = required for v1.0, **P1** = strongly expected, **P2** = later.

### A. Story authoring (the "given story" half) — *today's biggest gap*

| ID | Requirement | Pri |
|---|---|---|
| R-A1 | A **story** is a first-class, validated, named artifact (not an implicit folder layout). | P0 |
| R-A2 | `vidkit init <dir>` scaffolds a runnable story (spec + narration + provider stub). | P0 |
| R-A3 | A **timeframe** is first-class in the spec and available to providers/scenes (e.g. `{days, as_of}` and/or `{start, end}`). | P0 |
| R-A4 | The timeframe **stated in narration** must match the spec timeframe (guarded). | P0 |
| R-A5 | Spec validation fails fast, with actionable messages, before any expensive rendering. | P0 |

### B. Data & providers (the "given environment" half)

| ID | Requirement | Pri |
|---|---|---|
| R-B1 | Providers are plugins loaded from the spec folder; the engine stays host-agnostic. | P0 |
| R-B2 | The timeframe is **threaded to providers** — no hard-coded `?days=`/date strings in provider code. | P0 |
| R-B3 | Datasets are snapshotted to disk (`data/*.json`) so panels can re-render and builds are reproducible. | P1 |
| R-B4 | Providers may declare secrets/env needs; the engine never prints them and never writes to the source system. | P1 |
| R-B5 | A **deterministic fallback** path exists when a model/LLM is unavailable (no stuck "loading" frames). | P2 |

### C. Capture (real product UI, never fabricated)

| ID | Requirement | Pri |
|---|---|---|
| R-C1 | Playwright capture of a URL with an **assertion that runs before the screenshot**; a failed assertion aborts the build. | P0 |
| R-C2 | An action DSL covering: `wait`, `wait_for`, `select`, `click`, `fill`, `press`, `scroll`, `eval`, `download`. | P0 |
| R-C3 | **Download captures**: click a real control, wait for the browser download, save the real bytes. | P0 |
| R-C4 | **Artifact rendering**: film real downloaded bytes as themselves (CSV/TSV/PDF/PNG), sniffed so the content must match its kind. | P0 |
| R-C5 | Explicit **element waits** (`wait_for_selector`), not only fixed sleeps. | P0 |
| R-C6 | **Take selection / retry**: re-issue an identical request and name the take you keep; never edit output to fake a better take. | P1 |
| R-C7 | Session/auth support (login or token) for non-anonymous products; a login form is filmed only when declared. | P1 |
| R-C8 | Deterministic rendering: fixed viewport, device scale, and a frozen clock, locale, timezone, motion and randomness. | P1 |

### D. Presentation

| ID | Requirement | Pri |
|---|---|---|
| R-D1 | Built-in panel kinds: line series, bar profile, stat cards, terminal, endpoints, strip, kv table, prose. | P0 |
| R-D2 | A registry so providers add custom panels without touching the engine. | P0 |
| R-D3 | **Proportional/date axis** for time series (x spaced by real date, not by index). | P0 |
| R-D4 | **Overlays / lower-thirds** (composite a graphic over a capture). | P1 |
| R-D5 | **Aspect-preserving crop** so full-page captures are not stretched. | P0 |
| R-D6 | Scene transitions/effects beyond `hold`/`zoom`. | P2 |
| R-D7 | Static asset pipeline (SVG → PNG) for title/end/diagram cards. | P0 |

### E. Audio & captions

| ID | Requirement | Pri |
|---|---|---|
| R-E1 | Per-scene TTS as the **master clock**; video clip lengths derive from **measured** audio. | P0 |
| R-E2 | Caption fidelity: no spoken word dropped or reordered (asserted). | P0 |
| R-E3 | Caption readability: ≤ 2 lines, ≤ 42 chars, asserted. | P0 |
| R-E4 | Burned-in captions with correct resolution metadata (`PlayResX/Y`). | P0 |
| R-E5 | Graceful silent fallback when no TTS engine/voice is present. | P1 |
| R-E6 | Voice acquisition/management is documented and scriptable. | P1 |

### F. Verification (honesty guarantees)

| ID | Requirement | Pri |
|---|---|---|
| R-F1 | A machine-readable `verify.json` and a non-zero exit on failure. | P0 |
| R-F2 | Runtime window check (min/max). | P0 |
| R-F3 | Banned/required phrase scan over narration **and** captions. | P0 |
| R-F4 | Caption readability + audio-present checks. | P0 |
| R-F5 | "All declared live captures present" (live-mode guarantee). | P0 |
| R-F6 | Speech-rate plausibility. | P1 |
| R-F7 | **Timeframe consistency** check (narration matches spec window). | P0 |
| R-F8 | Provenance manifest: dataset tag/source, spec hash, tool versions, when built. | P2 |

### G. Agent surface — *the stated purpose*

| ID | Requirement | Pri |
|---|---|---|
| R-G1 | An **MCP server** exposing plan/build/tts/capture/verify/doctor as tools (+ docs resources). | P0 |
| R-G2 | A **headless JSON CLI** (`--json` on every command) usable without an MCP host. | P0 |
| R-G3 | A **job contract**: accept `{story, timeframe, out}` and return an artifact manifest. | P0 |
| R-G4 | `init`/scaffold so the agent can start a new story from a prompt. | P0 |
| R-G5 | Long jobs report **progress** and are cancellable/async-safe. | P1 |
| R-G6 | Errors are structured and actionable (no stack traces as the final word). | P1 |

### H. Distribution & operations

| ID | Requirement | Pri |
|---|---|---|
| R-H1 | Standalone repo; the engine imports nothing from a host project. | P0 |
| R-H2 | Installable (`pip install vidkit`, extras `[capture]`, `[tts]`); console script; launchable without copy (`uvx`/`pipx`/pinned git ref). | P0 |
| R-H2b | **Consumer integration via MCP**: OneAquaHealth (and others) reference the standalone server; no vidkit source is vendored into a consuming repo. | P0 |
| R-H2c | A **story owned by a consumer** lives in that consumer's repo; vidkit never bundles a host story. | P0 |
| R-H3 | A self-contained **`examples/hello-world`** (no host deps) used as the CI fixture. | P0 |
| R-H4 | CI: lint + unit tests + a hello-world build (headless-safe). | P0 |
| R-H5 | Docs set: concepts, spec reference, provider guide, panels reference, capture guide, verification, CLI, troubleshooting, recipes. | P0 |
| R-H6 | Portability: Linux/macOS first-class; Windows documented (best-effort). | P1 |
| R-H7 | LICENSE present (MIT). | P0 |
| R-H8 | Versioning + changelog + release tags. | P1 |
| R-H9 | Optional PyPI publish. | P2 |

---

## 3. Current state

### 3.0 Baseline (verified on disk, 2026-10-07)

This repo **is** the extraction target — the M0 split has happened. §3.1–§3.5 below are the
**pre-extraction** snapshot from `2026-10-04`, kept because they are the evidence base for the
requirement IDs; read them as "what the new repo must fix", not as today's state. The
authoritative "what is done now" record is
[`docs/plan/HISTORY.md`](docs/plan/HISTORY.md), and the forward plan is
[`docs/plan/FEATURE-ROADMAP.md`](docs/plan/FEATURE-ROADMAP.md).

| Item | State today |
|---|---|
| Package | `vidkit/` — **21 modules**, incl. `secrets`, `snapshot`, `scaffold`, `reports`, `timeframe` |
| Tests | `test_core`, `test_mcp`, `test_timeframe`, `test_providers`, `test_capture` — **198 passing** (1.7 s) |
| Examples | `examples/hello-world/` (host-free, offline) and `examples/capture-kit/` (a local server, a real CSV and PDF; needs Chromium) |
| `docs/` | **21 docs in 7 modules** under `docs/`, routed by `docs/README.md` + `docs/modules.yaml` |
| MCP server | **present** — `vidkit/mcp_server.py`; 10 tools + 3 resources |
| `LICENSE` | **present** (MIT) |
| `CHANGELOG.md` | **present** (Keep a Changelog) |
| `py.typed` | **present**, and ships in the built wheel |
| CI | **present** — `.github/workflows/ci.yml` (`test` + `build-example` + `capture-probe`) |
| Host coupling in engine | **0** — `grep -rniE "oneaquahealth\|oah_\|fhir" vidkit/*.py` → 0 |
| OAH story | **removed** from this repo; preserved at `~/Projects/oneaquahealth-story-backup/` pending its move into the OAH repo |
| Git history | **published** — first commit `87b7435` on `main`, pushed to <https://github.com/anindyasundarbera/vidkit> (public) |

### 3.1 Inventory (pre-extraction snapshot, 2026-10-04)

| Item | State |
|---|---|
| Package | `vidkit/vidkit/` — 15 modules (`spec, context, provider, capture, narration, panels, svg, tts, ffmpeg, assembler, verify, cli, errors, __init__, __main__`) |
| Tests | `vidkit/tests/test_core.py` only — **18 tests**, pure-Python core |
| Packaging | `pyproject.toml`: `vidkit` 0.1.0, `requires-python >=3.10`, core dep `PyYAML>=6`, extras `capture`/`tts`/`dev`, script `vidkit = vidkit.cli:main` |
| Examples | `examples/oneaquahealth/` only — **host-coupled** (needs gateway :8000, dashboard :8090) |
| Docs | `README.md` only |
| Console script | `vidkit` |
| `LICENSE` | **absent** |
| `py.typed` | **absent** |
| CI | **absent** |
| MCP server | **absent** — `vidkit/vidkit/mcp_server.py` does not exist and was never committed |
| MCP wiring | `.mcp.json` and `.vscode/mcp.json` in OneAquaHealth both `run -m vidkit.mcp_server` → **dangling** |
| `docs/` | **landed** — 14 docs in 6 modules under `docs/`, routed by `docs/README.md` + `docs/modules.yaml` (see §3.5) |
| `reports.py` | absent |

### 3.2 Engine capability — present *(as of 2026-10-04)*

- Spec load/validate: `project, voice, narration, provider, captures, charts, scenes, guard`.
- Stages: `data, panels, stills, capture, narration, clips, concat, render, verify` with `--only`.
- CLI: `doctor, plan, build, tts, capture, verify`.
- Capture: Playwright, actions `wait/wait_for/select/click/fill/press/scroll/eval/download`,
  `assert` **before** the frame, real downloads filmed as themselves, named takes, session reuse.
- Panels: 8 built-in kinds + `register()` extension.
- Narration: scene-header parsing, bold-line extraction, token-faithful SRT, ≤2 lines/≤42 chars.
- TTS: per-scene piper WAVs; measured duration is the clock; silent fallback.
- ffmpeg/rsvg wrappers; duration without ffprobe; `still_to_clip` (hold/zoom); `mux_captioned`; `mean_volume`.
- Verify: output exists, runtime window, audio present, banned/required phrases, caption readability, live captures present, speech rate, mock-mode leakage.
- **Host-free in code**: `grep -rniE "oneaquahealth|oah_|yam-|fhir|8080|8090" vidkit/vidkit --include=*.py` → **0 code hits** (2 mentions live in comments/docstrings only).

### 3.3 Engine capability — absent *(as of 2026-10-04; several are now closed — see §3.0)*

| Gap | Requirement |
|---|---|
| ~~No timeframe field anywhere in the spec; windows hard-coded in provider URL strings (`?days=28`, `?days=90`)~~ — **closed in M1** | R-A3, R-B2 |
| ~~No story manifest / story identity~~ — **closed in M1** | R-A1, R-G3 |
| ~~No `init`/scaffold~~ — **closed in M1** | R-A2, R-G4 |
| ~~No download capture (`expect_download`)~~ — **closed in M3** | R-C3 |
| ~~No artifact rendering~~ — **closed in M3** | R-C4 |
| ~~No `wait_for_selector` action~~ — **closed in M3** | R-C5 |
| ~~No take-selection/retry~~ — **closed in M3** | R-C6 |
| ~~No auth/session support~~ — **closed in M3** | R-C7 |
| Panel x-axis is index-based, not date-proportional | R-D3 |
| No overlay / lower-thirds composite (`ffmpeg overlay`) | R-D4 |
| `still_to_clip` uses bare `scale=W:H` → **stretches** full-page captures (regression risk) | R-D5 |
| ~~No timeframe consistency check~~ — **closed in M1** | R-F7 |
| No provenance manifest | R-F8 |
| No MCP server (dangling wiring) | R-G1 |
| No `--json` on CLI | R-G2 |
| No progress/cancel for long jobs | R-G5 |
| No `hello-world` example; CI has no offline fixture | R-H3, R-H4 |
| No docs set | R-H5 |
| No `LICENSE`, no CI, no changelog | R-H7, R-H4, R-H8 |
| Still physically inside OneAquaHealth; single host-coupled example | R-H1, R-H3 |

### 3.4 Scorecard against the stated goal *(as of 2026-10-04)*

| Goal element | Aligned? | Note |
|---|---|---|
| Standalone, host-agnostic engine | ✅ | code is host-free; only the *repo location* is wrong |
| Installable toolkit | ✅ | pyproject + console script |
| Declarative story input | ⚠️ | spec exists; **story identity does not** |
| Given a **timeframe** | ❌ | no representation; windows hard-coded |
| Agent can drive it | ❌ | MCP wiring is dangling; no JSON contract |
| Self-documenting | ❌ | docs never landed |
| Verifiable output | ✅ | `verify.json` with 9 checks (missing the timeframe check) |

### 3.5 Docs modules *(pre-extraction: 14 docs / 6 modules; now 20 docs / 7 modules)*

The 14-file docs set landed and was reorganised into modules. `docs/README.md` is the
**router** and `docs/modules.yaml` is the machine-readable route table; `tool_docs`/
`vidkit_docs` resolve a bare name to a module path through it.

| Module | Docs |
|---|---|
| `foundations/` | concepts, pipeline, architecture |
| `authoring/` | spec-reference, provider-guide, panels-reference, narration-and-captions |
| `capture/` | capture-guide |
| `verification/` | verification |
| `operations/` | cli-reference, mcp-server, troubleshooting, extracting-to-new-repo |
| `guides/` | recipes |

---

## 4. Roadmap

Phases are sequential; each has an exit criterion. Effort is order-of-magnitude for one
engineer familiar with the code.

### M0 — Extract & baseline *(P0)* — **✅ COMPLETE (2026-10-06)**

Move the engine to the new repo **without** the host example; make it prove its own
standalone-ness. Move the OneAquaHealth story **into the OAH repo**, where it becomes an
MCP consumer.

**In the new vidkit repo**

- [x] Create the repo. *(Done: `gh repo create anindyasundarbera/vidkit --public`.)*
- [x] Add `LICENSE` (MIT), `CHANGELOG.md`, `.github/workflows/ci.yml`, `py.typed`.
- [x] Add `examples/hello-world/` (engine `none`; only `ffmpeg` + `rsvg-convert`) and wire it as the CI fixture.
- [x] Make `verify` and `doctor` pass on hello-world with no browser/voice installed.
- [x] Remove host references from comments/docstrings — `grep` now returns **0** across `vidkit/`, `tests/`, and `examples/`.
- [x] **Do not copy `examples/oneaquahealth/`** — removed from this repo and preserved at
      `~/Projects/oneaquahealth-story-backup/` for the OAH repo.
- [x] Create the GitHub repo and push the first commit — 54 files, commit `87b7435`.
- [x] Confirm CI green on the remote — run `37513459095`: `pytest (3.10)`, `pytest (3.12)`,
      `build hello-world end to end` all succeeded.

**In the OneAquaHealth repo** *(tracked here for completeness; executed in that repo)*

- [ ] Move the preserved story into OAH at `video/story/oneaquahealth/`.
- [ ] Add a `.mcp.json` entry that launches the standalone vidkit MCP server (once M5 lands).
- [ ] Decide D6 pinning (tag vs. git ref) and record it in the OAH README.

**Exit:** a fresh clone of the vidkit repo → `pip install -e ".[dev]"` → `pytest` green →
`vidkit build examples/hello-world/video.yaml` succeeds with only ffmpeg + rsvg-convert;
`grep` shows no host terms. **Verified locally:** 44 tests pass; hello-world builds **ALL
PASS** (8 panels, 12 stills, 87.20 s); the wheel ships `py.typed` + `LICENSE`. **Verified on a
clean GitHub runner** (run `37513459095`): all three jobs green, including `build hello-world
end to end`, which installs only `ffmpeg` + `librsvg2-bin` and asserts `verify.json` is ok.

### M1 — Story & timeframe contract *(P0)* — **COMPLETE 2026-10-06**

The functional gap that blocked the whole premise is closed.

- [x] Add `story` identity + manifest (D1) and validate it.
- [x] Add `timeframe` to the spec: **both** `{days, as_of}` and `{start, end}` (D3); expose as `ctx.timeframe`, and record the resolved window in the provenance manifest.
- [x] Thread `ctx.timeframe` into `provider.datasets(ctx)`; forbid hard-coded windows in the reference example.
- [x] Add a **timeframe-consistency verify check** (R-F7): the window stated in narration/captions matches the spec.
- [x] `vidkit init <dir>` scaffold (R-A2) producing a runnable story, including timeframe placeholders.
- [x] Update `plan` to print the resolved timeframe.

**Exit:** two builds of the same story with different timeframes produce different, correctly-labelled videos; a story with a mismatched narration window fails `verify`. **Both are now asserted by CI** (a second build with a different window; a mismatched narration that must exit 2 with the timeframe check as its only failure; a scaffolded story that must build and verify clean). Tests 44 → **84** in ~1.5 s.

### M2 — Provider & data hardening *(P1)* — ~2–3 days

- [x] Dataset snapshotting documented/guaranteed; re-render panels without re-fetching (R-B3).
- [x] Env/secret contract; never print secrets; read-only guarantee documented (R-B4).
- [x] Deterministic fallback pattern for model-dependent scenes (R-B5).
- [x] Provider guide (R-H5 partial).

**Exit:** `vidkit build --only panels,clips,render` works from persisted data with no network.
**Met** — and hardened: re-rendering from a snapshot taken for a *different* provider or window
is now refused with a sentence naming what changed, `--refresh` forces a refetch, `--from STAGE`
resumes a suffix, and `guard.require_live_data` turns a declared degradation into a verify
failure. Tests 84 → **124** in ~0.7 s.

### M3 — Capture v2 *(P0)* — **DONE**

Brought the artifact-capture capability that only ever existed in the ad-hoc OneAquaHealth
script into the engine.

- [x] `download` action: click + `expect_download` + save real bytes to `_capture/artifacts/` (R-C3).
- [x] `artifact` capture: film real downloaded bytes as themselves, sniffed by kind, a PDF
      rasterised through `pdftoppm`/`gs` (R-C4).
- [x] `wait_for` action with named states and a timeout (R-C5).
- [x] Named takes: `take: N` records and promotes explicitly (R-C6).
- [x] `vidkit auth` records a session once; `storage_state:` reuses it; a login form needs
      `allow_login: true` (R-C7); determinism frozen by default (R-C8).

**Exit met, against a real Chromium**: `examples/capture-kit/video.yaml` films five captures, a
real 158-byte CSV and a real 1104-byte PDF, and rasterises the PDF to 1275×1650. Suite 124 →
**198** tests. CI gained a `capture-probe` job that installs poppler and Chromium.

### M4 — Presentation v2 *(P0/P1)* — ~3–5 days

- [ ] Date-proportional axis in `line_series` (R-D3).
- [ ] Overlay/lower-third composite in `ffmpeg.py` (R-D4).
- [ ] Aspect-preserving crop in `still_to_clip` (R-D5) — **bug fix**.
- [ ] Extra panel kinds + `text_panel`/annotations polish (R-D1/D2).
- [ ] Transition effects catalogue (R-D6).

**Exit:** full-page captures are never stretched; a time series is spaced by real dates; an overlay renders.

### M5 — Agent surface *(P0)* — ~3–5 days

Rebuild the surface that was lost, on top of M1's contract.

- [ ] `mcp_server.py`: tools `doctor/plan/build/tts/capture/verify/verify_report/panel_kinds/docs`; resources for docs (R-G1). Wrap any printing stage so stdout can't corrupt JSON-RPC.
- [ ] `--json` on all CLI commands (R-G2).
- [ ] Job contract `{story, timeframe, out}` → artifact manifest (R-G3), reusing `init` (R-G4).
- [ ] Progress + cancellation for `build` (R-G5); structured errors (R-G6).
- [ ] Add `vidkit-mcp` console script; ship MCP config examples.

**Exit:** an MCP client can `init → build → verify` a story purely from tool calls; the same is possible from a shell with `--json`.

### M6 — Hardening & v1.0 *(P0/P1)* — ~3–5 days

- [ ] Docs set (R-H5): concepts, spec-reference, provider-guide, panels-reference, capture-guide, narration-and-captions, verification, cli-reference, architecture, recipes, troubleshooting, mcp-server.
- [ ] Portability pass + documented matrix (R-H6).
- [ ] Provenance manifest (R-F8).
- [ ] Release: tag v1.0.0, changelog, optional PyPI (R-H8/H9).

**Exit:** a fresh clone can produce a verified video for a new story + timeframe using only the docs, via both CLI and MCP.

---

## 5. Extraction runbook (M0 detail) — **executed 2026-10-06**

> Kept as the historical record of how this repo was split out. The state below is the
> *plan as written*; §3.0 describes what actually landed. The OneAquaHealth-side steps have
> **not** been executed — they belong to the OAH repo.

### Target layout (after the split)

```
vidkit (new repo)                     OneAquaHealth (this repo)
  vidkit/         engine                video/story/oneaquahealth/   the OAH story
  tests/                                ├─ video.yaml                (now lives here)
  examples/hello-world/                 ├─ narration.md
  docs/                                 ├─ provider.py
  mcp_server.py                         └─ assets/
  pyproject.toml                        dashboard/  gateway/  ...
  LICENSE  CHANGELOG.md                 .mcp.json  →  points at the vidkit repo
```

**Copy into the new repo**

```
vidkit/vidkit/        # engine (15 modules)
vidkit/tests/         # test_core.py (18 tests)
vidkit/pyproject.toml
vidkit/README.md
vidkit/.gitignore
```

**Do not copy** (extract **this** side into the OAH repo instead)

- `examples/oneaquahealth/` — requires the OneAquaHealth host (gateway :8000, dashboard :8090,
  the `oah_*` panels). It **moves to `video/story/oneaquahealth/` in the OAH repo** and
  references vidkit as an external tool (D4, D5).

**Build fresh in the new repo**

- `LICENSE` (MIT), `CHANGELOG.md`, `pyproject` metadata (`authors`, `urls`, `classifiers`).
- `examples/hello-world/` — the offline CI fixture.
- `docs/` — the set listed under R-H5.
- `.github/workflows/ci.yml` — lint (`ruff`) + `pytest` + hello-world build.
- `mcp_server.py` + `vidkit-mcp` (rebuilt, not recovered — it never existed in git).
- **MCP packaging**: a published `vidkit-mcp` entry point so a consumer can reference the
  repo/tag without copying source (D6).

**History-preserving split**

```bash
git subtree split -P vidkit -b vidkit-split
# then, in the new repo:
git pull ../OneAquaHealth vidkit-split
```

**Cleanup in OneAquaHealth**

- Move `vidkit/examples/oneaquahealth/` → `video/story/oneaquahealth/`.
- Delete `vidkit/` (and the untracked `.out/` scratch if present).
- Remove the dangling `vidkit` entry from `.mcp.json` and `.vscode/mcp.json`, then add a
  **new** entry that launches the standalone vidkit MCP server (once M5 lands).
- Update `README.md` / video docs to point at the standalone repo and the story folder.

---

## 6. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| "Story" stays an implicit convention → agents can't be handed one | High | R-A1 manifest is P0 in M1 |
| Timeframe keeps leaking into provider strings → wrong window on screen | High | R-B2 interpolation + R-F7 verify check |
| Rebuilding MCP reintroduces the stdout-corrupts-JSON-RPC bug | Medium | stdout→stderr guard around printing stages; regression test |
| Extraction drags host coupling along | Medium | R-H3 hello-world CI fixture; host-term grep in CI |
| Consumer re-vendors vidkit "just to make it work" | Medium | R-H2b/R-H2c: document the MCP reference + pinned launch; keep the story in the consumer repo |
| MCP becomes a hard requirement for consumers | Medium | Keep R-G2 (`--json` CLI) as a transport-independent fallback |
| Full-page capture stretching (silent quality bug) | Medium | R-D5 fix in M4; add a verify/size check |
| Docs/notes assume capabilities that aren't on disk | Medium | This document's §3 is verified; keep it that way |
| Single-maintainer bus factor | Medium | Docs set + CI make the repo self-explaining |

---

## 7. Appendix — how the current state was verified

**As of 2026-10-06 (this repo):**

```bash
# engine is host-free
grep -rniE "oneaquahealth|oah_|fhir|8080|8090" vidkit/*.py tests/*.py examples/   # → 0

# suite
python3 -m pytest tests -q                                    # → 44 passed

# the offline fixture builds and verifies
vidkit build examples/hello-world/video.yaml                  # → ALL PASS, 8 panels, 12 stills

# MCP surface
python3 -c "import vidkit.mcp_server"                         # 10 tools + 3 resources

# the wheel is complete
python3 -m pip wheel . --no-deps -w /tmp/wt && \
  python3 -c "import zipfile,glob;print([n for n in zipfile.ZipFile(glob.glob('/tmp/wt/*.whl')[0]).namelist() if 'py.typed' in n or 'LICENSE' in n])"
```

**Pre-extraction, 2026-10-04** (the evidence base for every requirement ID above):

```bash
# engine was host-free then too
grep -rniE "oneaquahealth|oah_|yam-|fhir|8080|8090" vidkit/vidkit --include=*.py

# no timeframe concept in the engine
grep -rniE "timeframe|date_range|window|since|days" vidkit/vidkit/*.py

# MCP server / docs / reports were never committed
git log --all --oneline -- vidkit/docs vidkit/vidkit/mcp_server.py vidkit/vidkit/reports.py

# dangling MCP wiring
cat .mcp.json .vscode/mcp.json     # both ran `python -m vidkit.mcp_server`
```

**Note on prior notes.** Earlier internal notes referenced a 14-file `vidkit/docs/`, a
`mcp_server.py` "verified 37/37", and `reports.py`. None of those existed on disk or in git at
the time. They have since been **rebuilt from scratch** — `mcp_server.py` and `reports.py` are
now real and tested (see §3.0), and the docs set has grown to 20 files in 7 modules.
