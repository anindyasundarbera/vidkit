# Recipes

Copy-paste patterns for common tasks. Each is self-contained.

## 1. Minimal video: one card, one line

```yaml
# video.yaml
project: {title: "Hello", slug: hello, output: hello.mp4, min_seconds: 1, max_seconds: 30}
narration: {inline: {0: "Hello world."}}
voice: {engine: none}          # silent, duration estimated from the text
scenes:
  - n: 0
    shots: [{still: card.svg}]
```

```bash
vidkit build video.yaml
```

## 2. Show a running product and prove it is live

```yaml
captures:
  - name: app
    url: "http://127.0.0.1:8090/?mode=live"
    viewport: [1920, 1080]
    device_scale: 2
    actions:
      - {type: wait,   seconds: 2.5}
      - {type: select, selector: "#site-selector", value: "yam-ito"}
      - {type: eval,   script: "window.scrollTo(0, 0)"}
    assert: {selector: "#mode-indicator", contains: "Live adapter"}
scenes:
  - n: 0
    shots: [{capture: app}]
guard:
  require_live_mode: true
```

If the app is not in live mode, the build **stops** — no wrong frame is written.

## 3. A trend chart from live data

```python
# provider.py
import json, urllib.request
from vidkit import panels as panel_lib

def datasets(ctx):
    with urllib.request.urlopen("http://127.0.0.1:8000/api/trend", timeout=30) as r:
        raw = json.load(r)
    return {"trend": {"series": [{"label": "value",
                                  "points": [{"x": p["date"], "y": p["value"]} for p in raw]}],
                      "thresholds": [{"value": 2500, "label": "screening value"}]}}

def panels():
    return {"trend": {"kind": "line_series", "dataset": "trend",
                      "options": {"title": "Trend", "kicker": "LIVE"}}}

def register():  # nothing custom needed here
    pass
```

```yaml
provider: provider
charts: [{name: trend, kind: line_series, dataset: trend}]
scenes: [{n: 0, shots: [{chart: trend}]}]
```

## 4. Two series on different scales (two stacked panels)

Render two panels in one scene so each gets its own y-axis:

```python
def _water_health(data, options, doc):
    from vidkit.svg import rect, polyline, text, THEME as t
    water, health = data["water"], data["health"]
    for (y0, y1), pts, colour in (((250, 500), water, t.accent),
                                  ((600, 850), health, t.accent2)):
        ymax = max(v for _, v in pts) * 1.15
        n = max(len(pts) - 1, 1)
        xy = [(640 + i / n * 1180, y1 - v / ymax * (y1 - y0)) for i, (_, v) in enumerate(pts)]
        doc.add(rect(620, y0 - 20, 1200, y1 - y0 + 20, rx=10, fill=t.panel, stroke=t.line),
                polyline(xy, stroke=colour))
```

## 5. A terminal panel of real command output

```python
import subprocess

def datasets(ctx):
    out = subprocess.run(["my-cli", "check"], capture_output=True, text=True).stdout
    return {"alert": {"lines": out.splitlines(),
                      "header": "my-cli check"}}

def panels():
    return {"alert": {"kind": "terminal", "dataset": "alert",
                      "options": {"colors": {"[HIGH]": "#FF8A5B", "ERROR": "#FF5B5B"}}}}
```

## 6. Big-number tiles

```python
def datasets(ctx):
    return {"totals": [{"label": "Observations", "value": 908, "note": "live"},
                       {"label": "Stations", "value": 6}]}

def panels():
    return {"stats": {"kind": "stat_cards", "dataset": "totals",
                      "options": {"title": "Live totals", "per_row": 2}}}
```

## 7. Re-render only the charts (fast loop)

```bash
vidkit build SPEC --only data,panels
rsvg-convert -w 1440 -h 810 -o /tmp/peek.png OUT/_build/panels/trend.svg
# when happy, push it into the video:
vidkit build SPEC --only clips,concat,render,verify
```

## 8. Change the narration pace

```yaml
voice: {engine: piper, model: voice.onnx, length_scale: 1.15}   # slower
```

```bash
vidkit build SPEC --only narration,clips,concat,render
```

Timing follows automatically because audio is measured.

## 9. Enforce a disclosure and forbid a claim

```yaml
guard:
  required: ["synthetic data"]     # must appear at least once
  banned: ["caused the", "proves", "legal limit"]
```

`vidkit verify SPEC` will fail the build (exit 2) if either is violated.

## 10. Add a custom panel kind and use it

```python
from vidkit import panels as panel_lib
from vidkit.svg import PanelDoc, text, THEME

def badge(data, options, doc: PanelDoc):
    colour = options.get("color", THEME.accent)
    doc.add(text(120, 300, data["label"], size=48, weight=800, fill=colour))

def register():
    panel_lib.register("badge", badge)
```

```yaml
charts: [{name: b, kind: badge, dataset: b, options: {color: "#B05A2A"}}]
```

## 11. Silent cut (no TTS available)

```yaml
voice: {engine: none}
```

Durations are estimated from word count (~2.5 words/sec); captions and the timeline are still
produced. Useful for drafting a spec before audio is set up.

## 12. Render into a different directory

```bash
vidkit build SPEC --out ./dist
```

Useful to keep a scratch render (`--out ./.out`) separate from a committed one.

## 13. Verify without re-rendering

```bash
vidkit verify SPEC --out ./dist   # exit 2 if any check fails
```

## 14. Gate a build in CI

```bash
set -e
vidkit doctor SPEC
vidkit build SPEC --out ./dist
vidkit verify SPEC --out ./dist
```

Any non-zero exit fails the job.

## 15. Reuse the hello-world example as a starting template

```bash
cp -r examples/hello-world my-video
# then edit my-video/video.yaml, narration.md, provider.py
```

Keep `provider.py` aliasing the panels import (`from vidkit import panels as panel_lib`).
`examples/hello-world` is host-free and self-contained, so it is the safest starting point:
it declares no `captures[]` and needs no browser, network, or TTS model.

## 16. Film a real download, then film the file

Two captures: one pulls the bytes down, the other films *them* as a page. The artifact
capture runs last automatically, so the file is always there.

```yaml
captures:
  - name: usage_csv
    url: "http://127.0.0.1:8090/"
    actions:
      - {type: download, selector: "#csv", save_as: usage.csv}
      - {type: eval, script: "fetch('/downloads/summary.pdf').then(r => r.blob())"}
        # …or just let the click above produce both files
  - name: csv_page
    artifact: usage.csv          # filmed as a table, sniffed first
  - name: pdf_page
    artifact: summary.pdf        # rasterised through pdftoppm or gs
scenes:
  - n: 0
    shots: [{capture: usage_csv}, {capture: csv_page, weight: 0.5}]
  - n: 1
    shots: [{capture: pdf_page}]
```

`vidkit plan` refuses the spec if `csv_page` names a file no `download` produces. The build
refuses if the bytes are not recognisable as the kind claimed. `verify` reports
`filmed artifacts are real files`.

## 17. Sign in once, film many times

Never put a password in a spec. Record the browser session by hand:

```bash
vidkit auth https://staging.example.com/login --spec video.yaml
# sign in the window that opens, then close it
```

```yaml
captures:
  - name: dashboard
    url: "https://staging.example.com/dashboard"
    storage_state: .auth/session.json
    actions: [{type: wait_for, selector: "[data-ready]", timeout: 20}]
```

`vidkit init` already gitignores `.auth/`. If filming the login form *is* the scene, say so
with `allow_login: true` instead — a capture that fills a password field is refused otherwise.
