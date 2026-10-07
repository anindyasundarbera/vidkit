"""Unit tests for capture v2 — actions, downloads, artifacts and takes (M3 / R-C1…R-C9).

Nothing here opens a browser. Every function that touches a page takes the page it
needs, so the whole contract is exercised against the fakes below: a download is a
real file on disk, an artifact is real bytes, and a refusal is a raised error with
the reason in it. The one thing a fake cannot prove — that a page really fills in
after a beat — is proved by ``examples/capture-kit`` under a real Chromium, in CI.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vidkit import capture as _capture
from vidkit.context import Context
from vidkit.errors import SpecError, ToolError
from vidkit.spec import Capture, load_spec

REPO_ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class FakeElement:
    def __init__(self, text: str = "") -> None:
        self.text = text

    def inner_text(self) -> str:
        return self.text


class FakeDownload:
    def __init__(self, path: Path, suggested: str) -> None:
        self._path = path
        self.suggested_filename = suggested

    def path(self) -> str:
        return str(self._path)


class FakeDownloadInfo:
    def __init__(self, download: FakeDownload) -> None:
        self.value = download


class FakeExpect:
    """Stands in for ``page.expect_download()``."""

    def __init__(self, page: "FakePage") -> None:
        self.page = page

    def __enter__(self) -> "FakeExpect":
        return self

    def __exit__(self, *exc) -> bool:
        self.page.downloaded = True
        return False

    @property
    def value(self) -> FakeDownload:
        return self.page.download


class FakePage:
    """The slice of Playwright's ``Page`` that capture v2 actually uses.

    Anything a test asserts about is recorded in ``self.calls``, so a test can
    check *what the capture did* rather than only that it did not raise.
    """

    def __init__(self, elements: dict[str, str] | None = None,
                 download: FakeDownload | None = None,
                 *, wait_fails: bool = False, downloads_without_click: bool = False,
                 screenshot: bytes = b"\x89PNG\r\n\x1a\n fake") -> None:
        self.elements = elements or {}
        self.download = download
        self.wait_fails = wait_fails
        self.downloads_without_click = downloads_without_click
        self.downloaded = False
        self.calls: list[tuple] = []
        self.content: str | None = None
        self.scripts: list[str] = []
        self._screenshot = screenshot

    # -- navigation + content -------------------------------------------- #
    def goto(self, url, **kw):
        self.calls.append(("goto", url))

    def set_content(self, html, **kw):
        self.content = html
        self.calls.append(("set_content", len(html)))

    def add_init_script(self, script):
        self.scripts.append(script)

    def screenshot(self, path=None, **kw):
        Path(path).write_bytes(self._screenshot)
        self.calls.append(("screenshot", str(path), kw.get("full_page", False)))

    # -- queries + assertions -------------------------------------------- #
    def query_selector(self, selector):
        self.calls.append(("query_selector", selector))
        return FakeElement(self.elements[selector]) if selector in self.elements else None

    def wait_for_selector(self, selector, *, state="visible", timeout=30000):
        self.calls.append(("wait_for_selector", selector, state, timeout))
        if self.wait_fails:
            raise TimeoutError("Timeout 15000ms exceeded")
        return FakeElement(self.elements.get(selector, ""))

    def wait_for_timeout(self, ms):
        self.calls.append(("wait_for_timeout", ms))

    # -- actions --------------------------------------------------------- #
    def select_option(self, selector, value):
        self.calls.append(("select_option", selector, value))

    def click(self, selector):
        self.calls.append(("click", selector))
        if self.download is not None and self.downloads_without_click:
            self.downloaded = True

    def fill(self, selector, value):
        self.calls.append(("fill", selector, value))

    def press(self, selector, key):
        self.calls.append(("press", selector, key))

    def eval_on_selector(self, selector, script):
        self.calls.append(("eval_on_selector", selector))

    def evaluate(self, script, arg=None):
        self.calls.append(("evaluate", script))

    # -- downloads ------------------------------------------------------- #
    def expect_download(self, timeout=None):
        self.calls.append(("expect_download", timeout))
        return FakeExpect(self)


def _page(elements: dict[str, str] | None = None, **kw) -> FakePage:
    return FakePage(elements, **kw)


def _artifact(ctx: Context, name: str, body: bytes) -> Path:
    ctx.capture_artifacts.mkdir(parents=True, exist_ok=True)
    path = ctx.capture_artifacts / name
    path.write_bytes(body)
    return path


# --------------------------------------------------------------------------- #
# Building a spec with captures
# --------------------------------------------------------------------------- #
def _spec_yaml(tmp_path: Path, captures: list[dict], *, guard: dict | None = None,
               scenes: list[dict] | None = None) -> Path:
    """A spec with the given captures and one shot per capture."""
    if scenes is None:
        scenes = [{"n": i, "title": f"s{i}", "shots": [{"capture": c["name"]}]}
                  for i, c in enumerate(captures)]
    body: dict = {
        "project": {"title": "T", "slug": "t", "output": "t.mp4",
                    "min_seconds": 1, "max_seconds": 100},
        "narration": {"source": "narration.md"},
        "captures": captures,
        "scenes": scenes or [{"n": 0, "shots": [{"still": "s.svg"}]}],
    }
    if guard:
        body["guard"] = guard
    (tmp_path / "s.svg").write_text("<svg/>", encoding="utf-8")
    (tmp_path / "narration.md").write_text("**hello.**", encoding="utf-8")
    path = tmp_path / "video.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def _ctx(spec, tmp_path: Path) -> Context:
    ctx = Context(spec=spec, root=spec.root, out_dir=tmp_path / "_out")
    ctx.ensure_dirs()
    return ctx


# --------------------------------------------------------------------------- #
# The spec surface (R-C1)
# --------------------------------------------------------------------------- #
def test_a_capture_defaults_are_stated_not_implied(tmp_path):
    spec = load_spec(_spec_yaml(tmp_path, [{"name": "p", "url": "http://x/"}]))
    cap = spec.captures[0]
    assert (cap.name, cap.url, cap.take, cap.deterministic) == ("p", "http://x/", 1, True)
    assert cap.storage_state is None and cap.artifact is None
    assert cap.allow_login is False and cap.actions == []


def test_every_action_kind_parses(tmp_path):
    spec = load_spec(_spec_yaml(tmp_path, [{
        "name": "p", "url": "http://x/",
        "actions": [
            {"type": "select", "selector": "#s", "value": "v"},
            {"type": "click", "selector": "#c"},
            {"type": "fill", "selector": "#f", "value": "v"},
            {"type": "press", "selector": "#q", "value": "Enter"},
            {"type": "wait", "seconds": 1.5},
            {"type": "wait_for", "selector": "#w"},
            {"type": "scroll", "selector": "#s"},
            {"type": "eval", "script": "1 + 1"},
            {"type": "download", "selector": "#d", "save_as": "out.csv"},
        ],
    }]))
    kinds = [a.kind for a in spec.captures[0].actions]
    assert kinds == ["select", "click", "fill", "press", "wait", "wait_for",
                     "scroll", "eval", "download"]


def test_wait_for_needs_a_selector(tmp_path):
    with pytest.raises(SpecError) as exc:
        load_spec(_spec_yaml(tmp_path, [{
            "name": "p", "url": "http://x/",
            "actions": [{"type": "wait_for", "state": "visible"}]}]))
    assert "wait_for needs a selector" in str(exc.value)


def test_wait_for_refuses_a_state_nobody_can_wait_for(tmp_path):
    with pytest.raises(SpecError) as exc:
        load_spec(_spec_yaml(tmp_path, [{
            "name": "p", "url": "http://x/",
            "actions": [{"type": "wait_for", "selector": "#x", "state": "maybe"}]}]))
    assert "wait_for state must be one of" in str(exc.value)


def test_download_needs_something_to_click(tmp_path):
    with pytest.raises(SpecError) as exc:
        load_spec(_spec_yaml(tmp_path, [{
            "name": "p", "url": "http://x/",
            "actions": [{"type": "download", "timeout": 5}]}]))
    assert "download needs a selector" in str(exc.value)


def test_an_unknown_action_is_named(tmp_path):
    with pytest.raises(SpecError) as exc:
        load_spec(_spec_yaml(tmp_path, [{
            "name": "p", "url": "http://x/",
            "actions": [{"type": "teleport", "selector": "#x"}]}]))
    assert "unknown action type 'teleport'" in str(exc.value)


def test_a_per_action_assert_is_carried_through(tmp_path):
    spec = load_spec(_spec_yaml(tmp_path, [{
        "name": "p", "url": "http://x/",
        "actions": [{"type": "click", "selector": "#c",
                     "assert": {"selector": "#ok", "contains": "done"}}]}]))
    check = spec.captures[0].actions[0].assert_
    assert (check.selector, check.contains) == ("#ok", "done")


# --------------------------------------------------------------------------- #
# Refusing captures that could only fail in a browser (R-C2)
# --------------------------------------------------------------------------- #
def test_two_captures_with_one_name_are_refused(tmp_path):
    with pytest.raises(SpecError) as exc:
        load_spec(_spec_yaml(tmp_path, [{"name": "p", "url": "http://x/"},
                                        {"name": "p", "url": "http://y/"}]))
    assert "second capture with the same name" in str(exc.value)


def test_a_take_below_one_is_refused(tmp_path):
    with pytest.raises(SpecError) as exc:
        load_spec(_spec_yaml(tmp_path, [{"name": "p", "url": "http://x/", "take": 0}]))
    assert "take must be >= 1" in str(exc.value)


def test_artifact_and_url_together_are_refused(tmp_path):
    with pytest.raises(SpecError) as exc:
        load_spec(_spec_yaml(tmp_path, [{
            "name": "p", "url": "http://x/", "artifact": "a.csv"}]))
    assert "mutually exclusive" in str(exc.value)


def test_an_artifact_nothing_downloads_is_refused(tmp_path):
    with pytest.raises(SpecError) as exc:
        load_spec(_spec_yaml(tmp_path, [
            {"name": "p", "url": "http://x/"},
            {"name": "shot", "artifact": "a.csv"}]))
    assert "not the `save_as` of any `download` action" in str(exc.value)
    assert "this spec downloads: nothing" in str(exc.value)


def test_a_capture_with_neither_url_nor_artifact_is_refused(tmp_path):
    with pytest.raises(SpecError) as exc:
        load_spec(_spec_yaml(tmp_path, [{"name": "p"}]))
    assert "needs a `url:` or an `artifact:`" in str(exc.value)


def test_a_storage_state_that_is_not_there_is_refused(tmp_path):
    with pytest.raises(SpecError) as exc:
        load_spec(_spec_yaml(tmp_path, [{
            "name": "p", "url": "http://x/", "storage_state": ".auth/state.json"}]))
    assert "storage_state '.auth/state.json' not found" in str(exc.value)


def test_a_storage_state_that_is_there_is_accepted(tmp_path):
    (tmp_path / ".auth").mkdir()
    (tmp_path / ".auth" / "state.json").write_text("{}", encoding="utf-8")
    spec = load_spec(_spec_yaml(tmp_path, [{
        "name": "p", "url": "http://x/", "storage_state": ".auth/state.json"}]))
    assert spec.captures[0].storage_state == ".auth/state.json"


def test_a_save_as_with_a_path_separator_is_refused(tmp_path):
    with pytest.raises(SpecError) as exc:
        load_spec(_spec_yaml(tmp_path, [{
            "name": "p", "url": "http://x/",
            "actions": [{"type": "download", "selector": "#d",
                         "save_as": "../escape.csv"}]}]))
    assert "must be a plain filename" in str(exc.value)


def test_a_password_fill_without_a_session_is_refused(tmp_path):
    with pytest.raises(SpecError) as exc:
        load_spec(_spec_yaml(tmp_path, [{
            "name": "p", "url": "http://x/",
            "actions": [{"type": "fill", "selector": "#password", "value": "hunter2"}]}]))
    assert "would film a login form" in str(exc.value)


def test_signing_in_on_purpose_is_allowed(tmp_path):
    spec = load_spec(_spec_yaml(tmp_path, [{
        "name": "p", "url": "http://x/", "allow_login": True,
        "actions": [{"type": "fill", "selector": "#password", "value": "hunter2"}]}]))
    assert spec.captures[0].allow_login is True


def test_a_session_makes_a_password_fill_fine(tmp_path):
    (tmp_path / ".auth").mkdir()
    (tmp_path / ".auth" / "state.json").write_text("{}", encoding="utf-8")
    spec = load_spec(_spec_yaml(tmp_path, [{
        "name": "p", "url": "http://x/", "storage_state": ".auth/state.json",
        "actions": [{"type": "fill", "selector": "#password", "value": "hunter2"}]}]))
    assert spec.captures[0].storage_state == ".auth/state.json"


def test_one_download_may_be_filmed_by_the_next_capture(tmp_path):
    spec = load_spec(_spec_yaml(tmp_path, [
        {"name": "live", "url": "http://x/",
         "actions": [{"type": "download", "selector": "#d", "save_as": "a.csv"}]},
        {"name": "shot", "artifact": "a.csv"}]))
    assert [c.name for c in spec.captures] == ["live", "shot"]


# --------------------------------------------------------------------------- #
# Actions (R-C1, R-C5)
# --------------------------------------------------------------------------- #
def _action(kind: str, **kw):
    from vidkit.spec import Action
    return Action(kind, **kw)


def test_actions_drive_the_page():
    page = _page()
    _capture.apply(page, _action("select", selector="#s", value="v"))
    _capture.apply(page, _action("click", selector="#c"))
    _capture.apply(page, _action("fill", selector="#f", value="typed"))
    _capture.apply(page, _action("press", selector="#q", value="Enter"))
    _capture.apply(page, _action("wait", seconds=0.5))
    _capture.apply(page, _action("eval", script="1+1"))
    assert ("select_option", "#s", "v") in page.calls
    assert ("click", "#c") in page.calls
    assert ("fill", "#f", "typed") in page.calls
    assert ("press", "#q", "Enter") in page.calls
    assert ("wait_for_timeout", 500) in page.calls
    assert ("evaluate", "1+1") in page.calls


def test_press_defaults_to_enter():
    page = _page()
    _capture.apply(page, _action("press", selector="#q"))
    assert ("press", "#q", "Enter") in page.calls


def test_scroll_with_a_selector_and_without():
    page = _page()
    _capture.apply(page, _action("scroll", selector="#far"))
    _capture.apply(page, _action("scroll"))
    assert ("eval_on_selector", "#far") in page.calls
    assert ("evaluate", "window.scrollTo(0,0)") in page.calls


def test_an_unknown_action_kind_raises():
    with pytest.raises(ToolError) as exc:
        _capture.apply(_page(), _action("levitate"))
    assert "unknown action 'levitate'" in str(exc.value)


def test_wait_for_reports_the_selector_and_the_state_it_wanted():
    page = _page(wait_fails=True)
    with pytest.raises(ToolError) as exc:
        _capture.wait_for(page, _action("wait_for", selector="#rows",
                                        state="visible", timeout=15))
    message = str(exc.value)
    assert "'#rows'" in message and "be visible" in message and "15s" in message
    assert ("wait_for_selector", "#rows", "visible", 15000) in page.calls


def test_wait_for_passes_the_timeout_through():
    page = _page()
    _capture.wait_for(page, _action("wait_for", selector="#x", state="detached",
                                    timeout=2.5))
    assert ("wait_for_selector", "#x", "detached", 2500) in page.calls


def test_a_failed_assert_refuses_to_record_the_wrong_state():
    page = _page({"#summary": "3 rows"})
    from vidkit.spec import Assert
    with pytest.raises(ToolError) as exc:
        _capture.check(page, Assert(selector="#summary", contains="5 rows"))
    assert "does not contain '5 rows'" in str(exc.value)
    assert "recording the wrong state" not in str(exc.value)  # that one is for absence


def test_a_missing_asserted_element_refuses_by_name():
    page = _page({})
    from vidkit.spec import Assert
    with pytest.raises(ToolError) as exc:
        _capture.check(page, Assert(selector="#gone"), where="after click")
    assert "after click: assertion failed" in str(exc.value)
    assert "#gone not found" in str(exc.value)


def test_assert_equals_is_exact_after_trimming():
    from vidkit.spec import Assert
    _capture.check(_page({"#t": "  42  "}), Assert(selector="#t", equals="42"))
    with pytest.raises(ToolError):
        _capture.check(_page({"#t": "42.0"}), Assert(selector="#t", equals="42"))


def test_an_action_assert_runs_after_the_action():
    page = _page({"#ok": "done"})
    from vidkit.spec import Assert
    _capture.apply(page, _action("click", selector="#c",
                                 assert_=Assert(selector="#ok", contains="done")))
    assert page.calls.index(("click", "#c")) < page.calls.index(("query_selector", "#ok"))


# --------------------------------------------------------------------------- #
# Downloads (R-C3)
# --------------------------------------------------------------------------- #
def _download_page(tmp_path: Path, body: bytes = b"day,channel\n1,search\n",
                   suggested: str = "usage.csv") -> tuple[FakePage, Path]:
    staging = tmp_path / "staging"
    staging.mkdir()
    src = staging / suggested
    src.write_bytes(body)
    return _page(download=FakeDownload(src, suggested)), staging


def test_a_download_keeps_the_real_bytes(tmp_path):
    page, _ = _download_page(tmp_path)
    dest = tmp_path / "artifacts"
    art = _capture.download(page, _action("download", selector="#csv",
                                          save_as="usage.csv"), artifacts_dir=dest)
    assert art.name == "usage.csv" and art.bytes > 0
    assert art.path.read_bytes() == b"day,channel\n1,search\n"
    assert ("expect_download", 30000) in page.calls


def test_a_download_uses_the_servers_name_when_the_spec_does_not_say(tmp_path):
    page, _ = _download_page(tmp_path, suggested="export-2026.csv")
    art = _capture.download(page, _action("download", selector="#csv"),
                            artifacts_dir=tmp_path / "artifacts")
    assert art.name == "export-2026.csv"


def test_a_download_with_no_directory_is_refused(tmp_path):
    page, _ = _download_page(tmp_path)
    with pytest.raises(ToolError) as exc:
        _capture.download(page, _action("download", selector="#csv"))
    assert "no artifact directory" in str(exc.value)


def test_a_header_only_download_is_refused(tmp_path):
    page, _ = _download_page(tmp_path, body=b"")
    with pytest.raises(ToolError) as exc:
        _capture.download(page, _action("download", selector="#csv", save_as="a.csv"),
                          artifacts_dir=tmp_path / "artifacts")
    assert "saved 0 bytes" in str(exc.value)


def test_a_page_without_expect_download_is_refused():
    class Old(FakePage):
        expect_download = None

    with pytest.raises(ToolError) as exc:
        _capture.download(Old(), _action("download", selector="#d", save_as="a.csv"),
                          artifacts_dir=Path("/tmp"))
    assert "no expect_download" in str(exc.value)


def test_a_download_name_can_never_escape_the_artifact_directory():
    from vidkit.spec import Action
    for suggested in ("../../etc/passwd", "..\\..\\win.ini", "C:\\tmp\\x.csv",
                      "/etc/shadow", "....//x"):
        name = _capture.artifact_name(Action("download"), suggested)
        assert "/" not in name and "\\" not in name and not name.startswith(".")
        assert name and name not in {".", ".."}


def test_save_as_beats_the_servers_suggestion():
    from vidkit.spec import Action
    assert _capture.artifact_name(
        Action("download", save_as="usage.csv"), "../../evil.sh") == "usage.csv"


def test_a_name_with_nothing_usable_in_it_falls_back():
    from vidkit.spec import Action
    assert _capture.artifact_name(Action("download", save_as="///"), "") == "download"


def test_a_download_is_recorded_as_an_artifact_of_the_right_size(tmp_path):
    body = b"a,b\n" * 40
    page, staging = _download_page(tmp_path, body=body)
    art = _capture.download(page, _action("download", selector="#d", save_as="a.csv"),
                            artifacts_dir=tmp_path / "artifacts")
    assert art.kind == "download" and art.bytes == len(body)
    assert art.path.stat().st_size == len(body)


# --------------------------------------------------------------------------- #
# Artifacts (R-C4)
# --------------------------------------------------------------------------- #
def test_sniff_reads_content_before_extension(tmp_path):
    pdf = tmp_path / "actually-a-pdf.txt"
    pdf.write_bytes(b"%PDF-1.4\n...")
    png = tmp_path / "no-extension"
    png.write_bytes(b"\x89PNG\r\n\x1a\nrest")
    gif = tmp_path / "x.bin"
    gif.write_bytes(b"GIF89a" + b"0" * 8)
    assert _capture.sniff(pdf) == "pdf"
    assert _capture.sniff(png) == "image"
    assert _capture.sniff(gif) == "image"


def test_sniff_falls_back_to_the_extension(tmp_path):
    csv = tmp_path / "rows.csv"
    csv.write_text("a,b\n", encoding="utf-8")
    md = tmp_path / "notes.md"
    md.write_text("# hi", encoding="utf-8")
    weird = tmp_path / "thing.bin"
    weird.write_bytes(b"\x00\x01\x02")
    assert _capture.sniff(csv) == "table"
    assert _capture.sniff(md) == "text"
    assert _capture.sniff(weird) is None


def test_csv_becomes_a_real_table(tmp_path):
    csv = tmp_path / "rows.csv"
    csv.write_text("day,channel,visits\n2026-09-07,search,1840\n2026-09-14,direct,1204\n",
                   encoding="utf-8")
    html = _capture.artifact_page(csv, kind="table", title="usage")
    assert "<table>" in html and "<thead>" in html
    assert "<th>day</th><th>channel</th><th>visits</th>" in html
    assert "<td>2026-09-07</td><td>search</td><td>1840</td>" in html
    assert "usage" in html and "rows.csv" in html


def test_a_quoted_csv_field_is_not_split_in_half(tmp_path):
    csv = tmp_path / "rows.csv"
    csv.write_text('a,b\n"one, two",three\n', encoding="utf-8")
    html = _capture.artifact_page(csv, kind="table", title="t")
    assert "<td>one, two</td>" in html


def test_a_tsv_is_split_on_tabs(tmp_path):
    tsv = tmp_path / "rows.tsv"
    tsv.write_text("a\tb\n1\t2\n", encoding="utf-8")
    html = _capture.artifact_page(tsv, kind="table", title="t")
    assert "<th>a</th><th>b</th>" in html


def test_text_becomes_pre_and_html_is_escaped(tmp_path):
    txt = tmp_path / "notes.txt"
    txt.write_text("<script>alert(1)</script>\n", encoding="utf-8")
    html = _capture.artifact_page(txt, kind="text", title="n")
    assert "<pre>" in html
    assert "&lt;script&gt;" in html and "<script>alert" not in html


def test_artifact_source_names_the_missing_file(tmp_path):
    spec = load_spec(_spec_yaml(tmp_path, [
        {"name": "live", "url": "http://x/",
         "actions": [{"type": "download", "selector": "#d", "save_as": "a.csv"}]},
        {"name": "shot", "artifact": "a.csv"}]))
    ctx = _ctx(spec, tmp_path)
    cap = next(c for c in spec.captures if c.artifact)
    with pytest.raises(ToolError) as exc:
        _capture.artifact_source(ctx, cap)
    message = str(exc.value)
    assert "'a.csv'" in message and "no such file" in message
    assert "must run before this capture" in message


def test_artifact_source_refuses_an_empty_file(tmp_path):
    spec = load_spec(_spec_yaml(tmp_path, [
        {"name": "live", "url": "http://x/",
         "actions": [{"type": "download", "selector": "#d", "save_as": "a.csv"}]},
        {"name": "shot", "artifact": "a.csv"}]))
    ctx = _ctx(spec, tmp_path)
    _artifact(ctx, "a.csv", b"")
    cap = next(c for c in spec.captures if c.artifact)
    with pytest.raises(ToolError) as exc:
        _capture.artifact_source(ctx, cap)
    assert "0 bytes" in str(exc.value)


def test_artifact_source_refuses_something_too_large_to_photograph(tmp_path):
    spec = load_spec(_spec_yaml(tmp_path, [
        {"name": "live", "url": "http://x/",
         "actions": [{"type": "download", "selector": "#d", "save_as": "a.csv"}]},
        {"name": "shot", "artifact": "a.csv"}]))
    ctx = _ctx(spec, tmp_path)
    big = ctx.capture_artifacts / "a.csv"
    big.parent.mkdir(parents=True, exist_ok=True)
    with big.open("wb") as fh:
        fh.truncate(_capture._MAX_ARTIFACT_BYTES + 1)
    cap = next(c for c in spec.captures if c.artifact)
    with pytest.raises(ToolError) as exc:
        _capture.artifact_source(ctx, cap)
    assert "too large to photograph" in str(exc.value)


def test_an_artifact_we_cannot_show_is_refused_rather_than_faked(tmp_path):
    spec = load_spec(_spec_yaml(tmp_path, [
        {"name": "live", "url": "http://x/",
         "actions": [{"type": "download", "selector": "#d", "save_as": "a.bin"}]},
        {"name": "shot", "artifact": "a.bin"}]))
    ctx = _ctx(spec, tmp_path)
    _artifact(ctx, "a.bin", b"\x00\x01\x02\x03")
    cap = next(c for c in spec.captures if c.artifact)
    with pytest.raises(_capture.ArtifactRefused) as exc:
        _capture.shoot_artifact(ctx, cap, _page())
    message = str(exc.value)
    assert "does not know how to show" in message and "lie about the evidence" in message


def test_a_csv_artifact_is_filmed_as_a_table(tmp_path):
    spec = load_spec(_spec_yaml(tmp_path, [
        {"name": "live", "url": "http://x/",
         "actions": [{"type": "download", "selector": "#d", "save_as": "a.csv"}]},
        {"name": "shot", "artifact": "a.csv"}]))
    ctx = _ctx(spec, tmp_path)
    _artifact(ctx, "a.csv", b"day,visits\n2026-09-07,1840\n")
    cap = next(c for c in spec.captures if c.artifact)
    page = _page()
    out = _capture.shoot_artifact(ctx, cap, page)
    assert out.exists() and out.read_bytes().startswith(b"\x89PNG")
    assert page.content is not None and "<table>" in page.content


def test_a_pdf_artifact_is_rasterised_when_a_tool_exists(tmp_path):
    if not (_shutil_which("pdftoppm") or _shutil_which("gs")):
        pytest.skip("no PDF rasteriser installed")
    spec = load_spec(_spec_yaml(tmp_path, [
        {"name": "live", "url": "http://x/",
         "actions": [{"type": "download", "selector": "#d", "save_as": "a.pdf"}]},
        {"name": "shot", "artifact": "a.pdf"}]))
    ctx = _ctx(spec, tmp_path)
    _artifact(ctx, "a.pdf", _tiny_pdf())
    cap = next(c for c in spec.captures if c.artifact)
    out = _capture.shoot_artifact(ctx, cap, _page())
    assert out.exists() and out.stat().st_size > 1000


def test_pdf_rasterising_refuses_when_no_tool_is_installed(tmp_path, monkeypatch):
    monkeypatch.setattr(_capture.shutil, "which", lambda name: None)
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(_tiny_pdf())
    with pytest.raises(_capture.ArtifactRefused) as exc:
        _capture.rasterize_pdf(pdf, tmp_path / "out.png")
    message = str(exc.value)
    assert "no PDF rasteriser is installed" in message
    assert "poppler-utils" in message and "ghostscript" in message


def test_pdf_rasterising_reports_a_failing_tool(tmp_path, monkeypatch):
    class Proc:
        returncode = 1
        stderr = "Syntax Error: Couldn't read xref table\n"

    monkeypatch.setattr(_capture.shutil, "which",
                        lambda name: "/usr/bin/pdftoppm" if name == "pdftoppm" else None)
    monkeypatch.setattr(_capture.subprocess, "run", lambda *a, **k: Proc())
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(_tiny_pdf())
    with pytest.raises(_capture.ArtifactRefused) as exc:
        _capture.rasterize_pdf(pdf, tmp_path / "out.png")
    message = str(exc.value)
    assert "cannot show a.pdf" in message and "pdftoppm failed" in message
    assert "Couldn't read xref table" in message


def test_pdf_rasterising_falls_back_to_ghostscript(tmp_path, monkeypatch):
    seen: list[str] = []

    class Proc:
        returncode = 0
        stderr = ""

    def fake_run(cmd, **kw):
        seen.append(Path(cmd[0]).name)
        (tmp_path / "out.png").write_bytes(b"\x89PNG")
        return Proc()

    monkeypatch.setattr(_capture.shutil, "which",
                        lambda name: "/usr/bin/gs" if name == "gs" else None)
    monkeypatch.setattr(_capture.subprocess, "run", fake_run)
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(_tiny_pdf())
    out = _capture.rasterize_pdf(pdf, tmp_path / "out.png")
    assert seen == ["gs"] and out == tmp_path / "out.png"


def _shutil_which(name: str) -> str | None:
    import shutil
    return shutil.which(name)


def _tiny_pdf() -> bytes:
    """A real, minimal one-page PDF — the same shape capture-kit serves."""
    content = b"BT /F1 12 Tf 60 740 Td (hello) Tj ET\n"
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n"
        + content + b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    start = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n"
            f"startxref\n{start}\n%%EOF\n").encode()
    return bytes(out)


# --------------------------------------------------------------------------- #
# Determinism (R-C8)
# --------------------------------------------------------------------------- #
def test_the_freeze_script_pins_time_locale_and_randomness():
    script = _capture.freeze_script()
    assert "2020-01-01T00:00:00Z" in script
    assert "en-US" in script
    for needle in ("Date", "performance.now", "Math.random",
                   "Intl.DateTimeFormat", "Intl.NumberFormat"):
        assert needle in script


def test_the_freeze_script_can_be_aimed_at_another_moment():
    assert "1999-12-31" in _capture.freeze_script(when="1999-12-31T23:59:59Z")
    assert "de-DE" in _capture.freeze_script(locale="de-DE")


# --------------------------------------------------------------------------- #
# Takes (R-C6)
# --------------------------------------------------------------------------- #
def test_take_one_keeps_the_bare_name():
    assert _capture.take_name("usage", 1) == "usage"
    assert _capture.take_name("usage", 2) == "usage.take2"
    assert _capture.take_name("usage", 7) == "usage.take7"


def test_promoting_a_later_take_copies_it_over_the_expected_name(tmp_path):
    (tmp_path / "usage.png").write_bytes(b"first")
    (tmp_path / "usage.take2.png").write_bytes(b"second")
    final = _capture.choose_take(tmp_path / "usage.png", 1, name="usage")
    assert final.read_bytes() == b"first"
    final = _capture.choose_take(tmp_path / "usage.png", 2, name="usage")
    assert final == tmp_path / "usage.png" and final.read_bytes() == b"second"


def test_promoting_a_take_that_was_never_recorded_is_refused(tmp_path):
    (tmp_path / "usage.png").write_bytes(b"first")
    with pytest.raises(ToolError) as exc:
        _capture.choose_take(tmp_path / "usage.png", 3, name="usage")
    message = str(exc.value)
    assert "usage.take3.png does not exist" in message and "capture it first" in message


def test_two_takes_that_differ_are_visible_in_their_digests(tmp_path):
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    a.write_bytes(b"one")
    b.write_bytes(b"two")
    assert _capture.digest(a) != _capture.digest(b)


# --------------------------------------------------------------------------- #
# capture_all ordering and the offline guarantee (R-C7)
# --------------------------------------------------------------------------- #
def test_capture_all_with_no_captures_does_nothing(tmp_path):
    spec = load_spec(_spec_yaml(tmp_path, [], scenes=[
        {"n": 0, "shots": [{"still": "s.svg"}]}]))
    ctx = _ctx(spec, tmp_path)
    assert _capture.capture_all(ctx) == []
    assert ctx.log == []


def test_capture_all_reports_every_capture_when_playwright_is_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(_capture, "_playwright_available", lambda: False)
    spec = load_spec(_spec_yaml(tmp_path, [
        {"name": "one", "url": "http://x/"},
        {"name": "two", "url": "http://y/"}]))
    ctx = _ctx(spec, tmp_path)
    results = _capture.capture_all(ctx)
    assert [r.name for r in results] == ["one", "two"]
    assert all(r.ok is False and r.path is None for r in results)
    assert any("playwright not installed" in line for line in ctx.log)


def test_the_producer_runs_before_the_artifact_capture(tmp_path, monkeypatch):
    seen: list[str] = []

    def fake_one(ctx, cap, chrome):
        seen.append(cap.name)
        return _capture.Result(cap.name, None, True, "")

    monkeypatch.setattr(_capture, "_playwright_available", lambda: True)
    monkeypatch.setattr(_capture, "capture_one", fake_one)
    spec = load_spec(_spec_yaml(tmp_path, [
        {"name": "shot", "artifact": "a.csv"},
        {"name": "live", "url": "http://x/",
         "actions": [{"type": "download", "selector": "#d", "save_as": "a.csv"}]},
    ], scenes=[{"n": 0, "shots": [{"capture": "shot"}]},
               {"n": 1, "shots": [{"capture": "live"}]}]))
    _capture.capture_all(_ctx(spec, tmp_path))
    assert seen == ["live", "shot"]


def test_a_failing_capture_names_itself(tmp_path, monkeypatch):
    def boom(ctx, cap, chrome):
        raise RuntimeError("the page was not there")

    monkeypatch.setattr(_capture, "_playwright_available", lambda: True)
    monkeypatch.setattr(_capture, "capture_one", boom)
    spec = load_spec(_spec_yaml(tmp_path, [{"name": "usage", "url": "http://x/"}]))
    with pytest.raises(ToolError) as exc:
        _capture.capture_all(_ctx(spec, tmp_path))
    assert "capture 'usage' failed" in str(exc.value)
    assert "the page was not there" in str(exc.value)


# --------------------------------------------------------------------------- #
# Environment probing and the offline guarantee
# --------------------------------------------------------------------------- #
def test_find_chrome_returns_something_or_nothing_but_never_raises():
    found = _capture._find_chrome()
    assert found is None or Path(found).exists()


def test_playwright_availability_is_a_bool():
    assert isinstance(_capture._playwright_available(), bool)


def test_the_capture_kit_exists_and_its_site_needs_no_network():
    kit = REPO_ROOT / "examples" / "capture-kit"
    assert (kit / "server.py").exists()
    assert (kit / "video.yaml").exists()
    assert (kit / "narration.md").exists()
    spec = load_spec(kit / "video.yaml")
    assert len(spec.captures) == 5
    urls = [c.url for c in spec.captures if c.url]
    assert urls and all(u.startswith("http://127.0.0.1:") for u in urls)
    assert {c.artifact for c in spec.captures if c.artifact} == {"usage.csv", "summary.pdf"}


def test_the_capture_kit_server_serves_real_bytes():
    """The fixture is the evidence, so it has to actually work — on localhost."""
    import sys
    import urllib.request

    sys.path.insert(0, str(REPO_ROOT / "examples" / "capture-kit"))
    try:
        import server  # type: ignore
    finally:
        sys.path.pop(0)
    httpd, url = server.serve()
    try:
        base, seen = url.rstrip("/"), {}
        for path in ("/", "/api/usage?days=60", "/downloads/usage.csv",
                     "/downloads/summary.pdf"):
            with urllib.request.urlopen(base + path) as res:
                seen[path] = (res.status, res.read())
    finally:
        httpd.shutdown()

    assert all(status == 200 for status, _ in seen.values())
    assert b"<tbody>" in seen["/"][1]
    assert b"loading" in seen["/"][1] and b"setTimeout(load, 700)" in seen["/"][1]
    assert json.loads(seen["/api/usage?days=60"][1])["totals"]["visits"] == 7016
    assert seen["/downloads/usage.csv"][1].startswith(b"day,channel,visits,signups")
    assert seen["/downloads/summary.pdf"][1].startswith(b"%PDF-")
    assert len(seen["/downloads/summary.pdf"][1]) > 500


def test_hello_world_stays_offline():
    """P6: the fixture the CI build step uses must never need a browser."""
    spec = load_spec(REPO_ROOT / "examples" / "hello-world" / "video.yaml")
    assert spec.captures == []
    assert spec.guard.require_live_mode is False


# --------------------------------------------------------------------------- #
# The auth command
# --------------------------------------------------------------------------- #
def test_the_default_state_path_sits_beside_the_spec(tmp_path):
    from vidkit.cli import default_state_path
    assert default_state_path(tmp_path / "video.yaml") == tmp_path / ".auth" / "state.json"
    assert default_state_path() == Path.cwd() / ".auth" / "state.json"


def test_scaffolding_a_story_ignores_a_recorded_session(tmp_path):
    from vidkit.scaffold import scaffold_story
    target = tmp_path / "story"
    scaffold_story(target, title="T")
    assert ".auth/" in (target / ".gitignore").read_text(encoding="utf-8")


def test_an_existing_gitignore_gains_the_auth_entry_only_once(tmp_path):
    from vidkit.scaffold import _ensure_auth_ignored
    ignore = tmp_path / ".gitignore"
    ignore.write_text("_build/\n", encoding="utf-8")
    _ensure_auth_ignored(tmp_path)
    _ensure_auth_ignored(tmp_path)
    body = ignore.read_text(encoding="utf-8")
    assert body.startswith("_build/")
    assert body.count(".auth/") == 1


def test_the_auth_command_refuses_clearly_without_playwright(monkeypatch, tmp_path):
    from vidkit import cli
    from vidkit.errors import VidkitError
    monkeypatch.setattr(_capture, "_playwright_available", lambda: False)
    with pytest.raises(VidkitError) as exc:
        cli._auth("http://127.0.0.1:1/", save=str(tmp_path / "s.json"), wait=0.1, spec=None)
    assert "needs Playwright" in str(exc.value)


# --------------------------------------------------------------------------- #
# The artifact check reaches the report (R-C4)
# --------------------------------------------------------------------------- #
def test_verify_refuses_a_declared_artifact_that_never_arrived(tmp_path):
    from vidkit.assembler import Assets
    from vidkit.verify import verify_output

    spec = load_spec(_spec_yaml(tmp_path, [
        {"name": "live", "url": "http://x/",
         "actions": [{"type": "download", "selector": "#d", "save_as": "a.csv"}]},
        {"name": "shot", "artifact": "a.csv"}]))
    ctx = _ctx(spec, tmp_path)
    assets = Assets()
    assets.output = tmp_path / "_out" / "t.mp4"
    rep = verify_output(ctx, assets, {0: "**hello.**"})
    check = next(c for c in rep.checks if c.name == "filmed artifacts are real files")
    assert check.ok is False and "missing: ['a.csv']" in check.detail


def test_verify_passes_when_the_artifact_is_really_there(tmp_path):
    from vidkit.assembler import Assets
    from vidkit.spec import Artifact
    from vidkit.verify import verify_output

    spec = load_spec(_spec_yaml(tmp_path, [
        {"name": "live", "url": "http://x/",
         "actions": [{"type": "download", "selector": "#d", "save_as": "a.csv"}]},
        {"name": "shot", "artifact": "a.csv"}]))
    ctx = _ctx(spec, tmp_path)
    path = _artifact(ctx, "a.csv", b"day,visits\n2026-09-07,1840\n")
    assets = Assets()
    assets.output = tmp_path / "_out" / "t.mp4"
    assets.artifacts["a.csv"] = Artifact("a.csv", path, "download", path.stat().st_size)
    rep = verify_output(ctx, assets, {0: "**hello.**"})
    check = next(c for c in rep.checks if c.name == "filmed artifacts are real files")
    assert check.ok is True and "1 artifact(s)" in check.detail
    assert rep.facts["artifacts"]["a.csv"]["bytes"] == path.stat().st_size


# --------------------------------------------------------------------------- #
# the driver is never allowed to speak for the engine
# --------------------------------------------------------------------------- #
def test_a_driver_failure_is_translated_into_a_refusal_not_raised():
    """Playwright signals a missing element with its own ``TimeoutError``.

    That is precisely the failure an author needs to *read* — which selector,
    how long — so it must surface as a ``ToolError`` naming both, with the
    driver's own exception kept as the cause. A driver exception escaping here
    becomes a traceback in ``vidkit capture`` and, in the studio, an exception
    where a failed step belongs.
    """
    class Hostile:
        def click(self, selector, **kw):
            raise TimeoutError(
                "Page.click: Timeout 30000ms exceeded.\n"
                "Call log:\n  \x1b[2m- waiting for locator(\"#gone\")\x1b[22m")

    with pytest.raises(ToolError) as exc:
        _capture.apply(Hostile(), _action("click", selector="#gone", timeout=1.5))
    text = str(exc.value)
    assert "click on '#gone'" in text
    assert "within 1.5s" in text
    assert "Timeout 30000ms exceeded" in text, "the driver's own words are the diagnosis"
    assert "\n" not in text, "a multi-line call log would break every report it lands in"
    assert isinstance(exc.value.__cause__, TimeoutError)


def test_every_selector_bound_action_translates_a_driver_failure():
    """All of them, not just ``wait_for`` and ``download``.

    Those two translated driver errors from the beginning; the pointer actions
    did not, so a ``click`` that could not find its selector escaped as
    Playwright's ``TimeoutError``.
    """
    class Hostile:
        def __getattr__(self, name):
            def boom(*a, **kw):
                raise TimeoutError(f"{name}: Timeout 30000ms exceeded.")
            return boom

    for kind, kw in [("select", {"value": "v"}), ("click", {}), ("fill", {"value": "v"}),
                     ("press", {"value": "Enter"}), ("wait_for", {}),
                     ("eval", {"script": "1+1"})]:
        with pytest.raises(ToolError) as exc:
            _capture.apply(Hostile(), _action(kind, selector="#x", **kw))
        text = str(exc.value)
        assert "'#x'" in text, kind
        assert "30s" in text, kind
        # `wait_for` has said this well since capture v2; the pointer actions were
        # the gap. Either wording is fine, so long as it is ours and not the driver's.
        assert "did not get there within" in text or "waited 30s for" in text, kind


def test_an_objection_from_the_engine_is_not_rewritten_as_a_driver_error():
    """``ToolError`` already names the action and what it wanted.

    Wrapping it in "did not get there within 30s" would bury the real reason —
    an action with no selector, say — under a timeout that never happened.
    """
    with pytest.raises(ToolError, match="click: needs a selector"):
        _capture.apply(_page(), _action("click"))


def test_the_action_timeout_reaches_the_driver_in_milliseconds():
    """A spec's ``timeout`` is seconds; Playwright's keyword is milliseconds."""
    seen: list[float] = []

    class Recording:
        def click(self, selector, *, timeout=None):
            seen.append(timeout)

    _capture.apply(Recording(), _action("click", selector="#c", timeout=2.5))
    assert seen == [2500.0]


def test_an_action_timeout_is_read_from_the_spec_for_pointer_actions(tmp_path):
    """The loader used to keep ``timeout`` only for ``wait_for``/``download``.

    A ``click`` that wrote one had it silently dropped and fell back to the
    driver's 30-second default — the spec said one thing and the engine did
    another, which is the failure this whole file exists to catch.
    """
    from vidkit.spec import _action as load_action

    for kind, extra in [("click", {}), ("fill", {"value": "v"}),
                        ("press", {"value": "Enter"}), ("select", {"value": "v"})]:
        action = load_action({"type": kind, "selector": "#x", "timeout": 2.5, **extra},
                              "capture 'c' action 1")
        assert action.timeout == 2.5, kind
    bare = load_action({"type": "click", "selector": "#x"}, "capture 'c' action 1")
    assert bare.timeout == 30.0, "the default stays visible on the parsed action"
