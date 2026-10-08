# vidkit

> Turn a small YAML spec and your own data into a **narrated, captioned, verified**
> screen-recording video — from a shell, or from an autonomous agent over MCP.

vidkit exists for one reason: **a demo video is a claim about a system, and most tools let
you make that claim without ever checking it.**

---

## The problem

Every product needs a demo. Today it is made by hand: someone drives the app, records the
screen, writes a script, records a voice-over, cuts the takes together, and types the
numbers onto the slides. It works — and it does not scale. Change the product and the video
is stale; change the numbers and the video is a lie that nobody notices until a customer does.

The failure modes are boring and predictable, which is exactly why they keep happening:

- The recording shows **development mode** while the narration says the product is live.
- A **caption runs off the screen** two lines into a sentence, so nobody reads it.
- The voice-over states a number that was **typed from memory**, not measured.
- The cut **drifts out of sync**, because the timing table was estimated rather than measured.
- The runtime is 26 minutes and the limit was 25.
- The script makes a claim the spec **explicitly forbade**, and nothing checks it.

Hand this job to an LLM agent and it hits every one of those faster, because the agent
cannot see the screen. It writes a spec, renders, and reports success. Nothing in that loop
ever asked whether the pixels agreed with the words.

## The idea

vidkit makes the honest path the only path.

**Nothing is fabricated.** Every frame traces to something real: a live capture of a running
product, a chart drawn from a provider's measured data, or a declared graphic the engine drew
from the script's own words. There is no "mock UI" mode, because a mock UI is
indistinguishable from a real one once it is inside the `.mp4`.

**The engine then reopens the render and proves it.** `verify` does not read your spec back
to you. It decodes the finished `.mp4`, the `.srt`, and the audio track, and checks the
artifact against the promises the spec made. A broken promise fails the build.

And one rule that turned out to matter more than any single feature:

> **A declaration is not a measurement.** A check about what a picture *did* decodes the
> picture. A camera move declared in the spec is not a camera move until two frames of the
> finished clip disagree.

That rule has since caught real defects three separate times — including a check that could
never fail, because it compared a list against a filter of itself and cheerfully reported
*"5 of 6 shots move"* about shots that had only **said** they move.

## What it does

```
 video.yaml ──┐
 provider.py ─┼─► vidkit build ─►   your-video.mp4
 narration.md ┘                    your-video.srt
 assets/*.svg                      _build/verify.json      ← did we keep our promises?
                                   _build/provenance.json  ← what is this file, exactly?
```

Ten stages, one pass, no timeline editor anywhere in it:

| Stage | What it produces |
|---|---|
| `data` | Runs your provider once; snapshots every dataset to `data/*.json` so panels can re-render offline. |
| `panels` | Renders each chart's dataset to SVG (11 built-in kinds, or yours). |
| `stills` | Resolves provider stills and declared graphic assets. |
| `capture` | Drives Playwright: runs your actions, **asserts the on-screen state**, then screenshots. |
| `exec` | Runs your declared commands in a real PTY inside a sandbox, and records the screen. |
| `narration` | Parses the script, builds the SRT, synthesizes one WAV per scene. |
| `clips` | Sizes every shot from the **measured** audio, not from an estimate. |
| `concat` | Joins the shots, applying declared per-shot transitions. |
| `render` | Draws overlays and burns in the captions; muxes audio. |
| `verify` | Reopens the result and runs the acceptance checks. |

The measured audio is the master clock. That is why sync is a consequence of the pipeline
rather than something you maintain by hand.

## See it run

No browser, no network, no voice model — every number in this example is counted from the
files in this repository at build time:

```bash
git clone https://github.com/anindyasundarbera/vidkit
cd vidkit
pip install -e ".[dev]"

vidkit doctor examples/hello-world/video.yaml   # is this machine ready?
vidkit plan   examples/hello-world/video.yaml   # scenes, timings, guards — render nothing
vidkit build  examples/hello-world/video.yaml   # → hello-world.mp4 + .srt + verify.json
```

`plan` is the cheap one: it prints the whole scene plan and the estimated runtime without
touching a pixel. This example is the fixture CI builds on every push.

## Install

```bash
pip install -e .              # the engine — YAML/JSON specs
pip install -e ".[capture]"   # + Playwright, to film a real browser UI
pip install -e ".[tts]"       # + Piper, for a local voice
pip install -e ".[mcp]"       # + the MCP server (`vidkit-mcp`)
pip install -e ".[dev]"       # + pytest
```

