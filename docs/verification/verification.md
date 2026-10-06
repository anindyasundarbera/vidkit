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
| `all datasets live` | no dataset was declared degraded (a fallback used after an outage) | provider + spec |
| `speech rate plausible` | 1.6–3.6 words/sec | script + duration |
| `no mock mode referenced` | `mode=mock` absent, or only as a prohibition | narration + captions |
| `timeframe consistent with spec` | every window the narration states matches the resolved timeframe | script + SRT + spec |

The `no mock mode referenced` check exists because a script may legitimately *say* "we never
open `?mode=mock`"; so it allows the phrase near the word "never".

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
                       "start": null, "end": null, "end_anchor": null}]
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
- **No visual QA.** It does not look at frames; a panel could be blank and still "pass".
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

## See also

- [`narration-and-captions.md`](../authoring/narration-and-captions.md) — where the text comes from
- [`stories-and-timeframes.md`](../authoring/stories-and-timeframes.md) — the window contract behind R-F7
- [`capture-guide.md`](../capture/capture-guide.md) — why a capture may not have run
