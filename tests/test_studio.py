"""Tests for the studio layer (M10) — the session, its takes, its sandboxes.

Split in four, by what the test actually needs from the host.

**The record** is pure Python and needs nothing: a session is JSON beside the
spec, a take is a hash of a file, and the interesting cases are all about what
happens when the *file* and the *record* disagree — which is the failure mode a
demo studio exists to prevent. These always run.

**Executing** needs a sandbox that can genuinely run, because the default
``backend: bubblewrap`` is refused at load time on a host where the kernel will
not allow it. They carry ``needs_sandbox``.

**Containers** need a real daemon and carry ``needs_docker``; the environment
lifecycle is the one part of the studio that owns a resource outside the process.

**The browser** needs the Playwright package *and* a downloaded Chromium, and
carries ``needs_playwright`` — because those are two facts, and the second one
fails with a message that reads like an engine bug.

The single most important test here is
:func:`test_a_take_recorded_for_a_file_that_is_not_there_is_refused`. A studio
whose whole purpose is to film something that really happened must not be able
to note down a take it never took; every other convenience in this module is
worth less than that refusal.
"""

from __future__ import annotations

import json
import textwrap
import time
from pathlib import Path

import pytest

from vidkit import studio as st
from vidkit.errors import SpecError, ToolError

from conftest import _HAVE_DOCKER, arun


needs_sandbox = pytest.mark.needs_sandbox
needs_docker = pytest.mark.needs_docker
needs_playwright = pytest.mark.needs_playwright
needs_render = pytest.mark.needs_render
needs_mcp = pytest.mark.needs_mcp


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "video.yaml"
    path.write_text(textwrap.dedent(text).strip() + "\n", encoding="utf-8")
    return path


#: The smallest spec that loads, with one still shot. `guard.require_audio: false`
#: because there is no voice here and a silent cut has to be *declared* (I6), not
#: discovered by a verifier that then fails.
_MINIMAL = """
    project:
      title: Studio
      slug: studio
      output: studio.mp4
      size: [320, 180]
      fps: 12
      min_seconds: 1
      max_seconds: 60
    style:
      font: DejaVu Sans
      background: "#101418"
      foreground: "#ffffff"
      accent: "#4aa3df"
      title: Studio
    voice: {engine: none}
    guard: {require_audio: false}
    narration: {inline: {1: "One two three."}}
    scenes:
      - n: 1
        title: One
        shots: [{still: shot.svg}]
"""


