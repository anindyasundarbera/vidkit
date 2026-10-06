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
2. **Fail loudly.** Let exceptions propagate; vidkit reports them with the provider name.
   A silent empty dataset produces an empty chart, which is worse than a crash.
3. **Return plain data.** Dicts/lists/scalars. Renderers are dumb on purpose.
4. **Keep the spec thin.** Compute in the provider, not in the spec.
5. **Idempotent.** The `data` stage re-runs freely; do not accumulate state.

## Testing a provider without a full render

```bash
# only the data stage — fast, catches fetch/compute errors
vidkit build SPEC --only data

# data + panels — catches renderer errors, produces PNGs
vidkit build SPEC --only data,panels
```

The persisted datasets in `_build/data/*.json` are exactly what the panels received, so you
can inspect them after a failure.

## See also

- Every built-in kind and its dataset shape: [`panels-reference.md`](panels-reference.md)
- A full real provider: `examples/hello-world/provider.py`
