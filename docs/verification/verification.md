# Verification

`verify.py` turns a spec's promises into mechanical checks. `vidkit build` runs them at the
end and returns exit code **2** if any check fails; `vidkit verify` re-runs them on the last
render. The report is written to `OUT/_build/verify.json`.

## The checks

| Check | Passes when | Reads |
|---|---|---|
| `output exists` | the final mp4 is on disk | filesystem |
| `runtime within window` | `min_seconds ≤ duration ≤ max_seconds` | ffmpeg |
| `audio present` | an audio track exists and mean volume > −50 dB | ffmpeg `volumedetect` |
| `banned phrase absent: <p>` | `<p>` appears 0 times in narration + captions | script + SRT |
| `required phrase present: <p>` | `<p>` appears ≥ 1 time | script + SRT |
| `captions readable` | every cue ≤ 2 lines × ≤ 42 chars | SRT |
| `all live captures present` | every declared capture produced a PNG | `assets.capture_stills` |
| `filmed artifacts are real files` | every `artifact:` capture filmed a non-empty file that came from a `download` | `assets.artifacts` |
| `all datasets live` | no dataset was declared degraded (a fallback used after an outage) | provider + spec |
| `speech rate plausible` | 1.6–3.6 words/sec | script + duration |
| `no mock mode referenced` | `mode=mock` absent, or only as a prohibition | narration + captions |
| `timeframe consistent with spec` | every window the narration states matches the resolved timeframe | script + SRT + spec |
| `every declared command ran` | each `exec.steps[]` entry produced a recorded run | `assets.exec_results` |
| `every command exited as declared` | the observed exit code is in the step's `expect_exit` | `assets.exec_results` |
| `commands ran sandboxed` | no `exec` step ran under `local` — the confining backends are read from the engine, so a container counts | `assets.exec_results` |
| `frames are the declared size` | the produced film is `project.size` in pixels | ffmpeg |
| `every picture has an honest source` | every shot's kind maps to a source class the engine knows: live capture, measured data, or declared asset | `spec.shots` |
| `every camera move is accounted for` | a real frame from the head and the tail of each moving clip is decoded and differenced | ffmpeg |
| `shot timing is expressed, not measured` | either every scene length was declared, or the voice was the master clock | spec + `assets.scene_audio` |
| `declared score is in the mix` | a declared `score:` reached the mix with the ducking that was actually applied | `assets.mix_result` |

The `no mock mode referenced` check exists because a script may legitimately *say* "we never
open `?mode=mock`"; so it allows the phrase near the word "never".

### `filmed artifacts are real files` (R-C4)

Emitted **only when the spec declares at least one `artifact:` capture** — a story that films
no files should not carry a check it cannot fail.

It asserts that each declared artifact resolved to a real file that a `download` action
actually produced this run, and that the file has bytes in it. A filename in a spec is not
evidence; a file on disk with a size is. `detail` reports how many artifacts were checked.

Most of the work happens earlier and more cheaply: an `artifact:` that no `download` in the
spec produces is refused by `load_spec`, and a zero-byte or oversized file is refused by
`capture.artifact_source`. This check is the last line — it catches an artifact that was
declared, validated, and then never actually written.

### `every camera move is accounted for`

A shot may declare `motion:`. That declaration is a claim about the picture, so this check
**measures the picture**: it decodes a frame near the head of the clip and a frame near its
tail at 64×36, differences them, and records the mean absolute error as `mae` on that shot's
`facts.motion` row. `MOVE_MAE = 0.10` is the threshold for "the picture changed".

- every declared move moved → passes, `4 of 4 declared move(s) change the picture`.
- a move over a flat field → **passes**, with `1 over a field with nothing in it to reveal`.
  A pan across a `solid:` is an honest thing to ask for; a uniform field simply has nothing
  in it to shift. Saying so is the point.
- a clip that could not be read or decoded → **fails**. A measurement that did not happen is
  not a measurement of zero.

