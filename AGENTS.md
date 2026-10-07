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
| I7 | **Nothing fabricated is rendered.** Not a mock UI, not an invented number, not a restaged take — and not a terminal transcript recorded off a pipe, where the program would have printed something else. | `verify.py`, `exec.py`, review |
| I8 | Specs are **plain data**. A spec never executes arbitrary code; only the named provider is imported. | `spec.py` |
| I9 | The **story lives in the consumer's repo**, never bundled into vidkit. Integration is **MCP-only, never vendored**. | [ROADMAP.md](ROADMAP.md) decision of record |
| I10 | Provider **datasets are snapshotted** to `data/*.json`, so panels re-render without re-fetching. | `assembler.py` |

---

## 3. Repository map

```
vidkit/
├─ AGENTS.md              ← you are here (agent contract)
├─ README.md              user-facing overview
├─ ROADMAP.md             requirements R-A1…R-H9, root milestones M0–M6  ← governing document
│                         (M7+ superseded by docs/plan/FEATURE-ROADMAP.md)
├─ CHANGELOG.md           release notes
├─ LICENSE                MIT
├─ pyproject.toml         packaging, extras, console scripts
├─ vidkit/                the engine (26 modules)
│    assembler.py         the 10-stage pipeline + Context/Assets wiring
│    spec.py              dataclasses + loader + cross-reference validation
│    context.py           Context/Assets: the paths every stage shares
│    provider.py          provider plugin loading (datasets/panels/stills/register)
│    capture.py           Playwright capture, action DSL, assert-before-shot
│    exec.py              declared execution: PTY, bubblewrap/docker sandbox, policy, records
│    terminal.py          ANSI/CSI screen model + .cast recording -> frames
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
│    provenance.py        what the build was and what made it -> provenance.json
│    verify.py            the acceptance checks → Report
│    reports.py           report rendering helpers (shared by CLI and MCP)
│    job.py               the {action, story, out} job contract -> one manifest
│    cli.py               doctor/plan/build/tts/capture/auth/init/run/verify/provenance/docs
│    mcp_server.py        MCP tools (15) + resources (3) + transports
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
│    test_provenance.py   the build record: shape, refusals, read-only (R-F8)
│    test_exec.py         the exec contract: policy, results, spans (R-E)
│    test_terminal.py     the screen model: CSI, SGR, cast round-trip, SVG
│    test_docker.py       the environment lifecycle: readiness, binding, teardown (R-E6)
├─ examples/
│    hello-world/         offline CI fixture (no browser, no voice, no network)
│    capture-kit/         a local fixture server the capture probe films
│    terminal-demo/       a recorded, sandboxed terminal session (exec probe)
│    docker-demo/         a real Postgres, written to and read back in one container
├─ docs/
│    modules.yaml         machine-readable doc route table (agents resolve by stem)
│    README.md            doc router
│    foundations/         concepts, pipeline, architecture
│    authoring/           spec-reference, provider-guide, panels-reference, narration-and-captions
│    capture/             capture-guide, exec-guide
│    verification/        verification, provenance
│    operations/          cli-reference, mcp-server, job-contract, troubleshooting, extracting-to-new-repo
│    guides/              recipes, first-video
│    plan/                PLAN.md, HISTORY.md, FEATURE-ROADMAP.md, DECISIONS.md, OPENMONTAGE.md
└─ .github/workflows/     CI (pytest + hello-world + capture + exec + docker probes)
```

---

## 4. How to work in this repo

### 4.1 Environment

`python3` (not `python`) is what exists here. `ffmpeg`, `rsvg-convert`, and `git` are present.
`playwright`/`piper` are **optional** extras and are not required for the core test suite.
`docker` and `bwrap` may or may not be present on this machine; the suite is written to
skip honestly when they are not.

```bash
pip install -e ".[dev]"          # core + pytest
python3 -m pytest tests -q       # 518 tests, ~8 min with every toolchain; 445 in ~6 s without
```

**Three capabilities, three independent markers.** CI runs `pytest` twice on a machine
with no `ffmpeg`, no `rsvg-convert`, and — measured, not assumed — no usable `bubblewrap`,
and separately builds `examples/hello-world` on a machine that has the render tools. A
test that needs a capability must carry the *matching* marker; `tests/conftest.py` probes
each one and skips independently:

