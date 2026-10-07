# PLAN.md — what we are doing

> **This file describes only *now* and *next*.** It is rewritten as work progresses.
> For the phase-wise plan see [FEATURE-ROADMAP.md](FEATURE-ROADMAP.md). For what already
> happened see [HISTORY.md](HISTORY.md). For why, see [DECISIONS.md](DECISIONS.md).
>
> Last updated: **2026-10-07** (M10 merged).

## Where we are

**M0–M10 are complete and merged to `main`.** The M10 studio session, cross-version MCP
support, and its CI exit proof landed in [PR #13](https://github.com/anindyasundarbera/vidkit/pull/13)
at merge commit [`b23de00`](https://github.com/anindyasundarbera/vidkit/commit/b23de00c973ed6edd6ebd7a287a9d34a1b54f5f8).
The final CI run passed both test-matrix jobs and all six end-to-end probes. The studio probe
passed nine checks and decoded the selected take from the delivered film.

The lean local suite reports **681 passed, 101 skipped**. A local full-suite run reported
**781 passed and one Chromium screenshot failure**; that test passed in isolation. The full
GitHub Actions test matrix passed, so retain both observations rather than calling the local
full suite green. Detailed evidence and M10's final defect ledger are in [HISTORY.md](HISTORY.md).

## Next

There is no unstarted feature phase in the current roadmap. The compositor (picture-in-picture,
masks, and text over live motion) remains unowned; do not begin it without an explicit scope and
exit criterion. The standalone MCP server now supports SDK 1.x and 2.x, with 3.x intentionally
outside the declared `mcp>=1.20,<3` range.

Release bookkeeping is separate from phase completion:

- The `v1.0.0` tag has not been pushed.
- M7–M10 remain in `## [Unreleased]`; the recorded default for their release version is
  `1.2.0`, pending the owner's version decision.
- PyPI publication remains deferred.

Do not publish a release or tag until those visible release choices are settled.
