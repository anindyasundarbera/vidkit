# Pipeline

The pipeline is a fixed, ordered list of **stages**. `vidkit build` runs them all;
`--only a,b` runs a subset. This document defines each stage precisely: what it reads,
what it writes, and what it needs.

## Stage order

```
data → panels → stills → capture → narration → clips → concat → render → verify
```

- Defined in `assembler.STAGES`.
- `--only` accepts any comma-separated subset, e.g. `--only panels` or
  `--only clips,concat,render`.
- **Dependency note:** `clips` needs `narration` results. If you run `--only clips`
  without narration, vidkit loads existing WAVs from `_build/wavs/` if present, else
  estimates duration from word count. `render` re-loads `_build/narration.wav` if the
  narration stage did not run.

## Stage reference

### `data`
**Reads:** the provider module (`provider.datasets(ctx)`).
**Writes:** `OUT/_build/data/<name>.json` — one file per dataset key.
**Purpose:** freeze the exact values the run used, so panels can re-render without the
source system, and so the run is auditable.
**Fails when:** the provider raises (wrapped as `ProviderError`), or returns a non-dict.

### `panels`
**Reads:** `spec.charts` merged with `provider.panels()`; `_build/data/*.json` (or the
in-memory datasets from this run).
**Writes:** `OUT/_build/panels/<name>.svg` and `OUT/_build/stills/<name>.png`.
**Purpose:** turn each chart definition into a full-frame PNG.
**Merge rule (guarantee):** for a chart that also exists in `provider.panels()`, the
spec's `options` are merged **over** the provider's; either side may set `title`/`kicker`,
and the provider's value wins only if the spec does not override it.
**Fails when:** a renderer raises, or the SVG is malformed.

### `stills`
**Reads:** every `still:` shot in every scene (paths relative to `ROOT`), and
`provider.stills(ctx)`.
**Writes:** renders `.svg` sources to `OUT/_build/stills/<stem>.png`; registers `.png`
sources as-is.
**Purpose:** guarantee every still a scene references exists as a PNG before clipping.
**Fails when:** a referenced still cannot be found.

### `capture`
**Reads:** `spec.captures[]`.
**Writes:** `OUT/_capture/<name>-take-N.png` (one take per capture) and
`OUT/_capture/artifacts/*` (files a `download` action produced), registered as stills.
**Purpose:** record real UI, and real files.
**Guarantee:** a capture's `assert`, and any per-action `assert`, run **before** the frame is
written. A failed assertion raises and aborts the build. An `artifact:` capture films only a
file that exists, has bytes, and whose content matches its kind; a `url:` capture refuses a
selector it cannot find. Artifact captures run **after** every other capture, so a `download`
earlier in the spec has always produced its file.
**Fails when:** Playwright is absent (warning + skip, unless the capture is required — see
`verify.require_live_mode`), no browser is found, a `wait_for` state never arrives, a
download times out, an assertion fails, an artifact is missing/empty/oversized, a PDF cannot
be rasterised, or a login form is filmed without declaring it.

### `narration`
**Reads:** the scene script (from `narration.source` merged with `narration.inline`).
**Writes:** `OUT/_build/wavs/scene-NN.txt` (the exact spoken text) and `scene-NN.wav`.
**Purpose:** produce per-scene audio and, critically, **measure** it.
**Guarantee:** `SceneAudio.seconds` is the measured duration (ffmpeg), not an estimate.
**Fails when:** the voice model is missing (falls back to estimated durations with a
warning — the pipeline does not hard-fail), or an engine configured but not runnable.

### `clips`
**Reads:** the scene spans from `narration`; the still for each shot.
**Writes:** `OUT/_build/clips/scene-<n>-<i>.mp4` one per shot; the pre-overlay take of an
overlaid scene goes to `OUT/_build/clips/base/`.
**Purpose:** render each still to a clip whose length is `scene_duration × (shot.weight / Σweights)`.
**Effect:** `hold` = static; `zoom` = slow Ken-Burns push-in ending at `1 + zoom`.
**Fails when:** a shot's still is unresolved, or ffmpeg fails.