| Marker | Probed by | Needed for |
|---|---|---|
| `needs_render` | `ffmpeg`+`rsvg-convert` on `PATH` | anything that reaches the pipeline |
| `needs_sandbox` | *running* `bwrap` around `/bin/true` | `exec` steps on the default backend |
| `needs_docker` | *running* `docker run --rm hello-world` | loading or building a `backend: docker` spec |

**The markers must stay independent.** Two of these were added after a CI failure, and both
times the failure was the same shape: a test passed locally because *this* machine happens to
have a capability, and failed in CI for a reason unrelated to the code. A marker that asks
"is the toolchain complete?" instead of "is *this* capability usable?" reintroduces exactly
that bug. Note also that **a Docker spec cannot even be *loaded* without Docker** — the
load-time policy check calls `resolve_backend("docker")` — so `@needs_docker` is required on
tests that only parse one.

Corollary for `doctor`: whether the machine is *complete* is a verdict, not a crash. Assert
`manifest["ok"] == manifest["doctor"]["ok"]`, never `ok is True`, or the test only holds on
a fully equipped box.

Corollary for `doctor`: whether the machine is *complete* is a verdict, not a crash. Assert
`manifest["ok"] == manifest["doctor"]["ok"]`, never `ok is True`, or the test only holds on
a fully equipped box.

### 4.2 Commands that must keep working

