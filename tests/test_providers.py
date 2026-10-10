"""Unit tests for the provider, secret and snapshot contracts (M2 / R-B3…R-B5).

Pure Python and no external tools, like the rest of the suite: a provider here is
a two-line module written into ``tmp_path``, and nothing is rendered.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from conftest import arun

from vidkit import provider as _provider
from vidkit.context import Context
from vidkit.errors import SpecError, ToolError, VidkitError
from vidkit.secrets import REDACTED, Secrets
from vidkit.snapshot import (
    SNAPSHOT_FILE,
    Snapshot,
    describe_difference,
    digest_text,
    file_digest,
    fingerprint,
    load_datasets,
    request_key,
    verify_fresh,
)
from vidkit.spec import load_spec
from vidkit.timeframe import from_relative


# --------------------------------------------------------------------------- #
# Building a minimal spec + provider on disk
# --------------------------------------------------------------------------- #
def _write_provider(tmp_path: Path, body: str, name: str = "acme") -> Path:
    (tmp_path / f"{name}.py").write_text(body, encoding="utf-8")
    return tmp_path / f"{name}.py"


def _spec(tmp_path: Path, *, provider=None, narration: str | None = None,
          extra: dict | None = None) -> Path:
    (tmp_path / "s.svg").write_text("<svg/>", encoding="utf-8")
    spec: dict = {
        "project": {"title": "T", "slug": "t", "output": "t.mp4",
                    "min_seconds": 1, "max_seconds": 100},
        "narration": {"source": "narration.md"},
        "scenes": [{"n": 0, "title": "s", "shots": [{"still": "s.svg"}]}],
    }
    (tmp_path / "narration.md").write_text(
        narration if narration is not None else "**hello there.**", encoding="utf-8")
    if provider is not None:
        spec["provider"] = provider
    if extra:
        spec.update(extra)
    (tmp_path / "video.json").write_text(json.dumps(spec), encoding="utf-8")
    return tmp_path / "video.json"


def _ctx(spec, data_dir: Path | None = None) -> Context:
    return Context(spec=spec, root=spec.root,
                   out_dir=(data_dir or (spec.root / "_out")))


def _module(path: Path):
    module, _ = _provider.load_provider(path.stem, path.parent)
    return module


# --------------------------------------------------------------------------- #
# The provider block
# --------------------------------------------------------------------------- #
def test_a_bare_provider_name_is_accepted(tmp_path):
    spec = load_spec(_spec(tmp_path, provider="acme"))
    assert spec.provider is not None
    assert spec.provider.module == "acme"
    assert spec.provider_name == "acme"
    assert spec.provider.secrets == {}
    assert spec.provider.write_back is False


def test_the_long_provider_spelling_declares_secrets(tmp_path):
    spec = load_spec(_spec(tmp_path, provider={
        "module": "acme",
        "secrets": {"ACME_TOKEN": True},
    }))
    assert spec.provider.module == "acme"
    assert spec.provider.secrets == {"ACME_TOKEN": True}


def test_an_empty_provider_block_means_no_provider(tmp_path):
    spec = load_spec(_spec(tmp_path, provider={}))
    assert spec.provider is None
    assert spec.provider_name is None


def test_a_secret_entry_without_a_module_is_refused(tmp_path):
    with pytest.raises(SpecError) as exc:
        load_spec(_spec(tmp_path, provider={"secrets": ["ACME_TOKEN"]}))
    assert "needs a `module`" in str(exc.value)


def test_a_short_provider_spelling_is_accepted():
    from vidkit.spec import _provider_spec
    assert _provider_spec("acme").module == "acme"
    assert _provider_spec("acme").secrets == {}
    assert _provider_spec("  ") is None
    assert _provider_spec(None) is None


def test_write_back_true_is_refused_at_load(tmp_path):
    with pytest.raises(SpecError) as exc:
        load_spec(_spec(tmp_path, provider={"module": "acme", "write_back": True}))
    assert "read-only" in str(exc.value)


def test_a_provider_block_rejects_an_unknown_key(tmp_path):
    with pytest.raises(SpecError):
        load_spec(_spec(tmp_path, provider={"module": "acme", "wat": 1}))


# --------------------------------------------------------------------------- #
# Secrets
# --------------------------------------------------------------------------- #
def test_a_secret_is_declared_then_resolved_from_the_environment():
    s = Secrets()
    s.declare("ACME_TOKEN")
    assert s.missing_required() and s.missing_required()[0].name == "ACME_TOKEN"
    s.resolve({"ACME_TOKEN": "hunter2"})
    assert s["ACME_TOKEN"] == "hunter2"
    assert not s.missing_required()


def test_an_empty_string_counts_as_unset():
    s = Secrets()
    s.declare("ACME_TOKEN")
    s.resolve({"ACME_TOKEN": ""})
    assert not s.has("ACME_TOKEN")
    assert s.missing_required()


def test_declaring_twice_keeps_the_strictest_requirement():
    s = Secrets()
    s.declare("ACME_TOKEN", required=False, why="optional nicety")
    s.declare("ACME_TOKEN", required=True, why="the docs endpoint rejects anonymous")
    assert len(s.needs) == 1
    assert s.needs["ACME_TOKEN"].required is True
    assert s.needs["ACME_TOKEN"].why == "optional nicety"


def test_reading_an_unresolved_secret_names_the_variable():
    s = Secrets()
    with pytest.raises(SpecError) as exc:
        s["ACME_TOKEN"]
    assert "ACME_TOKEN" in str(exc.value)


def test_redact_masks_the_longest_value_first():
    s = Secrets()
    s.declare(["A", "B"])
    s.resolve({"A": "tok", "B": "token-longer"})
    text = s.redact("using token-longer and tok and token")
    assert "token-longer" not in text
    assert not text.startswith("using tok")
    assert REDACTED in text


def test_redact_leaves_text_alone_when_nothing_is_resolved():
    s = Secrets()
    s.declare("ACME_TOKEN")
    assert s.redact("no secrets here") == "no secrets here"


def test_describe_shows_a_length_but_never_a_value():
    s = Secrets()
    s.declare("ACME_TOKEN")
    s.resolve({"ACME_TOKEN": "hunter2"})
    lines = s.describe()
    assert len(lines) == 1
    assert lines[0].startswith("ACME_TOKEN")
    assert "hunter2" not in lines[0]


def test_a_provider_reaches_a_secret_through_the_context(tmp_path):
    ctx = _ctx(load_spec(_spec(tmp_path)))
    ctx.secrets.declare("ACME_TOKEN", required=False)
    ctx.secrets.resolve({"ACME_TOKEN": "x"})
    assert ctx.require_secret("ACME_TOKEN") == "x"
    with pytest.raises(SpecError) as exc:
        ctx.require_secret("NOT_DECLARED")
    assert "NOT_DECLARED" in str(exc.value)


def test_the_context_never_raises_for_an_undeclared_name(tmp_path):
    ctx = _ctx(load_spec(_spec(tmp_path)))
    ctx.secrets.declare("ACME_TOKEN", required=False)
    ctx.secrets.resolve({"ACME_TOKEN": "x"})
    assert ctx.secret("ACME_TOKEN") == "x"
    assert ctx.secret("SOMETHING_ELSE") is None
    assert ctx.secret("SOMETHING_ELSE", "fallback") == "fallback"


# --------------------------------------------------------------------------- #
# Snapshots
# --------------------------------------------------------------------------- #
def test_the_request_key_narrows_to_provider_and_window(tmp_path):
    prov = _write_provider(tmp_path, "def datasets(ctx):\n    return {}\n")
    key = request_key(provider="acme", provider_path=prov,
                      timeframe=from_relative(30, date(2026, 10, 6)))
    assert key["provider"] == "acme"
    assert key["provider_sha256"] == file_digest(prov)
    assert key["timeframe"]["days"] == 30


def test_the_request_key_is_blind_to_a_chart_title(tmp_path):
    """A cosmetic edit must not force a refetch."""
    prov = _write_provider(tmp_path, "def datasets(ctx):\n    return {}\n")
    a = request_key(provider="acme", provider_path=prov, timeframe=None)
    b = request_key(provider="acme", provider_path=prov, timeframe=None)
    assert fingerprint(a) == fingerprint(b)


def test_a_snapshot_round_trips(tmp_path):
    snap = Snapshot(path=tmp_path / SNAPSHOT_FILE,
                    request={"provider": "acme", "provider_sha256": "abc", "timeframe": None},
                    datasets={"d": digest_text("[1]")},
                    degraded={})
    snap.write()
    back = Snapshot.read(tmp_path)
    assert back.request == snap.request
    assert back.datasets == snap.datasets


def test_a_corrupt_snapshot_reads_as_absent(tmp_path):
    (tmp_path / SNAPSHOT_FILE).write_text("{not json", encoding="utf-8")
    assert Snapshot.read(tmp_path) is None


def test_verify_fresh_names_what_changed(tmp_path):
    recorded = {"provider": "acme", "provider_sha256": "abc",
                "timeframe": from_relative(30, date(2026, 10, 6)).to_dict()}
    wanted = {"provider": "acme", "provider_sha256": "abc",
              "timeframe": from_relative(60, date(2026, 10, 6)).to_dict()}
    with pytest.raises(SpecError) as exc:
        verify_fresh(Snapshot(path=tmp_path / SNAPSHOT_FILE, request=recorded,
                              datasets={}, degraded={}), wanted, data_dir=tmp_path)
    assert "the window changed" in str(exc.value)
    assert "2026-10-06" in str(exc.value)


def test_verify_fresh_refuses_when_nothing_was_recorded(tmp_path):
    with pytest.raises(SpecError) as exc:
        verify_fresh(None, {"provider": "acme"}, data_dir=tmp_path)
    assert "has not run" in str(exc.value)


def test_verify_fresh_accepts_the_same_request(tmp_path):
    snap = Snapshot(path=tmp_path / SNAPSHOT_FILE, request={"provider": "acme"},
                    datasets={}, degraded={})
    verify_fresh(snap, {"provider": "acme"}, data_dir=tmp_path)


def test_describe_difference_says_the_provider_changed():
    text = describe_difference({"provider": "a"}, {"provider": "b"})
    assert "provider changed (a -> b)" in text


def test_load_datasets_skips_the_snapshot_index(tmp_path):
    (tmp_path / SNAPSHOT_FILE).write_text("{}", encoding="utf-8")
    (tmp_path / "sales.json").write_text("[1, 2]", encoding="utf-8")
    assert load_datasets(tmp_path) == {"sales": [1, 2]}


def test_load_datasets_names_a_dataset_that_is_missing(tmp_path):
    with pytest.raises(SpecError) as exc:
        load_datasets(tmp_path, needed={"sales"})
    assert "sales" in str(exc.value)


def test_load_datasets_ignores_an_unreadable_file(tmp_path):
    (tmp_path / "bad.json").write_text("{oops", encoding="utf-8")
    (tmp_path / "good.json").write_text("1", encoding="utf-8")
    assert load_datasets(tmp_path) == {"good": 1}


# --------------------------------------------------------------------------- #
# Declared degradation
# --------------------------------------------------------------------------- #
def test_degrade_records_a_reason_on_the_spec(tmp_path):
    spec = load_spec(_spec(tmp_path))
    ctx = _ctx(spec, tmp_path / "data")
    ctx.degrade("forecast", "the model endpoint timed out")
    assert spec.degraded == {"forecast": "the model endpoint timed out"}
    assert ctx.facts()["degraded"] == {"forecast": "the model endpoint timed out"}
    assert ctx.degraded == {"forecast": "the model endpoint timed out"}


def test_source_unavailable_names_the_source():
    exc = _provider.SourceUnavailable("the model endpoint", "DNS failure")
    assert "the model endpoint" in str(exc)
    assert "DNS failure" in str(exc)
    assert isinstance(exc, VidkitError)


def test_fallback_without_a_declaration_explains_itself(tmp_path):
    module = _write_provider(tmp_path, "def datasets(ctx):\n    return {}\n")
    spec = load_spec(_spec(tmp_path))
    ctx = _ctx(spec, tmp_path / "data")
    ctx._provider_module = _module(module)
    with pytest.raises(_provider.SourceUnavailable) as exc:
        _provider.fallback(ctx, "forecast", why="the API was down")
    assert "nothing honest to show" in str(exc.value)


def test_fallback_uses_a_declared_fallback_and_marks_the_dataset(tmp_path):
    module = _write_provider(tmp_path, (
        "def fallbacks(ctx):\n"
        "    return {'forecast': [1, 2, 3]}\n"))
    spec = load_spec(_spec(tmp_path))
    ctx = _ctx(spec, tmp_path / "data")
    ctx._provider_module = _module(module)
    value = _provider.fallback(ctx, "forecast", why="the API was down")
    assert value == [1, 2, 3]
    assert spec.degraded == {"forecast": "the API was down"}


def test_fallback_prefers_the_single_dataset_form(tmp_path):
    module = _write_provider(tmp_path, (
        "def fallbacks(ctx):\n"
        "    return {'forecast': 'wrong'}\n"
        "def fallback_for(name, ctx):\n"
        "    return 'right'\n"))
    ctx = _ctx(load_spec(_spec(tmp_path)), tmp_path / "data")
    ctx._provider_module = _module(module)
    assert _provider.fallback(ctx, "forecast", why="down") == "right"


def test_a_provider_that_raises_is_wrapped_and_redacted(tmp_path):
    module = _write_provider(tmp_path, (
        "def datasets(ctx):\n"
        "    raise RuntimeError('sent TOKENVALUE to the server')\n"))
    spec = load_spec(_spec(tmp_path))
    ctx = _ctx(spec, tmp_path / "data")
    ctx.secrets.declare("ACME_TOKEN")
    ctx.secrets.resolve({"ACME_TOKEN": "TOKENVALUE"})
    with pytest.raises(_provider.ProviderError) as exc:
        _provider.collect_datasets(_module(module), ctx)
    assert "TOKENVALUE" not in str(exc.value)
    assert REDACTED in str(exc.value)


def test_source_unavailable_is_not_wrapped_as_a_provider_bug(tmp_path):
    module = _write_provider(tmp_path, (
        "from vidkit.provider import SourceUnavailable\n"
        "def datasets(ctx):\n"
        "    raise SourceUnavailable('the API', '503')\n"))
    ctx = _ctx(load_spec(_spec(tmp_path)), tmp_path / "data")
    with pytest.raises(_provider.SourceUnavailable):
        _provider.collect_datasets(_module(module), ctx)


def test_provider_secrets_are_collected_in_every_accepted_shape():
    class Mod:
        pass

    for raw, want in [("A", {"A": True}), (["A", "B"], {"A": True, "B": True}),
                      ({"A": False}, {"A": False})]:
        m = Mod()
        m.secrets = lambda raw=raw: raw
        assert _provider.collect_secrets(m) == want
    assert _provider.collect_secrets(None) == {}


def test_provider_secrets_rejects_a_number():
    class Mod:
        secrets = staticmethod(lambda: 3)

    with pytest.raises(_provider.ProviderError):
        _provider.collect_secrets(Mod())


def test_a_provider_without_a_datasets_function_yields_nothing(tmp_path):
    class Mod:
        pass

    ctx = _ctx(load_spec(_spec(tmp_path)), tmp_path / "data")
    assert _provider.collect_datasets(Mod(), ctx) == {}


def test_datasets_must_return_a_mapping(tmp_path):
    class Mod:
        datasets = staticmethod(lambda ctx: [1, 2])

    ctx = _ctx(load_spec(_spec(tmp_path)), tmp_path / "data")
    with pytest.raises(_provider.ProviderError):
        _provider.collect_datasets(Mod(), ctx)


# --------------------------------------------------------------------------- #
# The MCP surface must expose the same stage contract (R-B3, M5 groundwork)
# --------------------------------------------------------------------------- #
def test_the_mcp_build_tool_refuses_only_together_with_from():
    from vidkit import mcp_server as m

    # `tool_build` runs off the event loop, so it is a coroutine. Calling it bare
    # leaves a coroutine object behind and `pytest.raises` sees nothing — the test
    # would pass whether or not the refusal existed. Note `arun` does *not*
    # forward keyword arguments to the callable, so the call goes in a lambda.
    with pytest.raises(ToolError):
        arun(lambda: m.tool_build(only=["panels"], from_stage="render"))


def test_the_mcp_build_tool_passes_the_stage_contract_through(monkeypatch, tmp_path):
    from vidkit import assembler
    from vidkit import mcp_server as m

    spec = _spec(tmp_path)
    seen: dict = {}

    def fake_run(spec_path, **kw):
        seen.update(kw, spec_path=spec_path)
        return assembler.Assets()

    monkeypatch.setattr(assembler, "run", fake_run)
    arun(lambda: m.tool_build(str(spec), from_stage="render", refresh=True))

    assert seen["from_stage"] == "render"
    assert seen["refresh"] is True
    assert seen["only"] is None
