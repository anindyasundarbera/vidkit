# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `examples/hello-world/` — a self-contained, host-free example that builds with
  nothing but `ffmpeg` and `rsvg-convert`. It doubles as the CI fixture: every
  number it displays is counted from this repository at build time, and its eight
  charts exercise all eight built-in panel kinds.
- `guard.require_audio` — a silent cut must now be *declared*. Defaults to `true`,
  so a missing TTS engine can no longer silently produce an audio-free video.
- Documentation module `docs/plan/` — plan, feature roadmap, history, decision log,
  and the OpenMontage integration assessment.
- `timeframe` — every spec states the window its data describes, as `{days, as_of}` or
  `{start, end}`; `verify` asserts the datasets match it.
- Named secrets (`secrets: {KEY: ENV_VAR}`) resolved at build time, never written to the
  snapshot or the report, and redacted from logs.
- Dataset snapshots (`_build/data/_snapshot.json`) recording the exact request that produced
  each dataset, with hashes.
- `captures[].actions[]` gained `wait_for` (wait for a *named* state:
  `visible`/`attached`/`hidden`/`detached`, with a timeout) and `download` (save a
  file the page produced, under `_capture/artifacts/`). Any action may carry its own
  `assert:`, so a change can be made and proven in one step.
- `captures[].artifact` — film a file a `download` produced, instead of a URL. The
  bytes are sniffed, a PDF is rasterised through `pdftoppm` or `gs`, and a file that
  cannot be recognised is refused rather than depicted. An `artifact:` that no
  `download` in the spec produces is rejected at load time.
- `captures[].storage_state` and `captures[].allow_login` — a capture reuses a
  session recorded by `vidkit auth`; filming a login form is refused unless
  `allow_login: true` says it is the scene.
- `captures[].deterministic` and `captures[].take` — pin the clock, locale, timezone,
  motion and randomness; record and promote a named take.
- `vidkit auth URL [--spec SPEC] [--save PATH] [--wait SECONDS]` — record a signed-in
  browser session once, by hand, into a Playwright storage state. `vidkit init` now
  gitignores `.auth/`.
- `examples/capture-kit/` — a self-contained fixture that serves a page whose table
  fills after first paint and offers a real CSV and a real PDF download.
- `vidkit init DIR` — scaffold a runnable story (`video.yaml`, `narration.md`,
  `provider.py`, `story.yaml`, `.gitignore`).
- `vidkit docs [NAME]` — a single router over the module docs and the plan documents, so a
  bare stem resolves without knowing the folder.
- New verification check `filmed artifacts are real files` — emitted only for a spec
  that declares an `artifact:` capture.
- New CI job `capture-probe` — installs poppler and Chromium, films the capture kit,
  asserts the artifacts are real, and asserts that a deliberately-wrong assertion
  fails the build.

### Changed

- `verify` treats a declared silent cut as a pass and skips the speech-rate check
  when no narration track was muxed.
- `build` gained `--only STAGES`, `--from STAGE` and `--refresh`. A skipped `data` stage
  reuses the snapshot when it is fresh and records the datasets as degraded, so a partial
  run is explicit rather than silently stale. `vidkit_build` and `vidkit_capture` expose the
  same three options over MCP.
- `ProviderSpec` is validated at load time: an unknown provider, a malformed `secrets` map,
  and a missing module are all caught before any stage runs.
- A dataset whose source is unreachable is reported as degraded and, where the spec allows,
  falls back to the snapshot with a warning instead of aborting.
- `examples/oneaquahealth/` removed from this repository; it is host-coupled and
  belongs with the OneAquaHealth project.

### Repository

- Published to <https://github.com/anindyasundarbera/vidkit> (MIT). CI runs the unit
  suite on Python 3.10 and 3.12, plus an end-to-end build of `examples/hello-world`
  on a clean runner that installs only `ffmpeg` and `librsvg2-bin`.

## [0.1.0] - 2026-10-06

### Added

- Initial engine: a declarative YAML/JSON spec compiled into a narrated,
  captioned screen-recording video.
- Nine-stage pipeline — data, panels, stills, capture, narration, clips, concat,
  render, verify — runnable individually or end to end.
- Provider seam: an ordinary Python module beside the spec supplying datasets,
  panels, and stills.
- Eight built-in panel kinds: `line_series`, `bar_profile`, `stat_cards`,
  `terminal`, `endpoints`, `strip`, `kv_table`, `text_panel`; third-party kinds can
  be registered.
- Playwright-backed screen capture with per-capture assertions, so a mock frame
  cannot be captured silently.
- Narration from Markdown or inline text, with caption wrapping and `verify`
  asserting token-for-token caption fidelity.
- Piper TTS integration, with silent-cut fallback when no voice model is present.
- `verify` acceptance report (`verify.json`) covering runtime window, banned and
  required phrasing, audio presence, caption readability, and live-mode guarantees.
- MCP server (`vidkit-mcp`) exposing the pipeline as tools plus documentation
  resources.
- CLIs: `vidkit doctor`, `plan`, `build`, `tts`, `capture`, `verify`, `docs`.

[Unreleased]: https://github.com/anindyasundarbera/vidkit/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/anindyasundarbera/vidkit/releases/tag/v0.1.0
