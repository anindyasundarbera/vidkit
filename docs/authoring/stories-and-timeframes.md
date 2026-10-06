# Stories and timeframes

A **story** is a folder. A **timeframe** is the window of time that story is about.
Together they answer the two questions every narrated video has to answer honestly: *what
is this?* and *when was it true?*

This is the contract that makes a claim like "the last 28 days" verifiable instead of
decorative: the spec declares the window, the narration may only state a window it can
actually honour, and `verify` fails if the two disagree.

---

## A story is a folder

Any directory containing a `video.yaml` is a story. Nothing else is required.

```
my-story/
├── video.yaml        # the spec — required
├── narration.md      # the spoken script — required unless narration.inline is used
├── provider.py       # optional: the bridge to your data
└── story.yaml        # optional: the manifest
```

The *slug* is the folder name, slugified (`My Story` → `my-story`). That is the only thing
you need to start. The manifest exists for when you want to say something the folder cannot
say for itself.

### `story.yaml` (optional)

```yaml
title: Two sources, one picture
slug: hello-world
owner: Data Platform
description: One screen, two panels, one honest claim.
timeframe:
  start: 2026-09-07
  end: 2026-10-06
```

| Field | Type | Notes |
|---|---|---|
| `title` | string | display title; defaults to the folder name |
| `slug` | string | slugified; defaults to the folder name |
| `owner` | string | free-form; surfaced in reports and `ctx.story` |
| `description` | string | free-form one-liner |
| `timeframe` | mapping | same spellings as the spec's `timeframe` (below) |

**Unknown keys are a hard error.** A typo in a manifest must fail loudly rather than be
silently ignored, because a silently ignored manifest is a lie about what the story is.

### Handing the story to a provider

Inside a provider, `ctx.story` is always present — synthesised from the folder when there
is no manifest, read from the manifest when there is. One code path either way:

```python
def panels():
    return {"identity": ("text_panel", {
        "title": ctx.story.title,          # never empty
        "lines": [f"owner: {ctx.story.owner or '—'}",
                  f"declared: {ctx.story.declared}"],
    })}
```

---

## A timeframe is an interval

A timeframe is a **single closed interval** `[start, end]`, both ends inclusive — *not* a
set of sample days. "The last 28 days" ending 2026-10-06 means 2026-09-09 … 2026-10-06,
which is 28 days, not 27, not 29.

Declare it in the spec:

```yaml
timeframe:
  days: 28
  as_of: 2026-10-06
```

or as an absolute range:

```yaml
timeframe:
  start: 2026-09-09
  end: 2026-10-06
```

Both spellings resolve to the same interval, and `tf.days` is the same number either way.

### Accepted spellings

| Spelling | Meaning |
|---|---|
| `{days: N, as_of: YYYY-MM-DD}` | `N` days ending on `as_of`, inclusive |
| `{days: N}` | same, ending *today* — **floating** (see below) |
| `{weeks: N, as_of: …}` | `N × 7` days |
| `{months: N, as_of: …}` | `N` **calendared** months back (2026-10-06 − 6 months = 2026-04-06) |
| `{start: …, end: …}` | an explicit interval |
| `28d` / `4w` / `6m` / `1y` | shorthand string |
| `2026-09-09..2026-10-06` | shorthand range (`..`, `to`, `through`, `until`, `–`, `—`, `--`, `,`) |
| `9 September 2026 to 6 October 2026` | spelled-out range |

Months and years are **calendared, not multiplied**: 6 months back from 2026-10-06 is
184 days, because it lands on 2026-04-06. Multiplying would give 180 and silently shift the
window by four days.

`start` and `end` must be given **together**, and `start` must not be after `end`. A lone
`start:` is refused rather than quietly treated as a one-day window.

### Where a window may be declared

Three places, resolved in this order:

1. **override** — `--timeframe` / `--days` / `--as-of` on the CLI, or the `timeframe` field
   on an MCP job. Wins over everything, because an external agent asking for a specific
   window must get that window.
