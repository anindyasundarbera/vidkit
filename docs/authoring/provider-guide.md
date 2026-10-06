# Provider guide

A **provider** is a plain Python module named in the spec (`provider: provider` → `provider.py`
in `ROOT`). It is the bridge between vidkit and your project. It is the *only* place
project-specific knowledge lives, which is what keeps vidkit itself generic.

## The interface

A provider may define any of these module-level callables. All are optional.

| Function | Called when | Returns | Purpose |
|---|---|---|---|
| `register()` | once, right after import | — | register custom panel kinds |
| `datasets(ctx)` | `data` stage | `dict[str, Any]` | supply data for charts |
| `panels()` | `panels` stage | `dict[str, PanelSpec]` | define named panels |
| `stills(ctx)` | `stills` stage | `dict[str, Path]` | supply pre-rendered images |

`ctx` is a [`Context`](../../vidkit/context.py): `ctx.root`, `ctx.out_dir`, `ctx.build`,
`ctx.captures`, `ctx.stills`, `ctx.panels_dir`, `ctx.clips`, `ctx.wavs`, `ctx.data_dir`,
`ctx.info(msg)`, `ctx.warn(msg)`, `ctx.shell`, `ctx.ffmpeg`, `ctx.rsvg`, `ctx.spec`.

### `datasets(ctx) -> dict`

Return a mapping of name → JSON-able value. vidkit persists each to
`OUT/_build/data/<name>.json` and hands the value to any panel whose `dataset` matches.

**Rules**
- It must be pure with respect to the repo: **read-only**. Never mutate source data.
- It may raise; vidkit wraps the exception as `ProviderError` and aborts with context.
- It must return a dict (else `ProviderError`).

```python
def datasets(ctx):
    return {
        "trend": fetch_trend(),          # whatever shape your renderer wants
        "totals": {"observations": 908, "stations": 6},
    }
```

### `panels() -> dict[str, PanelSpec]`

Define named panels. A `PanelSpec` is a dict or a 3-tuple:

```python
def panels():
    return {
        "trend": {"kind": "myapp_trend", "dataset": "trend",
                  "options": {"title": "Trend", "kicker": "LIVE"}},
        "stats": ("stat_cards", "totals", {"title": "Totals", "per_row": 4}),
    }
```

If the spec also declares a chart with the same name, the spec's `options` are merged over
the provider's (the provider supplies structure; the spec may tweak it).

### `stills(ctx) -> dict[str, Path]`

Return named paths to already-rendered PNG/SVG images a scene can reference with `still:`.
Usually unnecessary — `still:` accepts a path directly. Use this when a still must be
*generated* by your code.

### `secrets() -> dict | list | str`

Declare the environment variables the provider reads, so `vidkit doctor` can report a
missing one *before* a render starts rather than in the middle of one. Any of these shapes
is accepted:

```python
def secrets():
    return {"ACME_TOKEN": True}          # required (default)
    # {"ACME_TOKEN": False}             # optional — a nice-to-have
    # ["ACME_TOKEN", "ACME_USER"]       # both required
    # "ACME_TOKEN"                      # one required
```

