# Troubleshooting

Diagnose from the error text outward. Start with `vidkit doctor`.

## First moves

```bash
vidkit doctor SPEC.yaml     # environment + spec sanity
vidkit plan SPEC.yaml       # catch spec problems before rendering
```

`doctor` reports missing tools. `plan` prints the scene plan and estimates runtime.

## Error → cause → fix

| Symptom / error text | Likely cause | Fix |
|---|---|---|
| `missing required tool: ffmpeg` | ffmpeg not installed / not on PATH | install ffmpeg |
| `missing required tool: rsvg-convert` | librsvg not installed | install librsvg (`rsvg-convert`) |
| `YAML but PyYAML is not installed` | `.yaml` spec without PyYAML | `pip install pyyaml`, or use `.json` |
| `spec not found: …` | wrong path | check the path |
| `project.output is required` | missing field | add it (`spec-reference.md`) |
| `project.min_seconds must be < max_seconds` | inverted window | fix the window |
| `scene N: a shot needs exactly one of still/capture/chart` | shot has 0 or 2 sources | give it exactly one |
| `scene N: still not found: …` | path wrong relative to `ROOT` | correct the path (resolution: `ROOT`, `ROOT/..`, cwd) |
| `scene N: capture 'x' is not defined` | typo, no provider | define it in `captures:` |
| `scene N: chart 'x' is not defined` | typo, no provider | define it in `charts:`/`provider.panels()` |
| `spec needs narration.source or narration.inline` | no script | add one |
| `scene N has no narration text` | scene missing from the script | add its `**bold**` line or `inline` |
| `narration file has no '## Scene N …' headers` | header format wrong | match the grammar exactly |
| `no spoken (**bold**) lines found` | no bold lines | bold the spoken lines |
| `provider module not found: …` | wrong `provider:` name/path | fix it |
| `provider.datasets() failed: <urlopen … Connection refused>` | your data source is down | start it, or point the provider elsewhere |
| `provider.datasets() must return a dict` | provider bug | return a dict |
| `provider.panels()[…] must be a dict or tuple` | provider bug | return the right shape |
| `provider.panels() must return a dict` | provider bug | return a dict |
| `unknown panel kind 'x'` | kind not built-in and not registered | register it, or fix the name |
| `capture 'x' failed: Page.click: Timeout …` | wrong selector / page not ready | inspect the markup; add a wait |
| `assertion failed: …, contains 'live' (saw 'Mock dataset')` | wrong app state — guard working | fix URL/state; do not remove the assert |
| `playwright not installed — skipping capture` | no Playwright | `pip install "vidkit[capture]"`, or use `still:` |
| `TTS failed for scene N …; estimating duration` | voice model missing/broken | fix `voice.model` |
| `no TTS engine available … silent cut` | engine off/unavailable | install piper or accept the silent cut |
| `no clips to concatenate` | `clips` produced nothing | usually a downstream symptom — check earlier stage logs |
| `caption cue N is not readable: …` | token > 42 chars | shorten it or move it to a panel |
| `caption fidelity check failed` | text mismatch | report as a bug; do not disable `strict` |
| `unknown stage(s): x` | bad `--only` | use stage names from `pipeline.md` |
| `command failed (1): rsvg-convert … EntityRef: expecting ';'` | unescaped `&` in an SVG you authored by hand | escape it (`&amp;`); vidkit's `text()` escapes automatically |
| `[FAIL] runtime within window` | script too long/short | adjust `length_scale` or trim |
| `[FAIL] audio present — no audio stream` | silent cut | set up TTS, or accept if intended |
| `[FAIL] required phrase present: 'x' — missing` | disclosure absent | add it to the script |
| `[FAIL] all live captures present — missing: […]` | a capture did not run | see [`capture-guide.md`](../capture/capture-guide.md) |

## Common scenarios

### "My panel change didn't appear in the video"

Rendering is staged. `--only panels` refreshes PNGs but existing **clips** still hold the old
frames. Push the change through:

```bash
vidkit build SPEC --only clips,concat,render
```

### "The video is the wrong length"

Runtime = sum of measured narration. Change the script or the pace, then:

```bash
vidkit build SPEC --only narration,clips,concat,render,verify
```

### "Captions are huge or overlapping"

The libass style must know the frame size. vidkit sets `PlayResX/PlayResY` from
`project.size`; if you hand-rolled an ffmpeg call, do the same, or the font/margins are scaled
against libass's default 384×288 canvas.

### "A capture keeps timing out"

The live system is slow or the selector changed. Add a `wait`, and verify the selector against
the real DOM. Prefer asserting a readiness marker over a long fixed sleep.

### "It worked, then the tag/data drifted"

If the provider reads a live system, its values change. That is intended. Persisted datasets
are in `OUT/_build/data/*.json` — diff them across runs to see what moved.

### "`Connection refused` from the provider"

The upstream service is not running. Start it (or point the provider at another host). vidkit
correctly refuses to build a video whose numbers it cannot fetch.

## Inspecting a failed run

```bash
ls OUT/_build/data/      # the exact datasets used
ls OUT/_build/panels/    # rendered SVG panels
ls OUT/_capture/         # the raw captures
cat OUT/_build/verify.json
```

## Resetting

Delete `OUT` (or just `OUT/_build`, `OUT/_capture`) to start clean. There is no other state.

## Reporting a bug

Include: the command, the full error text, the `verify.json` (if produced), and the relevant
`_build/data/*.json`. These pin the exact inputs.
