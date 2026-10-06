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

### Changed

- `verify` treats a declared silent cut as a pass and skips the speech-rate check
  when no narration track was muxed.
- `examples/oneaquahealth/` removed from this repository; it is host-coupled and
  belongs with the OneAquaHealth project.

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
