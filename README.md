# vidkit

A declarative toolkit for producing **narrated, captioned screen-recording videos**
from a small YAML spec plus your own data.

vidkit was extracted from a real demo-video pipeline. It generalises the
hard-won parts of that work — real screen capture that cannot silently film the wrong
state, captions that never drop a word, per-scene audio that keeps video in sync, and
acceptance checks that fail the build when a video breaks its own promises.

**Status:** the engine is stable and independently verified — CI builds the bundled
example end to end on a clean runner.

> **Docs are modular.** Start at [`docs/README.md`](docs/README.md) — the module router — or
> read the machine-readable route table at [`docs/modules.yaml`](docs/modules.yaml).
> An agent can fetch any doc by name over MCP (`vidkit_docs`).

```
spec.yaml ─┐
provider.py┼─► vidkit build ─► your-video.mp4  (+ narration.srt, verify.json)
narration.md┘
```

## Why it exists

Most "make a demo video" attempts go wrong in predictable ways: the recording shows the
wrong app mode, a caption is unreadable, the numbers are stale, someone says "this proves"
about a correlation, or the runtime drifts past the limit. vidkit treats each of those as a
**structural guarantee**:

| Risk | How vidkit prevents it |
|---|---|
| Filming mock/dev state | A capture can `assert` the on-screen state (e.g. mode reads *live*); a failed assertion aborts the build instead of screenshotting the wrong thing. |
| Unreadable captions | SRT cues are wrapped to ≤ 2 lines / ≤ 42 chars and asserted; the build fails otherwise. |
| Dropped narration | The caption builder asserts its text is token-for-token equal to the script. |
| Audio/video drift | Video clips are sized from the **measured** TTS duration of each scene, not a hand-typed table. |
| Stale numbers | Charts are drawn from a provider that reads live data; nothing is hard-coded in the spec. |
| Overlong runtime | A hard `-t` ceiling plus a post-render duration window check. |
| Unsafe claims | `guard.banned` / `guard.required` scan all narration and caption text. |

## Install

```bash
pip install -e .              # JSON specs only
pip install -e ".[capture]"   # + Playwright screen capture
pip install -e ".[tts]"       # + Piper local text-to-speech
pip install -e ".[mcp]"       # + MCP server (vidkit-mcp)
```

Required binaries: **ffmpeg** and **rsvg-convert** (librsvg). Optional: `ffprobe`
(durations are read from ffmpeg if absent), a Chrome/Chromium for capture, and a Piper
voice model for audio (`python -m piper.download_voices en_US-lessac-medium`).

## Quick start

```bash
vidkit doctor            # check the environment (and optionally a spec)
vidkit plan SPEC.yaml    # preview scenes, timings, and guards — no rendering
vidkit build SPEC.yaml   # run the whole pipeline
vidkit verify SPEC.yaml  # re-run the acceptance checks on the last render
```

The `hello-world` worked example (at `examples/hello-world/`) builds a complete video
with **no browser, no network, and no voice model** — every number it shows is measured
from the repository on disk:

```bash
vidkit doctor examples/hello-world/video.yaml
vidkit build  examples/hello-world/video.yaml
```

It is the fixture CI builds on every push (see [`.github/workflows/ci.yml`](.github/workflows/ci.yml)).

## The spec

A spec is data — no code executes from it. Five sections:

```yaml
project:  { title, slug, output, size: [1920,1080], fps, min_seconds, max_seconds }

voice:    { engine: piper, model: path/to/voice.onnx, length_scale: 1.08 }

narration: { source: narration.md }     # scenes "## Scene N — … · mm:ss–mm:ss"
                                        # with spoken lines in **bold**

provider: provider                      # provider.py supplies data + custom panels

captures: [...]      # real screen recordings (Playwright)
charts:   [...]      # data panels (built-in or provider kinds)
scenes:   [...]      # the shot plan; shot weights split a scene's duration
guard:    { banned: [...], required: [...], require_live_mode: true }
```

Scenes reference `still:` (an SVG/PNG), `capture:` (a named capture), or `chart:` (a named
panel). See the example spec for a full, commented reference.

### Captures — the live-mode guarantee

```yaml
captures:
  - name: overview
    url: "http://127.0.0.1:8090/?mode=live"
    viewport: [1920, 1080]
    device_scale: 2
    actions:
      - {type: wait,   seconds: 2.5}
      - {type: select, selector: "#site-selector", value: "yam-ito"}
      - {type: click,  selector: "[data-local-tab=evidence]"}
      - {type: scroll, selector: "#site-workspace"}
    assert: {selector: "#mode-indicator", contains: "Live adapter"}
```

