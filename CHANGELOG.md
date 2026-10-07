# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **A session-oriented studio surface (M10) — `vidkit/studio.py`.** The tool layer no longer
  speaks only in stateless verbs. A `Session` holds a spec, a record directory, a budget and a
  set of selected takes; `Registry` finds it again by id; `Take` records are **re-hashed on
  every list**, so a digest in a record is a live measurement rather than a claim;
  `status(session)` returns a `next_step` so an agent always knows what it may do next. The
  MCP surface grew from 15 tools to **34** and from 3 resources to **7**.
- **`select_take` — keep the best of several attempts.** The choice is recorded in
  `Context.selections` and **survives the render**: `capture.capture_all` keeps the promoted
  file instead of re-shooting. Before this, a selected take was silently destroyed by the next
  build.
- **Per-shot `transition:` (R-D6).** Shots can now blend rather than only cut:
  `transition: {kind: fade, seconds: 0.4}` (also `slide`, `wipe`, and an explicit `cut`).
  Building it exposed a latent engine bug — `concat=n=2` hands its **output** the *first*
  input's timebase, so *any* hard cut preceding a dissolve aborted the render. Every input is
  now normalised with `settb=AVTB`.
- **`vidkit/_loop.py`** — blocking work is offloaded off the event loop. FastMCP runs *sync*
  tools **on the loop thread** (proven, not assumed), so Playwright's sync API refused
  outright and every browser and capture tool was dead over MCP, always. Most tools are now
  `async def` around a per-session `Worker` thread.
- **Budget governance** — wall-clock, container and step budgets are declared
  on a session and enforced, with `Budget.remaining()` and a refusal rather than a silent
  overrun.
- The **`studio-probe` CI job** (the seventh): an MCP client opens a session, films three
  distinctly-coloured takes of the same page, **keeps take 2**, renders, and proves the kept
  take is what reached the film by decoding the delivered `.mp4`'s middle frame.

### Fixed

- **The spec loader no longer drops a top-level key silently.** It read only
  `raw.get("captures")`, so a top-level `capture:` block vanished with no warning and the only
  error named the *scene*. `_SPEC_KEYS` now names the 14 legal keys and the load fails on the
  offending key. The captures key is **`captures:`** (plural); the per-shot key is `capture:`.
- **`session_open` dropped four parameters** and reported success — a call that changed
  nothing said it had changed something.
- **`browser_open` raised after opening a real browser** (`'tuple' object is not a mapping`),
  telling the caller the call failed when the world had already changed.
- **`browser_shot` promoted its own record to "chosen."** The record now carries
  `"promoted": False`; selection is a separate verb.
- **`timeout:` on pointer actions was silently dropped** (`select`, `click`, `fill`, `press`
  now go through `_pointer_timeout`, default `30.0` s), and driver exceptions escaped
  `capture.apply` uncaught for every action but three.
- **`close_session` forgot a session *after* saving it**, so a failing `save` left a
  shut-down session pinned in the live registry forever.
- **`vidkit://sessions/{s}/status` awaited the *sync* `tool_session_status`**, yielding
  `'dict' object can't be awaited` — one of three mismatches between a registration closure
  and the coroutine (or non-coroutine) it wraps. A structural AST scan now pins this in both
  directions.
- **`doctor` reported the sandbox not at all** with no spec, and repeated the same line once
  per command on a sandbox-less host.

### Changed

- **Tests that call an `async` tool must await it.** A bare call returns a coroutine, so
  `pytest.raises` sees no exception and `result == {...}` compares a dict to a coroutine —
  green, and meaningless. Two such tests were found; `tests/test_mcp.py` now scans every
  `tests/test_*.py` for the pattern. Note **`anyio.run(fn, *args)` does not forward keyword
  arguments** — wrap in a lambda.
- **`tests/conftest.py` gained a fourth capability marker, `needs_playwright`**, probed by
  importing `playwright.sync_api` and *launching* Chromium, and independent of the others.
  Nine `tests/test_studio.py` tests gained the marker they had been missing.

### Added

- **Declared environments (R-E6) — services a command runs *inside*.** A spec can now
  declare `environment: [{name, image, command, env, ports, volumes, ready, ready_timeout,
  timeout, network}]`, and a step with `backend: docker` names the one it runs in. Every
  command in an environment is `docker exec`'d into the *same* container, so a demo whose
  claim is "step 2 read back the row step 1 wrote" is a claim about one real database
  rather than about two containers that happened to share an image.
- **`docker` as a backend** alongside `bubblewrap` and `local`. A container has the image's
  own filesystem, its own PID namespace and no view of the host beyond the read-only
  project bind — a *stronger* boundary than namespaces around a host process, which is why
  `CONFINING_BACKENDS` is a set read from the engine rather than the word "bubblewrap"
  spelled in the verifier.