This check replaced one that compared a list against a filter of itself and so could never
fail. That is worse than having no check, because it reads as assurance. See
[the honesty rule](#what-verification-does-not-do).

### `shot timing is expressed, not measured` (a film, not a demo)

`facts.timing_source` is `"spec"` when every scene length was declared with `seconds:`, and
`"audio"` when the measured voice was the master clock. A film declares its lengths; a demo
derives them. Both are honest — what is not honest is reporting declared lengths as if they
were measured. The check's `detail` names every length and its origin.

### `declared score is in the mix`

Passes when a declared `score:` reached the mix, and reports the ducking that was **actually
applied** rather than the ducking that was configured:

- `facts.score.ducked` is `true` when the bed was ducked under measured narration spans,
  `false` when the score plays alone, and `null` when the score never reached the mix.
- `ducked: false` on a silent cut is correct, not a failure — there is nothing to duck under.
  `facts.score.duck_seconds` is `0.0` there for the same reason.

An earlier version recomputed the ducked spans from the spec, so a silent cut reported
`duck_seconds: 16.01` for ducking that never existed. `ffmpeg.mix()` now **returns** what it
did and verify reports that.

### `narration_spans` vs `narration_estimate`

`facts.narration_spans` is published **only when every scene has a real wav file on disk** —
each span is a seek offset into a concatenated narration track, and a span without a wav
behind it is a fiction. When any scene is silent (no voice engine, a declared silent cut, or
a TTS failure), verify publishes `facts.narration_estimate` instead: one entry per scene of
the word count divided by `_FALLBACK_WPS = 2.5`, clearly named as an estimate.

Machine consumers must branch: `narration_spans` present → real offsets; `narration_estimate`
present → estimates; **neither** → a film with no scene audio at all. Never read one as the
other. An estimate is not a measurement, and this is the difference between the two.

### `timeframe consistent with spec` (R-F7)

`verify` reads the window out of the narration *and* the captions and compares it with the
window the spec resolved. It understands an absolute range (`9 September 2026 to 6 October
2026`), a relative window (`the last 28 days`, `over the past six months`), a relative window
with a named end (`the last 28 days to 2026-10-06` — checked on both count and end date), and
a bare day count (`a 28-day window`).

- narration silent about time → **passes**, with a note (`narration states no window; spec
  says …`). Silence is checkable and is not a failure.
- narration states a window that disagrees with the spec → **fails**, naming both windows.
- spec declares **no** timeframe while narration states a window → **fails**.

A window narration states that the spec *cannot guarantee* — dates while the window floats —
is refused earlier, at `load_spec`, rather than reaching verify. → [Stories and
timeframes](../authoring/stories-and-timeframes.md)

## `verify.json` shape

```json
{
  "ok": true,
  "facts": {
    "duration_seconds": 260.7,
    "duration_human": "4:20.70",
    "output": "/abs/path/demo.mp4",
    "mean_volume_db": -16.9,
    "narration_words": 729,
    "timeframe": {"start": "2026-09-09", "end": "2026-10-06", "days": 28,
                  "as_of": "2026-10-06", "source": "spec", "floating": false},
    "window_claims": [{"raw": "the last 28 days", "days": 28, "exact": false,
                       "start": null, "end": null, "end_anchor": null}],
    "artwork": [
      {"scene": 1, "index": 0, "name": "scene-01-0", "kind": "card",
       "source": "declared asset", "asset": null, "motion": "zoom in 8% (start)",
       "mae": 1.309, "label": null}
    ],
    "artwork_sources": ["declared asset"],
    "motion": [
      {"scene": 2, "index": 0, "kind": "pan", "direction": "left", "amount": 0.1,
       "span": 3.0, "at": "start", "mae": 0.0, "label": null}
    ],
    "narration_estimate": {"1": 4.0, "2": 3.0},
    "timing_source": "spec",
    "score": {"src": "assets/theme.ogg", "seconds": 16.01, "ducked": false,
              "duck_seconds": 0.0, "duck_db": -12.0, "volume_db": -6.9, "spans": []},
    "exec": [
      {"label": "write", "cmd": ["psql", "-c", "…"], "backend": "docker",
       "container": "vidkit-db-10e98a0eb4e", "exit_code": 0, "expect_exit": [0],
       "expected": true, "seconds": 0.088, "cast": "write.cast",
       "frames": null, "playback": null}
    ],
    "environments": [
      {"name": "db", "image": "postgres:16-alpine",
       "image_digest": "sha256:721873c3…", "ready": true,
       "ready_detail": "`docker exec` of the declared readiness command answered for 0.98s without a single failure: … accepting connections",
       "seconds": 2.663,
       "teardown": {"attempted": true, "stopped": true, "removed": true,
                    "detail": "container vidkit-db-10e98a0eb4e stopped and removed"}}
    ]
  },
  "checks": [
    {"name": "runtime within window", "ok": true, "detail": "260.70s within [180, 300]"},
    {"name": "banned phrase absent: 'legal limit'", "ok": true, "detail": "0 hit(s)"},
    {"name": "timeframe consistent with spec", "ok": true,
     "detail": "matches 2026-09-09 to 2026-10-06 (28 days)"}
  ]
}
```

Machine consumers should read `ok` and `facts`; the `checks` array is the human detail.

## Configuring the checks

Checks are driven entirely by the spec's `guard` block and `project` window:

```yaml
project: {min_seconds: 180, max_seconds: 300}
guard:
  banned: ["legal limit", "proves a", "a real event"]
  required: ["synthetic", "causation"]
  require_live_mode: true       # every capture must have succeeded
  require_live_data: true       # no dataset may have fallen back to a declared default
```

- `guard.min_seconds` / `guard.max_seconds` override the project window for the check.
- `require_live_mode: true` enforces that captures actually ran (use it whenever the story
  depends on real UI).
- `require_live_data: true` enforces that every dataset came from its source. A provider
  whose source was unreachable may raise `SourceUnavailable` and return a value it
  *declared* in advance; that dataset is recorded in `facts.degraded` and fails this check.
  Use it whenever the video's claim is "this is what the system says today"; leave it
  `false`, and say so in the spec, for a demo whose provider synthesizes its own series.
  See [the provider guide](../authoring/provider-guide.md#when-the-source-is-down).

## What verification does NOT do

Be explicit about this — over-trusting a green report is the main risk.

- **No semantic judgement.** `banned`/`required` are substring matches. A sentence can pass
  every check and still be misleading. Human review is required.
- **No visual QA.** It checks exactly one thing about the pixels — whether a declared camera
  move changed the picture (a 64×36 head/tail difference). A panel can still be blank, a card
  can still be clipped, and a shot can still be dull, and the report will pass.
- **No number correctness.** It cannot tell whether a figure on screen is *true* — that is
  the provider's job.
- **No caption/audio alignment beyond duration.** It checks the caption file's shape and the
  audio's presence, not that a specific word lands at a specific millisecond.
- **Substring false negatives.** `banned: ["caused"]` will also match "caused" inside a
  quoted safe phrase. Choose banned strings carefully (prefer distinctive phrases).

## Using it as a gate

```bash
vidkit build SPEC          # exit 0 = all checks pass; 2 = a check failed; 1 = a hard error
vidkit verify SPEC         # re-check without re-rendering
```

In CI:

```bash
vidkit build SPEC || { echo "video failed verification"; exit 1; }
```

## Reading a failure

```
[FAIL] runtime within window — 312.00s within [180, 300]
[FAIL] required phrase present: 'causation' — missing
```

- **runtime** — trim the script or lower `length_scale`, or widen the window.
- **required missing** — add the disclosure to the script.
- **banned present** — rephrase; the guard is protecting a stated boundary.
- **audio present** — no TTS audio was produced; check `voice`.
- **live captures present** — a capture did not run; see [`capture-guide.md`](../capture/capture-guide.md).
- **speech rate** — usually a sign the audio failed and durations were estimated.
- **every camera move is accounted for** — a clip was missing or unreadable, so nothing could
  be measured. Check `facts.motion[*].mae`; `0.0` with `ok: true` is a move over a flat field.
- **declared score is in the mix** — `facts.score` was absent. The score never reached ffmpeg.

## See also

- [`narration-and-captions.md`](../authoring/narration-and-captions.md) — where the text comes from
- [`stories-and-timeframes.md`](../authoring/stories-and-timeframes.md) — the window contract behind R-F7
- [`capture-guide.md`](../capture/capture-guide.md) — why a capture may not have run
- [`exec-guide.md`](../capture/exec-guide.md) — commands, environments, and what "sandboxed" counts
