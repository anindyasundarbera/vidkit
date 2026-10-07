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
import sys
from importlib.metadata import PackageNotFoundError, metadata
from pathlib import Path

import pytest

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


# --------------------------------------------------------------------------- #
# no syntax the oldest supported interpreter cannot read
# --------------------------------------------------------------------------- #
_QUOTES = ('"""', "'''", '"', "'")


def _fstring_quote(text: str) -> str | None:
    """The quote character delimiting an f-string prefix such as ``f'`` or ``f\"\"\"``."""
    s = text
    if s[:1] in ("f", "F"):
        s = s[1:]
        if s[:1] in ("r", "R"):
            s = s[1:]
    for q in _QUOTES:
        if s.startswith(q):
            return q
    return None


def _pre_312_fstrings(source: str) -> list[tuple[int, str]]:
    """f-strings that Python < 3.12 rejects, as ``(line, snippet)`` pairs.

    The rule, established by compiling cases under 3.11 and 3.14 rather than
    guessed: **inside an f-string delimited by quote ``Q``, an unescaped ``Q`` may
    not appear — not in a replacement field's expression, and not as the delimiter
    of a string literal nested in that field.** It is narrower than "no nested
    f-strings": ``f"{f' at {x!r}' if x else ''}"`` is fine (different quotes),
    while ``f"{f"{x}"}"`` and ``f'{d['k']}'`` are not.

    It must be done per *field*, not per node. An earlier per-node AST attempt
    returned confident false zeros: for an implicitly concatenated f-string the
    ``JoinedStr``'s source segment spans several lines and the offending literal is
    a *sibling* node, never a child, so walking children can never see it.
    """
    import io
    import tokenize

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []  # already reported by the parse check above

    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr):
            continue
        segment = ast.get_source_segment(source, node)
        outer = _fstring_quote(segment) if segment else None
        if outer is None:
            continue
        for field in node.values:
            if not isinstance(field, ast.FormattedValue):
                continue
            field_src = ast.get_source_segment(source, field)
            if not field_src:
                continue
            try:
                tokens = tokenize.generate_tokens(io.StringIO(field_src).readline)
                for tok in tokens:
                    if tok.type in (tokenize.STRING, getattr(tokenize, "FSTRING_START", -1)):
                        if _fstring_quote(tok.string) == outer:
                            out.append((node.lineno, (segment or "").strip()[:80]))
                            break
                else:
                    continue
                break
            except (tokenize.TokenError, IndentationError):
                continue
    return out


def test_the_pre_312_fstring_scan_can_actually_fail():
    """A check that cannot fail is worse than no check — so the scan is canaried.

    This is the exact shape of the defect that shipped, and it is asserted to be
    flagged. Without this test, a scan that had quietly stopped working would look
    identical to a clean repo.
    """
    offending = 'value = f"open{f\' at {d.get(\'url\')!r}\'}"\n'
    assert _pre_312_fstrings(offending), "the canary must be flagged"

    # ...and the near-misses that are legal must stay legal, or the check will be
    # silenced the first time it cries wolf.
    assert not _pre_312_fstrings('value = f"open{f\' at {x!r}\'}"\n')
    assert not _pre_312_fstrings('value = f"{d[\'k\']}"\n')


def test_requires_python_matches_the_ci_matrix():
    """The repo promises an interpreter range; CI must actually exercise it.

    The PEP 701 defect was only reachable because a 3.10 job exists. If that job
    is ever dropped while ``requires-python`` still says ``>=3.10``, the promise
    becomes untested and the same syntax can return with nothing to catch it.
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
def test_every_module_parses_as_the_oldest_supported_python(path: Path):
    """No module may use syntax the oldest supported interpreter rejects.

    Two checks, because neither alone is sufficient — which was measured, not
    assumed. ``py_compile`` run by an interpreter *older* than 3.12 catches the
    tokenizer error exactly, but this host has no 3.10, and on 3.12+ the compiler
    accepts the syntax outright. ``ast.parse(feature_version=...)`` catches syntax
    *features* (match, PEP 695 type parameters) on any interpreter, but f-strings
    are lexed rather than parsed, so it sails straight past the quoting rule.

    So: the oldest interpreter available below 3.12 compiles the file when there
    is one, and the tokenizer scan runs unconditionally. Together they close the
    hole that let the original defect reach CI from a machine with none of the
    CI interpreters installed.
    """
    import shutil
    import subprocess

    for candidate in ("python3.10", "python3.11"):
        exe = shutil.which(candidate)
        if exe:
            proc = subprocess.run([exe, "-m", "py_compile", str(path)],
                                  capture_output=True, text=True)
            assert proc.returncode == 0, f"{candidate}: {proc.stderr.strip()}"
            break

    source = path.read_text(encoding="utf-8")
    try:
        ast.parse(source, filename=str(path), feature_version=(3, 10))
    except SyntaxError as exc:  # pragma: no cover - only on a regression
        raise AssertionError(f"{path.name} does not parse as Python 3.10: {exc}") from exc

    offenders = _pre_312_fstrings(source)
    assert not offenders, (
        f"{path.name} has an f-string Python < 3.12 rejects (a nested string literal "
        f"reuses the outer f-string's own quote character): "
        + "; ".join(f"line {n}: {seg}" for n, seg in offenders))