- **A readiness contract that outlives one sample.** `ready:` (an argv, never a shell line)
  must succeed *and keep succeeding* for `READY_HOLD` (0.75 s) before anything runs. A
  single sample is not enough and never was: `pg_isready` answers at ~1.30 s against
  Postgres' *bootstrap* server, which is stopped at ~1.45 s, and a real query only succeeds
  from ~1.84 s — so a one-shot gate hands the next command a database on its way down.
- **`report.facts.environments`** — per environment: the image **by digest** (a tag is a
  name that can move), whether it became ready, how long the answer *held*, how long the
  container lived, and how it was torn down. Plus `container` on every `facts.exec` entry,
  so the sharing is visible rather than presumed.
- `vidkit doctor` reports the three Docker questions **separately** — client, daemon,
  container — because a missing client is an install, a dead daemon is a service to start,
  and an absent image is a pull, and one boolean sends all three to the same unhelpful
  sentence. The container rung is *demonstrated* (`docker run --rm hello-world`), on the
  rule that a capability gate must demonstrate the capability rather than observe a
  precondition of it.
- `examples/docker-demo/` — a real Postgres from a pinned image, written to and read back by
  two commands inside the same container, torn down on every exit path. Probed by a new
  `docker-probe` CI job that asserts the row really crossed between the two commands by
  reading the second command's own recording.
- `tests/test_docker.py` (~50 tests) and `tests/conftest.py`'s third capability marker,
  `needs_docker` — probed, and independent of `needs_render` and `needs_sandbox`.

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

**Movie mode (M9) — a film, not a demo.** The engine can now make a scored, captioned film
with **no capture, no provider and no browser**, entirely from declared pictures:

- **Camera motion.** A shot may declare `motion: {kind: zoom|pan, direction: …, amount: …}`.
  The engine builds the ffmpeg expression, and `motion:` is refused alongside a non-`hold`
  `effect:` because the two are the same statement made twice.
- **Pictures the engine draws (R-D9).** Two new shot kinds. `card:` renders a title from the
  shot's own words — a kicker, a rule, a wrapped body, an optional scrim over a `backdrop:`
  that is resolved and checked at load time — so a film needs no artwork it did not ship.
  `solid:` is one flat field.
- **An expressed clock.** `seconds:` is accepted on a **scene** and on a **shot**, and when
  every length is declared `facts.timing_source` is `"spec"`: the film is cut to its own
  number rather than to an estimate of how long someone might talk.
- **A music bed.** A top-level `score: {src, volume, duck_db, ramp, fade_in, fade_out}` is
  looped to the film's real length and ducked under the measured narration spans. Silence
  and the score are mutually exclusive — a cut with no voice plays the bed alone.
- `plan_shots(spec, audio)` is the **one** timing rule, read by both the renderer and
  `vidkit plan`, so the plan cannot disagree with the film it predicts.
- Four new verify checks — `every picture has an honest source`, `every camera move is
  accounted for`, `shot timing is expressed, not measured`, `declared score is in the mix` —
  and two new fact blocks, `artwork` and `motion`, alongside `score` and `timing_source`.
- `examples/movie-demo/` — the exit proof: five scenes, 16.01 s, a drawn card, a drawn field,
  declared artwork, an authored zoom, a looping score, and no browser at all. Probed by a new
  `movie-probe` CI job.

### Changed

- `exec.steps[]` gained `environment:`; `backend:` gained `docker`. A `docker` step that
  names no environment, a non-`docker` step that names one, an environment nothing
  references, a volume without a container path, a duplicate environment name, and an
  environment with no image are all refused at load time rather than warned about.
- The readiness gate, the command, and the log capture for a run all address the container
  through **one binding keyed by the command label**, so the gate cannot end up gating a
  different container from the one it is gating for.
- `spec.exec_environment(label)` is the single rule for "which environment does this command
  run in", read by both the verifier and the provenance writer — two walks of the same list
  were two chances to disagree.
- `provenance.json` records the commands a build ran, so the record of *how* a film was
  made includes what it filmed.
- The pipeline is now 10 stages (`exec` sits between `capture` and `narration`).
- `vidkit doctor` now reports a **sandbox** row, with or without a spec — whether a confined
  command can run here is a fact about the host, not about the story. `available: false` in
  its `backends` block means the sandbox **cannot start**, which is a different answer from
  "the binary is missing": the check starts a real sandbox around `/bin/true` (14 ms,
  memoised) rather than looking for `bwrap` on `PATH`.

### Fixed

**Movie mode (M9) — defects found while proving it.** Eight, three of one class. They are
grouped here rather than folded into the M8 list below because they were all found by
building `examples/movie-demo` and by writing tests whose job was to disagree with the
report:

- **A camera move was reported as fact without ever being looked at.** The check compared a
  list of moving shots against a filter of that same list, so it could not fail, and M9's
  whole claim is that a declaration is checked against the picture. It now decodes a frame
  from the head and the tail of every moving clip, differences them, and records the result
  as `mae` on each `facts.motion` row. It found a real defect on its first run: scene 2 of
  `movie-demo` pans across a flat `solid:`, so the picture does not change by a pixel. That
  is an honest request honestly reported — the check passes and says so — but it was being
  counted among the moving shots before. The fixture keeps that shot on purpose: it is the
  only one whose `mae` is `0.0` while its declaration is non-empty, and therefore the only
  one that proves the report separates a declaration from a measurement.
