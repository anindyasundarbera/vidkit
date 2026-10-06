# Capture guide

Captures are how vidkit shows a **real** product. A capture is a scripted Playwright visit
that produces one PNG. Two properties define it:

* a capture can **assert the on-screen state before it screenshots**, so a build can never
  silently film the wrong thing; and
* a capture can **keep the bytes a page gave it** — a downloaded CSV or PDF — and later film
  *that file*, so a generated document is shown as itself rather than described.

## Anatomy

```yaml
captures:
  - name: usage                         # referenced by shots[].capture
    url: "http://127.0.0.1:8090/?mode=live"
    viewport: [1920, 1080]
    device_scale: 2
    wait_until: networkidle
    wait_after: 0.5
    actions:
      - {type: wait_for, selector: "#usage tbody tr", state: visible, timeout: 15}
      - {type: select,   selector: "#site-selector", value: "yam-ito"}
      - {type: eval,     script: "window.scrollTo(0, 0)"}
    assert: {selector: "#mode-indicator", contains: "Live adapter"}
```

Order of operations (`capture.capture_one`):

1. launch Chromium (headless) with `--no-sandbox --hide-scrollbars`
2. open the page and wait for `wait_until`
3. run each action in order — `assert` attached to an action runs immediately after it
4. wait `wait_after` more seconds
5. **run `assert`** → raises `ToolError` on failure
6. screenshot to `OUT/_capture/<name>.png`

Because step 5 precedes step 6, a failed assertion aborts the build with no wrong frame saved.

## Capture fields

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
| `storage_state` | — | path | — | a recorded session (see *Signing in*) |
| `allow_login` | — | bool | `false` | declare that filming a login form is the scene |
| `deterministic` | — | bool | `true` | pin clock, locale, timezone, motion, randomness |
| `take` | — | int | `1` | which take to record, and promote (see *Takes*) |

`url:` and `artifact:` are **mutually exclusive**: an artifact capture films a file and has
nothing to navigate to.

## Actions

| Action | Fields | Behaviour |
|---|---|---|
| `wait` | `seconds` | sleep (ms precision) |
| `wait_for` | `selector`, `state`, `timeout` | wait until the selector reaches the state |
| `select` | `selector`, `value` | `select_option` — for `<select>` elements |
| `click` | `selector` | click the element |
| `fill` | `selector`, `value` | fill an input |
| `press` | `selector`, `value` | key press (e.g. `Enter`) |
| `scroll` | `selector`? | `scrollIntoView({block:start})`; omit selector for `scrollTo(0,0)` |
| `eval` | `script` | run arbitrary JS in the page |
| `download` | `selector`, `save_as`, `timeout` | click, and keep the real bytes that arrive |

Any action may also carry an `assert:` that runs **immediately after it** — this is how a
value is changed and proven changed in one step:

```yaml
- {type: select, selector: "#period", value: "60"}
- {type: click,  selector: "#apply"}
- {type: wait_for, selector: "#usage tbody tr:nth-child(5)"}
- {type: click,  selector: "#apply", assert: {selector: "#summary", contains: "5 rows"}}
```

Canonical form is `{type: <kind>, ...}`; a single-key form `{<kind>: {...}}` also works, but
its value must be a mapping (`- {select: {selector: "#x", value: "y"}}`). `- {wait_for: "#x"}`
is **not** accepted.

### `wait_for` — waiting is a condition, not a prayer

`wait` is a sleep. `wait_for` states what must become true:

```yaml
- {type: wait_for, selector: "#usage tbody tr", state: visible, timeout: 15}
```

`state` is one of `visible` (default), `attached`, `hidden`, `detached`. When it fails the
message names the selector and the state, which is the whole diagnosis:

```
vidkit: error: capture 'usage' failed: waited 15s for '#usage tbody tr' to be visible,
and it was not (Page.wait_for_selector: Timeout 15000ms exceeded…)
```

Prefer this to a long `wait` for any content that arrives asynchronously — a table that is
empty at first paint, a chart that renders after a fetch, a panel that replaces a spinner.

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
- **Change guards** — an action had the effect it claims (assert the *new* number).

A missing selector on `contains`/`equals` is reported as *"not found — refusing to record
the wrong state"*, because photographing a page whose guard element is gone is exactly the
failure being prevented.

## Downloads and artifacts (R-C3, R-C4)

A `download` action clicks an element, catches the bytes, and writes them under
`OUT/_capture/artifacts/`. Then a separate capture with `artifact:` films those bytes.

```yaml
captures:
  - name: usage_pdf
    url: "http://127.0.0.1:8090/"
    actions:
      - {type: wait_for, selector: "#pdf", state: visible, timeout: 15}
      - {type: download, selector: "#pdf", save_as: summary.pdf, timeout: 20}

  - name: pdf_page
    artifact: summary.pdf
```

What the engine guarantees:

- **The filename is never trusted.** A server can call a file `../../etc/passwd`; the name is
  reduced to a safe basename and the spec's `save_as` always wins. `save_as` must be a plain
  filename — no path separators — and that is checked at load time.
- **A zero-byte download is refused.** A header-only file or an error page is not evidence.
- **`artifact:` must name the `save_as` of a `download` somewhere in the spec**, checked
  before a browser opens. The producer and the artifact capture do not have to be the same
  capture — and artifact captures always run after the ones that produce files.
- **The type is decided by content, not extension** (`sniff`): `%PDF-` → PDF, PNG/JPEG/GIF
  signatures → image, otherwise the suffix decides between table (CSV/TSV), text, and image.
  A file whose type cannot be established is **refused** rather than filmed as a grey box
  labelled "PDF".