Required external binaries are **`ffmpeg`** and **`rsvg-convert`** (Debian/Ubuntu:
`sudo apt-get install ffmpeg librsvg2-bin`). Optional: `ffprobe` (durations are read from
ffmpeg when absent), `pdftoppm`/`gs` (for filming PDFs), Chromium (Playwright), and a Piper
voice model. The extras are additive and independent — the core suite needs none of them.

`vidkit doctor` reports exactly which of these are present, and names the **missing rung**
rather than a bare "Docker: unavailable".

## The spec

A spec is data. No code executes from it; the only code that runs is the provider module you
name. The loader refuses unknown top-level keys **by name**, so a typo is an error rather than
a silently dropped section:

```yaml
project:   { title: …, slug: …, output: out.mp4, size: [1920, 1080], fps: 30,
             min_seconds: 60, max_seconds: 120 }
story:     { slug: …, title: … }        # optional manifest, or a story.yaml folder
timeframe: { start: 2026-09-07, end: 2026-10-06 }   # or { days: 90, as_of: … }
voice:     { engine: piper, model: voice.onnx }    # engine: none → declared silent cut

narration: { source: narration.md }     # "## Scene N — … · mm:ss–mm:ss", spoken lines **bold**
provider:  provider                     # provider.py: datasets, panels, stills

captures:    [ … ]   # real screen recordings (Playwright)
exec:        { steps: [ … ] }          # real commands, sandboxed, recorded
environment: [ … ]   # a real service for those commands to run inside
charts:      [ … ]   # datasets → panels
score:       { src: bed.ogg, volume: 0.45, duck_db: -12.0 }   # looped, ducked under narration
scenes:      [ … ]   # the shot plan
guard:       { banned: […], required: […], require_live_mode: true }
style:       { … }
```

Fourteen legal top-level keys, and that is all of them.

### Shots — what can be on screen

A scene is a narration block; it holds one or more shots, and a shot's `weight` splits the
scene's time between them. Every shot is one of:

| Shot | Shows |
|---|---|
| `still:` | An image you shipped (SVG/PNG), fitted — never stretched. |
| `capture:` | A named capture: a real Playwright run against a real URL or a downloaded artifact. |
| `chart:` | A named panel, drawn from a provider dataset. |
| `exec:` | A recording of a real command that ran in a declared sandbox or container. |
| `card:` | A title card the engine **draws** from the shot's own words — kicker, rule, scrim. |
| `solid:` | One flat declared field. |

Any shot can also carry `motion:` (a declared camera move) or `transition:` (how it joins the
next shot). Both are *declarations*, and both are measured in the finished file.

### Captures — the live-mode guarantee

```yaml
captures:
  - name: overview
    url: "http://127.0.0.1:8090/?mode=live"
    viewport: [1920, 1080]
    actions:
      - {type: wait,   seconds: 2.5}
      - {type: select, selector: "#site-selector", value: "yam-ito"}
      - {type: click,  selector: "[data-local-tab=evidence]"}
    assert: {selector: "#mode-indicator", contains: "Live adapter"}
```

The assertion runs *between* the interactions and the screenshot. If it fails, the build
stops — it never captures the wrong frame. Actions: `wait`, `wait_for`, `select`, `click`,
`fill`, `press`, `scroll`, `eval`, `download`. Any action may carry its own `assert:`, and
`wait_for` refuses when a state never arrives rather than treating a slow page as a correct one.

A capture that declares `artifact:` films a file the page downloaded, as itself — vidkit
sniffs the bytes and rasterises a PDF rather than filming a filename. Signing in is not an
action: `vidkit auth <url>` records a session once, by hand, and captures reuse it.

### Panels — real numbers, no hard-coding

Eleven built-in kinds: `line_series`, `bar_profile`, `stat_cards`, `terminal`, `endpoints`,
`strip`, `kv_table`, `text_panel`, `progress`, `comparison`, `quote`. An x-axis of dates is
drawn by **elapsed time**, so a three-month gap is three times as wide as a one-month gap;
ambiguous labels stay categorical, because treating them as dates would invent a timeline.
Register your own with `vidkit.panels.register(name, fn)` from your provider.

## The provider — the bridge to your data

`provider.py` is a plain module named in the spec. All project-specific knowledge lives here,
which is what keeps the engine generic:

```python
from vidkit import panels as panel_lib

def register():
    panel_lib.register("my_chart", my_chart_renderer)

def datasets(ctx):
    return {"trend": fetch_trend(), "totals": compute_totals()}   # read-only

def panels():
    return {
        "trend":  {"kind": "my_chart",   "dataset": "trend"},
        "totals": {"kind": "stat_cards", "dataset": "totals"},
    }
```

It may also define `stills(ctx) -> {name: path}`. Datasets are snapshotted on every build, so
a later render replays them offline — and a *degraded* one is declared in the report rather
than passed off as live.

## The studio — driving it from an agent

`vidkit-mcp` runs **separately** from the consumer's repo. The story stays in your repo; the
tool stays a tool. There are **34 MCP tools** and **7 resources**, and they are
session-oriented: an agent opens a sitting, pokes at a live environment, tries several takes,
keeps the best, builds, and reads the report back.

```
session_open ──► session_exec / browser_open+browser_act ──► browser_shot ×3
                                                                    │
                                                         take_select ┘
                                                                    ▼
                                                    session_build ──► session_report
```

| Group | Tools |
|---|---|
| Session | `session_open`, `session_list`, `session_status`, `session_close`, `session_build`, `session_capture`, `session_exec`, `session_report` |
| Takes | `take_list`, `take_record`, `take_select` |
| Browser | `browser_open`, `browser_act`, `browser_shot`, `browser_status`, `browser_close` |
| Environments | `env_up`, `env_down`, `env_status` |
| Render & inspect | `vidkit_build`, `vidkit_plan`, `vidkit_tts`, `vidkit_capture`, `vidkit_verify`, `vidkit_verify_report`, `vidkit_provenance`, `vidkit_doctor` |
| Authoring | `vidkit_init`, `vidkit_panel_kinds`, `vidkit_capture_plan`, `vidkit_docs`, `vidkit_docs_index`, `vidkit_actions`, `vidkit_run` |

Resources let an agent read back what it produced: `vidkit://sessions/{id}/status`,
`.../takes`, `.../report`, plus the docs index and the job-action list.

A **selected take survives the build** — `take_select` records the choice and the renderer
consumes the promoted file instead of re-shooting it. And *budgets* are declared and enforced:
wall-clock, container, and step limits refuse rather than silently overrun.

For a transport-independent integration, the same work is available as a job:

```bash
vidkit --json run plan --story examples/hello-world     # {action, story, out} → one manifest
```

## Verification — the part that makes it worth using

`verify.json` is the point of the project. It is not a log; it is an argument about the
finished file, and every check can fail:

| Check name in `verify.json` | What it establishes |
|---|---|
| `output exists` | The file is there at all. |
| `runtime within window` | The cut is inside the declared `min_seconds`/`max_seconds`. |
| `frames are the declared size` | The video really is 1920×1080 — probed, not assumed. |
| `audio present` | Audio exists — or the cut is **declared** silent (`guard.require_audio: false`). |
| `captions readable (<=2 lines, <=42 chars)` | Every cue fits on screen, two lines at most. |
| `speech rate plausible` | The voice is neither a chipmunk nor a dirge (1.6–3.6 wps). |
| `banned phrase absent` / `required phrase present` | The script says what it must, and never what it must not. |
| `timeframe consistent with spec` | Narration never states a window the spec did not declare. |
| `all live captures present` | Every capture the spec named is really in the film. |
| `filmed artifacts are real files` | A filmed download is a real, non-empty file. |
| `all datasets live` | Nothing was quietly replayed from a degraded snapshot. |
| `every declared command ran` / `every command exited as declared` | Exec steps are accounted for, with the exit codes that were promised. |
| `commands ran sandboxed` | The recording came from a confinement backend, not the bare host. |
| `every picture has an honest source` | Each artwork is a capture, a dataset, or a declared asset — nothing unknown. |
| `every camera move is accounted for` | `facts.motion[].mae` is measured from real frames; a move that did not move is reported. |
| `shot timing is expressed, not measured` | Which clock ruled the cut is stated, not implied. |
| `declared score is in the mix` | The bed really was mixed, with the measured ducking depth. |
| `no mock mode referenced` | The narration never claims a state the film does not show. |

`provenance.json` answers a different question — *what is this file?* — with the spec digest,
the resolved timeframe, the provider, and the tool versions that made it.

## Examples in this repo