- **`narration_spans` published scene lengths as positions in the film.** On a silent cut
  there is no concatenated narration track, so there are no offsets to seek to, yet verify
  reported each scene's *estimated* duration as a span in the finished cut. Verify now
  publishes `narration_spans` **only** when every scene has a real wav behind it, and
  `facts.narration_estimate` otherwise — an estimate named as one rather than a measurement
  it is not.
- **A silent cut claimed ducking that never happened.** `facts.score.duck_seconds` was
  recomputed from the spec, so a film with no voice reported `16.01` seconds of ducking
  applied over a mix where the score simply played alone. `Ffmpeg.mix()` now returns a
  `MixResult` describing what it did, and verify reports that; `ducked: false` is
  distinguished from `ducked: null` (the score never reached the mix).
- **A camera-move filter expression was folded to a constant by ffmpeg.** `iw-iw/zoom*(1-p)`
  evaluates to a single value and renders a still; `(iw-iw/zoom)*(1-p)` travels. **The
  parentheses are load-bearing, and the failure was silent** — no error, just a film that did
  not move. Found by measuring real frames against the declared direction and amount.
- **`_spans` could not be imported where it was used.** `assembler` imports `verify`, so a
  module-level import is circular, and a generator expression is its own scope, so binding it
  inside one left the loop body unbound. It is now bound in the function body.
- **`assets_of(ctx)` bound the wrong object**, so the artwork resolver read a path that did
  not exist and every card resolved over nothing but its backdrop.
- **`vidkit plan` predicted lengths the renderer did not produce.** `plan_shots`/`_clip_plan`
  and `reports.plan_report` each carried their own copy of the timing rule. There is now one
  rule, `plan_shots(spec, audio)`, with two readers — so the plan cannot disagree with the
  film it predicts.
- **An SVG root without `xmlns:xlink` rendered nothing under `rsvg-convert`.** Any still that
  referenced a declared asset by `xlink:href` — every card with a `backdrop:` — drew an empty
  frame, silently: rsvg resolves an **absolute** href and renders nothing at all for a
  relative one, with no error either way. `svg.document()` now declares the namespace, and
  the backdrop test renders through the real rasteriser so a false pass is not possible.

- **`docker exec -t` was asked for a TTY with no terminal on Docker's own stdin**, so every
  readiness probe failed with `cannot attach stdin to a TTY-enabled container because stdin
  is not a terminal` (exit 125) and no container could ever be reported ready. The probe now
  runs without `-i`/`-t`, and it is launched the same way the commands it gates are, with
  the environment already bound.
- **A `backend: docker` step ran `docker docker exec …`.** The argv builder already began
  with the literal `docker`, and the runner prepended its own. Every such command failed
  with `unknown shorthand flag: 'w' in -w`, exit 125. The filmed path was unaffected because
  it uses `Popen` directly, which is exactly why the unit tests did not notice.
- **The container never received the declared environment.** `docker exec` does not inherit
  the client's environment, and the argv builder only forwarded `req.env`, so `PATH`,
  `LANG`, `LC_ALL`, `TERM`, `COLUMNS` and `LINES` were all empty inside. The builder now
  forwards the same environment the host path gets.
- **The Docker client's own `HOME` no longer leaks onto the filmed PTY.** With `HOME` set to
  the container user's, the client printed `WARNING: Error loading config file: open
  /root/.docker/config.json: permission denied` into the recording, where it would have been
  presented as the container's output. `HOME` is now unset for the client, and the container
  still resolves `/root` from its own `/etc/passwd`.
- **A single readiness failure erased the evidence of a service that *did* answer.** The
  "answered but never held" branch was unreachable because a failure both cleared
  `ready_since` and overwrote the detail with the last exit code — destroying the record in
  precisely the Postgres bootstrap-server case the contract exists for. The answer is now
  remembered across the whole wait and reported as "answered once, then stopped holding".
- **A crash between starting a container and binding it leaked the container.** Startup,
  binding, command running, log capture and teardown are one `try/finally`; an environment
  is recorded as *started* before readiness is awaited, so a container that came up and
  never became ready is still removed.
- **Removing a container twice rewrote the first pass's evidence.** The second teardown pass
  used to overwrite `attempted: true` and re-emit the "removed" line, so a report could claim
  four removals for one container. It is now a no-op that returns the first record unchanged.
- `cwd: "."` inside a container produced the workdir `/work/.`. It is normalised, and a
  `cwd` that escapes the project is still refused.
- A readiness command written as a YAML list of one string (`ready: ["sh -c '…'"]`) was exec'd
  as a program literally named `sh -c '…'` (exit 127). A readiness command is an argv; the
  documentation now says so in the same terms the spec reference does.
- The project is bound into the container **read-only**, and the docs now say so: a command
  that wants to write belongs in `/tmp` or a declared volume.

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