Actions: `wait`, `wait_for`, `select`, `click`, `fill`, `press`, `scroll`, `eval`,
`download`. Any action may carry its own `assert:`; a scene-level `assert` runs after the
actions and before the screenshot. If a check fails, the build stops — it never films the
wrong frame.

`wait_for` waits for a *named* state (`visible`/`attached`/`hidden`/`detached`) and refuses
when it never arrives, so a slow page cannot be mistaken for a correct one. `download` saves
a file the page produced; a capture may then declare `artifact:` **instead of** `url:` to film
that file as itself — vidkit sniffs the bytes, rasterises a PDF, and refuses if neither is
possible. An `artifact:` no `download` produces is rejected at load time.

Signing in is not an action: `vidkit auth <url>` records a browser session once, by hand, and
captures reuse it with `storage_state:`. Filming a login form is possible only when the spec
says `allow_login: true`.

### Charts — real numbers, no hard-coding

Built-in panel kinds (a `dataset` is any JSON the provider returns):

| kind | draws |
|---|---|
| `line_series` | one or more series + dashed thresholds + peak annotations |
| `bar_profile` | a ranked/ordered bar set (e.g. a river reach) |
| `stat_cards` | big-number tiles |
| `terminal` | a dark terminal block (perfect for CLI/alert output) |
| `endpoints` | a list of API routes |
| `strip` | a persistence calendar strip |
| `kv_table` | key/value rows |
| `text_panel` | wrapped prose |
| `progress` | named stages of a process (done / active / to-do) |
| `comparison` | two columns drawn at identical geometry — only content differs |
| `quote` | a quotation with its attribution |

An x axis whose labels are dates is drawn by **elapsed time**, not list order: a
three-month gap is three times as wide as a one-month one. Ambiguous labels (`"3"`,
`"March"`) are left as categories, because treating them as dates would invent a timeline.

Register your own with `vidkit.panels.register(name, fn)` from your provider.

## The provider — the bridge to your data

`provider.py` is a plain module named in the spec. It is where project-specific knowledge
lives, so the toolkit itself stays generic:

```python
from vidkit import panels as panel_lib

def register():
    panel_lib.register("my_chart", my_chart_renderer)

def datasets(ctx):
    # fetch / compute whatever your panels need (read-only!)
    return {"trend": fetch_trend(), "alert": run_pipeline()}

def panels():
    return {
        "trend": {"kind": "my_chart",   "dataset": "trend"},
        "stats": {"kind": "stat_cards", "dataset": "stats",
                  "options": {"title": "Live totals", "per_row": 4}},
    }
```

A provider may also define `stills(ctx) -> {name: path}` for pre-rendered images.

## Extending

* **New chart** — `panels.register(name, fn)`; `fn(data, options, doc)` appends SVG via the
  helpers in `vidkit.svg` (`text`, `rect`, `line`, `polyline`, `circle`, `text_block`).
* **New capture action** — add a branch in `vidkit/capture.py::apply`.
* **New TTS engine** — add a branch in `vidkit/tts.py`.
* **New stage** — add to `vidkit/assembler.py::STAGES` and guard with the `only` set.

## How it maps to the code

```
vidkit/
  spec.py       load + validate a spec (fails fast on typos)
  context.py    the shared runtime object (paths, shell, ffmpeg, rsvg)
  provider.py   plugin loading + interface
  capture.py    Playwright capture: downloads, artifacts, takes, assertions
  narration.py  parse the script; build readable, faithful SRT
  overlay.py    banner/image graphics drawn over a shot
  panels.py     data -> SVG panel renderers (built-in + registry)
  svg.py        SVG primitives + theme
  tts.py        per-scene speech -> WAVs (duration is the master clock)
  ffmpeg.py     ffmpeg/rsvg wrappers (duration without ffprobe; fit, xfade, overlay)
  assembler.py  the pipeline: data → panels → stills → capture → narration → clips → render
  verify.py     acceptance checks -> verify.json
  cli.py        doctor / plan / build / tts / capture / verify
```

## Tests

```bash
PYTHONPATH=. python3 -m pytest tests -q
```

The unit tests cover the pure-Python core (spec validation, narration parsing, caption
fidelity and readability, every built-in panel, the custom-kind registry) and the MCP
tool surface; they need no external tools.