Values are read from the environment only — never from a file, never from the spec — and
the engine keeps them out of every log line, exception message, report and error it prints
(see [Secrets](#secrets-and-redaction) below).

### `fallbacks(ctx)` / `fallback_for(name, ctx)`

Declare what to show when a source is unreachable, so an outage degrades a chart instead of
hanging a render or inventing a number (see [When the source is down](#when-the-source-is-down)).

### `register()`

Call `vidkit.panels.register(name, fn)` for each custom renderer. See
[`panels-reference.md`](panels-reference.md).

```python
from vidkit import panels as panel_lib   # ALIAS IT — see the naming trap below

def register():
    panel_lib.register("myapp_trend", _trend)   # a kind name you own
```

> **Naming trap (real, easy to hit).** If your module defines a function called `panels`,
> it shadows a bare `from vidkit import panels`. Always alias the import
> (`from vidkit import panels as panel_lib`). This exact bug has bitten this project.

## Secrets and redaction

A provider that talks to a real system usually needs a credential. vidkit treats those values
as the one thing in a build that must never reach a screen, a log, a snapshot, or a report,
and makes that the *engine's* job rather than a rule you have to remember:

- **Declare, do not read.** The spec's `provider:` block and your `secrets()` are merged, and
  only the declared names are read from the environment. Reading `os.environ` directly still
  works, but then nobody can check for it and nothing masks it.
- **Read through the context.** `ctx.require_secret("ACME_TOKEN")` returns the value or raises
  naming the variable. `ctx.secret("ACME_TOKEN", default)` is the non-raising form.
- **Leaks are masked.** If your code raises with a token inside the message, the engine
  replaces the occurrence with `***` before printing it, longest value first, so a token that
  is a prefix of another is not partially revealed.

```yaml
provider:
  module: acme
  secrets:
    ACME_TOKEN: true          # required
    ACME_REGION: false        # optional
  write_back: false           # must stay false — see below
```

`write_back: true` is **refused at load time**. vidkit is read-only by contract: a provider
may read from a source system and report on it, and nothing else. That is what makes a
second run of the same spec safe.

## When the source is down

A dashboard is not a build system. If a model endpoint, an API or a database is unreachable,
the honest outcomes are "show what you declared" or "fail", never "hang" and never "invent a
number". Raise `SourceUnavailable` from `datasets()` and return a *declared* fallback:

```python
from vidkit.provider import SourceUnavailable, fallback

def fallbacks(ctx):
    return {"forecast": {"points": [0.0] * 12, "note": "offline"}}

def datasets(ctx):
    out = {}
    try:
        out["forecast"] = fetch_forecast(ctx)
    except SourceUnavailable as exc:
        out["forecast"] = fallback(ctx, "forecast", why=str(exc))
    return out
```

`fallback_for(name, ctx)` is the alternative spelling when one dataset at a time is easier.
Either way the dataset is recorded as **degraded**, with your reason, and:

- `vidkit build` logs it and keeps going, so one dead source does not stop a render;
- `verify.json` records the reason in `facts.degraded`;
- `guard.require_live_data` turns any degraded dataset into a **verification failure**.

Choose `require_live_data: true` when the video's claim is "this is what the system says
today". Leave it `false` for a demo whose provider synthesizes its own series, and say so in
the spec — a declared degradation is honest; a silent one is not.

## Datasets, snapshots, and staleness

The `data` stage writes each dataset to `_build/data/<name>.json` and, beside them,
`_build/data/_snapshot.json` recording **what request produced them**: the provider, a hash of
the provider's source, and the resolved window, plus a hash of each dataset.

That index exists because every later stage reads its numbers from disk — which is what lets
you re-render panels or clips without asking the source again — and because that convenience
can quietly lie. Re-render from a snapshot taken for a *different window* and the video says
"the last 90 days" over 30 days of data. So before a stage reuses on-disk datasets it compares
its own request against the record and refuses when they disagree:

```console
$ vidkit build video.yaml --only panels --timeframe 2026-08-01..2026-09-30
vidkit: error: dataset snapshot is stale: the window changed (2026-09-07 to 2026-10-06
(30 days) -> 2026-08-01 to 2026-09-30 (61 days)) — re-run the `data` stage (drop it from
--only, or pass --refresh) to fetch it again
```

The request key is deliberately *narrow*: the provider and the window change the numbers;
a chart's title or a shot's effect do not, and editing one must not force a refetch.

## A complete example

```python
"""Provider for <project>."""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from vidkit import panels as panel_lib
from vidkit.svg import PanelDoc, text, rect, THEME

GATEWAY = "http://127.0.0.1:8000"


# --- custom renderers ------------------------------------------------------- #
def _trend(data, options, doc: PanelDoc):
    t = THEME
    doc.add(rect(120, 240, 1680, 360, rx=14, fill=t.panel, stroke=t.line))
    x, y0, y1 = 560, 300, 720
    pts = data["points"]                       # [{"x": "d1", "y": 3}, ...]
    ymax = max(p["y"] for p in pts) * 1.15
    n = max(len(pts) - 1, 1)
    xy = [(x + i / n * 1200, y1 - p["y"] / ymax * (y1 - y0))
          for i, p in enumerate(pts)]
    doc.add(rect(x, y0, 1200, y1 - y0, fill="#FFFFFF00"))
    from vidkit.svg import polyline
    doc.add(polyline(xy, stroke=t.accent))


def register():
    panel_lib.register("trend", _trend)


# --- data ------------------------------------------------------------------- #
def datasets(ctx):
    with urllib.request.urlopen(f"{GATEWAY}/api/trend", timeout=30) as r:
        raw = json.load(r)
    return {"trend": {"points": [{"x": p["date"], "y": p["value"]} for p in raw]}}


def panels():
    return {"trend": {"kind": "trend", "dataset": "trend",
                      "options": {"title": "Trend", "kicker": "LIVE"}}}
```

Spec usage:

```yaml
provider: provider
charts:
  - {name: trend, kind: trend, dataset: trend}
scenes:
  - n: 0
    shots: [{chart: trend}]
```

## Design rules for providers

1. **Read-only.** The provider must not modify application code, config, fixtures, or data.
   If it must exercise a pipeline (as a story provider does to run a sample), do it
   in a way that writes nothing (e.g. disable uploads).
2. **Fail loudly.** Let exceptions propagate; vidkit reports them with the provider name and
   the message redacted. A silent empty dataset produces an empty chart, which is worse than
   a crash. The one exception is a source that is genuinely *down*: raise
   `SourceUnavailable` and declare a fallback, so the outage is recorded rather than hidden.
3. **Return plain data.** Dicts/lists/scalars. Renderers are dumb on purpose.
4. **Keep the spec thin.** Compute in the provider, not in the spec.
5. **Idempotent.** The `data` stage re-runs freely; do not accumulate state.
6. **Declare your secrets.** A credential the engine does not know about cannot be checked
   for, and cannot be masked.

## Testing a provider without a full render

```bash
# only the data stage — fast, catches fetch/compute errors
vidkit build SPEC --only data

# data + panels — catches renderer errors, produces PNGs
vidkit build SPEC --only data,panels

# from a stage onwards — same as listing every later stage
vidkit build SPEC --from panels

# re-render from the snapshot, without touching the source again
vidkit build SPEC --only panels,clips,render

# ...and force a refetch even though the snapshot would do
vidkit build SPEC --only panels,clips,render --refresh
```

The persisted datasets in `_build/data/*.json` are exactly what the panels received, so you
can inspect them after a failure. Remember that a `--only` which skips `data` renders from
the snapshot: it is refused if that snapshot was taken for a different provider or window,
so pass `--refresh` when you have edited the provider itself.

## See also

- Every built-in kind and its dataset shape: [`panels-reference.md`](panels-reference.md)
- The windows a snapshot is keyed on: [`stories-and-timeframes.md`](stories-and-timeframes.md)
- What `verify` reports: [`verification.md`](../verification/verification.md)
- A full real provider: `examples/hello-world/provider.py`
