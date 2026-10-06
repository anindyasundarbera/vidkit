# Panels reference

A **panel** is a full-frame SVG drawn from data. Renderers are pure functions
`fn(data, options, doc)` that append SVG fragments to a `PanelDoc`. Built-in kinds live in
`vidkit/panels.py`; providers add more via `panels.register()`.

## The PanelDoc API

Every renderer receives a `PanelDoc` sized `(project.width, project.height)`. Use these
helpers from `vidkit.svg` (all return strings; `doc.add(*fragments)` appends):

| Helper | Signature (abbrev.) |
|---|---|
| `text` | `text(x, y, s, *, size=22, fill, weight, anchor, italic, mono, letter)` |
| `text_block` | `text_block(x, y, s, *, size, fill, width=92, line_height=34, max_lines)` |
| `rect` | `rect(x, y, w, h, *, fill, stroke, rx, sw, dash)` |
| `line` | `line(x1, y1, x2, y2, *, stroke, sw, dash)` |
| `polyline` | `polyline(points, *, stroke, sw, fill)` |
| `circle` | `circle(cx, cy, r, *, fill)` |

`PanelDoc` also offers `head(title, kicker="")` (accent rule + kicker + title) and
`foot(text)` (an italic note near the bottom), and `doc.svg()` renders the document.

> **Escaping guarantee.** `text`/`text_block` **escape automatically** by default
> (`escape=True`). Do not pre-escape — that would double-escape. Pass `escape=False` only
> if you are deliberately injecting markup. This is why a URL containing `&` is safe.

Colours come from `THEME` (`THEME.accent`, `THEME.accent2`, `THEME.ink`, `THEME.muted`,
`THEME.line`, `THEME.panel`, `THEME.good`, `THEME.bg`, `THEME.dark`, `THEME.darktext`,
`THEME.darkaccent`, `THEME.font`, `THEME.mono`).

## Built-in kinds

Pass a renderer `options` to control labels/layout. Common options: `title`, `kicker`
(consumed by the assembler's `head()`), plus kind-specific keys below.

### `line_series`
One or more series with dashed thresholds and peak annotations.

**Shape**
```json
{
  "series": [{"label": "Water", "points": [{"x": "2026-09-06", "y": 19208}], "color": "#1F6FB2"}],
  "thresholds": [{"value": 2500, "label": "screening value"}],
  "annotations": [{"x": 600, "y": 300, "text": "note"}]
}
```
`points` accepts `{x,y}`, `{date,value}`, `{when,value}`, `[x, y]`, or bare `y` values.

**Options:** `x0, x1, y0, y1` (plot box), `y_max, y_min`, `label`, `color`,
`peak_label` (a format string with `{v}` and `{x}`).

**Notes:** one shared y-axis across series — if series have very different magnitudes, use
two panels (see the OAH example) or normalize.

### `bar_profile`
An ordered/ranked bar set (e.g. a river reach, a leaderboard).

**Shape**
```json
[{"label": "Wazirabad", "value": 886, "note": "within", "highlight": false},
 {"label": "ITO",       "value": 29104, "display": "29,104", "highlight": true}]
```
Accepts a bare list, or `{"bars": [...]}`.

**Options:** `x0, x1, y0, y1`, `v_max`, `bar_width`, `caption`, `caption_y`.

### `stat_cards`
Big-number tiles.

**Shape:** `[{"label": "Observations", "value": 908, "note": "live"}]` or `{label: value}`.

**Options:** `per_row` (default 3), `x0, y0`.

### `terminal`
A dark terminal block — ideal for CLI/alert output.

**Shape:** `{"lines": ["[HIGH] yam-ito", "  detail"]}` or a bare list.

**Options:** `header`, `width`, `height`, `font_size`, `colors` (`{prefix: colour}` to
colour lines by their first characters).

### `endpoints`
A stacked list of API routes.

**Shape:** `[{"path": "/api/x", "note": "does a thing", "method": "GET"}]`.

**Options:** `x0, y0, width`.

### `strip`
A persistence calendar strip.

**Shape:** `{"cells": [true, false, true], "headline": "28/28 days over", "sub": ["longest run 28"]}`.

**Options:** `cell` (size, default 34), `gap`, `per_row` (default 14), `x0, y0`.

### `kv_table`
Key/value rows.

**Shape:** `[{"k": "dataset-tag", "v": "oah-demo-final"}]` or `{k: v}`.

**Options:** `x0, y0`, `value_x`.

### `text_panel`
Wrapped prose.

**Shape:** `{"paragraphs": ["First paragraph.", "Second."]}` or a bare list.

**Options:** `x0, y0`, `width` (chars, default 110), `font_size`.

## Registering a custom kind

```python
from vidkit import panels as panel_lib
from vidkit.svg import PanelDoc, rect, polyline, text, THEME

def my_kind(data, options, doc: PanelDoc):
    t = THEME
    doc.add(rect(120, 240, 1680, 400, rx=14, fill=t.panel, stroke=t.line))
    doc.add(text(150, 300, options.get("title", ""), size=26, weight=700))
    ...

def register():
    panel_lib.register("my_kind", my_kind)
```

Then reference it by name in a chart: `{name: x, kind: my_kind, dataset: d}`.

**Contract**
- Signature is exactly `(data, options, doc)`.
- `data` is whatever the provider returned for `dataset` (any JSON-able shape).
- `options` is the merged `options` dict (spec wins over provider).
- Mutate `doc`; do not return anything.
- Raise on bad data — a loud failure beats a blank chart.

## Layout advice (learned)

- Reserve the **bottom ~200 px** — captions are burned in there (margins ≈ 16 px at 1080p).
  `PanelDoc.foot()` already sits above the band.
- Reserve the **top ~200 px** for `head()`.
- Keep a **single, legible message** per panel; put detail in the footer note.
- Prefer a muted palette (off-white bg, dark ink, one or two accents) so the panel reads on
  video and compresses well.
- Test render at target size; `rsvg-convert` metrics differ from a browser.

## Checking a panel visually

```bash
vidkit build SPEC --only data,panels
rsvg-convert -w 1440 -h 810 -o /tmp/peek.png OUT/_build/panels/<name>.svg
```

See also: [`provider-guide.md`](provider-guide.md) for how datasets reach renderers.
