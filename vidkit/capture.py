"""Screen capture via Playwright — real product UI, never fabricated.

Captures are the only way to show a running product honestly. Each capture names
a URL, a short script of actions (select an option, click a tab, wait for a
table to fill in, download the CSV), and assertions. If an assertion fails, the
capture **fails loudly** — the tool refuses to screenshot the wrong state (this
is the "no mock mode on screen" guarantee, expressed structurally).

Three things this module is careful about:

* **Waiting is an action, not a prayer.** ``wait_for`` exists so a capture can
  state the condition it needs instead of sleeping and hoping. Its failure names
  the selector and the state it waited for.
* **A download is bytes, not a filename on a slide.** ``download`` writes the
  real file into ``_capture/artifacts/`` and records its size. An ``artifact:``
  capture then films *that file* — which is how a generated PDF becomes a shot.
* **Two captures of the same flow should be comparable.** When ``deterministic``
  is on (the default) the clock, locale, viewport and reduced-motion preference
  are pinned, so a difference between two takes means the product changed, not
  the afternoon.

Playwright is optional. Everything that touches a browser takes the ``page`` it
needs, so the logic is testable against a fake; only ``capture_one`` opens a real
one. When Playwright is absent, ``capture_all`` reports which captures were
skipped so the operator can supply pre-recorded stills instead.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .context import Context
from .errors import ToolError
from .spec import Action, Artifact, Assert, Capture

FROZEN_TIME = "2020-01-01T00:00:00Z"
FROZEN_LOCALE = "en-US"
FROZEN_TZ = "UTC"


@dataclass
class Result:
    name: str
    path: Path | None
    ok: bool
    detail: str = ""
    artifacts: list[Artifact] = field(default_factory=list)


class ArtifactRefused(ToolError):
    """A file this build is asked to film cannot be shown honestly."""


# --------------------------------------------------------------------------- #
# environment probing
# --------------------------------------------------------------------------- #
def _find_chrome() -> str | None:
    """Prefer the Playwright-managed Chrome, then any system Chrome/Chromium.

    Playwright unpacks its browser to a different place on each platform, so all
    three layouts are searched. A path that is not there simply does not match —
    a Windows path on Linux costs one failed ``glob`` and nothing else, which is
    cheaper than making the reader guess which branch their machine takes.
    """
    import glob
    import shutil as _sh

    cache = Path.home() / ".cache/ms-playwright"          # Linux
    for base, patterns in (
        (cache, ("chromium-*/chrome-linux64/chrome", "chromium-*/chrome-linux/chrome")),
        # macOS: PLAYWRIGHT_BROWSERS_PATH, then the per-user cache
        (Path.home() / "Library/Caches/ms-playwright",
         ("chromium-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium",
          "chromium-*/chrome-mac-arm64/Chromium.app/Contents/MacOS/Chromium")),
        (cache, ("chromium-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium",)),
        # Windows: %USERPROFILE%\AppData\Local\ms-playwright
        (Path.home() / "AppData/Local/ms-playwright",
         ("chromium-*/chrome-win/chrome.exe", "chromium-*/chrome-win64/chrome.exe")),
    ):
        for pattern in patterns:
            hits = sorted(glob.glob(str(base / pattern)))
            if hits:
                return hits[-1]
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                 "chrome", "msedge",
                 # macOS, where the app bundle is not on PATH by its binary name
                 "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                 "/Applications/Chromium.app/Contents/MacOS/Chromium"):
        found = _sh.which(name) or (name if Path(name).exists() else None)
        if found:
            return found
    return None


def _playwright_available() -> bool:
    try:
        import importlib.util
        return importlib.util.find_spec("playwright.sync_api") is not None
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# determinism (R-C8)
# --------------------------------------------------------------------------- #
def freeze_script(when: str = FROZEN_TIME, locale: str = FROZEN_LOCALE) -> str:
    """The init script that pins everything a capture could otherwise race.

    Deliberately small. Each pinned value answers a specific way a recording goes
    non-reproducible:

    * ``Date``/``performance`` — a "last updated 2 minutes ago" banner;
    * ``Intl`` — a date that renders as ``10/6/2026`` on one machine and
      ``06/10/2026`` on another;
    * ``Math.random`` — jitter in a chart, so that no two takes can be diffed;
    * reduced motion — an animation caught mid-flight at screenshot time.
    """
    return f"""
