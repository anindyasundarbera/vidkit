# CLI reference

Run as `vidkit …` (installed console script) or `python -m vidkit …`.

> For programmatic/agent use there is also an MCP server (`vidkit-mcp`); see
> [`mcp-server.md`](mcp-server.md).

## Commands

| Command | Purpose |
|---|---|
| `vidkit init DIR` | scaffold a new runnable story |
| `vidkit doctor [SPEC]` | check the environment (and a spec if given) |
| `vidkit plan SPEC` | print the scene plan, timings, and guards — no rendering |
| `vidkit build SPEC [--out DIR] [--only STAGES] [--from STAGE] [--refresh]` | run the pipeline |
| `vidkit tts SPEC [--out DIR]` | (re)synthesize narration only |
| `vidkit capture SPEC [--out DIR]` | (re)capture screen recordings only |
| `vidkit verify SPEC [--out DIR]` | re-run the acceptance checks |
| `vidkit docs [NAME] [--index]` | print the docs router, a named doc, or the route table |

`--version` prints the version.

Every command that reads a spec also accepts the **timeframe overrides** below.

| Flag | Meaning |
|---|---|
| `--timeframe WINDOW` | an explicit window: `28d`, `6m`, `2026-09-09..2026-10-06`, `9 September 2026 to 6 October 2026` |
| `--days N` | `N` days ending on `--as-of` (or today) |
| `--as-of YYYY-MM-DD` | the end date for a relative window, and the date a floating window resolves against |

Precedence is **override > `video.yaml` > `story.yaml`**; the winner is reported by
`plan`, `doctor`, and the build banner. → [Stories and timeframes](../authoring/stories-and-timeframes.md)

## `init`

```bash
vidkit init my-story --title "My Story" --days 14 --as-of 2026-10-06
```

Writes a four-file runnable story into `DIR`: `story.yaml`, `video.yaml`, `narration.md`, and
`provider.py`. The result builds and passes `verify` unmodified, and its runtime window is
sized from the narration's own word count. **Existing files are never overwritten** — running
`init` over a folder that already has work in it fails instead of clobbering.

| Flag | Meaning |
|---|---|
| `--title TEXT` | story title (default: the folder name, prettified) |
| `--slug TEXT` | story slug (default: slugified folder name) |
| `--timeframe WINDOW` / `--days N` / `--as-of DATE` | the window to scaffold |
| `--owner TEXT` | owner recorded in `story.yaml` |

## Exit codes

| Code | Meaning |
|---|---|
| `0` | success; verification passed (or was not run) |
| `1` | hard error: bad spec, tool failure, provider failure, capture failure |
| `2` | the build ran but a **verification check failed** (or `doctor` found a missing required tool or secret) |
| `2` | `doctor` found a missing **required** tool |

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
- the story (`slug`, and where its identity came from) and the resolved **timeframe**,
  labelled with its source (`override` / `spec` / `story`);
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
vidkit build SPEC.yaml --from render
vidkit build SPEC.yaml --only panels,clips,render --refresh
```

- `--out DIR` — where outputs go (default: the spec's folder). `_build/`, `_capture/`, the
  mp4, and `narration.srt` are written under it.
- `--only` — comma-separated subset of stages: `data, panels, stills, capture, narration,
  clips, concat, render, verify`. An unknown stage name is a hard error.
- `--from STAGE` — that stage and every later one. Equivalent to `--only` with the suffix,
  and easier to read when you are resuming. `--only` and `--from` are mutually exclusive.
- `--refresh` — fetch provider data again instead of reusing `_build/data`. It re-adds the
  `data` stage to whatever `--only`/`--from` selected, so any snapshot is replaced.

Skipping `data` does **not** mean the datasets are trusted blindly: the `_build/data/_snapshot.json`
record must match the current provider and window, or the build refuses rather than
re-rendering yesterday's numbers under today's title. See
[the provider guide](../authoring/provider-guide.md#datasets-snapshots-and-staleness).

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

# same spec, a different window
vidkit build SPEC --out ./last-quarter --timeframe 2026-07-01..2026-09-30

# start a new story
vidkit init my-story --days 28 --as-of 2026-10-06

# only re-cut after a narration pace change
vidkit build SPEC --only narration,clips,concat,render
```

## See also

- [`pipeline.md`](../foundations/pipeline.md) — what each stage does
- [`troubleshooting.md`](troubleshooting.md) — when a command fails
