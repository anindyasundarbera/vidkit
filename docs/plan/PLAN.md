# PLAN.md — what we are doing

> **This file describes only *now* and *next*.** It is rewritten as work progresses.
> For the phase-wise plan see [FEATURE-ROADMAP.md](FEATURE-ROADMAP.md). For what already
> happened see [HISTORY.md](HISTORY.md). For why, see [DECISIONS.md](DECISIONS.md).
>
> Last updated: **2026-10-08** (front door rewritten).

## Where we are

**M0–M10 are complete and merged to `main`.** The M10 studio session, cross-version MCP
support, and its CI exit proof landed in [PR #13](https://github.com/anindyasundarbera/vidkit/pull/13)
at merge commit [`b23de00`](https://github.com/anindyasundarbera/vidkit/commit/b23de00c973ed6edd6ebd7a287a9d34a1b54f5f8).
The final CI run passed both test-matrix jobs and all six end-to-end probes. The studio probe
passed nine checks and decoded the selected take from the delivered film.

The lean local suite reports **681 passed, 101 skipped**. A later full local run reported
**782 passed in 609.57 s** with every toolchain present. (An earlier full run had one Chromium
screenshot failure that passed in isolation; it has not recurred.) Detailed evidence and M10's
final defect ledger are in [HISTORY.md](HISTORY.md).

## Recently landed

The **front door** was rewritten (PR #15, `ddfac1c`): the README now leads with the problem
it solves rather than the artifact it emits, the GitHub About says the same thing in one
line, and the repository carries ten discoverable topics. Writing it from the code corrected
four false claims the docs would otherwise have repeated (tool names, the `score.src` key, a
`session_browser` tool that does not exist, and the probe count). Recorded in
[HISTORY.md](HISTORY.md).

## Next

There is no unstarted feature phase in the current roadmap. The compositor (picture-in-picture,
masks, and text over live motion) remains unowned; do not begin it without an explicit scope and
exit criterion. The standalone MCP server now supports SDK 1.x and 2.x, with 3.x intentionally
outside the declared `mcp>=1.20,<3` range.

The production-readiness **P0** items are landed (2026-10-10): the version is single-sourced
(`vidkit/_version.py`), every dependency carries an upper bound with dependabot watching the
ranges, the HTTP MCP transport refuses a non-loopback bind without `--expose`, and
`SECURITY.md`/`CONTRIBUTING.md` exist. Recorded in [HISTORY.md](HISTORY.md) and
[DECISIONS.md](DECISIONS.md) D63.

The production-readiness **P1** items are also landed (2026-10-10): a curated `ruff` lint
gate, an advisory `mypy` type gate, a 40% coverage floor, a CodeQL workflow, issue/PR
templates, and a widened Python matrix (3.10–3.14, `requires-python = ">=3.10,<3.15"`).
Recorded in [HISTORY.md](HISTORY.md) and [DECISIONS.md](DECISIONS.md) D65. Two deliberate
follow-ons remain: tightening mypy to *blocking* once the optional-extra stubs are declared,
and (a separate, unowned scope) the compositor.

Release bookkeeping is separate from phase completion and remains owner-owned:

- The `v1.0.0` tag has not been pushed.
- M7–M10 remain in `## [Unreleased]`; the recorded default for their release version is
  `1.2.0`, pending the owner's version decision.
- PyPI publication remains deferred.

Do not publish a release or tag until those visible release choices are settled.