(() => {{
  const FIXED = {when!r};
  const at = new Date(FIXED).getTime();
  const RealDate = Date;
  class FrozenDate extends RealDate {{
    constructor(...a) {{ super(...(a.length ? a : [at])); }}
    static now() {{ return at; }}
  }}
  FrozenDate.parse = RealDate.parse;
  FrozenDate.UTC = RealDate.UTC;
  window.Date = FrozenDate;
  if (window.performance) performance.now = () => 0;
  let seed = 0;
  Math.random = () => {{
    seed = (seed * 1103515245 + 12345) % 2147483648;
    return seed / 2147483648;
  }};
  const loc = {locale!r};
  try {{
    const RealDTF = Intl.DateTimeFormat, RealNum = Intl.NumberFormat;
    Intl.DateTimeFormat = function (...a) {{ return new RealDTF(loc, ...a.slice(1)); }};
    Intl.DateTimeFormat.prototype = RealDTF.prototype;
    Intl.NumberFormat = function (...a) {{ return new RealNum(loc, ...a.slice(1)); }};
    Intl.NumberFormat.prototype = RealNum.prototype;
  }} catch (e) {{}}
}})();
"""


# --------------------------------------------------------------------------- #
# actions
# --------------------------------------------------------------------------- #
def _require(action: Action, what: str) -> str:
    if not action.selector:
        raise ToolError(f"{action.kind}: needs a {what}")
    return action.selector


# A driver failure reduced to one short paragraph. Playwright's timeout message
# opens with the whole call log across four lines and then repeats the locator,
# and every caller here appends it to a sentence of its own, so it is collapsed
# to its first line. Long enough to diagnose, short enough to sit in a report.
_DRIVER_TEXT = 200


def _driver_message(exc: Exception) -> str:
    first = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
    if not first:
        first = type(exc).__name__
    if len(first) > _DRIVER_TEXT:
        first = first[: _DRIVER_TEXT - 1].rstrip() + "…"
    return first


def _patience(fn, *args, timeout: float):
    """Call a driver method with a timeout, dropping the keyword if it is refused.

    Playwright has accepted ``timeout`` on its selector-bound methods for a long
    time, but ``apply`` is also driven by the fake pages in the test suite and by
    whatever a caller passes in. A driver that will not take the keyword is not a
    reason to lose the patience the spec asked for, so it is retried bare.
    """
    try:
        return fn(*args, timeout=timeout * 1000)
    except TypeError:
        return fn(*args)


def apply(page, action: Action) -> None:
    """Run one action. Raises ``ToolError`` naming what it was waiting for.

    The driver is never allowed to speak for the engine. Playwright signals a
    missing element with its own ``TimeoutError``, and that is exactly the
    failure an author is trying to *read* — which selector, how long. So every
    call below is translated into a ``ToolError`` that names the action, the
    selector and the patience, and the driver's exception is kept as the cause
    rather than replacing the message. Without this the studio's
    ``browser_act`` cannot report a failed step as a row; it can only raise.
    """
    timeout = float(action.timeout if action.timeout is not None else 30.0)
    try:
        if action.kind == "select":
            _patience(page.select_option, _require(action, "selector"),
                      action.value, timeout=timeout)
        elif action.kind == "click":
            _patience(page.click, _require(action, "selector"), timeout=timeout)
        elif action.kind == "fill":
            _patience(page.fill, _require(action, "selector"), action.value or "",
                      timeout=timeout)
        elif action.kind == "press":
            _patience(page.press, _require(action, "selector"),
                      action.value or "Enter", timeout=timeout)
        elif action.kind == "wait":
            page.wait_for_timeout(int((action.seconds or 1.0) * 1000))
        elif action.kind == "wait_for":
            wait_for(page, action)
        elif action.kind == "scroll":
            if action.selector:
                page.eval_on_selector(
                    action.selector, "el => el.scrollIntoView({block:'start'})")
            else:
                page.evaluate("window.scrollTo(0,0)")
        elif action.kind == "eval":
            page.evaluate(action.script or "")
        elif action.kind == "download":
            download(page, action)
        else:  # pragma: no cover - guarded by the spec loader
            raise ToolError(f"unknown action {action.kind!r}")
    except ToolError:
        raise
    except Exception as exc:  # noqa: BLE001 - the driver's error, not ours
        what = (action.selector or (action.script or "").splitlines()[0][:60]
                or "the page")
        raise ToolError(
            f"{action.kind} on {what!r} did not get there within {timeout:g}s "
            f"({_driver_message(exc)})") from exc
    if action.assert_ is not None and action.kind != "download":
        check(page, action.assert_, where=f"after {action.kind}")


def wait_for(page, action: Action) -> None:
    """Wait for a selector to reach a state, and refuse by name if it never does.

    ``wait`` is a sleep. This is a *condition*, and that difference is what makes
    a capture re-runnable: when it fails it says which selector was missing and
    in which state, which is the whole diagnosis.
    """
    selector = _require(action, "selector")
    state = action.state or "visible"
    timeout = int((action.timeout if action.timeout is not None else 30.0) * 1000)
    try:
        page.wait_for_selector(selector, state=state, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - playwright's TimeoutError, or a fake's
        raise ToolError(
            f"waited {timeout / 1000:g}s for {selector!r} to be {state}, and it was "
            f"not ({exc})") from exc


def check(page, a: Assert, *, where: str = "") -> None:
    """Assert something about the page before we photograph it."""
    prefix = f"{where}: " if where else ""
    el = page.query_selector(a.selector)
    if el is None:
        if a.exists or (a.contains is None and a.equals is None):
            raise ToolError(
                f"{prefix}assertion failed: {a.selector} not found — refusing to "
                "record the wrong state")
        raise ToolError(f"{prefix}assertion failed: {a.selector} not found")
    body = el.inner_text()
    if a.contains is not None and a.contains.lower() not in body.lower():
        raise ToolError(
            f"{prefix}assertion failed: {a.selector} does not contain {a.contains!r} "
            f"(saw {body[:120]!r})")
    if a.equals is not None and body.strip() != a.equals:
        raise ToolError(
            f"{prefix}assertion failed: {a.selector} != {a.equals!r} "
            f"(saw {body[:120]!r})")


# --------------------------------------------------------------------------- #
# downloads (R-C3)
# --------------------------------------------------------------------------- #
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def artifact_name(action: Action, suggested: str | None) -> str:
    """The filename an artifact gets. Never taken from the page alone.

    A downloaded filename is untrusted input as far as this engine is concerned:
    a server can call a file ``../../etc/passwd``. So the name is reduced to a
    safe basename, and the spec's ``save_as`` always wins.
    """
    raw = action.save_as or suggested or "download"
    name = Path(raw.replace("\\", "/")).name
    name = _UNSAFE.sub("-", name).strip("-.")
    return name or "download"


def download(page, action: Action, *, artifacts_dir: Path | None = None) -> Artifact:
    """Click, catch the real bytes, and keep them. The bytes are the evidence."""
    selector = _require(action, "selector")
    timeout = int((action.timeout if action.timeout is not None else 30.0) * 1000)
    expect = getattr(page, "expect_download", None)
    if expect is None:
        raise ToolError(
            "download: this Playwright page has no expect_download — the installed "
            "Playwright is too old for this action")
    if artifacts_dir is None:
        raise ToolError("download: no artifact directory was provided")
    try:
        with expect(timeout=timeout) as info:
            page.click(selector)
        dl = info.value
        tmp = Path(dl.path())
        name = artifact_name(action, dl.suggested_filename)
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        dest = artifacts_dir / name
        if tmp.resolve() != dest.resolve():
            shutil.copyfile(tmp, dest)
        blob = dest.read_bytes()
        if not blob:
            raise ToolError(
                f"download: {name!r} saved 0 bytes — a header-only file or an error "
                "page is not evidence worth filming")
        return Artifact(name=name, path=dest, kind="download", bytes=len(blob))
    except ToolError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ToolError(
            f"download: clicking {selector!r} started no download within "
            f"{timeout / 1000:g}s ({exc})") from exc


# --------------------------------------------------------------------------- #
# artifacts (R-C4)
# --------------------------------------------------------------------------- #
_ARTIFACT_SUFFIXES = {
    ".pdf": "pdf", ".png": "image", ".jpg": "image", ".jpeg": "image",
    ".gif": "image", ".webp": "image", ".svg": "image", ".bmp": "image",
    ".csv": "table", ".tsv": "table", ".txt": "text", ".md": "text",
    ".json": "text", ".yaml": "text", ".yml": "text", ".log": "text",
}
_MAX_ARTIFACT_BYTES = 8 * 1024 * 1024


def sniff(path: Path) -> str | None:
    """What kind of thing is this? By **content** first, extension second."""
    try:
        head = Path(path).read_bytes()[:8]
    except OSError:
        return None
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"\x89PNG") or head.startswith(b"\xff\xd8\xff"):
        return "image"
    if head[:6] in {b"GIF87a", b"GIF89a"}:
        return "image"
    return _ARTIFACT_SUFFIXES.get(Path(path).suffix.lower())


def _html_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def artifact_page(path: Path, *, kind: str, title: str) -> str:
    """The HTML page an artifact is filmed in — a real view of the real bytes."""
    body = _html_escape(path.read_text(encoding="utf-8", errors="replace")[:20000])
    label = _html_escape(title or path.name)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>{label}</title><style>
  :root {{ color-scheme: light }}
  body {{ margin:0; background:#f6f7f9;
         font:14px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; color:#1b1f24 }}
  header {{ padding:18px 28px; background:#fff; border-bottom:1px solid #e3e6ea;
            font-family: ui-sans-serif, system-ui, sans-serif }}
  h1 {{ margin:0; font-size:17px; font-weight:600 }}
  .meta {{ color:#5b6570; font-size:12px; margin-top:4px }}
  main {{ padding:22px 28px }}
  table {{ border-collapse:collapse; background:#fff; font-size:13px }}
  th, td {{ border:1px solid #e3e6ea; padding:6px 10px; text-align:left }}
  th {{ background:#eef1f4; position:sticky; top:0 }}
  pre {{ margin:0; background:#fff; border:1px solid #e3e6ea; padding:16px;
         overflow:auto; max-height:820px }}
</style></head><body>
<header><h1>{label}</h1>
<div class="meta">{_html_escape(path.name)} &middot; {_html_escape(kind)}</div></header>
<main id="vidkit-artifact">{_body_for(kind, body)}</main>
</body></html>
"""


