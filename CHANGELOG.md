# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Declared execution (R-E1…R-E5)** — a spec can now name commands to run and film, and
  the film is a replay of the recording: `exec: {steps: [...]}` plus `exec` shots. A command
  is `cmd:` (argv, or a shell script when written as a string), with `cwd`/`env`/`timeout`/
  `network`/`reads`/`expect_exit`. Every one of them is recorded as an asciinema `.cast`
  *before* any frame is drawn, so the picture and the recording cannot tell different
  stories.
- **`vidkit/exec.py`** — the bounded, auditable execution environment. Commands run under
  `bwrap(1)` with `--unshare-all`, the network off unless the *command* asks for it *and*
  the *spec* allows it, `/usr` and friends mounted read-only, and the repo bind-mounted as
  the working directory. Falls back to `local` only when the spec says so. A policy refusal
  is a result (`refused=`, exit 126), never an exception.
- **`vidkit/terminal.py`** — a hand-rolled ANSI/CSI screen model (SGR colour, cursor
  positioning, erase-in-line modes, scroll, tabs, 8-bit-safe UTF-8) that replays a recording
  into frames and renders each as SVG. `pyte` was considered and deliberately not taken as
  a dependency.
- **The two-layer network policy** — a command may ask for the network and the spec may
  permit it; either alone is not enough, and the refusal names `exec.allow_network` so the
  author knows which layer to change.
- **`guard.require_sandbox`** (default `true`) and **`guard.require_exec_success`** (default
  `true`) — the run must be sandboxed, and exit codes must match `expect_exit`, unless the
  spec declares otherwise.
- Three new verify checks: `every declared command ran`, `every command exited as
  declared`, `commands ran sandboxed` — each emitted whether it passes or fails, with the
  commands, their exit codes and their sandbox in `report.facts.exec`.
- `examples/terminal-demo/` — a recorded, sandboxed session (a counting shell
  script, an argv command, and a declared failure) that builds with no browser and no
  voice, and is probed by CI.
- `docs/capture/exec-guide.md` — what "recorded" means, the `exec:` block, the two command
  forms, backends, the network policy, the guard promises, and what execution is *not*.

### Changed

- `provenance.json` records the commands a build ran, so the record of *how* a film was
  made includes what it filmed.
- The pipeline is now 10 stages (`exec` sits between `capture` and `narration`).
- `vidkit doctor` now reports a **sandbox** row, with or without a spec — whether a confined
  command can run here is a fact about the host, not about the story. `available: false` in
  its `backends` block means the sandbox **cannot start**, which is a different answer from
  "the binary is missing": the check starts a real sandbox around `/bin/true` (14 ms,
  memoised) rather than looking for `bwrap` on `PATH`.

### Fixed

- **A backend that is present but cannot run is now a refusal, not a silent downgrade.**
  `bubblewrap` was reported available whenever the binary existed, but Ubuntu 24.04 installs
  it and then denies the unprivileged user namespaces it needs under
  `/proc/sys/kernel/apparmor_restrict_unprivileged_userns = 1`, so every invocation failed
  with `setting up uid map: Permission denied` while vidkit said the sandbox was fine. The
  refusal and `doctor` now distinguish the two cases, and name the
  `sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0` workaround.
- The load-time refusal for an unusable backend is reported **once per backend**, not once
  per command that declares it — three commands on a machine that cannot sandbox is one
  problem, and repeating it buried the per-command refusals underneath.
- A recording that only ever showed one screen used to be indistinguishable in `verify.json`
  from one that was replayed as a moving take: `playback` was `null` for both. The report now
  carries `frames` as well, so "shown as a single held screen" and "played at its real pace"
  read differently.
- `every declared command ran` was added to the report only when it *failed*, so a passing
  `verify.json` could not attest that the commands ran — a passing check and an inapplicable
  one were indistinguishable. The check is now always emitted when commands are declared.
- The message for "a scene shows an `exec` shot but the spec declares no `exec:` steps" was
  unreachable: a vaguer error was raised first. The actionable message is now the one an
  author sees.

## [1.0.0] - 2026-10-07

### Added

- **The job contract** — one call, `{action, story, out}`, returning a manifest whose keys
  never change, so an external agent can drive vidkit without knowing its verbs:
  `vidkit run ACTION` on the CLI, `vidkit_run` over MCP. A refusal is data (`ok: false`,
  `failure.kind`, `failure.hint`), not an exception, and the manifest records the window
  that was *asked for* even when the job then refuses.
