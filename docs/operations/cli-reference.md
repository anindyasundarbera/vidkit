# CLI reference

Run as `vidkit …` (installed console script) or `python -m vidkit …`.

> For programmatic/agent use there is also an MCP server (`vidkit-mcp`); see
> [`mcp-server.md`](mcp-server.md).

## Commands

| Command | Purpose |
|---|---|
| `vidkit doctor [SPEC]` | check the environment (and a spec if given) |
| `vidkit plan SPEC` | print the scene plan, timings, and guards — no rendering |
| `vidkit build SPEC [--out DIR] [--only STAGES]` | run the pipeline |
| `vidkit tts SPEC [--out DIR]` | (re)synthesize narration only |
| `vidkit capture SPEC [--out DIR]` | (re)capture screen recordings only |
| `vidkit verify SPEC [--out DIR]` | re-run the acceptance checks |
| `vidkit docs [NAME] [--index]` | print the docs router, a named doc, or the route table |

`--version` prints the version.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | success; verification passed (or was not run) |
| `1` | hard error: bad spec, tool failure, provider failure, capture failure |
| `2` | the build ran but a **verification check failed** (or `doctor` found a missing required tool) |

CI should treat non-zero as failure.

## `doctor`

```bash
vidkit doctor                 # environment only
vidkit doctor SPEC.yaml       # environment + spec sanity
```

Reports presence of `ffmpeg` (required), `rsvg-convert` (required), `ffprobe` (optional),
`playwright` (optional), `chrome/chromium` (optional), `piper` (optional). With a spec, also
prints the project, size/fps, scene/capture/chart counts, provider, and available panel kinds.

`doctor` exits `1` if a **required** tool is missing, else `0`.

## `plan`

```bash
vidkit plan SPEC.yaml
```

Prints, without rendering:

- the project, output, size/fps, and the runtime window;
- every scene with its **estimated** duration (from word count) and its shot list;
- total narration words and estimated total runtime (with a warning if outside the window);
- the banned and required phrase lists.

Use it as the fastest feedback loop while authoring a spec.

## `build`

```bash
vidkit build SPEC.yaml
vidkit build SPEC.yaml --out ./video
vidkit build SPEC.yaml --only panels
vidkit build SPEC.yaml --only data,panels
vidkit build SPEC.yaml --only clips,concat,render
```

- `--out DIR` — where outputs go (default: the spec's folder). `_build/`, `_capture/`, the
  mp4, and `narration.srt` are written under it.
- `--only` — comma-separated subset of stages: `data, panels, stills, capture, narration,
  clips, concat, render, verify`. An unknown stage name is a hard error.

On success it prints a small JSON summary (`output`, `srt`, `clips`, `report`) so a caller can
locate the artifacts.

## `tts` / `capture`

Thin wrappers over `build --only narration` / `--only capture`, for iterating on the voice or
the recordings without touching the rest.

```bash
vidkit tts SPEC.yaml       # regenerate per-scene WAVs (re-measures timing)
vidkit capture SPEC.yaml   # refresh stills from the live UI
```

> After `tts`, re-run `clips,concat,render` for the new timings to reach the video. After
> `capture`, re-run the same.

## `verify`

Re-evaluates the checks against whatever is currently in `--out`. Exits `2` on failure.

```bash
vidkit verify SPEC.yaml --out ./video
```

## `docs`

Prints the documentation **module router**, or a named document. Names are routed through
`docs/modules.yaml`, so a bare stem works without knowing the module folder.

```bash
vidkit docs                      # the module router (docs/README.md)
vidkit docs concepts             # -> foundations/concepts.md
vidkit docs authoring/spec-reference
vidkit docs --index              # the machine-readable route table (JSON)
```

## Environment variables

vidkit reads none by itself, but your **provider** might (e.g. `MYAPP_API_URL`). Keep such
settings in the environment; keep structure in the spec.

## Common invocations

```bash
# fast authoring loop
vidkit plan SPEC && vidkit build SPEC --only data,panels

# full render
vidkit build SPEC --out ./video

# refresh everything from the source system and rebuild
vidkit build SPEC --out ./video

# only re-cut after a narration pace change
vidkit build SPEC --only narration,clips,concat,render
```

## See also

- [`pipeline.md`](../foundations/pipeline.md) — what each stage does
- [`troubleshooting.md`](troubleshooting.md) — when a command fails
