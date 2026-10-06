"""Screen capture via Playwright — real product UI, never fabricated.

Captures are the only way to show a running product honestly. Each capture names
a URL, a short script of actions (select an option, click a tab, wait), and an
optional assertion. If the assertion fails, the capture **fails loudly** — the
tool refuses to screenshot the wrong state (this is the "no mock mode on screen"
guarantee, expressed structurally).

Playwright is optional. When absent, ``capture_all`` reports which captures were
skipped so the operator can supply pre-recorded stills instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .context import Context
from .errors import ToolError
from .spec import Capture


@dataclass
class Result:
    name: str
    path: Path | None
    ok: bool
    detail: str = ""


def _find_chrome() -> str | None:
    """Prefer the Playwright-managed Chrome, then any system Chrome/Chromium."""
    import glob
    import shutil

    for pattern in (
        Path.home() / ".cache/ms-playwright/chromium-*/chrome-linux64/chrome",
        Path.home() / ".cache/ms-playwright/chromium-*/chrome-linux/chrome",
    ):
        hits = sorted(glob.glob(str(pattern)))
        if hits:
            return hits[-1]
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                 "chrome", "msedge"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _playwright_available() -> bool:
    try:
        import importlib.util
        return importlib.util.find_spec("playwright.sync_api") is not None
    except Exception:
        return False


def _apply(page, action) -> None:
    if action.kind == "select":
        page.select_option(action.selector, action.value)
    elif action.kind == "click":
        page.click(action.selector)
    elif action.kind == "fill":
        page.fill(action.selector, action.value or "")
    elif action.kind == "press":
        page.press(action.selector, action.value or "Enter")
    elif action.kind == "wait":
        page.wait_for_timeout(int((action.seconds or 1.0) * 1000))
    elif action.kind == "scroll":
        if action.selector:
            page.eval_on_selector(
                action.selector, "el => el.scrollIntoView({block:'start'})")
        else:
            page.evaluate("window.scrollTo(0,0)")
    elif action.kind == "eval":
        page.evaluate(action.script or "")
    else:  # pragma: no cover - guarded by the spec loader
        raise ToolError(f"unknown action {action.kind!r}")


def _check_assert(page, cap: Capture) -> None:
    a = cap.assert_
    if a is None:
        return
    el = page.query_selector(a.selector)
    if a.exists or a.contains is None and a.equals is None:
        if el is None:
            raise ToolError(f"assertion failed: {a.selector} not found")
        return
    if el is None:
        raise ToolError(f"assertion failed: {a.selector} not found")
    body = el.inner_text()
    if a.contains is not None and a.contains.lower() not in body.lower():
        raise ToolError(
            f"assertion failed: {a.selector} does not contain {a.contains!r} "
            f"(saw {body[:120]!r})")
    if a.equals is not None and body.strip() != a.equals:
        raise ToolError(
            f"assertion failed: {a.selector} != {a.equals!r} (saw {body[:120]!r})")


def capture_one(ctx: Context, cap: Capture, chrome: str | None) -> Result:
    from playwright.sync_api import sync_playwright  # local import (optional dep)

    vp = cap.viewport or ctx.project.size
    out = ctx.captures / f"{cap.name}.png"
    ctx.captures.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True, executable_path=chrome,
            args=["--no-sandbox", "--hide-scrollbars"])
        page = browser.new_page(
            viewport={"width": vp[0], "height": vp[1]},
            device_scale_factor=cap.device_scale)
        try:
            page.goto(cap.url, wait_until=cap.wait_until, timeout=60000)
            for action in cap.actions:
                _apply(page, action)
            if cap.wait_after:
                page.wait_for_timeout(int(cap.wait_after * 1000))
            _check_assert(page, cap)
            page.screenshot(path=str(out), full_page=cap.full_page)
        finally:
            browser.close()
    return Result(cap.name, out, True, cap.url)


def capture_all(ctx: Context) -> list[Result]:
    caps = ctx.spec.captures
    if not caps:
        return []
    if not _playwright_available():
        ctx.warn("playwright not installed — skipping capture; supply pre-recorded "
                 "stills and reference them with `still:` shots")
        return [Result(c.name, None, False, "playwright not installed") for c in caps]

    chrome = _find_chrome()
    if chrome is None:
        ctx.warn("no Chrome/Chromium found; playwright will try its own downloader")
    results: list[Result] = []
    for cap in caps:
        try:
            res = capture_one(ctx, cap, chrome)
            ctx.info(f"captured {cap.name} -> {res.path}")
        except Exception as exc:  # noqa: BLE001
            raise ToolError(f"capture {cap.name!r} failed: {exc}") from exc
        results.append(res)
    return results