```bash
python3 -m pytest tests -q                                 # 518 passed
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
3. **Run `python3 -m pytest tests -q`.** Run the *lean* form while iterating; run the full
   form before you claim a phase is done. Never run two `pytest` processes at once — they
   share `.pytest-tmp/` and will fail each other spuriously.
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
- **The exec stage films a PTY, never a pipe.** A program checks `isatty` and changes what it
  prints when it is not on one, so piping would record a transcript that never happened
  (I7). `test_run_is_handed_a_real_terminal_not_a_pipe` pins this.
- **`terminal.replay_events(events, …)` is the engine's entry point; `replay(cast_text)` is
  the cast-file one.** They are not interchangeable and must not be merged by sniffing the
  input: a cast file carries its own timestamps, and recovering them from the stream loses
  the measured pace.
- **A recording's interior frames keep their *measured* spans; only the final frame is given
  the time that remains.** Sampling on an interval means the last screen regularly falls
  between samples, so the assembler appends it explicitly.
- **`Secrets.redact_bytes` must be length-preserving.** A cast is timed cursor movements;
  shortening one chunk shears every escape sequence after it.
- **`guard.require_sandbox` defaults `True`.** A spec that wants to run a command unsandboxed
  must say `guard.require_sandbox: false`, exactly as with `require_audio`.
- **bwrap's refusal wording is not stable.** A path that is not mounted at all reports
  `Directory nonexistent` (exit 2); only a path under a read-only mount reports a permission
  error. Assert *the file is unchanged*, never a specific errno.
- **`bwrap(1)` may exist where the render toolchain does not** (CI's `pytest` jobs are exactly
  this case), so exec tests are split: pure-Python policy/renderer tests run everywhere,
  anything that *starts* a process is `@pytest.mark.needs_sandbox` (a *probed* sandbox, not a
  binary on `PATH`).
- **A Docker spec cannot even be *loaded* without Docker.** `_validate_exec` calls
  `check_policy` → `resolve_backend("docker")`, which raises when no container can run. Any
  test that so much as parses a `backend: docker` spec carries `@pytest.mark.needs_docker`.
- **The project directory is bind-mounted into a container read-only** (`${root}:/work:ro`).
  A test command that writes must target `/tmp` or a declared volume; writing to `/work`
  fails for a reason that looks like the engine's fault.
- **`docker exec -t` demands a TTY on *Docker's own* stdin.** With stdin at `/dev/null` it
  fails with `cannot attach stdin to a TTY-enabled container because stdin is not a
  terminal`, exit 125 (defect O). `_docker_argv`/`_launch_argv` take a keyword-only
  `tty: bool = True`; the filmed path passes `True`, every internal probe passes `False`.
- **The argv *builders* name the binary; `_docker_run` prefixes it.** Handing a builder's
  output to `_docker_run` produced `docker docker exec …` (defect S). Builders answer "what
  is the argv **of** this command" — launch them with `subprocess`/`Popen` directly.
- **`docker exec` does not inherit the client's environment.** Declared `env:` must be
  forwarded as `-e` on every `exec`, and the client's own `HOME` must be *unset* or its
  unreadable `~/.docker/config.json` warning is filmed as though the container said it.
  A container is told what it needs; the host leaks nothing (defect T).
- **Readiness must hold, not merely succeed once.** `pg_isready` answers at ~1.30 s against
  Postgres' bootstrap server, which is stopped at ~1.45 s. `READY_HOLD = 0.75`. And when the
  gate fails, keep the "it *did* answer" evidence: a failure must not erase it (defect U).
- **The binding is keyed by the command *label*, never the environment name.**
  `bind_step(label, state)` is the only writer; `unbind_environments()` is called from
  `_stop_environments`, once, after the last step.
- **A container is removed in a `finally`, and teardown is idempotent.** A second pass must
  `return state` *unchanged* — overwriting the first record or re-emitting the "removed"
  line makes one container look like two (defect K).
- **`_docker_workdir` must `normpath` its `posixpath.join`.** `cwd: '.'` otherwise yields
  `/work/.`, and a `../` escape must still be refused (defect R).
- **A capability report names the missing rung, not the missing tool.** Docker has three —
  client, daemon, container — with three different fixes. One boolean sends all three to the
  same unhelpful sentence (D48). And a gate must *demonstrate*, never observe a precondition
  (**D41**).

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

> Snapshot taken 2026-10-07 (after the M8 merge). If this disagrees with
> [docs/plan/PLAN.md](docs/plan/PLAN.md), trust PLAN.md.

- **Repo state:** public on GitHub (`anindyasundarbera/vidkit`), default branch `main`,
  CI green. **M0–M8 are merged.** Nothing is in flight.
- **Tests:** `python3 -m pytest tests -q` → **518 passed in ~470 s** with every toolchain
  present, **445 passed / 73 skipped** without. Run the lean form while iterating — it is
  two orders of magnitude cheaper and it is what CI's `pytest` jobs actually do.
  **Never run two `pytest` processes at once**: they share `.pytest-tmp/` (gitignored) and
  will fail each other spuriously.
- **Three capabilities, three independent markers:** `needs_render`, `needs_sandbox`,
  `needs_docker`. See §4.1 — a marker that asks "is the toolchain complete?" rather than
  "is *this* capability usable?" is the bug the markers exist to prevent (defect G).
- **Engine:** host-free. **10 stages** (`data, panels, stills, capture, exec, narration,
  clips, concat, render, verify`), **26 modules**, 11 panel kinds, **15 MCP tools**,
  3 resources, docs across 7 modules. M8 added a backend and a resource lifecycle
  **without adding a stage** — if a future phase needs an eleventh, that is the signal to
  rethink the design, not to append (P5).
- **Active phase:** **M9 — Movie mode**
  ([docs/plan/FEATURE-ROADMAP.md](docs/plan/FEATURE-ROADMAP.md) §12). If this line disagrees
  with [docs/plan/PLAN.md](docs/plan/PLAN.md), trust PLAN.md.
- **Biggest remaining gap:** vidkit can *demonstrate* but not yet *narrate*. Stills are
  captures or declared images with no motion, audio is narration only — no score, no
  ambience, no ducking — and shot length is duration-divided-by-weight rather than chosen.
  That is M9, and it must land as an *addition* to the existing ten stages.
- **The one item needing an owner decision:** the public **`v1.0.0` tag** — the code is at
  `1.0.0` and merged, but the tag itself is a visible release and has not been pushed. M7
  and M8 both sit under `## [Unreleased]` in the CHANGELOG; whether that becomes `1.1.0` or
  `1.2.0` at release time is a second owner call.
- **Host-safety contract (M8).** A container may never mount the Docker socket, runs
  unprivileged, has a hard timeout, and is torn down in a `finally` on every exit path.
  Teardown is *reported*, not assumed (`facts.environments[].teardown`). Do not weaken this
  to make a build pass.
- **Dated risk:** GitHub announced **`ubuntu-latest` migrates to Ubuntu 26 beginning
  2026-10-19**. Every runner fact recorded for M7/M8 is a statement about Ubuntu 24.04 —
  the AppArmor restriction, the missing `bubblewrap`, the `sudo sysctl` step in `exec-probe`,
  and the working Docker daemon. Re-verify before trusting them; both probe jobs print the
  conditions they found precisely so the log is self-explaining.

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
