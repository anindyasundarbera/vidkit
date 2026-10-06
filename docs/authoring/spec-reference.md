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

**Constraint:** `min_seconds < max_seconds` (else `SpecError`).

```yaml
project:
  title: "Two sources, one picture"
  slug: hello-world
  output: hello-world.mp4
  size: [1920, 1080]
  fps: 30
  min_seconds: 180
  max_seconds: 300
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

### `shots[]`

| Field | Required | Type | Default | Meaning |
|---|---|---|---|---|
| `still` | one of these | string | — | path to an SVG/PNG asset |
| `capture` | | string | — | name of a `captures[]` entry |
| `chart` | | string | — | name of a `charts[]` (or provider) panel |
| `effect` | — | `"hold"` \| `"zoom"` | `"hold"` | static vs. slow push-in |
| `weight` | — | number | `1.0` | share of the scene's duration |

**Constraint:** exactly one of `still`/`capture`/`chart`.

Scene duration = the measured narration duration of that scene. Each shot gets
`duration × weight / Σweights`.

```yaml
scenes:
  - n: 2
    title: Two kinds of evidence
    shots:
      - {capture: context, effect: hold, weight: 0.6}
      - {still: assets/two-streams.svg, effect: zoom, weight: 0.4}
```

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