def _body_for(kind: str, text: str) -> str:
    if kind != "table":
        return f"<pre>{text}</pre>"
    rows = [r for r in text.splitlines() if r.strip()]
    if not rows:
        return "<pre></pre>"
    split = "\t" if "\t" in rows[0] else ","
    cells = [_parse_row(r, split) for r in rows]
    head, rest = cells[0], cells[1:]
    out = ["<table><thead><tr>"]
    out += [f"<th>{_html_escape(c)}</th>" for c in head]
    out.append("</tr></thead><tbody>")
    for row in rest:
        out.append("<tr>" + "".join(f"<td>{_html_escape(c)}</td>" for c in row) + "</tr>")
    out.append("</tbody></table>")
    return "".join(out)


def _parse_row(row: str, split: str) -> list[str]:
    if split == ",":
        import csv
        import io
        return next(csv.reader(io.StringIO(row)))
    return row.split(split)


def rasterize_pdf(src: Path, out_png: Path, *, page: int = 1, dpi: int = 150) -> Path:
    """Turn a PDF into a still we can show, using a tool that is actually here.

    Prefers ``pdftoppm`` (poppler) and falls back to Ghostscript. If neither
    exists the build **refuses** rather than drawing a grey rectangle with the
    word "PDF" on it — a placeholder standing in for a document is exactly the
    kind of dishonesty this project exists to avoid.
    """
    src, out_png = Path(src), Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    stem = out_png.with_suffix("")
    if shutil.which("pdftoppm"):
        cmd = ["pdftoppm", "-png", "-r", str(dpi), "-f", str(page), "-l", str(page),
               "-singlefile", str(src), str(stem)]
    elif shutil.which("gs"):
        cmd = ["gs", "-q", "-dNOPAUSE", "-dBATCH", "-sDEVICE=png16m",
               f"-r{dpi}", f"-dFirstPage={page}", f"-dLastPage={page}",
               f"-sOutputFile={out_png}", str(src)]
    else:
        raise ArtifactRefused(
            f"cannot show {src.name}: no PDF rasteriser is installed — install "
            "poppler-utils (pdftoppm) or ghostscript, or capture the document from "
            "the product's own viewer instead")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not out_png.exists():
        last = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else ""
        raise ArtifactRefused(
            f"cannot show {src.name}: {Path(cmd[0]).name} failed"
            + (f" ({last})" if last else ""))
    return out_png


