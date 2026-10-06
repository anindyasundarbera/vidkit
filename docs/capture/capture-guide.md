# Capture guide

Captures are how vidkit shows a **real** product. A capture is a scripted Playwright visit
that produces one PNG. The defining feature is that a capture can **assert the on-screen
state before it screenshots** — so a build can never silently film the wrong thing.

## Anatomy

```yaml
captures:
  - name: overview                      # referenced by shots[].capture
    url: "http://127.0.0.1:8090/?mode=live"
    viewport: [1920, 1080]
    device_scale: 2
    wait_until: networkidle
    wait_after: 0.5
    actions:
      - {type: wait,   seconds: 2.5}
      - {type: select, selector: "#site-selector", value: "yam-ito"}
      - {type: eval,   script: "window.scrollTo(0, 0)"}
    assert: {selector: "#mode-indicator", contains: "Live adapter"}
```

Order of operations (`capture.capture_one`):

1. launch Chromium (headless) with `--no-sandbox --hide-scrollbars`
2. open the page and wait for `wait_until`
3. run each action in order
4. wait `wait_after` more seconds
5. **run `assert`** → raises `ToolError` on failure
6. screenshot to `OUT/_capture/<name>.png`

Because step 5 precedes step 6, a failed assertion aborts the build with no wrong frame saved.

## Actions

| Action | Fields | Behaviour |
|---|---|---|
| `wait` | `seconds` | sleep (ms precision) |
| `select` | `selector`, `value` | `select_option` — for `<select>` elements |
| `click` | `selector` | click the element |
| `fill` | `selector`, `value` | fill an input |
| `press` | `selector`, `value` | key press (e.g. `Enter`) |
| `scroll` | `selector`? | `scrollIntoView({block:start})`; omit selector for `scrollTo(0,0)` |
| `eval` | `script` | run arbitrary JS in the page |

Canonical form is `{type: <kind>, ...}`; a single-key form `{<kind>: {...}}` also works.

## Assertions

```yaml
assert: {selector: "#mode-indicator", contains: "Live adapter"}   # substring, case-insensitive
assert: {selector: "#title", equals: "Overview"}                  # exact (trimmed)
assert: {selector: "#panel", exists: true}                        # presence only
assert: {selector: "#panel"}                                      # presence (default)
```

Assertions run against the element's `inner_text()`. Use them for:

- **Mode/state guards** — the page is in the intended mode (live, not mock).
- **Identity guards** — the right station/record is selected.
- **Readiness guards** — a panel finished loading (assert a loaded marker, not a spinner).

## Browser discovery

`capture._find_chrome()` prefers, in order:

1. Playwright's managed Chrome (`~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome`)
2. any system `google-chrome` / `chromium` / `chrome` / `msedge` on `PATH`

Playwright itself is optional. If absent, `capture_all` prints a warning and skips captures
— supply pre-rendered stills and reference them with `still:` instead.

## Why not the integrated browser

Wide desktop layouts need a **fixed viewport**. Some host browser panes clamp their width,
producing a narrow layout that hides the UI you want to show. Always drive a *standalone*
headless browser (which vidkit does) with `viewport: [1920, 1080]`.

## Resolution

`device_scale: 2` yields a 2× PNG (e.g. 3840×2160 for a 1920×1080 viewport). Downstream,
clips are scaled to `project.size`, so capture 2× for crispness and let the pipeline size it.

## Reliability tactics

- **Wait generously.** Network + client render + live-data fetches can take seconds.
  A `wait` of 2.5 s before interacting and 4.5 s after is a reasonable starting point.
- **Scroll deterministically.** `eval: window.scrollTo(0, 0)` beats hoping the page is at top;
  `scroll` with a selector beats guessing pixel offsets.
- **Assert readiness, not timing.** Prefer `assert` on a content marker over a long fixed wait.
- **Keep interactions minimal.** Each extra step is another thing that can flake.

## Debugging a failed capture

The error names the failing step:

```
vidkit: error: capture 'drawer' failed: Page.click: Timeout 30000ms exceeded.
```

- **selector not found / click timeout** — wrong selector. Inspect the page's real markup; do
  not guess class names.
- **assertion failed: … does not contain 'live' (saw 'Mock dataset')** — the app is in the
  wrong mode. This is the guard doing its job; fix the URL/state, do not remove the assert.
- **no browser found** — set up Playwright (`playwright install chromium`) or a system Chrome.
- **playwright not installed** — `pip install "vidkit[capture]"`.

Re-run just captures while iterating:

```bash
vidkit build SPEC --only capture
```

## See also

- [`spec-reference.md`](../authoring/spec-reference.md) → `captures[]`
- A guarded-capture recipe, start to finish: [`recipes.md`](../guides/recipes.md) §2 (prove a
  running product is live) and §3 (a trend chart from live data)