| Example | Proves |
|---|---|
| [`hello-world`](examples/hello-world/) | The smallest complete build: offline, silent, every number measured from disk. The CI fixture. |
| [`capture-kit`](examples/capture-kit/) | A real page, scripted interactions, and assert-before-shot. |
| [`terminal-demo`](examples/terminal-demo/) | A real command in a real sandbox, recorded through a PTY and filmed. |
| [`docker-demo`](examples/docker-demo/) | A real Postgres, written to and read back **inside one container**, then torn down. |
| [`movie-demo`](examples/movie-demo/) | A film with **no capture, no provider, no browser**: drawn cards, a moving camera, a score. |

CI builds each of these as an end-to-end probe on a clean runner, and one more probe drives
the MCP server through a whole sitting — on top of the unit suite.

## Extending

- **A new chart** — `panels.register(name, fn)` from your provider; `fn(data, options, doc)`
  appends SVG via the helpers in `vidkit.svg`.
- **A new capture action** — add a branch in `vidkit/capture.py::apply`.
- **A new TTS engine** — add a branch in `vidkit/tts.py`.
- **A new stage** — *don't, not casually.* The stage list is the design's contract; ten phases
  added docker, an executor, movie mode, and a whole session layer without an eleventh.

## Layout

```
vidkit/
  spec.py       load + validate a spec (fails fast, names the offending key)
  context.py    the shared runtime object (paths, shell, ffmpeg, rsvg)
  provider.py   plugin loading + interface
  capture.py    Playwright: actions, assertions, downloads, artifacts, takes
  exec.py       declared commands: PTY, sandbox/container, policy, records
  terminal.py   the ANSI screen model: a .cast recording becomes frames
  narration.py  parse the script; build readable, faithful SRT
  panels.py     data → SVG panels (11 built-in kinds + a registry)
  svg.py        SVG primitives + theme
  card.py       engine-drawn title cards and solid fields
  overlay.py    banner/image graphics drawn over a shot
  tts.py        per-scene speech → WAVs (the master clock)
  ffmpeg.py     duration, fit, transitions, motion, overlay, mix, mux
  timeframe.py  the resolved window: days/as_of or start/end
  snapshot.py   dataset snapshots, freshness, declared degradation
  secrets.py    declared secrets + length-preserving redaction
  assembler.py  the ten-stage pipeline
  verify.py     the acceptance checks → verify.json
  provenance.py what built this, and from what → provenance.json
  studio.py     sessions, takes, budget, live browsers
  _loop.py      blocking work off the event loop
  job.py        the {action, story, out} job contract → one manifest
  mcp_server.py the MCP surface: 34 tools, 7 resources, transports
  cli.py        doctor / plan / build / tts / capture / auth / init / run / verify / provenance / docs
```

## Docs

Docs are modular and machine-routable. Start at [`docs/README.md`](docs/README.md), or read
the route table in [`docs/modules.yaml`](docs/modules.yaml) — 24 routes across 7 modules.
An agent can fetch any doc by bare name over MCP (`vidkit_docs name="spec-reference"`).

For the project's own record, see [`docs/plan/`](docs/plan/): [PLAN](docs/plan/PLAN.md) (now and
next), [HISTORY](docs/plan/HISTORY.md) (what happened, with evidence),
[DECISIONS](docs/plan/DECISIONS.md) (why, with alternatives), and the root
[ROADMAP.md](ROADMAP.md) (requirements and milestones).

## Tests

```bash
python3 -m pytest tests -q          # 782 tests; the core needs no external tools
```

The suite is written to **skip honestly**: six independent capability markers
(`needs_render`, `needs_sandbox`, `needs_docker`, `needs_playwright`, `needs_mcp`,
`needs_pre_312_python`) each probe *whether that capability is usable*, not whether the
toolchain looks complete. CI runs the lean suite on Python 3.10 and 3.12, then builds the
examples end to end.

## What it is not

- **Not an NLE.** No timeline UI, no keyframe editing; a film is a sequence of shots.
- **Not a UI generator.** It films what runs. It will not invent an interface for you.
- **Not your data layer.** It reads; your provider owns the truth and the fetching.
- **Not a hosted service.** It runs locally and offline after install.
- **Not vendored.** Consumers point at the standalone server; the story stays in their repo.

## Status

`1.0.0`, MIT, and honest about where it is: the engine, the studio surface, capture,
sandboxed exec, Docker environments, and movie mode are merged and verified, and CI builds
the examples end to end on a clean runner. The MCP server supports SDK 1.x and 2.x
(`mcp>=1.20,<3`). What remains is release bookkeeping — the `v1.0.0` tag and the version for
these post-1.0 milestones are still an open owner decision — and a compositor
(picture-in-picture, masks, text over live motion), which is deliberately unowned.