2. **`video.yaml`** — the spec's own `timeframe:`.
3. **`story.yaml`** — the manifest's `timeframe:`.

The winner is recorded on `spec.timeframe.source` (`override` / `spec` / `story`) and shown
by `plan`, `doctor`, and the build banner, so a `--timeframe` run never leaves you guessing
which window was used.

### Floating windows are deliberately second-class

`{days: 28}` with no `as_of` resolves against *today* and is marked **floating**. The same
spec would describe a different window tomorrow, so narration is not allowed to spell out a
date when the window floats — `load_spec` refuses it up front:

```
narration states the window `9 September 2026 to 6 October 2026` but the spec's timeframe
is relative and pins no `as_of`, so it would mean a different window tomorrow — add
`as_of: YYYY-MM-DD` to the spec timeframe, or use `timeframe: {start: ..., end: ...}`
```

A floating window may still state its **day count** ("the last 28 days"): that claim is true
whenever the video is built. `--as-of YYYY-MM-DD` pins it for a reproducible render without
editing the spec.

---

## What narration may state, and what happens if it is wrong

`verify` reads the window out of the narration prose *and* the captions (R-F7) and compares
it with the resolved timeframe. It understands:

- an absolute range — `9 September 2026 to 6 October 2026`
- a relative window — `the last 28 days`, `over the past six months`
- a relative window with a named end — `the last 28 days to 2026-10-06`, checked on both the
  day count and the end date
- a bare day count — `a 28-day window`

```
[PASS] timeframe consistent with spec — matches 2026-09-09 to 2026-10-06 (28 days)
[FAIL] timeframe consistent with spec — narration says 2026-09-07 to 2026-10-06, spec says
       2026-09-09 to 2026-10-06 (28 days)
```

When narration is silent about time, the check passes with a note (`narration states no
window; spec says …`) — silence is checkable, and it is not a failure.

Narration that states a window the spec cannot guarantee fails at **load**; narration that
states a window that simply disagrees with the spec fails at **verify**. Both are errors —
the split just means each is caught by whichever stage can prove it.

### Authoring rule of thumb

Write the dates **once**, in the spec, and let the narration prose be generated or reviewed
against `tf.prose()` (`7 September 2026 to 6 October 2026`). If you find yourself typing a
date into `narration.md` by hand, the window is either floating (and will be rejected) or
you are about to create a mismatch verify will find.

---

## Scaffolding a new story

```bash
vidkit init my-story --title "My Story" --days 14 --as-of 2026-10-06
```

Writes a runnable four-file story — `story.yaml`, `video.yaml`, `narration.md`,
`provider.py` — that builds with `vidkit build my-story/video.yaml` and passes `verify`
unmodified. The narration states the window it was given, and the runtime window
(`min_seconds`/`max_seconds`) is sized from the narration's own word count at 2.5 words/sec,
so a fresh scaffold never trips its own runtime check.

Existing files are **never** overwritten: `vidkit init` in a folder that already has work in
it fails rather than clobbering.

---

## Quick reference

```python
from vidkit.timeframe import parse_timeframe, find_window_claims, timeframe_matches

tf = parse_timeframe({"days": 28, "as_of": "2026-10-06"})
tf.days                     # 28 — inclusive
tf.prose()                  # '9 September 2026 to 6 October 2026'
tf.as_prompt()              # {'start': ..., 'end': ..., 'days': ..., 'as_of': ..., 'label': ...}
tf.floating                 # False — an `as_of` was written down

for claim in find_window_claims("the last 28 days to 2026-10-06"):
    timeframe_matches(tf, claim)        # -> (ok, 'narration says …, spec says …')
```

`ctx.timeframe` is the same object inside a provider.

---

## See also

- [Spec reference](./spec-reference.md) — the `timeframe:` key in context.
- [Verification](../verification/verification.md) — R-F7 among the other checks.
- [Narration and captions](./narration-and-captions.md) — script grammar and caption rules.
- [CLI reference](../operations/cli-reference.md) — `vidkit init`, `--timeframe`, `--days`, `--as-of`.