def _spec(tmp_path: Path, *, extra: str = "") -> Path:
    """A loadable spec with one still, plus an optional dedented fragment."""
    body = textwrap.dedent(_MINIMAL)
    if extra:
        body += textwrap.dedent(extra).rstrip("\n") + "\n"
    path = _write(tmp_path, body)
    (tmp_path / "shot.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180">'
        '<rect width="320" height="180" fill="#223344"/></svg>', encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _clean_bindings():
    """A step binding is global process state; a leaked one changes the next test."""
    from vidkit import exec as ex

    ex.unbind_environments()
    for sess in st.live_sessions():          # a held session is process state too
        st.close_session(sess)
    yield
    ex.unbind_environments()
    for sess in st.live_sessions():
        st.close_session(sess)


def _png(path: Path, payload: bytes = b"png-bytes") -> Path:
    """A file that is a take file as far as the studio is concerned.

    Deliberately not a real PNG: nothing in the take machinery decodes one, and a
    test that had to render an image to check a hash would be testing rsvg.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


# --------------------------------------------------------------------------- #
# budgets
# --------------------------------------------------------------------------- #
def test_no_declared_ceiling_is_not_a_zero_second_budget():
    """`seconds_left` is `None`, never `0`, when nothing was declared.

    A sentinel `0` would read as "out of time" and every caller would refuse to
    work; a session that declared no ceiling has, by its own account, no ceiling.
    """
    b = st.Budget()
    assert b.seconds_left is None
    assert b.exhausted is False
    assert b.check(seconds=10_000) == ""
    assert b.to_dict()["seconds_left"] is None


def test_a_declared_ceiling_counts_down_and_eventually_refuses():
    b = st.Budget(max_seconds=100.0)
    assert b.check(seconds=40) == ""
    b.note_spend(90.0)
    assert b.seconds_left == pytest.approx(10.0)
    why = b.check(seconds=30)
    assert "100s budget" in why and "10s" in why
    assert b.exhausted is False


def test_a_spent_budget_reads_as_exhausted_and_at_zero_seconds_left():
    b = st.Budget(max_seconds=5.0)
    b.note_spend(5.0)
    assert b.seconds_left == 0.0
    assert b.exhausted is True


def test_the_container_ceiling_counts_what_is_held_at_once_not_what_was_started():
    """One at a time, twelve times, is not twelve sandboxes on the machine."""
    b = st.Budget(max_containers=1)
    assert b.check(containers=1) == ""
    assert "would be up at once" in b.check(containers=2)
    b.note_spend(0.0, containers=1)
    assert b.containers == 1, "the peak, not the sum"


def test_the_container_high_water_mark_never_goes_down():
    b = st.Budget()
    b.note_spend(0.0, containers=3)
    b.note_spend(0.0, containers=1)
    assert b.containers == 3


def test_a_budget_round_trips_through_the_record():
    b = st.Budget(max_seconds=99.0, max_containers=2, max_tokens=1000,
                  tokens=42, spent_seconds=3.5, containers=1)
    s = st.Session(id="s1", budgets=b)
    back = st.Session.from_dict(s.to_dict())
    assert back.budgets.to_dict() == s.budgets.to_dict()


# --------------------------------------------------------------------------- #
# the session record
# --------------------------------------------------------------------------- #
def test_opening_a_session_writes_a_record_beside_the_spec(tmp_path):
    spec = _spec(tmp_path)
    sess = st.open_session(tmp_path, spec=str(spec), story="a story")
    p = tmp_path / ".vidkit" / "sessions" / f"{sess.id}.json"
    assert p.is_file(), "the record is the point: a sitting that leaves no trace is a rumour"
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw["id"] == sess.id and raw["open"] is True
    assert raw["story"] == "a story"
    assert raw["root"] == str(tmp_path)


def test_a_second_session_cannot_reuse_an_id(tmp_path):
    """Sessions are never resumed under the same id.

    A record of a sitting that was interrupted still has to be readable as what it
    was; overwriting it would erase the only account of the half-done work.
    """
    st.open_session(tmp_path, session_id="s1")
    with pytest.raises(ToolError, match="already exists"):
        st.open_session(tmp_path, session_id="s1")


def test_a_session_id_that_could_escape_the_state_directory_is_refused(tmp_path):
    with pytest.raises(ToolError, match="not usable"):
        st.open_session(tmp_path, session_id="../../etc/passwd")


def test_a_corrupt_record_is_skipped_by_the_list_and_not_fatal(tmp_path):
    good = st.open_session(tmp_path, session_id="good")
    d = tmp_path / ".vidkit" / "sessions"
    (d / "broken.json").write_text("{not json", encoding="utf-8")
    rows = st.list_sessions(tmp_path)
    assert [r["id"] for r in rows["sessions"]] == [good.id]
    with pytest.raises(ToolError, match="could not be read"):
        st.Registry(tmp_path).load("broken")


def test_listing_sessions_names_the_directory_they_are_in(tmp_path):
    st.open_session(tmp_path, session_id="s1")
    rows = st.list_sessions(tmp_path)
    assert rows["sessions_dir"].endswith("/.vidkit/sessions")
    assert rows["count"] == 1


def test_closing_a_session_records_the_time_and_a_later_list_can_hide_it(tmp_path):
    sess = st.open_session(tmp_path, session_id="s1")
    st.close_session(sess, reason="done")
    assert sess.open is False and sess.closed is not None
    assert st.list_sessions(tmp_path)["count"] == 1
    assert st.list_sessions(tmp_path, include_closed=False)["count"] == 0


def test_a_session_loaded_from_disk_knows_where_its_record_came_from(tmp_path):
    """`record_dir` is where the *record* is, which is not `out_dir`.

    A client that kept only the session id needs the first one to find it again.
    Pointing both at the project root would tell it nothing it did not already have.
    """
    sess = st.open_session(tmp_path, session_id="s1")
    back = st.Registry(tmp_path).load("s1")
    assert back._record_dir == str(st.Registry(tmp_path).dir)
    assert back._record_dir != back.out_dir
    assert Path(back._record_dir).is_dir() and Path(back._record_dir).name == "sessions"
    assert back.out_dir == str(tmp_path.resolve())


def test_sync_budget_is_a_high_water_mark_of_two_kinds_of_spend(tmp_path):
    """The clock and one long command are both real spend; neither erases the other."""
    sess = st.open_session(tmp_path, session_id="s1")
    sess.sync_run_seconds(30.0)
    sess.sync_budget()
    assert sess.budgets.spent_seconds >= 30.0
    sess.opened = time.time() - 1.0          # as though the process restarted
    sess.sync_budget()
    assert sess.budgets.spent_seconds >= 30.0, "a short clock must not lower it"


def test_saving_is_atomic_so_a_crash_cannot_leave_a_half_written_record(tmp_path):
    sess = st.open_session(tmp_path, session_id="s1")
    reg = st.Registry(tmp_path)
    reg.save(sess)
    leftovers = list(reg.dir.glob("*.tmp"))
    assert leftovers == []
    assert json.loads(reg.path("s1").read_text(encoding="utf-8"))["id"] == "s1"


# --------------------------------------------------------------------------- #
# takes
# --------------------------------------------------------------------------- #
def test_a_take_recorded_for_a_file_that_is_not_there_is_refused(tmp_path):
    """The one refusal this whole module exists for.

    A take that was never taken is a recorded fact that is not true, and a video
    built from it would show a screen the product never showed (I7). The file is
    the fact; the record may only describe it.
    """
    sess = st.open_session(tmp_path, session_id="s1")
    with pytest.raises(SpecError, match="was not recorded because there is no"):
        st.record_take(sess, "login", 1)
    assert sess.takes == []


def test_a_recorded_take_carries_the_hash_of_the_bytes_it_is_named_for(tmp_path):
    sess = st.open_session(tmp_path, session_id="s1")
    _png(st.take_path(Path(sess.out_dir), "login", 1), b"first attempt")
    entry = st.record_take(sess, "login", 1, note="first")
    assert entry.bytes == len(b"first attempt")
    assert entry.digest == st._digest(st.take_path(Path(sess.out_dir), "login", 1))
    assert entry.digest != "", "a take with no hash answers 'did it change?' with a shrug"


def test_two_takes_of_one_capture_have_different_hashes_and_both_are_kept(tmp_path):
    sess = st.open_session(tmp_path, session_id="s1")
    a = _png(st.take_path(Path(sess.out_dir), "login", 1), b"attempt one")
    st.record_take(sess, "login", 1)
    b = _png(st.take_path(Path(sess.out_dir), "login", 2), b"attempt two")
    st.record_take(sess, "login", 2)
    assert a != b
    rows = st.list_takes(sess)["takes"]
    assert [r["take"] for r in rows] == [1, 2]
    assert rows[0]["digest"] != rows[1]["digest"]
    assert all(r["selected"] is False for r in rows)


def test_recording_the_same_take_twice_replaces_the_note_rather_than_duplicating(tmp_path):
    sess = st.open_session(tmp_path, session_id="s1")
    _png(st.take_path(Path(sess.out_dir), "login", 1))
    st.record_take(sess, "login", 1, note="first")
    st.record_take(sess, "login", 1, note="second")
    assert len(sess.takes) == 1
    assert sess.takes[0].note == "second"


def test_a_take_number_below_one_is_refused(tmp_path):
    sess = st.open_session(tmp_path, session_id="s1")
    with pytest.raises(ToolError, match="starts at 1"):
        st.record_take(sess, "login", 0)


def test_the_scan_finds_a_take_that_was_never_recorded(tmp_path):
    """"Which takes exist" is a question about the filesystem, not the record.

    A capture run outside a session, or a record written by an older build, leaves
    files the record does not know about; the record supplies the *notes*, which
    are the part only a caller knows.
    """
    sess = st.open_session(tmp_path, session_id="s1")
    _png(st.take_path(Path(sess.out_dir), "login", 3), b"orphan")
    rows = st.list_takes(sess)["takes"]
    assert [(r["capture"], r["take"]) for r in rows] == [("login", 3)]
    assert rows[0]["digest"] != ""
    assert rows[0]["note"] == ""
    assert st.status(sess)["unrecorded_takes"] == ["login/3"]


def test_a_note_from_the_record_is_carried_onto_a_scanned_take(tmp_path):
    sess = st.open_session(tmp_path, session_id="s1")
    _png(st.take_path(Path(sess.out_dir), "login", 1))
    st.record_take(sess, "login", 1, note="after the fix")
    rows = st.list_takes(sess)["takes"]
    assert rows[0]["note"] == "after the fix"
    assert rows[0]["at"] != ""


def test_takes_of_different_captures_are_not_confused_with_one_another(tmp_path):
    sess = st.open_session(tmp_path, session_id="s1")
    _png(st.take_path(Path(sess.out_dir), "login", 1))
    _png(st.take_path(Path(sess.out_dir), "checkout", 1))
    assert st.takes_summary(sess)["captures"] == {"checkout": [1], "login": [1]}
    assert st.list_takes(sess, "login")["takes"][0]["capture"] == "login"


def test_selecting_a_take_promotes_its_bytes_over_the_base_name(tmp_path):
    sess = st.open_session(tmp_path, session_id="s1")
    _png(st.take_path(Path(sess.out_dir), "login", 1), b"first")
    _png(st.take_path(Path(sess.out_dir), "login", 2), b"second")
    st.select_take(sess, "login", 2)
    assert (Path(sess.out_dir) / "_capture" / "login.png").read_bytes() == b"second"
    assert sess.selections == ["login/2"]
    rows = st.list_takes(sess)["takes"]
    assert [r["selected"] for r in rows] == [False, True]


def test_selecting_a_take_that_does_not_exist_is_refused(tmp_path):
    """"Film from take 3" must not quietly film from take 1."""
    sess = st.open_session(tmp_path, session_id="s1")
    _png(st.take_path(Path(sess.out_dir), "login", 1))
    with pytest.raises(SpecError, match="does not exist"):
        st.select_take(sess, "login", 3)


def test_promoting_a_byte_identical_retry_is_refused(tmp_path):
    """A promotion that changes nothing would leave the record claiming a take the
    film is not built from — and the honest answer is that the retry produced the
    same screen, which is worth knowing rather than hiding."""
    sess = st.open_session(tmp_path, session_id="s1")
    _png(st.take_path(Path(sess.out_dir), "login", 1), b"same")
    _png(st.take_path(Path(sess.out_dir), "login", 2), b"same")
    # take 1 is the base name once promoted; make that true the way the pipeline would
    st.select_take(sess, "login", 1)
    with pytest.raises(ToolError, match="byte-identical"):
        st.select_take(sess, "login", 2)


def test_every_promotion_is_kept_in_the_record_not_only_the_last(tmp_path):
    """A session that changed its mind twice should show both decisions."""
    sess = st.open_session(tmp_path, session_id="s1")
    for i, payload in ((1, b"a"), (2, b"b"), (3, b"c")):
        _png(st.take_path(Path(sess.out_dir), "login", i), payload)
    st.select_take(sess, "login", 2)
    st.select_take(sess, "login", 3)
    assert sess.selections == ["login/2", "login/3"]
    assert st.list_takes(sess)["selections"] == ["login/2", "login/3"]


#: the bytes a promotion leaves at the plain name — deliberately not the same
#: bytes a fresh screenshot would produce, so the two are distinguishable.
_PROMOTED = b"promoted-take-bytes"


def _capture_ctx(tmp_path: Path, *, base: bytes | None):
    """A context whose spec declares one capture named ``login`` and whose take files
    are ``base``/``take2`` bytes at the plain name and at ``.take2``."""
    from vidkit.assembler import make_context

    spec_path = _spec(tmp_path, extra="""
        captures:
          - name: login
            url: "data:text/html,<h1 id=t>hi</h1>"
            actions: [{type: wait_for, selector: "#t"}]
    """)
    out = tmp_path / "out"
    ctx = make_context(spec_path, out_dir=out)
    if base is not None:
        _png(out / "_capture" / "login.png", base)
    _png(out / "_capture" / "login.take2.png", _PROMOTED)
    return ctx


def test_a_build_honours_the_take_the_sitting_selected(tmp_path, monkeypatch):
    """The whole sitting is theatre unless the render respects its casting.

    `select_take` copies take 2 over the plain name, and reading the record afterwards
    says take 2 is in place — but the *render* stage used to re-shoot every declared
    capture and overwrite the promotion. The film then contained a second the client
    had rejected while the record still named the one it kept: two halves of one
    artefact disagreeing, with nothing in the transcript to show it.

    ``capture_one`` is booby-trapped rather than merely counted: the point is that the
    browser is not opened at all, so a version that shot the page and then discarded
    the result would still fail here.
    """
    from vidkit import capture as _cap

    ctx = _capture_ctx(tmp_path, base=_PROMOTED)
    ctx.selections = {"login/2"}

    def boom(*a, **k):
        raise AssertionError("the page was re-shot despite a selected take")

    monkeypatch.setattr(_cap, "capture_one", boom)
    got = _cap.capture_all(ctx)
    assert [r.detail for r in got] == ["selected take 2"], got
    assert (ctx.captures / "login.png").read_bytes() == _PROMOTED


def test_the_delivered_frame_is_the_one_the_record_says_is_selected(tmp_path):
    """`select_take`'s promotion and the pipeline's read must agree *by bytes*.

    The bug this pins was not that a take was lost — the file was still there under
    `.take2` — but that the plain name, which is the only name the pipeline reads, was
    overwritten by a fresh screenshot. So compare the bytes the renderer will pick up
    against the take the record claims, rather than comparing two paths to themselves.
    """
    spec_path = _spec(tmp_path, extra="""
        captures:
          - name: login
            url: "data:text/html,<h1 id=t>hi</h1>"
    """)
    sess = st.open_session(tmp_path, spec=str(spec_path), session_id="s1")
    _png(st.take_path(Path(sess.out_dir), "login", 1), b"rejected")
    _png(st.take_path(Path(sess.out_dir), "login", 2), b"chosen")
    st.select_take(sess, "login", 2)
    ctx = st.session_context(sess)
    chosen = ctx.selected_take("login")
    assert chosen == 2, "the session's promotion did not reach the pipeline's context"
    assert (ctx.captures / "login.png").read_bytes() == b"chosen"


def test_a_build_with_no_selection_still_takes_a_fresh_capture(tmp_path, monkeypatch):
    """The escape hatch is only for a *chosen* take. With nothing chosen the capture
    stage must still run: the page is the frame the spec asked for, and skipping the
    whole stage would film whatever file happened to be left on disk while reporting
    that a capture had been taken."""
    from vidkit import capture as _cap

    ctx = _capture_ctx(tmp_path, base=b"take-one")
    assert ctx.selected_take("login") is None

    calls: list[str] = []

    def fake_one(c, cap, chrome):
        calls.append(cap.name)
        return _cap.Result(cap.name, c.captures / "login.png", True, cap.url, [])

    monkeypatch.setattr(_cap, "capture_one", fake_one)
    monkeypatch.setattr(_cap, "_playwright_available", lambda: True)
    monkeypatch.setattr(_cap, "_find_chrome", lambda: None)
    got = _cap.capture_all(ctx)
    assert calls == ["login"], "the stage skipped a capture nobody had promoted"
    assert [r.detail for r in got] == [ctx.spec.captures[0].url], got


def test_a_build_whose_promoted_file_vanished_takes_a_fresh_capture(tmp_path, monkeypatch):
    """A record can name a take whose bytes were deleted — a cleaned output directory,
    a copied record. Reporting "keeping selected take 2" for a file that is not there
    would put the *absence* into the film and call it the chosen moment."""
    from vidkit import capture as _cap

    ctx = _capture_ctx(tmp_path, base=None)          # `.take2` exists, the base does not
    ctx.selections = {"login/2"}
    (ctx.captures / "login.take2.png").unlink()

    calls: list[str] = []
    monkeypatch.setattr(_cap, "capture_one",
                        lambda c, cap, chrome: (calls.append(cap.name),
                                                _cap.Result(cap.name, None, False, "x", []))[1])
    monkeypatch.setattr(_cap, "_playwright_available", lambda: True)
    monkeypatch.setattr(_cap, "_find_chrome", lambda: None)
    _cap.capture_all(ctx)
    assert calls == ["login"], "a vanished promotion must fall back to a real capture"


def test_a_selection_for_a_capture_the_spec_does_not_declare_is_not_consulted(tmp_path):
    """A record may outlive an edit to the story it was opened against. A marker for a
    capture that is no longer declared names nothing, and must not be read as one."""
    ctx = _capture_ctx(tmp_path, base=b"take-one")
    ctx.selections = {"gone/2"}
    assert ctx.selected_take("login") is None
    assert ctx.selected_take("gone") == 2


def test_the_highest_selection_wins_when_a_sitting_changes_its_mind(tmp_path):
    """A caller may promote take 2, watch the render, prefer take 3, and promote that.
    The second choice is the one it means; honouring the first would film a rejected
    take while the record's last word said otherwise."""
    ctx = _capture_ctx(tmp_path, base=None)
    ctx.selections = {"login/2", "login/3"}
    assert ctx.selected_take("login") == 3


# --------------------------------------------------------------------------- #
# status: what to do next
# --------------------------------------------------------------------------- #
def test_status_says_what_to_do_next_and_changes_its_mind_as_the_session_does(tmp_path):
    sess = st.open_session(tmp_path, session_id="s1")
    assert "nothing rendered yet" in st.status(sess)["next"]
    _png(st.take_path(Path(sess.out_dir), "login", 1))
    assert "none is selected" in st.status(sess)["next"]
    st.select_take(sess, "login", 1)
    assert "vidkit_run" in st.status(sess)["next"]


def test_status_of_a_closed_session_tells_the_caller_to_open_a_new_one(tmp_path):
    sess = st.open_session(tmp_path, session_id="s1")
    st.close_session(sess)
    assert "closed" in st.status(sess)["next"]


def test_status_names_the_artifacts_that_are_actually_on_disk(tmp_path):
    sess = st.open_session(tmp_path, session_id="s1")
    assert st.status(sess)["artifacts"] == {"output": None, "srt": None, "verify": None}
    (Path(sess.out_dir) / "studio.mp4").write_bytes(b"x")
    (Path(sess.out_dir) / "verify.json").write_text("{}", encoding="utf-8")
    art = st.status(sess)["artifacts"]
    assert art["output"].endswith("studio.mp4") and art["verify"].endswith("verify.json")
    assert art["srt"] is None, "an absent artifact is absent, not invented"


def test_status_reports_the_budget_it_was_opened_with(tmp_path):
    sess = st.open_session(tmp_path, session_id="s1", max_seconds=600.0)
    row = st.status(sess)
    assert row["budgets"]["max_seconds"] == 600.0
    assert row["budgets"]["seconds_left"] is not None


# --------------------------------------------------------------------------- #
# reading the report
# --------------------------------------------------------------------------- #
def test_reading_a_report_that_was_never_written_is_refused(tmp_path):
    sess = st.open_session(tmp_path, session_id="s1")
    with pytest.raises(ToolError, match="no report at"):
        st.read_report(sess)


def test_reading_the_report_returns_the_checks_that_failed_whole(tmp_path):
    """A studio that could only say `ok: false` would make the caller guess which
    claim broke."""
    sess = st.open_session(tmp_path, session_id="s1")
    (Path(sess.out_dir) / "verify.json").write_text(json.dumps({
        "ok": False,
        "checks": [{"name": "runtime within window", "ok": True},
                   {"name": "captions readable", "ok": False, "detail": "3 lines"}],
    }), encoding="utf-8")
    got = st.read_report(sess)
    assert got["ok"] is False and got["checks"] == 2
    assert [c["name"] for c in got["failed"]] == ["captions readable"]
    assert got["failed"][0]["detail"] == "3 lines"


def test_a_report_is_read_from_the_file_not_from_memory(tmp_path):
    """The file is what a reviewer opens; answering from memory could disagree
    with the artifact beside it."""
    sess = st.open_session(tmp_path, session_id="s1")
    p = Path(sess.out_dir) / "verify.json"
    p.write_text(json.dumps({"ok": True, "checks": []}), encoding="utf-8")
    assert st.read_report(sess)["ok"] is True
    p.write_text(json.dumps({"ok": False, "checks": [{"name": "x", "ok": False}]}),
                 encoding="utf-8")
    assert st.read_report(sess)["ok"] is False


def test_a_report_that_is_not_json_is_refused_rather_than_crashing(tmp_path):
    sess = st.open_session(tmp_path, session_id="s1")
    (Path(sess.out_dir) / "verify.json").write_text("{oops", encoding="utf-8")
    with pytest.raises(ToolError, match="could not be read"):
        st.read_report(sess)


# --------------------------------------------------------------------------- #
# the spec a session works against
# --------------------------------------------------------------------------- #
def test_a_session_re_reads_its_spec_so_an_edit_is_not_missed(tmp_path):
    spec = _spec(tmp_path)
    sess = st.open_session(tmp_path, spec=str(spec), session_id="s1")
    assert st.load_spec(sess).project.title == "Studio"
    _write(tmp_path, textwrap.dedent(_MINIMAL).replace("title: Studio", "title: Renamed"))
    assert st.load_spec(sess).project.title == "Renamed"


def test_a_spec_that_vanished_is_named_rather_than_replaced(tmp_path):
    spec = _spec(tmp_path)
    sess = st.open_session(tmp_path, spec=str(spec), session_id="s1")
    spec.unlink()
    with pytest.raises(SpecError, match="no longer there"):
        st.load_spec(sess)


def test_a_session_without_a_spec_can_still_be_opened_and_stays_honest(tmp_path):
    """A session may be opened before its story exists."""
    sess = st.open_session(tmp_path, session_id="s1")
    assert st.status(sess)["spec"] == ""
    with pytest.raises(SpecError, match="nothing to plan or build"):
        st.session_context(sess)
    with pytest.raises(SpecError, match="none was given"):
        st.with_spec(sess)


# --------------------------------------------------------------------------- #
# running commands
# --------------------------------------------------------------------------- #
@needs_sandbox
def test_a_step_the_spec_does_not_declare_is_refused(tmp_path):
    """A tool that runs an arbitrary command handed to it over the wire is a remote
    shell. The spec is the single account of what the video shows; a caller that
    wants a new command edits the spec."""
    spec_path = _spec(tmp_path, extra="""
        exec:
          steps: [{label: probe, cmd: ["true"]}]
    """)
    from vidkit.spec import load_spec
    sess = st.open_session(tmp_path, spec=str(spec_path), session_id="s1")
    with pytest.raises(SpecError, match="declares no exec step 'nuke'"):
        st.run_step(sess, load_spec(spec_path), "nuke")


@needs_sandbox
def test_a_declared_step_runs_and_is_recorded_with_what_it_cost(tmp_path):
    from vidkit.spec import load_spec
    spec_path = _spec(tmp_path, extra="""
        exec:
          steps:
            - label: say
              cmd: ["echo", "hello from the sandbox"]
              capture_stdout: true
    """)
    spec = load_spec(spec_path)
    sess = st.open_session(tmp_path, spec=str(spec_path), session_id="s1")
    row = st.run_step(sess, spec, "say")
    assert row["label"] == "say" and row["exit_code"] == 0 and row["expected"] is True
    assert row["session"] == sess.id
    kinds = [e["kind"] for e in sess.events]
    assert "exec" in kinds
    assert sess.budgets.spent_seconds > 0.0, "a command that ran cost time, and the record says so"


@needs_sandbox
def test_the_record_of_a_step_carries_its_timing_and_not_its_transcript(tmp_path):
    """`ExecResult.to_dict()` is a *result*, never a stream: a studio that returned
    every byte of a long build on every call would be unusable over a wire."""
    from vidkit.spec import load_spec
    spec_path = _spec(tmp_path, extra="""
        exec:
          steps: [{label: say, cmd: ["true"]}]
    """)
    spec = load_spec(spec_path)
    sess = st.open_session(tmp_path, spec=str(spec_path), session_id="s1")
    row = st.run_step(sess, spec, "say")
    assert "seconds" in row and "stdout_bytes" in row
    assert "stdout" not in row and "stderr" not in row


@needs_sandbox
def test_a_command_that_fails_is_reported_and_not_raised(tmp_path):
    """A session reports; the *build* aborts (I2). That difference is the whole
    reason an agent can drive this and a pipeline cannot."""
    from vidkit.spec import load_spec
    spec_path = _spec(tmp_path, extra="""
        exec:
          steps:
            - label: fail
              cmd: ["false"]
    """)
    spec = load_spec(spec_path)
    sess = st.open_session(tmp_path, spec=str(spec_path), session_id="s1")
    row = st.run_step(sess, spec, "fail")
    assert row["exit_code"] != 0 and row["expected"] is False
    assert [e for e in sess.events if e["kind"] == "exec"][0]["ok"] is False


@needs_sandbox
def test_a_step_can_be_run_only_when_there_is_budget_left(tmp_path):
    from vidkit.spec import load_spec
    spec_path = _spec(tmp_path, extra="""
        exec:
          steps: [{label: say, cmd: ["true"]}]
    """)
    spec = load_spec(spec_path)
    sess = st.open_session(tmp_path, spec=str(spec_path), session_id="s1",
                           max_seconds=1.0)
    # The clock and the declared spend are both real; `sync_budget` takes the
    # larger, so winding the record's own spend back is not a way to buy time.
    sess.opened = time.time() - 5.0
    sess.sync_budget()
    with pytest.raises(ToolError, match="session budget"):
        st.run_step(sess, spec, "say")


@needs_docker
def test_a_docker_step_without_its_environment_up_is_refused(tmp_path):
    """Silently starting a container would hide which lifecycle the video was
    filmed against."""
    from vidkit.spec import load_spec
    spec_path = _spec(tmp_path, extra="""
        environment:
          - name: db
            image: alpine:3
            ready: ["true"]
        exec:
          steps:
            - label: probe
              backend: docker
              environment: db
              cmd: ["true"]
    """)
    spec = load_spec(spec_path)
    sess = st.open_session(tmp_path, spec=str(spec_path), session_id="s1")
    with pytest.raises(ToolError, match="is not up for this session"):
        st.environment_exec(sess, spec, "probe")


@needs_sandbox
def test_a_local_step_is_not_sent_to_environment_exec(tmp_path):
    from vidkit.spec import load_spec
    spec_path = _spec(tmp_path, extra="""
        exec:
          steps: [{label: say, cmd: ["true"]}]
    """)
    spec = load_spec(spec_path)
    sess = st.open_session(tmp_path, spec=str(spec_path), session_id="s1")
    with pytest.raises(ToolError, match="does not run in an environment"):
        st.environment_exec(sess, spec, "say")


# --------------------------------------------------------------------------- #
# environments
# --------------------------------------------------------------------------- #
# `command:` is not decoration. `alpine:3` with no command runs `/bin/sh`, which
# exits the instant there is nothing on stdin — so a container without one is a
# container that is already dead by the time anything asks it anything, and every
# assertion here would be measuring the wrong failure.
_DB_SPEC = """
    environment:
      - name: db
        image: alpine:3
        ready: ["true"]
        command: ["sleep", "300"]
    exec:
      steps:
        - label: probe
          backend: docker
          environment: db
          cmd: ["true"]
"""


@needs_docker
def test_an_environment_the_spec_does_not_declare_is_named_in_the_refusal(tmp_path):
    from vidkit.spec import load_spec
    spec_path = _spec(tmp_path, extra=_DB_SPEC)
    sess = st.open_session(tmp_path, spec=str(spec_path), session_id="s1")
    with pytest.raises(SpecError, match="declares no environment 'nope' \\(declared: db\\)"):
        st.start_environment(sess, load_spec(spec_path), "nope")


def test_asking_about_a_never_started_environment_says_nothing_is_held(tmp_path):
    spec_path = _spec(tmp_path, extra=_DB_SPEC)
    sess = st.open_session(tmp_path, spec=str(spec_path), session_id="s1")
    row = st.environment_status(sess)
    assert row["held"] == []
    assert "alive: false" in row["note"]


def test_the_host_is_asked_what_is_up_rather_than_trusting_a_record(tmp_path):
    """What is actually running must not depend on which JSON file you opened."""
    rows = st.environments_in_use()
    assert isinstance(rows, list)
    for r in rows:
        assert "name" in r or "error" in r


@needs_docker
def test_a_started_environment_is_labelled_with_the_session_that_started_it(tmp_path):
    """The stamp is the session id: `docker ps` on a machine that has run vidkit
    shows which sitting a container belongs to, which is how a leak is traced."""
    from vidkit.spec import load_spec
    spec_path = _spec(tmp_path, extra=_DB_SPEC)
    spec = load_spec(spec_path)
    sess = st.open_session(tmp_path, spec=str(spec_path), session_id="s1")
    try:
        ref = st.start_environment(sess, spec, "db")
        assert ref.container_name, "a container with no name cannot be stopped"
        assert sess.id in ref.container_name
        assert ref.container_id, "a truncated id cannot be stopped either"
        assert ref.teardown == {}
    finally:
        for ref in st.stop_environment(sess):
            assert ref.teardown.get("removed") is True, ref.teardown
    assert st.live_refs(sess) == []


@needs_docker
def test_one_session_holds_one_container_per_environment(tmp_path):
    """A second container under the same name cannot exist; two under different
    names is how a machine ends up running four copies of Postgres."""
    from vidkit.spec import load_spec
    spec_path = _spec(tmp_path, extra=_DB_SPEC)
    spec = load_spec(spec_path)
    sess = st.open_session(tmp_path, spec=str(spec_path), session_id="s1")
    try:
        ref = st.start_environment(sess, spec, "db")
        with pytest.raises(ToolError, match="is already up for this session"):
            st.start_environment(sess, spec, "db")
        assert len(st.live_refs(sess)) == 1
        assert ref.ready is True
    finally:
        st.stop_environment(sess)

    # and after a teardown the name is free again
    ref2 = st.start_environment(sess, spec, "db")
    try:
        assert ref2.container_id, "a second sitting must be able to use the name"
    finally:
        st.stop_environment(sess)


@needs_docker
def test_tearing_down_takes_everything_the_session_holds(tmp_path):
    """A session ending should not be able to leave a database behind because the
    caller forgot which one it started."""
    from vidkit.spec import load_spec
    spec_path = _spec(tmp_path, extra=_DB_SPEC)
    spec = load_spec(spec_path)
    sess = st.open_session(tmp_path, spec=str(spec_path), session_id="s1")
    st.start_environment(sess, spec, "db")
    down = st.stop_environment(sess)
    assert [r.name for r in down] == ["db"]
    assert st.live_refs(sess) == []
    assert st.stop_environment(sess) == [], "teardown is idempotent"


@needs_docker
def test_a_step_runs_inside_the_session_own_container(tmp_path):
    """The studio reaches the container through the same module-level binding the
    pipeline uses, so a step filmed here is filmed the way the build films it."""
    from vidkit.spec import load_spec
    spec_path = _spec(tmp_path, extra=_DB_SPEC)
    spec = load_spec(spec_path)
    sess = st.open_session(tmp_path, spec=str(spec_path), session_id="s1")
    try:
        st.start_environment(sess, spec, "db")
        row = st.environment_exec(sess, spec, "probe")
        assert row["exit_code"] == 0 and row["expected"] is True
        assert row["backend"] == "docker"
        # The image is part of what the command *was*, so the record carries it —
        # together with the digest, because a tag is a name that can move.
        assert row["image"] == "alpine:3"
        assert row["image_digest"].startswith("sha256:")
    finally:
        st.stop_environment(sess)


@needs_docker
def test_a_container_that_died_is_distinguishable_from_one_that_never_started(tmp_path):
    """`alive: false` on a *held* environment is the single most useful thing this
    call can say, and neither half of the answer contains it on its own."""
    from vidkit.spec import load_spec
    spec_path = _spec(tmp_path, extra=_DB_SPEC)
    spec = load_spec(spec_path)
    sess = st.open_session(tmp_path, spec=str(spec_path), session_id="s1")
    try:
        ref = st.start_environment(sess, spec, "db")
        row = st.environment_status(sess)["held"]
        assert row and row[0]["alive"] is True
        st.stop_environment(sess)          # the service goes away
        # the record still holds it, but the host does not — that is a death
        sess.environment_refs[0].stopped = None
        row = st.environment_status(sess)["held"]
        assert row and row[0]["alive"] is False
    finally:
        st.stop_environment(sess)


@needs_docker
def test_closing_a_session_leaves_no_container_behind(tmp_path):
    from vidkit.spec import load_spec
    spec_path = _spec(tmp_path, extra=_DB_SPEC)
    spec = load_spec(spec_path)
    sess = st.open_session(tmp_path, spec=str(spec_path), session_id="s1")
    st.start_environment(sess, spec, "db")
    out = st.close_session(sess, reason="done")
    assert out["problems"] == [], "a session that cannot shut down cleanly is a leak"
    assert all(r["name"] != sess.id for r in st.environments_in_use()
               if isinstance(r, dict) and "name" in r)


# --------------------------------------------------------------------------- #
# driving a browser
# --------------------------------------------------------------------------- #
def test_acting_before_a_browser_is_open_is_refused(tmp_path):
    sess = st.open_session(tmp_path, session_id="s1")
    with pytest.raises(ToolError, match="no browser is open"):
        st.browser_act(sess, [{"type": "click", "selector": "#x"}])
    with pytest.raises(ToolError, match="no browser is open"):
        st.browser_shot(sess, "login")


def test_closing_a_browser_that_was_never_open_is_not_an_error(tmp_path):
    sess = st.open_session(tmp_path, session_id="s1")
    assert st.browser_close(sess) == {"ok": True, "closed": False,
                                      "note": "no browser was open"}


@needs_playwright
def test_a_browser_can_be_opened_driven_and_photographed_into_the_take_folder(tmp_path):
    """The end-to-end browser path, with no network: a data: URL the page wrote
    itself. What it proves is the plumbing — the page survives between calls, the
    action DSL drives it, and the screenshot lands where `capture` would put it.
    """
    from vidkit.spec import load_spec
    spec_path = _spec(tmp_path, extra="""
        captures:
          - name: login
            url: "data:text/html,<h1 id=t>hello studio</h1>"
            actions:
              - {type: wait_for, selector: "#t"}
    """)
    spec = load_spec(spec_path)
    sess = st.open_session(tmp_path, spec=str(spec_path), session_id="s1")
    assert st._capture._playwright_available()
    try:
        st.browser_open(sess, spec, "data:text/html,<h1 id=t>hello studio</h1>")
        acted = st.browser_act(sess, [{"type": "wait_for", "selector": "#t"},
                                      {"type": "wait_for", "selector": "#t",
                                       "timeout": 2.0}])
        assert acted["ok"] is True
        assert acted["steps"][0]["text"] == "hello studio", acted["steps"]
        shot = st.browser_shot(sess, "login", take=1)
        assert shot["promoted"] is False, "an ad-hoc shot must not silently become the film"
        assert Path(sess.out_dir, shot["path"]).is_file()
        assert st.take_path(Path(sess.out_dir), "login", 1).is_file()
    finally:
        st.browser_close(sess)
    assert sess._live.get("browser") is None


@needs_playwright
def test_a_second_browser_in_one_session_is_refused(tmp_path):
    """One session, one page: a caller that opens two has lost track of which one
    the pictures came from."""
    from vidkit.spec import load_spec
    spec_path = _spec(tmp_path)
    spec = load_spec(spec_path)
    sess = st.open_session(tmp_path, spec=str(spec_path), session_id="s1")
    try:
        st.browser_open(sess, spec, "data:text/html,<p>one</p>")
        with pytest.raises(ToolError, match="already has a browser open"):
            st.browser_open(sess, spec, "data:text/html,<p>two</p>")
    finally:
        st.browser_close(sess)


@needs_playwright
def test_an_action_that_fails_is_the_last_step_reported_not_an_exception(tmp_path):
    """An agent that clicks a stale selector needs to *read* the failure and try
    again; an exception would end the sitting."""
    from vidkit.spec import load_spec
    spec_path = _spec(tmp_path)
    spec = load_spec(spec_path)
    sess = st.open_session(tmp_path, spec=str(spec_path), session_id="s1")
    try:
        st.browser_open(sess, spec, "data:text/html,<p>here</p>")
        # A deliberately short patience, so what the test measures is the
        # engine's own refusal and not Playwright's 30-second default. The
        # point is that a failing action comes back as a *row*, not an exception.
        out = st.browser_act(sess, [
            {"type": "wait_for", "selector": "p"},
            {"type": "click", "selector": "#not-there", "timeout": 0.3},
            {"type": "click", "selector": "p"},
        ])
        assert out["ok"] is False and out["stopped_at"] == 1
        assert len(out["steps"]) == 2, "the steps after the failure must not be attempted"
        assert out["steps"][0]["ok"] is True and out["steps"][1]["ok"] is False
    finally:
        st.browser_close(sess)


@needs_playwright
def test_a_browser_is_frozen_the_same_way_the_capture_stage_freezes_one(tmp_path):
    """A picture taken through this door has to be the picture the build would
    film, or the video's frames are unreproducible by the only code that is
    supposed to be able to reproduce them."""
    from vidkit.capture import FROZEN_LOCALE, FROZEN_TZ
    from vidkit.spec import load_spec
    spec_path = _spec(tmp_path)
    spec = load_spec(spec_path)
    sess = st.open_session(tmp_path, spec=str(spec_path), session_id="s1")
    try:
        st.browser_open(sess, spec, "data:text/html,<p>x</p>")
        page = sess._live["page"]
        assert page.evaluate("() => navigator.language") == FROZEN_LOCALE
        assert page.evaluate(
            "() => Intl.DateTimeFormat().resolvedOptions().timeZone") == FROZEN_TZ
        assert page.evaluate(
            "() => matchMedia('(prefers-reduced-motion: reduce)').matches") is True
    finally:
        st.browser_close(sess)


# --------------------------------------------------------------------------- #
# the session doing the pipeline's work one stage at a time
# --------------------------------------------------------------------------- #
def test_capturing_a_name_the_spec_does_not_declare_is_refused(tmp_path):
    """`--only`-style narrowing is a request, not a licence to invent a capture."""
    spec_path = _spec(tmp_path, extra="""
        captures:
          - name: login
            url: "data:text/html,<p>x</p>"
    """)
    sess = st.open_session(tmp_path, spec=str(spec_path), session_id="s1")
    with pytest.raises(SpecError, match="declares no capture among"):
        st.capture_run(sess, ["nope"])


@needs_sandbox
def test_the_session_holds_one_context_and_one_assets_across_calls(tmp_path):
    """Rebuilding either would give the pipeline a *different* object graph from
    the one the session's own browser belongs to, which is how two halves of one
    sitting start disagreeing about the spec."""
    spec_path = _spec(tmp_path)
    sess = st.open_session(tmp_path, spec=str(spec_path), session_id="s1")
    assert st.session_context(sess) is st.session_context(sess)
    assert st.session_assets(sess) is st.session_assets(sess)


@needs_sandbox
def test_a_session_builds_a_video_the_same_run_the_cli_uses(tmp_path):
    """The exit criterion, minus the browser: a session runs the pipeline and the
    report comes back readable. Deliberately *not* a second assembly path — the
    verification story (I7) only holds if there is exactly one way a spec becomes
    a film."""
    spec_path = _spec(tmp_path)
    sess = st.open_session(tmp_path, spec=str(spec_path), session_id="s1")
    out = st.build(sess)
    assert out["report"] is not None, "a build that measured nothing has proved nothing"
    assert Path(out["output"]).is_file() and Path(out["srt"]).is_file()
    report = st.read_report(sess)
    assert report["ok"] is True, report["failed"]
    assert report["checks"] > 0


def test_a_build_that_has_not_run_has_no_report_to_read(tmp_path):
    sess = st.open_session(tmp_path, session_id="s1")
    with pytest.raises(ToolError, match="no report at"):
        st.read_report(sess)


def test_a_session_saves_after_work_so_the_record_and_the_work_cannot_diverge(tmp_path):
    spec_path = _spec(tmp_path)
    sess = st.open_session(tmp_path, spec=str(spec_path), session_id="s1")
    _png(st.take_path(Path(sess.out_dir), "login", 1))
    st.record_take(sess, "login", 1, note="done by hand")
    st.save(sess)
    back = st.Registry(tmp_path).load("s1")
    assert [t.note for t in back.takes] == ["done by hand"]


def test_the_default_output_directory_is_beside_the_spec(tmp_path):
    spec_path = _spec(tmp_path)
    assert st.default_out_dir(spec_path) == tmp_path.resolve()
    assert st.default_out_dir(None) == Path.cwd()


@needs_docker
def test_an_environment_reference_can_rebuild_the_runtime_state_it_stands_for(tmp_path):
    """`EnvRef.to_state` is why a session can use one engine instead of growing a
    second implementation of the same lifecycle."""
    from vidkit import exec as ex
    spec_path = _spec(tmp_path, extra=_DB_SPEC)
    from vidkit.spec import load_spec
    spec = load_spec(spec_path)
    env = st.env_spec(spec, "db")
    ref = st.EnvRef(name="db", container_name="vidkit-x", container_id="abc123",
                    image="alpine:3", image_digest="sha256:deadbeef",
                    started=time.time(), ready=True, ready_detail="ok")
    state = ref.to_state(env)
    assert isinstance(state, ex.EnvState)
    assert state.container_id == "abc123"
    assert state.spec is env
    assert ref.to_dict()["container_id"] == "abc123"[:12]


# --------------------------------------------------------------------------- #
# the exit criterion, over the wire
# --------------------------------------------------------------------------- #
@needs_playwright
@needs_render
@needs_mcp
def test_an_mcp_client_can_take_a_sitting_end_to_end(tmp_path):
    """The exit criterion, driven the way a real agent drives it.

    Not by importing the studio's functions — by speaking MCP to the server over an
    in-memory transport, which is the only thing an external agent can do. The
    sitting is: open against a spec, drive the live page, take three pictures of it,
    pick the best take, assemble, and read the report back. Every argument name below
    is the one in the tool's published schema, because that is what a client sees;
    if a verb were unreachable, misspelled, or shaped differently over the wire than
    in Python, this is where it shows.
    """
    from mcp.shared.memory import create_connected_server_and_client_session
    from vidkit import mcp_server as m

    spec_path = _spec(tmp_path, extra="""
        captures:
          - name: login
            url: "data:text/html,<h1 id=t>hello studio</h1>"
            actions:
              - {type: wait_for, selector: "#t"}
        scenes:
          - n: 1
            title: Hello
            script: "**Hello studio.**"
            shots:
              - {capture: login, effect: hold}
    """)
    m.set_project(tmp_path)

    out = tmp_path / "out"

    # Each take paints the page a colour of its own. That is what makes the last
    # assertion in this test *able to fail*: the film is decoded and its colour read,
    # so "the chosen take was used" is a measurement of the delivered bytes rather
    # than a re-reading of the record that chose them. An assertion that reads the
    # same field twice agrees with itself no matter what the render did.
    #
    # A first attempt used `#333333` for take 1 and `#777777` for take 2, which differ
    # by 68/255 = 0.27 in every channel — and a *dissolve* between them lands exactly
    # at the mean, so the midpoint frame read `#555555` and matched take 1 by a
    # round-tripped hair. These four are ≥ 0.75 apart in red and 0.5 apart in green,
    # and no blend of two is nearer a third than the frames themselves are.
    takes = ((1, "#000000", "#000000"), (2, "#ff0000", "#00ff00"),
             (3, "#0000ff", "#ffff00"))

    async def go():
        import json as _json

        async def call(client, name, args):
            # `out` is passed on every call rather than relied on from `session_open`,
            # because that is the contract: a server may serve several projects, and
            # the session id does not name one. The tools that take it are the ones
            # that have to find the record.
            answered = await client.call_tool(name, {"out": str(out), **args})
            assert not answered.isError, (name, answered.content)
            return _json.loads(answered.content[0].text)

        server = m.build_server()
        async with create_connected_server_and_client_session(server) as client:
            opened = await call(client, "session_open",
                                {"spec": str(spec_path), "title": "exit proof"})
            sid = opened["id"]
            assert opened["open"] is True and opened["title"] == "exit proof", opened
            assert Path(opened["record_dir"]) == out / ".vidkit" / "sessions", opened

            # Three photographs of the same moment, taken the way an agent takes
            # them: it acts, then shoots, then acts again. The page has to *change*
            # between takes, because the studio refuses to promote a take that is
            # byte-identical to the one already in use — a retry that changed nothing
            # is not a retry. Take 1 doubles as the capture's own frame, so a build
            # that selected nothing would still have a film.
            await call(client, "browser_open",
                       {"session": sid,
                        "url": "data:text/html,<h1 id=t>hello studio</h1>"})
            await call(client, "browser_act",
                       {"session": sid,
                        "actions": [{"type": "wait_for", "selector": "#t"}]})
            for take, back, fore in takes:
                # The page has to *change* between takes, because the studio refuses to
                # promote a take byte-identical to the one already in use — a retry that
                # changed nothing is not a retry.
                await call(client, "browser_act",
                           {"session": sid,
                            "actions": [{"type": "eval", "script":
                                         f"document.body.style.background = {back!r};"
                                         f"document.getElementById('t').style.color ="
                                         f" {fore!r}"}]})
                shot = await call(client, "browser_shot",
                                  {"session": sid, "name": "login", "take": take})
                assert shot["take"] == take and shot["promoted"] is False, shot
            await call(client, "browser_close", {"session": sid})

            listed = await call(client, "take_list",
                                {"session": sid, "capture": "login"})
            assert [t["take"] for t in listed["takes"]] == [1, 2, 3], listed
            assert all(t["selected"] is False for t in listed["takes"]), listed

            best = await call(client, "take_select",
                              {"session": sid, "capture": "login", "take": 2})
            assert best["ok"] is True, best

            status = await call(client, "session_status", {"session": sid})
            assert status["selections"] == ["login/2"], status["selections"]

            built = await call(client, "session_build", {"session": sid})
            assert built["ok"] is True, built

            report = await call(client, "session_report", {"session": sid})
            assert report["ok"] is True, report
            assert report["report"]["checks"], "a report with no checks proves nothing"
            film = Path(report["report"]["facts"]["output"])
            assert film.exists(), film

            await call(client, "session_close", {"session": sid})
            return report["report"], film

    report, film = arun(go)
    assert report["ok"] is True, [c for c in report["checks"] if not c["ok"]]

    # The claim this test exists to make: what was *delivered* is the take that was
    # chosen. Take 1 painted the page black and take 2 painted it red, so only a render
    # that actually used the promoted bytes can produce this frame. Before the build
    # was taught to honour a selection, it re-shot the page here, and the film came out
    # black while the record still said `login/2` — this test could not have failed.
    from vidkit.ffmpeg import Ffmpeg

    ff = Ffmpeg()
    scratch = out / "exit-proof.raw"
    rgb = ff.frame_rgb(film, ff.duration(film) * 0.5, scratch)
    scratch.unlink(missing_ok=True)
    assert rgb, "no frame could be read out of the film"
    pixels = [rgb[i:i + 3] for i in range(0, len(rgb), 3)]
    mean = tuple(round(sum(p[c] for p in pixels) / len(pixels)) for c in range(3))
    assert mean[0] >= 200 and mean[1] <= 60 and mean[2] <= 60, (
        f"the middle frame of the film averages {mean} — that is take 1's black page, "
        f"not the red one the sitting selected and promoted")


# --------------------------------------------------------------------------- #
# the registry, over the wire
# --------------------------------------------------------------------------- #
@needs_playwright
@needs_mcp
def test_a_second_tool_call_finds_the_page_the_first_one_opened(tmp_path):
    """The registry has to be reachable *through a tool*, or a sitting is one call long.

    This is the second half of the affinity problem. One thread per session is only
    useful if the next tool call finds the session that owns it — and after a call has
    returned, the only thing the client still holds is an id. Re-reading the record from
    JSON would build a `Session` with an empty `_live`, so `browser_status` would report
    no browser while a real Chromium sat open, and `browser_shot` would have nothing to
    photograph. Both facts are asserted here, because either one alone can pass by luck.
    """
    from mcp.shared.memory import create_connected_server_and_client_session
    from vidkit import mcp_server as m

    spec_path = _spec(tmp_path, extra="""
        captures:
          - name: login
            url: "data:text/html,<h1 id=t>held</h1>"
            actions:
              - {type: wait_for, selector: "#t"}
        scenes:
          - n: 1
            title: Hello
            script: "**Hello held session.**"
            shots:
              - {solid: "#16232B"}
    """)
    m.set_project(tmp_path)
    out = tmp_path / "out"

    async def go():
        async def attempt(client, name, args):
            """The refusal door. A tool that refuses answers with `isError` and the
            reason as text; a test that only ever asserted the happy path could not
            tell a working guard from a tool that silently did nothing."""
            answered = await client.call_tool(name, {"out": str(out), **args})
            return answered

        async def call(client, name, args):
            answered = await attempt(client, name, args)
            assert not answered.isError, (name, answered.content)
            return json.loads(answered.content[0].text)

        async with create_connected_server_and_client_session(m.build_server()) as client:
            opened = await call(client, "session_open",
                                {"spec": str(spec_path), "session_id": "wire"})
            sid = opened["id"]

            # opened on the first call, held after it returns. The url is passed
            # rather than read from the spec's `capture:` — this is the manual door,
            # and `session_capture` is the door that reads the spec.
            url = "data:text/html,<h1 id=t>held</h1>"
            await call(client, "browser_open", {"session": sid, "url": url})

            # a *separate* call, with nothing but the id: it must see the same page
            seen = await call(client, "browser_status", {"session": sid})
            assert seen["open"] is True, seen
            assert seen["url"].startswith("data:text/html"), seen

            shot = await call(client, "browser_shot",
                              {"session": sid, "name": "held", "take": 1})
            assert shot["bytes"] > 0, shot

            # The guard can only fire if the session is genuinely held: a session
            # re-read from its record has an empty `_live`, so asking for a second
            # browser would sail past the check and open one it could never close.
            twice = await attempt(client, "browser_open", {"session": sid, "url": url})
            assert twice.isError, twice
            assert "already has a browser open" in twice.content[0].text, twice.content

            closed = await call(client, "session_close", {"session": sid})
            assert closed["closed"] is True, closed

            # after a close the id must be gone from this process, not merely shut
            after = await call(client, "browser_status", {"session": sid})
            assert after["open"] is False, after
        return True

    assert arun(go) is True


# --------------------------------------------------------------------------- #
# the thread that makes Playwright possible at all
# --------------------------------------------------------------------------- #
# The problem this section exists for: FastMCP awaits a *synchronous* tool
# directly on the event loop, so a sync tool that drives Playwright gets
# `Sync API inside the asyncio loop`, and a sync tool that shells out to ffmpeg
# stops the whole server for the duration. A tool cannot escape the loop by
# itself — by the time its body runs the loop is already blocked. So the
# registered functions are `async` and hand their blocking half to a thread.
#
# That thread has to be *the same* thread every time, because Playwright binds
# its objects to the thread that created them. Affinity is not about the loop;
# it is about the thread. Hence one `Worker` per session, and a registry that
# keeps the session — and therefore its worker and its page — alive across calls.
def test_offload_runs_off_the_event_loop_and_returns_the_value():
    import asyncio
    import threading

    from vidkit import _loop

    async def go():
        here = threading.get_ident()
        there = await _loop.offload(threading.get_ident)
        return here, there, await _loop.offload(lambda a, b: a + b, 2, 3)

    here, there, summed = asyncio.run(go())
    assert there != here, "the work must not run on the loop thread"
    assert summed == 5


def test_offload_propagates_the_exception_rather_than_a_future():
    import asyncio

    from vidkit import _loop

    def boom():
        raise SpecError("the shot does not exist")

    async def go():
        await _loop.offload(boom)

    with pytest.raises(SpecError, match="does not exist"):
        asyncio.run(go())


def test_a_worker_serves_every_job_on_one_thread():
    """Playwright affinity is thread affinity, so this is a correctness property."""
    import threading

    from vidkit import _loop

    w = _loop.Worker("t-one-thread")
    try:
        ids = {w.submit(threading.get_ident).result() for _ in range(5)}
        assert len(ids) == 1, "one worker must mean one thread"
        assert threading.get_ident() not in ids
        assert w.alive is True
    finally:
        assert w.stop() is True


def test_stopping_a_worker_twice_is_harmless():
    """The second `stop()` returns `False` — "there was nothing left to stop" — and
    must not raise. A `Session.close` runs on a path that can be walked twice."""
    from vidkit import _loop

    w = _loop.Worker("t-twice")
    w.submit(int)
    assert w.stop() is True
    assert w.stop() is False, "the second stop has nothing to stop, and says so"
    assert w.alive is False


def test_a_worker_can_stop_itself_without_deadlocking():
    """A session closing itself must not wait for the thread it is running on.

    Joining from the worker is the thread waiting for its own death, so `stop()`
    returns as soon as the sentinel is queued instead. The thread then finishes the
    job it is in and exits on the next turn of its loop.
    """
    from vidkit import _loop

    w = _loop.Worker("t-self")
    assert w.submit(w.stop).result() is True, "a self-stop must not deadlock"
    assert w.stop() is False, "the thread the self-stop asked to leave is already gone"
    assert w.alive is False


def test_session_routes_through_the_worker_when_there_is_one():
    """`session()` is the sync door onto a worker's thread."""
    import threading

    from vidkit import _loop

    class Holder:
        worker = None

    bare = Holder()
    assert _loop.session(bare, threading.get_ident) == threading.get_ident()

    w = _loop.Worker("t-route")
    routed = Holder()
    routed.worker = w
    try:
        assert _loop.session(routed, threading.get_ident) == w.submit(
            threading.get_ident).result()
        assert _loop.session(routed, threading.get_ident) != threading.get_ident()
    finally:
        w.stop()


def test_a_worker_propagates_a_jobs_exception_to_its_caller():
    """A refusal raised on the worker must reach the caller unchanged, not vanish."""
    from vidkit import _loop

    def boom():
        raise SpecError("nope — this shot has no source")

    w = _loop.Worker("t-raise")
    try:
        with pytest.raises(SpecError, match="no source"):
            w.submit(boom).result()
        assert w.alive is True, "one failed job must not kill the session's thread"
        assert w.submit(lambda: "still here").result() == "still here"
    finally:
        w.stop()


# --------------------------------------------------------------------------- #
# the process-level live-session registry
# --------------------------------------------------------------------------- #
# Without this, every tool call re-reads the session from JSON and `_live` is
# empty every time — so `browser_open`'s "already has a browser" guard could
# never fire, and a page opened by one call would be invisible to the next.
# A sitting is a *running thing*; the record on disk cannot hold it.
def test_an_open_session_is_held_by_this_process(tmp_path):
    from vidkit import _loop, studio

    sess = st.open_session(tmp_path, session_id="held")
    try:
        assert st.held("held", tmp_path) is sess
        assert isinstance(sess.worker, _loop.Worker)
        assert sess.worker.name == "vidkit-held"
    finally:
        st.close_session(sess)


def test_a_held_session_is_found_by_id_alone(tmp_path):
    """A client that kept only the id must still reach the live page."""
    sess = st.open_session(tmp_path, session_id="byid")
    try:
        assert "byid" in st.live_ids()
        assert st.held("byid") is sess
    finally:
        st.close_session(sess)


def test_one_id_in_two_projects_is_two_sittings(tmp_path):
    """The key prefixes the output directory, because an id does not name a project."""
    a, b = tmp_path / "a", tmp_path / "b"
    sa = st.open_session(a, session_id="dup")
    sb = st.open_session(b, session_id="dup")
    try:
        assert sa is not sb
        assert st.held("dup", a) is sa
        assert st.held("dup", b) is sb
        assert st.held("dup", tmp_path / "nowhere") is None
    finally:
        st.close_session(sa)
        st.close_session(sb)


def test_closing_a_session_evicts_it_and_stops_its_thread(tmp_path):
    sess = st.open_session(tmp_path, session_id="gone")
    worker = sess.worker
    st.close_session(sess)
    assert st.held("gone", tmp_path) is None
    assert worker.alive is False
    assert "gone" not in st.live_ids()


def test_forgetting_a_session_is_idempotent(tmp_path):
    sess = st.open_session(tmp_path, session_id="forgetme")
    st.forget(sess)
    st.forget(sess)
    st.forget(st.Registry(tmp_path).load("forgetme"))
    assert st.held("forgetme", tmp_path) is None