- **A PDF is rasterised** with `pdftoppm` (poppler-utils), falling back to Ghostscript. If
  neither is installed the build refuses and says to install one — a placeholder standing in
  for a document is a lie about the evidence.
- **CSV/TSV is filmed as a real table** parsed from the bytes, so what is on screen is what
  the file contains.
- Artifacts are capped at 8 MB for one shot.

## Signing in without filming a login

Some scenes need an authenticated product, and a login form is almost never the story. Record
a session once, by hand:

```bash
vidkit auth http://127.0.0.1:8090/ --spec video.yaml --save .auth/session.json
```

This opens a **headed** browser for a human to sign in however the product requires — SSO,
MFA, a magic link. vidkit never sees the password. The cookies are written to the storage
state, which captures then reuse:

```yaml
  - name: dashboard
    url: "http://127.0.0.1:8090/dashboard"
    storage_state: .auth/session.json
```

Two rules follow from this:

- A storage state is **a credential**. `vidkit auth` says so on every run, and `vidkit init`
  writes `.auth/` into the story's `.gitignore` so it cannot be committed by accident.
- A capture that **types into a password-shaped field** without a `storage_state:` is refused
  at load time, because it would film a login form. If signing in genuinely *is* the scene,
  say so: `allow_login: true`.

## Determinism (R-C8)

`deterministic` defaults to **true** and pins everything a recording could otherwise race:

| Pinned | Why |
|---|---|
| `Date`, `performance.now` | a "last updated 2 minutes ago" banner |
| `Intl.DateTimeFormat`, `Intl.NumberFormat` | a date that renders `10/6/2026` here and `06/10/2026` there |
| `Math.random` (seeded) | jitter in a chart, so two takes cannot be diffed |
| locale, timezone, reduced motion, light colour scheme | animations caught mid-flight; dark/light drift |

The consequence: **a difference between two takes means the product changed, not the
afternoon.** Turn it off only when a capture must show the real wall clock.

## Takes (R-C6)

A flaky flow should not force re-authoring the scene. Record a second take beside the first
and promote it explicitly:

```yaml
  - name: checkout
    url: "http://127.0.0.1:8090/checkout"
    take: 2                      # records checkout.take2.png, then copies it to checkout.png
```

Take 1 keeps the bare name; take 2 records `checkout.take2.png`. Both files remain on disk so
you can diff them (`capture.digest`). Promotion happens only because the spec asked for it —
nothing is ever silently replaced.

## Browser discovery

`capture._find_chrome()` prefers, in order:

1. Playwright's managed Chrome (`~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome`)
2. any system `google-chrome` / `chromium` / `chrome` / `msedge` on `PATH`

Playwright itself is optional. If absent, `capture_all` warns and skips captures — supply
pre-rendered stills and reference them with `still:` instead.

## Why not the integrated browser

Wide desktop layouts need a **fixed viewport**. Some host browser panes clamp their width,
producing a narrow layout that hides the UI you want to show. Always drive a *standalone*
headless browser (which vidkit does) with `viewport: [1920, 1080]`.

## Resolution

`device_scale: 2` yields a 2× PNG (e.g. 3840×2160 for a 1920×1080 viewport). Downstream,
clips are scaled to `project.size`, so capture 2× for crispness and let the pipeline size it.

## Reliability tactics

- **Wait for the condition, not the clock.** `wait_for` names the selector; use `wait` only
  for animations you genuinely cannot observe.
- **Assert readiness, not timing.** Assert a loaded marker rather than a spinner's absence.
- **Assert the change.** After an action that alters the page, assert the new value. A
  capture that clicks without asserting proves only that the click did not throw.
- **Keep interactions minimal.** Each extra step is another thing that can flake.
- **Scroll deterministically.** `eval: window.scrollTo(0, 0)` beats hoping; `scroll` with a
  selector beats guessing pixel offsets.

## Debugging a failed capture

The error names the failing step:

```
vidkit: error: capture 'drawer' failed: Page.click: Timeout 30000ms exceeded.
```

- **selector not found / click timeout** — wrong selector. Inspect the page's real markup; do
  not guess class names.
- **waited 15s for '#x' to be visible, and it was not** — the content never arrived. Check
  whether the request failed, or whether the selector matches what actually rendered.
- **assertion failed: … does not contain 'live' (saw 'Mock dataset')** — the app is in the
  wrong mode. This is the guard doing its job; fix the URL/state, do not remove the assert.
- **no such file is in _capture/artifacts** — the `download` that produces an artifact did
  not run. Artifact captures are ordered last; check the producer's own assertions.
- **no PDF rasteriser is installed** — `apt-get install poppler-utils` (or `ghostscript`).
- **no browser found** — set up Playwright (`playwright install chromium`) or a system Chrome.
- **playwright not installed** — `pip install "vidkit[capture]"`.

Re-run just captures while iterating:

```bash
vidkit build SPEC --only capture
```

## A worked example in this repo

[`examples/capture-kit/`](../../examples/capture-kit/) is a small product page — stdlib only,
no network — built to exercise the whole feature: a table that is **empty at first paint** and
fills in after a beat (`wait_for`), a period selector that changes the numbers (an action that
is then asserted), a real CSV and a real PDF endpoint (`download`), and two captures that film
those files (`artifact:`). CI runs it in the `capture-probe` job against a real headless
Chromium, and separately proves that a capture whose assertion is false **fails the build**.

## See also

- [`spec-reference.md`](../authoring/spec-reference.md) → `captures[]`
- A guarded-capture recipe, start to finish: [`recipes.md`](../guides/recipes.md) §2 (prove a
  running product is live) and §3 (a trend chart from live data)
