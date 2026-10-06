"""Built-in panel renderers: data -> SVG.

A *panel* is a full-frame SVG drawn from data. The spec names a ``kind`` and a
``dataset``; a provider supplies the dataset value. Built-in kinds cover the
common video needs (trend lines, bar profiles, stat cards, terminal text,
endpoint lists, persistence strips, prose). Providers can register more with
:func:`register`.

Each renderer receives ``(data, options, doc)`` and mutates ``doc``. ``data`` is
whatever the provider returned for the panel's dataset (any JSON-able shape);
``options`` carries labels, colours, and layout tweaks.

Dataset shapes (all optional — renderers are tolerant):

* ``line_series``  -> ``{"series": [{"label", "points": [{"x", "y"}], "color"?}],
  "thresholds": [{"value", "label"}], "annotations": [{"x", "y", "text"}]}``
* ``bar_profile``  -> ``[{"label", "value", "note"?, "highlight"?}]``
* ``stat_cards``   -> ``[{"label", "value", "note"?}]`` or ``{label: value}``
* ``terminal``     -> ``{"lines": [...]}`` or ``[...]``
* ``endpoints``    -> ``[{"path", "note"?, "method"?}]``
* ``strip``        -> ``{"cells": [bool|0/1], "headline", "sub": [...]}``
* ``kv_table``     -> ``[{"k", "v"}]`` or ``{k: v}``
* ``text_panel``   -> ``{"title"?, "paragraphs": [...]}``
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Callable

from .errors import SpecError
from .svg import PanelDoc, circle, esc, line, polyline, rect, text, text_block, THEME


# --------------------------------------------------------------------------- #
def _series_points(raw: list) -> list[tuple[str, float]]:
    """Normalise a series to (x_label, y) pairs."""
    out: list[tuple[str, float]] = []
    for i, p in enumerate(raw):
        if isinstance(p, dict):
            x = p.get("x", p.get("date", p.get("when", p.get("time", i))))
            y = p.get("y", p.get("value", p.get("v", 0)))
        elif isinstance(p, (list, tuple)) and len(p) >= 2:
            x, y = p[0], p[1]
        else:
            x, y = i, p
        out.append((str(x), float(y)))
    return out


def _as_float(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def render_line_series(data: dict, options: dict, doc: PanelDoc) -> None:
    t = THEME
    series_in = data.get("series") if isinstance(data, dict) else None
    if not series_in:
        series_in = [{"label": options.get("label", "series"), "points": data}]
    series = []
    for s in series_in:
        pts = _series_points(s.get("points", []))
        series.append({"label": s.get("label", ""), "points": pts,
                       "color": s.get("color") or options.get("color") or t.accent})
    if not series or not any(s["points"] for s in series):
        raise SpecError("line_series: no points")

    x0 = options.get("x0", 560)
    x1 = options.get("x1", doc.width - 100)
    y0 = options.get("y0", 300)
    y1 = options.get("y1", 760)
    ymax = options.get("y_max") or max(y for s in series for _, y in s["points"]) * 1.15
    ymin = options.get("y_min", 0.0)

    def sx(i: int, n: int) -> float:
        return x0 + (i / max(n - 1, 1)) * (x1 - x0)

    def sy(v: float) -> float:
        return y1 - (v - ymin) / max(ymax - ymin, 1e-9) * (y1 - y0)

    for th in data.get("thresholds", []) if isinstance(data, dict) else []:
        y = sy(_as_float(th.get("value", 0)))
        doc.add(line(x0, y, x1, y, stroke=t.accent2, dash="7 6", sw=2),
                text(x1, y - 8, th.get("label", ""), size=19, fill=t.accent2, anchor="end"))

    for s in series:
        colour = s["color"]
        n = len(s["points"])
        pts = [(sx(i, n), sy(v)) for i, (_, v) in enumerate(s["points"])]
        doc.add(polyline(pts, stroke=colour))
        peak_i = max(range(n), key=lambda k: s["points"][k][1])
        px, py = pts[peak_i]
        label = options.get("peak_label", "peak {v} · {x}").format(
            v=s["points"][peak_i][1], x=s["points"][peak_i][0][:10])
        anchor = "end" if px > x1 - 320 else "middle"
        doc.add(circle(px, py, 6, fill=colour),
                text(px - (12 if anchor == "end" else 0), py - 14, label,
                     size=20, weight=700, fill=colour, anchor=anchor))
        doc.add(text(x0, y1 + 36, s["label"], size=20, fill=t.muted))

    for a in data.get("annotations", []) if isinstance(data, dict) else []:
        doc.add(text(_as_float(a.get("x", x0)), _as_float(a.get("y", y0)),
                     a.get("text", ""), size=20, fill=a.get("color", t.muted)))


def render_bar_profile(data: Any, options: dict, doc: PanelDoc) -> None:
    t = THEME
    items = data.get("bars") if isinstance(data, dict) else data
    items = items or []
    x0, x1 = options.get("x0", 120), options.get("x1", doc.width - 200)
    y0, y1 = options.get("y0", 340), options.get("y1", 700)
    vmax = options.get("v_max") or max((_as_float(b.get("value", 0)) for b in items), default=1) * 1.15
    n = max(len(items), 1)
    bw = options.get("bar_width", min(180, (x1 - x0) / n * 0.6))
    gap = (x1 - x0 - n * bw) / (n + 1)
    x = x0
    for b in items:
        val = _as_float(b.get("value", 0))
        bh = val / max(vmax, 1e-9) * (y1 - y0)
        y = y1 - bh
        col = b.get("color") or (t.accent if b.get("highlight", True) else t.good)
        doc.add(rect(x, y, bw, bh, rx=8, fill=col),
                text(x + bw / 2, y - 12, b.get("display", f"{val:,.0f}"),
                     size=26, weight=800, anchor="middle"),
                text(x + bw / 2, y1 + 38, b.get("label", ""), size=22, weight=700,
                     anchor="middle"))
        if b.get("note"):
            doc.add(text(x + bw / 2, y1 + 68, b["note"], size=20, fill=t.muted,
                         anchor="middle"))
        x += bw + gap
    if options.get("caption"):
        doc.add(text(x0, y1 + options.get("caption_y", 120), options["caption"],
                     size=24))


def render_stat_cards(data: Any, options: dict, doc: PanelDoc) -> None:
    t = THEME
    if isinstance(data, dict):
        items = [{"label": k, "value": v} for k, v in data.items()]
    else:
        items = list(data or [])
    per_row = int(options.get("per_row", 3))
    cw, ch, gx, gy = 420, 150, 24, 24
    x0, y0 = options.get("x0", 120), options.get("y0", 260)
    for i, it in enumerate(items):
        r, c = divmod(i, per_row)
        cx, cy = x0 + c * (cw + gx), y0 + r * (ch + gy)
        doc.add(rect(cx, cy, cw, ch, rx=14, fill=t.panel, stroke=t.line),
                text(cx + 28, cy + 96, it.get("display", it.get("value", "")),
                     size=44, weight=800, fill=it.get("color", t.ink)),
                text(cx + 28, cy + 134, it.get("label", ""), size=22, fill=t.muted))
        if it.get("note"):
            doc.add(text(cx + cw - 20, cy + 134, it["note"], size=18, fill=t.muted,
                         anchor="end"))


def render_terminal(data: Any, options: dict, doc: PanelDoc) -> None:
    lines = data.get("lines") if isinstance(data, dict) else data
    lines = lines or []
    x0, y0 = options.get("x0", 120), options.get("y0", 240)
    w = options.get("width", doc.width - 240)
    h = min(options.get("height", 500), 44 * (len(lines) + 2) + 40)
    doc.add(rect(x0, y0, w, h, rx=14, fill=THEME.dark))
    if options.get("header"):
        doc.add(text(x0 + 30, y0 + 56, options["header"], size=22, fill=THEME.darkaccent))
    yy = y0 + (110 if options.get("header") else 70)
    for ln in lines:
        s = str(ln)
        colour = THEME.darktext
        for prefix, c in (options.get("colors") or {}).items():
            if s.startswith(prefix):
                colour = c
                break
        doc.add(text(x0 + 30, yy, s, size=options.get("font_size", 26), fill=colour,
                     weight=800 if s.startswith(("[", "ERROR", "HIGH")) else 400,
                     mono=True))
        yy += 44


def render_endpoints(data: Any, options: dict, doc: PanelDoc) -> None:
    t = THEME
    items = list(data or [])
    x0 = options.get("x0", 120)
    w = options.get("width", doc.width - 240)
    y = options.get("y0", 270)
    for it in items:
        method = it.get("method", "GET")
        doc.add(rect(x0, y - 46, w, 88, rx=10, fill=t.panel, stroke=t.line),
                text(x0 + 30, y, f"{method} {it.get('path', '')}", size=28,
                     weight=800, fill=t.accent, mono=True),
                text(x0 + w - 30, y, it.get("note", ""), size=22, fill=t.muted,
                     anchor="end"))
        y += 108


def render_strip(data: Any, options: dict, doc: PanelDoc) -> None:
    t = THEME
    cells = data.get("cells") if isinstance(data, dict) else data
    cells = cells or []
    x0, y0 = options.get("x0", 120), options.get("y0", 320)
    cell = options.get("cell", 34)
    gap = options.get("gap", 4)
    per_row = int(options.get("per_row", 14))
    for i, v in enumerate(cells):
        cx = x0 + (i % per_row) * (cell + gap)
        cy = y0 + (i // per_row) * (cell + gap)
        on = bool(v)
        doc.add(rect(cx, cy, cell, cell, rx=5, fill=t.accent if on else t.good))
    if isinstance(data, dict):
        if data.get("headline"):
            doc.add(text(x0, y0 + per_row * (cell + gap) + 60, data["headline"],
                         size=36, weight=800))
        for i, s in enumerate(data.get("sub", [])[:2]):
            doc.add(text(x0, y0 + per_row * (cell + gap) + 100 + i * 34, s,
                         size=22, fill=t.muted))


def render_kv_table(data: Any, options: dict, doc: PanelDoc) -> None:
    t = THEME
    if isinstance(data, dict):
        rows = [{"k": k, "v": v} for k, v in data.items()]
    else:
        rows = list(data or [])
    x0, y0 = options.get("x0", 120), options.get("y0", 280)
    for i, r in enumerate(rows):
        y = y0 + i * 52
        doc.add(text(x0, y, r.get("k", ""), size=24, fill=t.muted),
                text(x0 + options.get("value_x", 640), y, r.get("v", ""),
                     size=24, weight=700, fill=r.get("color", t.ink)))


def render_text_panel(data: Any, options: dict, doc: PanelDoc) -> None:
    paras = data.get("paragraphs") if isinstance(data, dict) else data
    paras = paras or []
    y = options.get("y0", 300)
    for p in paras:
        doc.add(text_block(options.get("x0", 120), y, p, size=options.get("font_size", 30),
                           width=options.get("width", 110)))
        y += 40 * (1 + len(str(p)) // options.get("width", 110) + 1)


# --------------------------------------------------------------------------- #
_REGISTRY: dict[str, Callable[[Any, dict, PanelDoc], None]] = {
    "line_series": render_line_series,
    "bar_profile": render_bar_profile,
    "stat_cards": render_stat_cards,
    "terminal": render_terminal,
    "endpoints": render_endpoints,
    "strip": render_strip,
    "kv_table": render_kv_table,
    "text_panel": render_text_panel,
}


def register(kind: str, fn: Callable[[Any, dict, PanelDoc], None]) -> None:
    """Register a custom panel renderer (used by providers)."""
    _REGISTRY[kind] = fn


def kinds() -> list[str]:
    return sorted(_REGISTRY)


def render(kind: str, data: Any, options: dict, doc: PanelDoc) -> None:
    fn = _REGISTRY.get(kind)
    if fn is None:
        raise SpecError(f"unknown panel kind {kind!r}; known: {', '.join(kinds())}")
    fn(data, options or {}, doc)
