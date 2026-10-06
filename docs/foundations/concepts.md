# Concepts

Read this once; everything else refers back to it.

## The one-sentence model

> A **story** is a folder; a **spec** declares *what* the video is; a **provider** supplies
> *the data*; the **pipeline** turns stills into clips; **captions + audio** drive the timing;
> **verify** checks the promises.

```
   spec.yaml ─────────────┐
   provider.py ───────────┼──►  pipeline  ──►  out.mp4  +  narration.srt  +  verify.json
   narration.md ──────────┘
   assets/*.svg ──────────┘
```

## Vocabulary

| Term | Meaning | Defined by |
|---|---|---|
| **Story** | The folder (spec + narration + provider), plus an optional `story.yaml` manifest carrying slug, title, owner and timeframe. | `story.yaml`, `spec.Story` |
| **Timeframe** | The closed interval `[start, end]` the video is about, both ends inclusive. May come from `story.yaml`, the spec, or an override. | `timeframe:` / `spec.Timeframe` |
| **Project** | Title, slug, output name, size, fps, runtime window. | `project:` in the spec |
| **Scene** | One narration block. Has an index `n`, a title, and ≥1 shot. | `scenes:` in the spec |
| **Shot** | One visual beat inside a scene: a `still`, a `capture`, or a `chart`, plus a `weight` (share of the scene's duration) and an `effect` (`hold`/`zoom`). | `scenes[].shots[]` |
| **Capture** | A scripted Playwright visit to a URL that produces one PNG, with an optional assertion. | `captures:` |
| **Chart** | A named panel: a `kind` + a `dataset` + `options`. | `charts:` and `provider.panels()` |
| **Panel** | The rendered SVG/PNG of a chart. A *renderer* draws it. | `panels.py` |
| **Dataset** | Any JSON-able value a provider returns, keyed by name. | `provider.datasets()` |
| **Provider** | A plain Python module that supplies datasets, panels, and optionally stills, and can register custom renderers. | `provider:` |
| **Narration** | The spoken script, either a Markdown file or inline per scene. | `narration:` |
| **Guard** | Banned/required phrases, runtime window, live-mode requirement. | `guard:` |
| **Stage** | One step of the pipeline (see `pipeline.md`). | `assembler.STAGES` |
| **Floating window** | A relative timeframe with no `as_of`: it resolves against *today*, so narration may state its day count but never its dates. | `spec._validate_timeframe` |
| **Context** | The shared runtime object: paths, shell, ffmpeg, rsvg, logging. | `context.Context` |

## Three ideas that explain most of the design

### 1. Audio is the master clock

Most slideshow-video failures come from a hand-typed timing table drifting away from the
actual narration. vidkit removes the table. It synthesizes **one WAV per scene**, *measures*
each with ffmpeg, and builds the scene timeline from those measurements. Each scene's video
segment is then sized to its measured audio. Result: sync is a consequence of the pipeline,
not a thing you maintain.

- Module: `tts.py` (`synthesize`, `SceneAudio.seconds`).
- The scene spans `[(n, start, end), …]` produced here drive both clip lengths and caption
  timings.

### 2. Captures must prove their state

A screen recording is honest only if it shows the state you claim. So a capture can carry
an **assertion** that runs *between* the interactions and the screenshot. If it fails, the
build stops — it does **not** save the wrong frame.

```yaml
assert: {selector: "#mode-indicator", contains: "Live adapter"}
```

- Module: `capture.py::check`.
- This is how "never film mock mode" becomes structural instead of aspirational.

The same rule covers the awkward waits. `wait_for` waits for a *named state* and refuses if it
never arrives, instead of a `wait: 5` that silently films whatever the page happened to be
showing. An action may carry its own `assert:`, so "click Apply, then prove the table has five
rows" is one atomic step.

### 3. An artifact is filmed as itself, or not at all

Some things cannot be screenshotted from the DOM — a downloaded CSV, a PDF, an export. A
capture may therefore declare `artifact:` instead of `url:` and film a file a `download`
action produced. The file must exist, must be non-empty, and must be *recognisably* what it
claims: vidkit sniffs the bytes, and a PDF is rasterised through `pdftoppm` (or `gs`). If
neither rasteriser is installed, or a file's bytes do not match its extension, the build
refuses. It never films a placeholder.

- Modules: `capture.py::sniff`, `capture.py::rasterize_pdf`, `capture.py::shoot_artifact`.
- `verify.py::filmed artifacts are real files` is the last line of that defence.

Signing in is deliberately **not** a capture action. `vidkit auth` records a storage state
once, by hand; a capture reuses it. Filming a login form is possible but must be declared,
with `allow_login: true`.

### 4. Data flows one way: provider → dataset → panel → still

The spec never contains data. It names a dataset; the provider computes it. Renderers are
pure functions of `(data, options, doc)`. This keeps specs small, keeps numbers live, and
means a typo in the spec is caught at load time (before any expensive render).

- Modules: `provider.py`, `panels.py`, `svg.py`.
- The spec's cross-reference validation lives in `spec.py::_validate`.

### 5. Every claim that can be checked is checked

The spec's `timeframe:` and the narration are two independent records of the same fact. Rather
than trusting the author to keep them in sync, `verify` reads the window back out of the
narration and captions and fails when it disagrees with the spec (R-F7). The same instinct
produced `guard.banned`/`guard.required`, the live-mode requirement, and caption-fidelity
assertions: **promises in the spec, proof in the report.**

## What is deterministic vs. what is captured

| Produced deterministically | Captured from a running system |
|---|---|
| Title/boundary/end cards, diagrams (your SVGs) | The browser UI (Playwright) |
| All chart panels (from datasets) | — |
| Narration audio (TTS) | — |
| Captions, timing, muxing | — |

vidkit will **never** synthesize something that purports to be a live interface. If a frame
shows a product, it came from a capture. (See the non-goals in `README.md`.)

## The lifetime of a run

1. `load_spec` parses and validates the spec → a `Spec`; the story is loaded and the
   timeframe resolved (`override > spec > story`).
2. `make_context` builds a `Context` (paths, tool wrappers) and creates output dirs.
3. The provider module is imported; its `secrets()` are declared and its `register()` runs if present.
4. Stages execute in order (`pipeline.md`), each writing into `OUT/_build/*`.
5. `verify` evaluates the guards and writes `verify.json`.
6. The process exits `0` only if verification passes.

## Where state lives

Nothing persists between runs except files under the output directory:

```
OUT/
  <project.output>        the final mp4
  narration.srt           the final captions (retimed to the real audio)
  _build/data/*.json      provider datasets (so panels can re-render alone)
  _build/data/_snapshot.json  what request produced those datasets, and their hashes
  _build/panels/*.svg     rendered panel SVGs
  _build/stills/*.png     every still as PNG
  _build/wavs/scene-NN.wav per-scene audio
  _build/clips/*.mp4      one clip per shot
  _capture/*.png          raw captures
  _capture/artifacts/*    files a download produced, for `artifact:` captures
  _build/verify.json      the acceptance report
```

There is no database and no daemon; deleting `OUT` resets everything.

## Related documents

- How the stages run: [`pipeline.md`](pipeline.md)
- Every spec field: [`spec-reference.md`](../authoring/spec-reference.md)
- Stories and windows: [`stories-and-timeframes.md`](../authoring/stories-and-timeframes.md)
- Writing a provider: [`provider-guide.md`](../authoring/provider-guide.md)
