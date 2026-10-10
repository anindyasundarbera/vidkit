# Contributing to vidkit

Thanks for contributing. vidkit's whole reason for existing is an unusually
strict correctness discipline — "a declaration is not a measurement" — and the
contribution process below exists to protect that. It is short, but it is not
negotiable.

## The contract

Before proposing any change, read [`AGENTS.md`](AGENTS.md). It records the
project's **invariants** (ten of them), the **gotchas** that have already cost
real bugs, and the rules for maintaining the plan documents. A change that
breaks an invariant is a bug no matter how convenient it is. If a design would
break one, say so in the pull request and propose an alternative.

## The two documents that are always true

- [docs/plan/PLAN.md](docs/plan/PLAN.md) — *now* and *next*. Rewritten as work
  progresses, kept short.
- [docs/plan/HISTORY.md](docs/plan/HISTORY.md) — append-only. Every entry carries
  a date and the evidence (the exact command and its output).

Every claim in these documents must be verifiable from the repo. "37 tests
passed" is not evidence; `python3 -m pytest tests -q` and its output is.

## Before you write code

1. Read the invariant table in `AGENTS.md` §2.
2. Make **surgical, complete** changes. Do not refactor unrelated code.
3. If you touched the pipeline, plan to rebuild the hello-world fixture.

## Definition of done

```bash
python3 -m pytest tests -q       # the lean suite — what CI actually runs
```

If you changed the pipeline, also:

```bash
vidkit build examples/hello-world/video.yaml
# must produce an .mp4, a narration.srt, and a verify.json with every check passing
```

Update the spec/panel/CLI docs your change invalidates (see
[docs/modules.yaml](docs/modules.yaml)), and record the work in `HISTORY.md`.

## Test-suite discipline

The six capability markers in `tests/conftest.py` — `needs_render`,
`needs_sandbox`, `needs_docker`, `needs_playwright`, `needs_mcp`,
`needs_pre_312_python` — must stay **independent**. A test that needs a
capability carries the *matching* marker and nothing broader. A marker that asks
"is the toolchain complete?" instead of "is *this* capability usable?" is the
bug the markers exist to prevent.

A test that calls an `async` tool **must await it** (through the stdlib-only
`arun()` helper in `tests/conftest.py`, never `anyio`). A bare call returns a
coroutine and the assertion silently compares against nothing. The suite scans
for this and fails.

## Pull requests

- Open a PR against `main` with a clear description of the problem and the
  evidence it is fixed.
- CI runs the lean suite on Python 3.10 and 3.12 plus six end-to-end probes.
  Green CI is required.
- `tests/test_hygiene.py` and `tests/test_mcp.py` pin structural discipline
  (single-sourced version, import hygiene, await hygiene, registration-closure
  hygiene). Do not bypass them; extend them.

## Commit message

Follow the existing convention — a short imperative subject, often prefixed with
a milestone or area (`M11: …`, `docs: …`, `fix: …`). Describe the *why*, not the
diff.

## Need help?

Open an issue, or reach the maintainer through the address in
[`SECURITY.md`](SECURITY.md) for anything sensitive.
