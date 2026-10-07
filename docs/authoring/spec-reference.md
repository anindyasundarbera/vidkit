# Spec reference

A spec is a plain-data document in **YAML** (`.yaml`/`.yml`, needs PyYAML) or **JSON**
(`.json`, always works). It has five sections plus three optionals. Nothing in a spec
executes code.

**Validation happens at load time** (`spec.load_spec` → `_validate`). Malformed specs fail
before any rendering, with a message naming the offending scene/field.

Path resolution: any relative path in a spec is resolved against `ROOT` (the spec's folder),
then `ROOT/..`, then the current directory.

---

## Top-level keys

| Key | Required | Type | Notes |
|---|---|---|---|
| `project` | ✅ | mapping | see below |
| `scenes` | ✅ | list | ≥ 1 scene |
| `narration` | ✅* | mapping | *required unless every scene has `narration.inline` |
| `voice` | — | mapping | defaults to Piper, engine on |
| `provider` | — | string or mapping | module name; enables custom data/renderers, secrets, fallbacks |
| `timeframe` | — | mapping | the window of time the story is about; see below |
| `captures` | — | list | screen recordings |
| `charts` | — | list | data panels |
| `exec` | — | mapping | commands to run and film in a real terminal |
| `environment` | — | list | services that `backend: docker` commands run inside |
| `score` | — | mapping or string | a music bed mixed under the narration; see below |
| `guard` | — | mapping | acceptance checks |

---

## `project`

| Field | Required | Type | Default | Meaning |
|---|---|---|---|---|
| `title` | ✅ | string | — | human title (used by `plan`, reports) |
| `slug` | ✅ | string | — | short id |
| `output` | ✅ | string | — | output filename, e.g. `demo.mp4` |
| `size` | — | `[w, h]` | `[1920, 1080]` | frame size |
| `fps` | — | int | `30` | frame rate |
| `min_seconds` | — | number | `180` | lower bound of the runtime window |
| `max_seconds` | — | number | `300` | upper bound; also the hard mux ceiling |
| `transition` | — | `"cut"` \| `"fade"` \| `"wipe"` \| `"slide"` | `"cut"` | how one shot becomes the next |
| `transition_seconds` | — | number | `0.5` | length of that transition, 0.05–2.0 |

**Constraint:** `min_seconds < max_seconds` (else `SpecError`).

`transition` is how the film gets from one shot to the next, and the four values
say four different things:

| Value | What it claims |
|---|---|
| `cut` | the state changed; nothing to linger on |
| `fade` | these two moments overlap — the old one is still resolving while the new one arrives |
| `wipe` | the new state *replaces* the old one at a definite instant |
| `slide` | the new state pushes the old one aside — a movement, not a replacement |

A transition is a **beat between two states, not a shot of its own**, so
`transition_seconds` is capped at 2.0. It also **cannot change the runtime**: the
dissolve overlaps two takes, and the engine takes that overlapped time back, so
the finished film is still exactly as long as the narration. If you find yourself
reaching for a long transition to cover a change you have no footage of, the fix
is footage, not a longer dissolve.

### `shots[].fit`

| Value | Default | Meaning |
|---|---|---|
| `cover` | ✅ | scale to fill the frame, then centre-crop the overflow — no bars, no distortion, but the extremes of a tall page are off screen |
| `contain` | | scale to fit and letterbox the remainder — nothing hidden, and the bars admit the source is not 16:9 |

Neither value ever stretches, and nothing invents pixels: `cover` discards the
overflow and `contain` fills the remainder with a flat colour. Choose
`contain` when the *whole* document body is the claim — a full CSV or a PDF page.

```yaml
project:
  title: "Two sources, one picture"
  slug: hello-world
  output: hello-world.mp4
  size: [1920, 1080]
  fps: 30
  min_seconds: 180
  max_seconds: 300
  transition: fade
  transition_seconds: 0.6
```

---

## `voice`

| Field | Type | Default | Meaning |
|---|---|---|---|
| `engine` | `"piper"` \| `"none"` | `"piper"` | TTS engine; `none` forces a silent cut |
| `model` | string | `null` | path to a Piper `.onnx` voice |
| `length_scale` | number | `1.0` | > 1 = slower; ~1.08 is a calm documentary pace |
| `executable` | string | `null` | override the piper entry point |
| `sentence_silence` | number | `null` | seconds of silence between sentences |

If no engine is available, the `narration` stage warns and estimates each scene's duration
from its word count (~2.5 words/sec). The pipeline does **not** hard-fail.

```yaml
voice:
  engine: piper
  model: ../../../video/_capture/voices/en_US-lessac-medium.onnx
  length_scale: 1.08
```

---

## `narration`

| Field | Type | Meaning |
|---|---|---|
| `source` | string | Markdown file with the spoken script (see below) |
| `inline` | mapping `scene_n -> text` | per-scene text; overrides `source` for those scenes |

Scene text is resolved: `inline[n]` if present, else the `source` block for scene `n`.
Every scene must resolve to non-empty text.

**Script file format** (`source`) — see
[`narration-and-captions.md`](narration-and-captions.md) for the full grammar:

```markdown
## Scene 3 — What deserves attention · 1:02–1:28

[stage direction — not spoken]

**The dashboard surfaces what deserves attention: a reading above a screening reference.**
```

- Headers: `## Scene <n> — <title> · <mm:ss>–<mm:ss>`. The times are informational; the
  pipeline uses measured audio for real timing, **not** these numbers.
- Spoken lines: the parts in `**bold**`.
- `[bracketed]` lines and everything else are ignored.

```yaml
narration:
  source: narration.md
  # inline: { 0: "A short replacement for scene 0." }
```

---

## `timeframe`

The window of time the video claims to be about. `verify` reads the window back out of the
narration and fails if the two disagree — so declaring it is what allows narration to say
"the last 28 days" honestly.

```yaml
timeframe: {days: 28, as_of: 2026-10-06}       # 28 days ending on as_of, inclusive
```

```yaml
timeframe: {start: 2026-09-09, end: 2026-10-06}
```

| Field | Type | Meaning |
|---|---|---|
| `days` | int ≥ 1 | window length in days, inclusive of both ends |
| `weeks` / `months` | int ≥ 1 | same, in weeks or **calendared** months |
| `as_of` | date | the window's end date; defaults to today (**floating**) |
| `start` / `end` | date | an explicit interval; must be given together |

A relative window with no `as_of` is **floating**: it means a different window tomorrow, so
narration may state its day count but not its dates (rejected at load). An explicit
`--timeframe` / `--days` / `--as-of` overrides whatever the spec or `story.yaml` declared.

→ [Stories and timeframes](./stories-and-timeframes.md) for the full contract, precedence,
and the accepted spellings.

---

## `provider`

Names a Python module in `ROOT` (with or without `.py`). If set, vidkit imports it and
calls, when present: `secrets()`, `register()`, `datasets(ctx)`, `panels()`, `stills(ctx)`.

Two spellings are accepted. The short one is enough when the module needs no credentials:

```yaml
provider: provider
```

The long one declares what the provider reads from the environment, so `vidkit doctor` can
report a missing variable before a render starts:

| Field | Type | Default | Meaning |
|---|---|---|---|
| `module` | string | — | the module name in `ROOT` (required in the long form) |
| `secrets` | mapping or list | `{}` | `NAME: true` for required, `NAME: false` for optional |
| `write_back` | bool | `false` | must stay `false`; `true` is refused at load time |

```yaml
provider:
  module: acme
  secrets:
    ACME_TOKEN: true
    ACME_REGION: false
```

`write_back: true` is refused when the spec is loaded: vidkit is **read-only by contract**,
so a provider may read from a source system and report on it, and nothing else. Secret values
are read from the environment only and are masked in everything the engine prints. When a
source is unreachable a provider raises `SourceUnavailable` and returns a declared fallback,
which is recorded as a degraded dataset rather than passed off as live data.

See [`provider-guide.md`](provider-guide.md).

---

## `captures[]`

A capture is a scripted Playwright visit that produces one PNG. It may be guarded by an
`assert:` that runs **before** the screenshot, so a build can never film the wrong state.
See the [capture guide](../capture/capture-guide.md) for tactics and worked examples.

| Field | Required | Type | Default | Meaning |
|---|---|---|---|---|
| `name` | ✅ | string | — | referenced by `shots[].capture` |
| `url` | one of | string | — | page to open |
| `artifact` | one of | string | — | name of a file a `download` produced; film *it* |
| `actions` | — | list | `[]` | interaction script (below) |
| `assert` | — | mapping | — | state check before screenshot |
| `viewport` | — | `[w, h]` | `project.size` | browser viewport |
| `device_scale` | — | number | `2.0` | device pixel ratio (2 → sharp 2× PNG) |
| `wait_until` | — | string | `"networkidle"` | Playwright load state |
| `wait_after` | — | number | `0.0` | extra settle time after actions |
| `full_page` | — | bool | `false` | full-page vs. viewport screenshot |
| `storage_state` | — | path | — | a session recorded with `vidkit auth` |
| `allow_login` | — | bool | `false` | declare that filming a login form *is* the scene |
| `deterministic` | — | bool | `true` | pin clock, locale, timezone, motion, randomness |
| `take` | — | int | `1` | which take to record, and promote |

**Exactly one** of `url:` / `artifact:` is required; they are mutually exclusive.

**Load-time refusals.** All of these are reported by `vidkit plan` before a browser opens:
two captures with the same name; `take < 1`; `artifact:` together with `url:`; neither
`url:` nor `artifact:`; an `artifact:` that no `download` in the spec produces; a
`storage_state:` file that does not exist; a `save_as:` containing a path separator; and a
capture that fills a password-shaped field without a `storage_state:` or `allow_login: true`.

### `assert`
Exactly one of the following is honoured (checked in this order):

| Field | Meaning |
|---|---|
| `selector` | element must exist (if nothing else is given) |
| `contains` | element's text must contain this substring (case-insensitive) |
| `equals` | element's text must equal this (exact, trimmed) |
| `exists` | `true` forces an existence check only |

### `actions[]` — canonical form

```yaml
- {type: wait,     seconds: 2.5}
- {type: wait_for, selector: "#usage tbody tr", state: visible, timeout: 15}
- {type: select,   selector: "#site-selector", value: "yam-ito"}
- {type: click,    selector: "[data-local-tab=evidence]"}
- {type: fill,     selector: "#q", value: "text"}
- {type: press,    selector: "#q", value: "Enter"}
- {type: scroll,   selector: "#site-workspace"}     # or omit selector to scroll to top
- {type: eval,     script: "window.scrollTo(0, 0)"}
- {type: download, selector: "#csv", save_as: usage.csv, timeout: 20}
```

| Field | Applies to | Meaning |
|---|---|---|
| `seconds` | `wait` | how long to sleep |
| `selector` | all but `wait`/`eval` | the element to act on |
| `value` | `select`, `fill`, `press` | the option text, text, or key |
| `script` | `eval` | JavaScript to run |
| `state` | `wait_for` | `visible` (default), `attached`, `hidden`, `detached` |
| `timeout` | `wait_for`, `download` | seconds before refusing (default 30) |
| `save_as` | `download` | plain filename under `OUT/_capture/artifacts/` |
| `assert` | any | check that runs **immediately after** this action |

Any action may carry its own `assert:`, which is how a change is made and proven in one step:

```yaml
- {type: click, selector: "#apply", assert: {selector: "#summary", contains: "5 rows"}}
```

A single-key form is also accepted: `- {select: {selector: "#x", value: "y"}}`. Its value must
be a mapping — `- {wait_for: "#x"}` is refused.

```yaml
captures:
  - name: overview
    url: "http://127.0.0.1:8090/?mode=live"
    viewport: [1920, 1080]
    device_scale: 2
    actions:
      - {type: wait,   seconds: 2.5}
      - {type: select, selector: "#site-selector", value: "yam-ito"}
      - {type: eval,   script: "window.scrollTo(0, 0)"}
    assert: {selector: "#mode-indicator", contains: "Live adapter"}

  - name: usage_csv                        # the bytes a download produced …
    url: "http://127.0.0.1:8090/"
    actions:
      - {type: download, selector: "#csv", save_as: usage.csv}

  - name: csv_page                         # … filmed as themselves
    artifact: usage.csv
```

---

## `exec`

Declares the commands a build may run and film in a real terminal. A shot names one by
`label`. Full guide: [exec guide](../capture/exec-guide.md).

| Field | Required | Type | Default | Meaning |
|---|---|---|---|---|
| `allow_network` | — | bool | `false` | whether any command's `network: true` is honoured |
| `max_timeout` | — | number | `300` | ceiling for a single command's `timeout` |
| `steps` | ✅ | list | — | the declared commands |

### `exec.steps[]`

| Field | Required | Type | Default | Meaning |
|---|---|---|---|---|
| `label` | ✅ | string | — | referenced by `shots[].exec`; must be unique |
| `cmd` | ✅ | string or list | — | string = a shell script; list = an argv run with no shell |
| `cwd` | — | string | `"."` | working directory, relative to the spec's directory |
| `backend` | — | `"bubblewrap"` \| `"docker"` \| `"local"` | `"bubblewrap"` | isolation; see [exec guide](../capture/exec-guide.md) §4 |
| `environment` | — | string | — | **required by, and only honoured by, `backend: docker`**: which declared environment the command runs inside |
| `network` | — | bool | `false` | asks to open the network; needs `exec.allow_network` too |
| `timeout` | — | number | `60` | seconds; must be `> 0` and `≤ max_timeout` |
| `expect_exit` | — | int or list[int] | `[0]` | exit codes that count as a passing build |
| `env` | — | mapping | `{}` | added to a fixed base environment |
| `reads` | — | string or list | `[]` | extra read-only mounts |
| `cols` | — | int | `100` | recorded terminal width |
| `rows` | — | int | `30` | recorded terminal height |

There is no `shell:` field: the string/list form of `cmd` already says whether the command
is a script, and a third spelling would only allow the question to be answered twice.

A `backend: docker` step must name an `environment:`; a step of any other backend must not.
Both are refused at load time, because the alternative is a container that starts, runs
nothing, and is torn down — work done for a frame that never mentions it.

```yaml
exec:
  allow_network: false
  max_timeout: 120
  steps:
    - label: test
      cmd: "pytest -q"
      timeout: 90
    - label: broken
      cmd: ["pytest", "--nonsense"]
      expect_exit: [4]
    - label: migrate
      cmd: ["python", "-m", "app.migrate"]
      backend: docker
      environment: db
```

---

## `environment[]`

Declares services that `backend: docker` steps run **inside**. Environments are a property
of the `exec` stage, not a stage of their own — the pipeline still has ten stages. Full
guide: [exec guide](../capture/exec-guide.md) §10.

| Field | Required | Type | Default | Meaning |
|---|---|---|---|---|
| `name` | ✅ | string | — | referenced by `exec.steps[].environment`; must be unique |
| `image` | ✅ | string | — | the image to run; a digest is recorded for what actually ran |
| `command` | — | string or list | the image's default | overrides the image's `CMD` |
| `env` | — | mapping | `{}` | passed to the container; the container does **not** inherit the host's |
| `ports` | — | string or list | `[]` | `HOST:CONTAINER` publications. Omit unless the host must reach in |
| `volumes` | — | string or list | `[]` | `HOST:CONTAINER` mounts, added after the read-only project bind |
| `ready` | — | string or list | — | an argv run inside the container until it **holds** ready |
| `ready_timeout` | — | number | `90` | how long `ready` may take to hold |
| `timeout` | — | number | `180` | how long the container may live in total |
| `network` | — | bool | `false` | `false` means `--network none` |

`ready:` is an **argv**, never a shell line: `ready: ["sh", "-c", "…"]` is how you say "run a
shell", and `ready: ["pg_isready", "-U", "postgres"]` is how you say "run this program". The
report records how long the answer *held*, not merely that it arrived once.

```yaml
environment:
  - name: db
    image: postgres:16-alpine
    env: {POSTGRES_PASSWORD: demo}
    ready: [pg_isready, -U, postgres]
    ready_timeout: 90
```

An environment that no `exec` step references is refused at load time — it would start a
container, put it on the machine, and never show it.

---

## `charts[]`

| Field | Required | Type | Default | Meaning |
|---|---|---|---|---|
| `name` | ✅ | string | — | referenced by `shots[].chart`; also the PNG stem |
| `kind` | ✅ | string | — | a built-in kind or a provider-registered kind |
| `dataset` | — | string | = `name` | key into the provider datasets |
| `options` | — | mapping | `{}` | passed to the renderer (`title`, `kicker`, colours, layout) |

**Merge rule (guarantee):** if `provider.panels()` also defines a panel with the same name,
the spec's `options` are merged **over** the provider's. So a spec can set
`{title: "x"}` on a chart the provider already defines.

```yaml
charts:
  - {name: trend, kind: line_series, dataset: trend}
  - {name: stats, kind: stat_cards, dataset: totals,
     options: {title: "Live totals", per_row: 4}}
```

---

## `scenes[]`

| Field | Required | Type | Meaning |
|---|---|---|---|
| `n` | ✅ | int | scene index (sorted ascending) |
| `title` | — | string | shown by `plan` |
| `shots` | ✅ | list | ≥ 1 shot |
| `seconds` | — | number | this scene's length, declared rather than measured |

### `seconds` — the clock, expressed

By default a scene is as long as its narration takes. A **silent** film has no narration
to measure, and a film whose timing is part of the story does not want the words deciding
its pacing. So a scene — or a single shot — may declare its own length:

```yaml
scenes:
  - {n: 1, seconds: 4.0, title: The premise, shots: [{solid: "#16232B"}]}
  - n: 2
    seconds: 3.0
    shots:
      - {card: {text: Declared, not measured}, weight: 2}
      - {still: assets/wide.svg, seconds: 1.2}
```

A shot's `seconds:` wins over its share of the scene. The sum of a scene's shots may not
exceed the scene's own length. `verify.json` reports which rule the clock used, as
`facts.timing_source` — `"narration"` or `"spec"` — and `vidkit plan` computes its
estimates with the renderer's own rule so the plan cannot disagree with the build.

### `shots[]`

| Field | Required | Type | Default | Meaning |
|---|---|---|---|---|
| `still` | one of these | string | — | path to an SVG/PNG asset |
| `capture` | | string | — | name of a `captures[]` entry |
| `chart` | | string | — | name of a `charts[]` (or provider) panel |
| `exec` | | string | — | label of an `exec.steps[]` entry |
| `card` | | mapping | — | a card the **engine** draws from declared words; see below |
| `solid` | | string | — | a flat colour, drawn by the engine (e.g. `"#16232B"`) |
| `at` | — | number | end of recording | with `exec`, which second of the recording to show |
| `effect` | — | `"hold"` \| `"zoom"` | `"hold"` | static vs. slow push-in |
| `motion` | — | string or mapping | — | a camera move; **supersedes `effect`**; see below |
| `seconds` | — | number | — | this shot's length, declared rather than measured |
| `weight` | — | number | `1.0` | share of the scene's duration |
| `fit` | — | `"cover"` \| `"contain"` | `"cover"` | how the still is fitted to the frame |
| `kicker` | — | string | — | small line above a `card`'s text |
| `backdrop` | — | string | — | background image behind a `card` (must exist) |

**Constraint:** exactly one of `still`/`capture`/`chart`/`exec`/`card`/`solid`.

Scene duration = the measured narration duration of that scene, **or** the scene's own
`seconds:`. Each shot gets `duration × weight / Σweights`.

```yaml
scenes:
  - n: 2
    title: Two kinds of evidence
    shots:
      - {capture: context, effect: hold, weight: 0.6}
      - {still: assets/two-streams.svg, effect: zoom, weight: 0.4}
```

An `exec` shot shows a recording, so a camera move has nothing to move across and falls
back to a single still. See the [exec guide](../capture/exec-guide.md).

### `card` and `solid` — pictures the engine draws

Every other shot kind shows something that already exists. These two draw the frame from
what the **spec declares**, which is how a film is cut with no assets at all — the honesty
rule still holds, because a card is text the spec authored rather than a picture of a
product pretending to be a measurement.

```yaml
shots:
  - {solid: "#16232B", seconds: 1.2}
  - card:
      text: A film with no footage
      kicker: chapter one
      backdrop: assets/frame.svg
      lines:
        - declared artwork only
        - no browser, no provider
```

| `card` field | Type | Meaning |
|---|---|---|
| `text` | string | the heading (**required**) |
| `kicker` | string | small line above the heading |
| `lines` | list of strings | body lines, wrapped to the panel |
| `backdrop` | string | background image (**must exist**) |

### `motion` — a camera move

```yaml
shots:
  - {still: assets/wide.svg, motion: {kind: pan, direction: right, amount: 0.25, span: 0.6}}
  - {still: assets/wide.svg, motion: zoom-in}     # bare string, direction implied
```

| Field | Default | Meaning |
|---|---|---|
| `kind` | — | `hold` \| `pan` \| `zoom` (**required**) |
| `direction` | from the kind | `left`/`right`/`up`/`down` for a pan; `in`/`out` for a zoom |
| `amount` | `0.12` | how far the camera travels; a pan's is a fraction of the frame, a zoom's of the scale |
| `span` | `1.0` | fraction of the clip the move occupies, `(0, 1]` |
| `at` | `full` | `start` \| `end` \| `full` — where in the clip the move sits |

`motion:` **supersedes** `effect:`. Declaring both is refused: keeping one is the point.
The engine records which shots actually moved in `verify.json` (`facts.motion`), so a
"camera move" that folded to a constant is visible rather than assumed.

### `overlay`

A graphic drawn **over** a shot for the whole scene. An overlay is decoration on
evidence — it can never stand in for a shot, and a scene still needs exactly one
of `still`/`capture`/`chart`.

| Field | Type | Default | Meaning |
|---|---|---|---|
| `kind` | `"banner"` \| `"image"` | required | build the graphic from text, or use the file at `src` |
| `text` | string | — | banner text (required for `kind: banner`) |
| `kicker` | string | — | small line above the text |
| `src` | string | — | image/SVG path (required for `kind: image`; **must exist**) |
| `position` | `"top"` \| `"bottom"` | `"bottom"` | which edge the graphic hugs |
| `opacity` | number | `0.92` | 0–1 |
| `fade` | number | `0.4` | seconds to fade in and out, clamped to a third of the scene |
| `height` | number | `0.16` | banner height as a fraction of the frame |

A banner is drawn inside the frame — never full width — on a translucent panel,
so the shot underneath stays visible. `fade` is clamped downwards so a declared
overlay can never render as nothing.

```yaml
scenes:
  - n: 3
    title: The result
    overlay: {kind: banner, kicker: measured, text: 908 rows indexed}
    shots:
      - {capture: result}
```

---

## `score` — the music bed

A film may carry a music bed under its narration. The bed is a declared file; nothing is
synthesised, for the same reason nothing is fabricated.

```yaml
score: {src: assets/theme.ogg, volume: 0.45, duck_db: -12.0, ramp: 0.30}
```

| Field | Default | Meaning |
|---|---|---|
| `src` | — | path to the audio file (**required**) |
| `volume` | `0.35` | how loud the bed plays. `≤ 0` is read as **dB**; `> 0` as a linear gain, which may not exceed `1` |
| `duck_db` | `-14.0` | how far the bed is pushed down under the voice; must be at or below `0` |
| `ramp` | `0.25` | seconds the duck takes to reach full depth and to come back |
| `fade_in` | `1.0` | seconds the bed fades up at the head |
| `fade_out` | `1.5` | seconds it fades down at the tail |

`score:` may also be a bare path: `score: assets/theme.ogg`.

The bed is **looped** to fill the film and only ducked under narration that was actually
measured. On a silent cut there is nothing to duck, and `verify.json` says so rather than
claiming a duck that never ran:

```json
"score": {"src": "assets/theme.ogg", "volume_db": -6.94, "duck_db": -12.0,
          "mixed": ".../mix.wav", "duck_seconds": 0.0, "ducked": false}
```

`ducked` and `duck_seconds` describe **the mix that exists on disk**. A `verify` run that
did not itself build the film reports both as `null` — an unmeasured number is not a
negative one, and the report never turns "not measured" into a claim.

---

## `guard`

| Field | Type | Default | Meaning |
|---|---|---|---|
| `min_seconds` | number | `project.min_seconds` | override the window floor |
| `max_seconds` | number | `project.max_seconds` | override the window ceiling |
| `banned` | list[string] | `[]` | substrings that must **not** appear in any narration/caption text |
| `required` | list[string] | `[]` | substrings that **must** appear |
| `require_live_mode` | bool | `false` | every declared capture must have been captured |
| `require_live_data` | bool | `false` | no dataset may be degraded (a declared fallback counts as degraded) |
| `require_audio` | bool | `true` | the build must have measured audio unless the silent cut is declared |
| `require_sandbox` | bool | `true` | every `exec` step ran in a declared, isolated backend |
| `require_exec_success` | bool | `true` | every `exec` step exited as it declared |

Matching is case-insensitive over the union of scene text and caption text. See
[`verification.md`](../verification/verification.md).

```yaml
guard:
  banned: ["legal limit", "proves a", "a real event"]
  required: ["synthetic", "causation"]
  require_live_mode: true
  require_live_data: true
```

---

## Minimal valid spec

```yaml
project: {title: "Hello", slug: hello, output: hello.mp4}
narration: {inline: {0: "Hello world."}}
scenes:
  - n: 0
    shots:
      - {still: card.svg}
```

## A note on what the spec cannot express

The spec deliberately cannot embed data, run code, or define logic. Anything project-specific
belongs in the **provider**. If you find yourself wishing a spec field could compute
something, that is a signal to move it into `provider.py`.