def artifact_source(ctx: Context, cap: Capture) -> Path:
    """Where the bytes an ``artifact:`` capture should film actually are."""
    assert cap.artifact is not None
    path = ctx.capture_artifacts / cap.artifact
    if not path.exists():
        raise ArtifactRefused(
            f"capture {cap.name!r} films artifact {cap.artifact!r}, but no such file "
            f"is in {ctx.capture_artifacts} — the `download` action that produces it "
            "must run before this capture")
    size = path.stat().st_size
    if size == 0:
        raise ArtifactRefused(
            f"capture {cap.name!r} films artifact {cap.artifact!r}, which is 0 bytes — "
            "there is nothing in it to show")
    if size > _MAX_ARTIFACT_BYTES:
        raise ArtifactRefused(
            f"capture {cap.name!r} films artifact {cap.artifact!r}, which is "
            f"{size / 1e6:.1f} MB — too large to photograph in one shot "
            f"(limit {_MAX_ARTIFACT_BYTES // 1024 // 1024} MB)")
    return path


def shoot_artifact(ctx: Context, cap: Capture, page, out: Path | None = None) -> Path:
    """Screenshot the bytes of a downloaded file, rendered as themselves."""
    src = artifact_source(ctx, cap)
    kind = sniff(src)
    if kind is None:
        raise ArtifactRefused(
            f"capture {cap.name!r} films {src.name!r}, and vidkit does not know how "
            "to show that file type — a blank frame with a filename on it would be a "
            "lie about the evidence. Capture it from the product's own viewer instead, "
            "or download a PDF, image, CSV or text file.")
    dest = Path(out) if out is not None else ctx.captures / f"{cap.name}.png"
    if kind == "pdf":
        rasterize_pdf(src, dest, dpi=150)
        return dest
    page.set_content(artifact_page(src, kind=kind, title=cap.name), wait_until="load")
    if cap.wait_after:
        page.wait_for_timeout(int(cap.wait_after * 1000))
    page.screenshot(path=str(dest), full_page=cap.full_page)
    return dest


