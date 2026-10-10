"""Structural checks on the test suite itself.

Two defects reached CI that no local run could have caught, and both were of the
same shape: a test module depended on something that is present on a developer's
machine but absent from the job that runs it.

* ``tests/test_mcp.py`` and friends imported ``anyio`` at module level. ``anyio``
  is not a declared dependency of vidkit at all — it arrives as a transitive
  dependency of ``mcp`` — so the lean ``pytest`` job, which installs only
  ``.[dev]``, died at *collection* with ``ModuleNotFoundError`` rather than at an
  assertion. Every run locally was green purely because ``mcp`` happened to be
  installed here.
* ``vidkit/studio.py`` contained a PEP 701 f-string, which Python 3.12 accepts and
  Python 3.10 rejects. The CI matrix runs 3.10, so the module could not be
  imported there at all, while the local 3.14 interpreter compiled it happily.

Neither is a bug in the engine's behaviour; both are bugs in what the suite
*assumes*. They are cheap to pin, and pinning them is the whole point of this
file, so they cannot come back unnoticed.

Note this module itself must import nothing past Python 3.10 — ``tomllib`` would
be exactly the defect it exists to prevent — so package facts are read from
installed distribution metadata rather than from ``pyproject.toml``.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, metadata
from pathlib import Path

import pytest
from conftest import _PEP701_ILLEGAL, _PEP701_LEGAL, _compiles_with

REPO = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# every test import is something the lean job is guaranteed to have
# --------------------------------------------------------------------------- #
#: The packages every ``pytest`` CI job installs by construction. ``.[dev]`` pulls
#: in ``pytest``; ``vidkit`` is the project itself, so its own declared runtime
#: dependencies (``PyYAML``) come with it; ``conftest`` is the suite's own module.
#: Anything outside this set may only be imported inside a *function* body, so a
#: missing package fails one test rather than the whole collection.
BASE = {"pytest", "yaml", "vidkit", "conftest"}


def _package_metadata():
    try:
        return metadata("vidkit")
    except PackageNotFoundError:  # pragma: no cover - a source checkout, uninstalled
        pytest.skip("vidkit is not installed, so its declared metadata is unreadable")


def _extras_of(requirement: str) -> set[str]:
    """The extras a ``Requires-Dist`` line is gated behind, e.g. ``{'dev'}``."""
    out: set[str] = set()
    for clause in requirement.split(";"):
        clause = clause.strip()
        if clause.startswith("extra =="):
            out.add(clause.split("==", 1)[1].strip().strip("\"'"))
    return out


def test_dev_extra_does_not_pull_in_the_mcp_server():
    """The premise the import check rests on, asserted rather than assumed.

    If someone ever adds ``mcp`` to ``dev``, the guard below would keep passing
    for the wrong reason — so the premise is pinned here as well.
    """
    md = _package_metadata()
    dev = [r for r in (md.get_all("Requires-Dist") or []) if "dev" in _extras_of(r)]
    assert dev, "the dev extra declares no dependencies at all"
    assert not any(r.split(">=")[0].split("[")[0].strip() == "mcp" for r in dev), dev


def test_mcp_extra_declares_only_supported_sdk_majors():
    """The optional extra must not claim compatibility with an untested major."""
    md = _package_metadata()
    requirements = [
        r.lower().replace(" ", "")
        for r in (md.get_all("Requires-Dist") or [])
        if r.split(";", 1)[0].strip().lower().startswith("mcp")
        and "mcp" in _extras_of(r)
    ]
    assert len(requirements) == 1, requirements
    assert ">=1.20" in requirements[0], requirements
    assert "<3" in requirements[0], requirements


def test_no_test_module_imports_a_package_the_lean_job_lacks():
    """A missing package must fail one test, never the whole collection.

    ``anyio`` did exactly that, in four modules at once. The rule is simple: a
    top-level import may only name something ``.[dev]`` guarantees. Anything else
    — an optional extra, a transitive dependency, a package that merely happens to
    be installed — must be imported inside the test that needs it, so the failure
    is local and the module stays collectable.
    """
    stdlib = sys.stdlib_module_names
    offenders = []
    for path in sorted((REPO / "tests").glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:  # module level only; a local import is the remedy
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    names = [node.module.split(".")[0]]
            for name in names:
                if name not in stdlib and name not in BASE:
                    offenders.append(f"{path.name}:{node.lineno} imports {name!r}")
    assert not offenders, (
        "a test module imports something the lean `pytest` job does not install, so "
        "the whole module fails to collect instead of one test failing: "
        + "; ".join(offenders))


def test_version_is_single_sourced():
    """``__version__`` lives in exactly one module.

    The distribution reads ``vidkit._version.__version__`` for its metadata, and
    ``vidkit.__version__`` re-exports it. A second literal somewhere in the package
    would drift from the one the distribution actually ships.
    """
    import vidkit
    import vidkit._version as v

    assert vidkit.__version__ == v.__version__

    import ast

    # The only assignment to a ``__version__`` string literal is the source module.
    literal_sites = []
    for py in sorted((REPO / "vidkit").glob("*.py")):
        for node in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Assign)
                    and any(t.id == "__version__" for t in node.targets
                            if isinstance(t, ast.Name))):
                literal_sites.append(str(py))
    assert literal_sites == [str(REPO / "vidkit" / "_version.py")], literal_sites


# --------------------------------------------------------------------------- #
# no syntax the oldest supported interpreter cannot read
# --------------------------------------------------------------------------- #
def _pre_312_interpreter() -> str:
    """An interpreter older than 3.12 that can actually compile, or ``""``.

    A compiler is the only thing that reliably finds the PEP 701 quoting rule: the
    rule lives in the *tokenizer*, so ``ast.parse`` cannot see it at any feature
    version, and 3.12+ accepts the syntax outright. Anything below 3.12 rejects it.

    The probe lives in ``conftest`` because it must not consult ``PATH``: the lean
    CI job narrows ``PATH`` to the tools the engine shells out to, and a lookup that
    trusted it reported "no old interpreter here" on a host that has one — turning
    the guard against PEP 701 into a guard that could not fail.
    """
    from conftest import _find_pre_312_interpreter

    return _find_pre_312_interpreter()


@pytest.mark.needs_pre_312_python
def test_this_repo_can_detect_the_defect_it_was_written_for():
    """The guard against PEP 701 must have a working detector on this machine.

    This is the *load-bearing* test, and it exists because the alternative passed.
    An earlier version of this file shipped a hand-written tokenizer scan, because
    the host has no ``python3.10`` and ``ast.parse(feature_version=(3, 10))`` cannot
    catch the rule. That scan was a check that could not be trusted: run by a 3.10
    interpreter it reported legal f-strings such as ``f"{sc.n:02d}"`` as offenders,
    and run by 3.11 it reported none — insensitive and non-specific at once, which
    is worse than no check, because it fails loudly on correct code and would be
    deleted the first time it cried wolf.

    So the scan is gone and this test takes its place. It asserts two things that
    together mean the guard is real: (a) some interpreter here can detect the defect,
    and (b) ``py_compile`` under it agrees with hand-established ground truth — the
    two illegal shapes fail, the five legal ones pass. Where the host has only
    3.12+, ``needs_pre_312_python`` skips this and the claim is not made at all,
    which is the honest outcome: an unmakeable claim is skipped, never faked.
    """
    exe = _pre_312_interpreter()
    assert exe, (
        "no interpreter below 3.12 on this host, so PEP 701 cannot be detected — see "
        "needs_pre_312_python; without one, do not claim this guard works")

    for src in _PEP701_ILLEGAL:
        assert not _compiles_with(exe, src), f"{exe} should reject: {src!r}"
    for src in _PEP701_LEGAL:
        assert _compiles_with(exe, src), f"{exe} should accept: {src!r}"


def test_requires_python_matches_the_ci_matrix():
    """The repo promises an interpreter range; CI must actually exercise it.

    The PEP 701 defect was only reachable because a 3.10 job exists — and 3.10 is
    the *only* job in the matrix that can detect it, because 3.12 accepts the syntax.
    If that job is ever dropped while ``requires-python`` still says ``>=3.10``, the
    promise becomes untested and the same syntax can return with nothing to catch it.
    """
    requires = _package_metadata()["Requires-Python"]
    assert requires and "3.10" in requires, requires

    import yaml

    workflow = yaml.safe_load((REPO / ".github" / "workflows" / "ci.yml").read_text())
    matrix = workflow["jobs"]["test"]["strategy"]["matrix"]["python-version"]
    versions = [str(v) for v in matrix]
    assert "3.10" in versions, versions


@pytest.mark.parametrize("path", sorted((REPO / "vidkit").glob("*.py")),
                         ids=lambda p: p.name)
def test_every_module_uses_no_syntax_feature_newer_than_310(path: Path):
    """No module may carry a syntax *feature* the oldest supported interpreter lacks.

    ``ast.parse(feature_version=(3, 10))`` catches grammar-level additions — ``match``,
    PEP 695 type parameters — on any interpreter, 3.12+ included, which is why this
    half is not gated on having an old interpreter present. It does **not** catch the
    tokenizer-level rules; that is ``test_every_module_compiles_as_the_oldest_supported_python``
    below, and the two are separate tests precisely so neither can silently cover
    for the other.
    """
    source = path.read_text(encoding="utf-8")
    try:
        ast.parse(source, filename=str(path), feature_version=(3, 10))
    except SyntaxError as exc:  # pragma: no cover - only on a regression
        raise AssertionError(f"{path.name} does not parse as Python 3.10: {exc}") from exc


@pytest.mark.needs_pre_312_python
@pytest.mark.parametrize("path", sorted((REPO / "vidkit").glob("*.py")),
                         ids=lambda p: p.name)
def test_every_module_compiles_as_the_oldest_supported_python(path: Path):
    """No module may carry a tokenizer rule a pre-3.12 interpreter rejects.

    A real subprocess ``py_compile`` under an interpreter below 3.12 catches the
    tokenizer-level rules, of which the PEP 701 f-string quoting change is the one
    that bit us. It has to be a subprocess: this host's ``python3`` is 3.14, and a
    compiler cannot be asked to *un*-know a rule it was built with. Where no such
    interpreter exists the test skips and says so, rather than passing for the wrong
    reason.
    """
    exe = _pre_312_interpreter()
    assert exe, (
        "needs_pre_312_python should have skipped this test, not run it; an empty "
        "interpreter here means the marker and the probe disagree")
    proc = subprocess.run([exe, "-m", "py_compile", str(path)],
                          capture_output=True, text=True)
    assert proc.returncode == 0, (
        f"{path.name} does not compile under {exe}: {proc.stderr.strip()}")