The stage first lays the **whole run out as a plan** (`_clip_plan`) — every
`(scene, shot, seconds)` in screen order — and only then renders any of it. A dissolve
overlaps two takes, so which take carries the extra `transition_seconds` cannot be decided
clip by clip; it is decided here, once, and it is always the **outgoing** take that carries
it. A transition therefore changes no runtime: the time it overlaps is the time it takes back.

An `overlay:` is composited onto the finished take and the pre-overlay take is kept in
`clips/base/` — the concatenation glob only matches `clips/scene-*.mp4`, so a resumed
`--from concat` run still finds exactly the finished takes.

### `concat`
**Reads:** the clips (sorted numerically by scene/shot) and the scene WAVs.
**Writes:** `OUT/_build/clips/video-track.mp4` and `OUT/_build/narration.wav`
(concatenated audio, or absent if silent).
**Purpose:** join the takes. With `project.transition: cut` (the default) this is a
stream copy, so nothing is re-encoded; with any other transition it becomes a chain of
`xfade` filters and is re-encoded, because the junction is now a picture, not a splice.

### `render`
**Reads:** the video track, the audio track, and the scene spans.
**Writes:** `OUT/narration.srt` (retimed to the *real* spans) and `OUT/<project.output>`.
**Purpose:** burn captions and mux.
**Guarantees:**
- The SRT is built with a **fidelity assertion** — its text must equal the script's text
  token-for-token (see `narration.build_srt(strict=True)`).
- Every cue is asserted to be ≤ 2 lines of ≤ 42 characters.
- The mux is bounded by `project.max_seconds` (a hard `-t` ceiling).

### `verify`
**Reads:** the output media, the guards, the narration text, and `provenance.json`.
**Writes:** `OUT/_build/verify.json`; prints a PASS/FAIL table.
**Purpose:** evaluate the acceptance checks (see [`verification.md`](../verification/verification.md)).
**Exit code:** `vidkit build` returns `2` if any check fails, `0` otherwise.

It *reads* provenance rather than writing it: it is describing a build somebody else made,
and a record composed at read time would describe today while appearing to describe the build
it was handed. The identifying fields are copied into `report.facts.provenance` so one
`verify.json` is self-sufficient — see [`provenance.md`](../verification/provenance.md).

### provenance (not a stage)
After the last stage, `assembler.run` writes `OUT/_build/provenance.json` for **every**
rendering action — not just `build`. It is not a stage, so it cannot be skipped by `--only`,
and it is not a check, so it cannot fail a build. It is the build's own identity: the spec and
its hash, the window, the provider and its hash, every tool with its version and path, the
stages that ran, the dataset hashes, and the UTC time it finished.

## Running a subset

```bash
# re-render panels only (fast; uses persisted datasets)
vidkit build SPEC --only panels

# re-clip and re-render after changing a scene's shot order
vidkit build SPEC --only clips,concat,render

# refresh the screen recordings without redoing anything else
vidkit build SPEC --only capture
```

> After `--only panels`, the PNG stills are refreshed, but existing **clips** still hold
> the old frames. Re-run `clips,concat,render` to propagate a panel change into the video.

## Data flow diagram

```
provider.datasets(ctx) ──► data/<name>.json ──► panels/<name>.svg ──► stills/<name>.png
                                                       │
narration.source ──► scene text ──┬──► tts ──► wavs/scene-NN.wav ──► narration.wav
                                  │                       │
spec.stills ─────────────► stills/<stem>.png             │
spec.captures ──► captures/<name>-take-N.png             │
                                  └────────► clips (sized by measured audio)
                                                       │
                              video-track.mp4 ─────────┴──► render ──► out.mp4 + narration.srt
                                                                          │
                                                          guards ────────►► verify.json
                                                                          │
                                                     provenance ──────────►► provenance.json
```

## Idempotence and re-runs

- Every stage overwrites its own outputs; the pipeline is safe to re-run.
- `data` re-fetches, so a re-run picks up new values (this is the point).
- `narration` re-synthesizes and re-measures, so timing follows the current voice settings.
- Deleting `OUT` resets completely.

See also: [`concepts.md`](concepts.md) for the mental model, and
[`spec-reference.md`](../authoring/spec-reference.md) for the fields that configure each stage.