# --------------------------------------------------------------------------- #
# takes (R-C6)
# --------------------------------------------------------------------------- #
def take_name(name: str, take: int) -> str:
    """The recorded output name for a take. Take 1 keeps the bare name."""
    if take <= 1:
        return name
    return f"{name}.take{take}"


def choose_take(dest: Path, take: int, *, name: str) -> Path:
    """Promote a later take to the name the rest of the pipeline expects.

    Re-running a flaky flow must not mean re-authoring the scene, so takes land
    beside the first one and are copied over it only when the spec asks.
    """
    if take <= 1:
        return dest
    src = dest.with_name(take_name(name, take) + dest.suffix)
    if not src.exists():
        raise ToolError(
            f"take {take} was requested for {name!r}, but {src.name} does not exist — "
            "capture it first")
    shutil.copyfile(src, dest)
    return dest


def digest(path: Path) -> str:
    """A short hash of a captured image, so two takes can be compared."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# a whole capture
# --------------------------------------------------------------------------- #
def capture_one(ctx: Context, cap: Capture, chrome: str | None) -> Result:
    """Record one capture. Downloads land in ``ctx.capture_artifacts``."""
    from playwright.sync_api import sync_playwright  # local import (optional dep)

    vp = cap.viewport or ctx.project.size
    out = ctx.captures / f"{take_name(cap.name, cap.take)}.png"
    ctx.captures.mkdir(parents=True, exist_ok=True)
    before = set(_list_artifacts(ctx))
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True, executable_path=chrome,
            args=["--no-sandbox", "--hide-scrollbars"])
        session = None
        try:
            if cap.storage_state:
                session = browser.new_context(
                    storage_state=str(ctx.root / cap.storage_state))
                holder = session
            else:
                holder = browser
            page = holder.new_page(
                viewport={"width": vp[0], "height": vp[1]},
                device_scale_factor=cap.device_scale,
                locale=FROZEN_LOCALE,
                timezone_id=FROZEN_TZ,
                reduced_motion="reduce",
                color_scheme="light",
            )
            try:
                if cap.deterministic:
                    page.add_init_script(freeze_script())
                if cap.artifact:
                    shoot_artifact(ctx, cap, page, out)
                else:
                    page.goto(cap.url, wait_until=cap.wait_until, timeout=60000)
                    for action in cap.actions:
                        if action.kind == "download":
                            download(page, action, artifacts_dir=ctx.capture_artifacts)
                        else:
                            apply(page, action)
                    if cap.wait_after:
                        page.wait_for_timeout(int(cap.wait_after * 1000))
                    if cap.assert_ is not None:
                        check(page, cap.assert_)
                    page.screenshot(path=str(out), full_page=cap.full_page)
            finally:
                page.close()
        finally:
            if session is not None:
                session.close()
            browser.close()
    final = ctx.captures / f"{take_name(cap.name, cap.take)}.png"
    if cap.take > 1:
        final = choose_take(ctx.captures / f"{cap.name}.png", cap.take, name=cap.name)
    detail = cap.artifact or cap.url
    if cap.deterministic:
        detail += "  [frozen clock/locale/motion]"
    return Result(cap.name, final, True, detail, _artifacts_after(ctx, before))


def capture_all(ctx: Context) -> list[Result]:
    caps = ctx.spec.captures
    if not caps:
        return []

    # The Playwright gate is *per capture*, not a gate on the whole function. A
    # capture whose take the caller already promoted needs no browser — the file is
    # already on disk under the plain name — so refusing it because Playwright is
    # absent would let a missing browser silently undo the promotion. That is the
    # same shape of defect the promotion exists to prevent, one layer down. Only the
    # captures that actually have to *shoot* the page require the browser.
    have_playwright = _playwright_available()
    if not have_playwright:
        ctx.warn("playwright not installed — skipping capture; supply pre-recorded "
                 "stills and reference them with `still:` shots")
    chrome = _find_chrome() if have_playwright else None
    if have_playwright and chrome is None:
        ctx.warn("no Chrome/Chromium found; playwright will try its own downloader")

    results: list[Result] = []
    # Producers first: an `artifact:` capture films what a `download` produced, in
    # whatever capture declared it. Everything else keeps the spec's own order.
    order = list(enumerate(caps))
    order.sort(key=lambda pair: (pair[1].artifact is not None, pair[0]))
    for _, cap in order:
        chosen = ctx.selected_take(cap.name)
        base = ctx.captures / f"{cap.name}.png"
        if chosen is not None and base.is_file():
            # The caller promoted a take, so this moment *is* the capture. Shooting
            # the page again would silently replace it with a screen the client never
            # chose, while the record still named the take it did — a report that
            # disagrees with the film it describes. The promoted file is already on
            # disk under the plain name, which is the name the pipeline reads.
            ctx.info(f"capture {cap.name}: keeping selected take {chosen}")
            results.append(Result(cap.name, base, True,
                                  f"selected take {chosen}", []))
            continue
        if not have_playwright:
            results.append(Result(cap.name, None, False, "playwright not installed"))
            continue
        try:
            res = capture_one(ctx, cap, chrome)
            ctx.info(f"captured {cap.name} -> {res.path}")
            for a in res.artifacts:
                ctx.info(f"  artifact {a.name} ({a.bytes} bytes)")
        except Exception as exc:  # noqa: BLE001
            raise ToolError(f"capture {cap.name!r} failed: {exc}") from exc
        results.append(res)
    return results


def _list_artifacts(ctx: Context) -> list[Path]:
    d = ctx.capture_artifacts
    return sorted(d.iterdir()) if d.exists() else []


def _artifacts_after(ctx: Context, before: set[Path]) -> list[Artifact]:
    out: list[Artifact] = []
    for p in _list_artifacts(ctx):
        if p in before or not p.is_file():
            continue
        out.append(Artifact(name=p.name, path=p, kind="download", bytes=p.stat().st_size))
    return out
