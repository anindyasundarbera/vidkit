# Architecture

This document is for someone **modifying vidkit** or adding an extension point. It maps the
modules, the data types, and the seams.

## Module map

```
vidkit/
  __init__.py     version + error re-exports
  errors.py       VidkitError, SpecError, ToolError, ProviderError
  spec.py         Project, Voice, Narration, Shot, Scene, Assert, Action, Capture, Chart,
                  Guard, Spec; load_spec(); _validate()
  context.py      Context — paths, Shell, Ffmpeg, Rsvg, logging
  provider.py     load_provider(); collect_datasets/panels/stills()
  capture.py      Playwright capture with assertions; _find_chrome()
  narration.py    parse_scene_script(); build_srt(); wrap_caption(); SceneScript
  panels.py       renderer registry + 8 built-in kinds; register(); kinds(); render()
  svg.py          Theme, THEME, primitives (text/rect/line/polyline/circle/text_block),
                  PanelDoc, document()
  tts.py          synthesize(); concat_audio(); SceneAudio
  ffmpeg.py       Shell, Ffmpeg (duration, still_to_clip, concat, mux_captioned,
                  extract_frame, mean_volume), Rsvg
  assembler.py    STAGES; run(); Assets; make_context(); stage helpers
  reports.py      doctor_report/plan_report + format_* (shared by CLI and MCP)
  mcp_server.py   build_server(); tool_* functions; MCP tools + resources
  verify.py       Check, Report, verify_output()
  cli.py          argparse front-end
```

Dependency direction is one-way and acyclic:

```
cli → assembler → {spec, context, provider, capture, narration, panels, tts, ffmpeg, verify}
panels → svg ;  tts → {ffmpeg, narration} ;  capture → spec
```

`svg`, `errors`, and `narration` are leaf-ish (only `errors`); they are safe to import anywhere.

## Key types

- **`Spec`** — the validated spec; carries typed sub-objects and a `root`. `spec.capture(name)`,
  `spec.chart(name)`, `spec.scene(n)`, `spec.size`.
- **`Context`** — the runtime object passed to providers and stages. Owns paths and tool
  wrappers so nothing else shells out directly. `ctx.info`/`ctx.warn` are the log.
- **`Assets`** — accumulates what a run produced (`stills`, `panel_stills`, `capture_stills`,
  `scene_audio`, `video_track`, `audio_track`, `srt`, `output`, `report`).
- **`SceneAudio`** — `(n, path|None, seconds, words)`; `seconds` is measured.
- **`Report`/`Check`** — verification output.

## The seams (extension points)

| To add… | Do this | Read |
|---|---|---|
| A panel kind | `panels.register(name, fn)` from a provider | [`panels-reference.md`](../authoring/panels-reference.md) |
| A capture action | a branch in `capture._apply` | [`capture-guide.md`](../capture/capture-guide.md) |
| A TTS engine | a branch in `tts._engine_available` / `_piper_cmd` | this doc |
| A pipeline stage | append to `assembler.STAGES`, guard with `only`, add a block in `run()` | [`pipeline.md`](pipeline.md) |
| A CLI command | a subparser in `cli.main` (+ a helper) | [`cli-reference.md`](../operations/cli-reference.md) |
| A verification check | append in `verify.verify_output` | [`verification.md`](../verification/verification.md) |
| An MCP tool | a `tool_*` function + a `@server.tool` wrapper | [`mcp-server.md`](../operations/mcp-server.md) |

## Adding a stage — the shape

```python
# assembler.py
STAGES = [..., "my_stage", "render", "verify"]

# inside run():
if "my_stage" in stages:
    _run_my_stage(ctx, assets)
```

`--only` then accepts `my_stage` automatically. If the stage depends on an earlier one, guard
for the case where that stage was skipped (as `clips` does for `narration`).

## Tool wrappers

`Shell` runs commands and raises `ToolError` on failure; it is injectable (a fake runner makes
the wrappers unit-testable). `Ffmpeg` and `Rsvg` build on it.

- **`Ffmpeg.duration`** uses `ffprobe` when present, else parses `ffmpeg -i`. This is why
  `ffprobe` is optional.
- **`Ffmpeg.mux_captioned`** is the single place that knows the libass style string. If
  captions render wrong, look here. Key detail: `PlayResX/PlayResY` must equal the frame size
  or libass scales font and margins against a 384×288 canvas (captions blow up).
- **`Ffmpeg.still_to_clip`** holds the Ken-Burns `zoompan` expression.

## Invariants to preserve

1. **Spec validation happens before rendering.** Keep `_validate` strict; catching a typo
   cheaply is the whole point.
2. **Audio is measured, never assumed.** Do not replace measured durations with estimates
   except in the explicit no-engine fallback.
3. **Captions are asserted faithful and readable.** `build_srt(strict=True)` must keep both
   assertions. A "fix" that disables them is a regression.
4. **Captures assert before screenshotting.** The order in `capture_one` is load-bearing.
5. **The provider is the only place with domain knowledge.** Keep vidkit's own modules
   domain-free.
6. **No writes to source systems from the toolkit.** Read-only by contract.
7. **`svg.text` escapes by default.** Do not reintroduce manual escaping.

## Error discipline

All errors derive from `VidkitError`. The CLI catches `VidkitError` and prints
`vidkit: error: <msg>` with exit `1`. Unexpected exceptions are not caught — they surface as
tracebacks (a bug, not a user error).

## Testing strategy

- **Pure logic is unit-tested** (`tests/test_core.py`): spec validation, narration parsing,
  caption fidelity/readability, all built-in panels, the registry. No external tools needed.
- **Wrapper logic is injectable** via `Shell(runner=…)` for fake-process tests.
- **Integration is exercised by the example** (`examples/hello-world`) — a real
  end-to-end run with verification. `.github/workflows/ci.yml` builds it on every push.

To add a custom panel kind in a test:

```python
from vidkit import panels
from vidkit.svg import PanelDoc, text
panels.register("t", lambda d, o, doc: doc.add(text(1, 1, "x")))
assert "t" in panels.kinds()
```

## Size and dependency budget

Keep vidkit small and local: stdlib + optional `PyYAML`, `playwright`, `piper-tts`. No web
framework, no ORM, no cloud SDK. If a change would add a heavy dependency, prefer putting it
behind an optional import with a graceful fallback (as capture/TTS do).

## See also

- [`extracting-to-new-repo.md`](../operations/extracting-to-new-repo.md) — packaging this code standalone
- [`pipeline.md`](pipeline.md) — the stage contract