- `--json` on every CLI command — the same manifest on stdout; `--progress` streams the
  run's own log to stderr, so stdout stays parseable. Both are accepted before or after the
  verb. `--progress` without `--json` is an error rather than a silent no-op.
- Five MCP tools: `vidkit_run`, `vidkit_actions`, `vidkit_init`, `vidkit_capture_plan`,
  `vidkit_provenance` (15 tools); a `vidkit://actions` resource; `progress=True` on
  `vidkit_run` and `vidkit_build`. `vidkit_run(timeout=…)` bounds a call
  (`VIDKIT_RUN_TIMEOUT`), so a long render returns a refusal instead of hanging the client.
- `progress` as data: `{steps: [{name, kind, ok, detail, seconds}], seconds}`, classified
  from the pipeline's own narration rather than a second, parallel account of it.
- `doctor` reports declared **secrets** as a tool row — present or missing, never the value —
  and folds a missing required secret into its verdict. `vidkit doctor` on a machine with no
  story at all is now valid, which is what a pre-flight check is for.
- `docs/operations/job-contract.md` — the manifest keys, the failure vocabulary, the exit
  codes, and the progress contract.

- **Provenance** (`_build/provenance.json`, R-F8) — every build records its own identity:
  the spec and a hash of its bytes, the resolved window, the provider and a hash of its
  source, the version and path of each of `ffmpeg`/`ffprobe`/`rsvg-convert`/`pdftoppm`/`gs`,
  the stages that ran, each dataset's snapshot hash, declared degradations, and the UTC
  time it finished. A tool that is missing is recorded as `present: false`, never omitted:
  "we did not check" and "it was not there" are different facts.
- The `provenance` job action and CLI verb, and `vidkit_provenance` over MCP — all three
  *read* what the build wrote. A verify reads too, and copies the identifying fields into
  `report.facts.provenance`, because a record composed at read time would describe today
  while appearing to describe last week's build.
- `docs/verification/provenance.md` — what `provenance.json` is, field by field, and how it
  differs from `verify.json` ("is this honest?" versus "what is this?").
- `docs/guides/first-video.md` — a fresh clone to a verified `.mp4` using only the docs, by
  CLI and by MCP, including the platform notes for macOS and Windows.

- `examples/hello-world/` — a self-contained, host-free example that builds with
  nothing but `ffmpeg` and `rsvg-convert`. It doubles as the CI fixture: every
  number it displays is counted from this repository at build time, and its eight
  charts exercise eight of the built-in panel kinds.
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

- `project.transition` (`cut` | `fade` | `wipe` | `slide`) and `project.transition_seconds`
  (0.05–2.0) — how one shot becomes the next. A transition *overlaps* two takes, and the
  time it overlaps is taken back, so the finished film is still exactly as long as the
  measured narration. `cut` remains the default and is still a stream copy.
- `shots[].fit` (`cover` | `contain`, default `cover`) — how a still is fitted to the frame.
  Neither value stretches: `cover` crops the overflow, `contain` letterboxes it.
- `scenes[].overlay` — a banner or image graphic composited **over** a shot, with
  `position`, `opacity`, `fade` and `height`. An overlay is drawn over evidence and can
  never stand in for it: the scene still needs its own `still`/`capture`/`chart`, and an
  `image` overlay naming a file that does not exist is refused at load time.
- Three new built-in panel kinds: `progress` (named stages, never an invented fraction),
  `comparison` (two columns at identical geometry) and `quote` (with its attribution).
  The registry now holds eleven kinds.
- `line_series` draws an x axis of *dates* by elapsed time, so a three-month gap is three
  times as wide as a one-month gap. Labels that are not unambiguously dates (`"3"`,
  `"March"`) keep even spacing — treating them as dates would invent a timeline.
  `options.x_axis: index` opts out.
- New verification check `frames are the declared size` — the produced film's geometry is
  read back from the file, so a `fit` or scale regression cannot pass unnoticed.
- New module `vidkit/overlay.py` — `banner_size`, `banner_svg`, `svg_size`.

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
- `concat` is a stream copy only for `transition: cut`. Any other transition builds an
  `xfade` chain and re-encodes, because the junction is a picture rather than a splice.
- `ffmpeg.still_to_clip` gained `fit=`; the bare `scale=W:H` that stretched a full-page
  capture is gone. `examples/capture-kit/` marks its CSV and PDF pages `fit: contain`,
  because for those two the whole document body is the claim.

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

[Unreleased]: https://github.com/anindyasundarbera/vidkit/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/anindyasundarbera/vidkit/releases/tag/v1.0.0
[0.1.0]: https://github.com/anindyasundarbera/vidkit/releases/tag/v0.1.0
