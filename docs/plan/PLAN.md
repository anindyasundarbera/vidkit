# PLAN.md — what we are doing

> **This file describes only *now* and *next*.** It is rewritten as work progresses.
> For the phase-wise plan see [FEATURE-ROADMAP.md](FEATURE-ROADMAP.md). For what already
> happened see [HISTORY.md](HISTORY.md). For why, see [DECISIONS.md](DECISIONS.md).
>
> Last updated: **2026-10-10** (M9 merged to `main` (`1894ec9`); M10 next).

---

## Where we are

One branch, one PR, one merge per phase. **M0–M9 are merged to `main` (`1894ec9`).**

| Phase | What it made true | Landed |
|---|---|---|
| **M0** Extract & baseline | A fresh clone installs, tests, and builds `hello-world` with only `ffmpeg` + `rsvg-convert`; no host terms in the engine. | `bbd1e40` |
| **M1** Story & timeframe | vidkit can be *aimed*: a story identity and a resolved window of time, independently checked by `verify`. | `aa3eb5d` |
| **M2** Provider & data hardening | An offline re-render from persisted snapshots is the default, not an option. | `21a96d4` |
| **M3** Capture v2 | Assert-before-shot, action DSL, takes. | `a824e09` |
| **M4** Presentation v2 | 10 panel kinds, overlays, still fitting. | `4ffff5c` |
| **M5** Agent surface | The job contract: `--json`, `--progress`, `run ACTION`, four MCP tools, a timeout guard. | `7c548de` |
| **M6** Hardening & v1.0 | Provenance as a first-class action; portability; `1.0.0`. | `6987090` |
| **M7** Executor & sandbox | A spec can declare commands that run in a real PTY inside a declared sandbox, and the film is proven to contain the recording. | `40cf724` |
| **M8** Docker & environment lab | A spec can declare a service, **prove** it is serving, film real commands inside the *same* container, and tear it down unconditionally — with the image recorded by digest. | `63ad046` |
| **M9** Movie mode | A film with **no capture, no provider and no browser**: a drawn title card, a drawn field, declared artwork that moves, an expressed clock, and a looping score — with `verify` measuring the picture rather than restating the spec. | `1894ec9` |

Full evidence for each is in [HISTORY.md](HISTORY.md); each phase's reasoning is in
[DECISIONS.md](DECISIONS.md) (D1–D52).

### M9 in one paragraph

Four things a film needs and a demo does not: a **camera that moves** (`motion:` on any shot),
**pictures the engine draws** from the shot's own words (`card:` and `solid:` — no artwork the
author did not ship), a **clock that is expressed** (`seconds:` on a scene or a shot; without
it the measured voice stays the master clock, so I5 is intact), and **a score** looped to the
film's real length and ducked under the measured narration spans. One timing rule
(`plan_shots(spec, audio)`) is read by both the renderer and `vidkit plan`.

**The headline is not a feature.** M9's subject is honesty, and its most valuable result is a
defect **class**: three separate checks were found claiming things they had not established,
and one of them could not fail at all — it compared a list against a filter of itself and
reported *"5 of 6 shot(s) move"* because five shots **declared** a move. It was replaced with a
measurement (two real frames per moving clip, differenced, `mae` recorded on every
`facts.motion` row), and the measurement immediately found a defect in the exit proof itself.

Two rules came out of it, and every future check is written under them:

> **A declaration is not a measurement.** A check about what a picture *did* decodes the
> picture. There is no other way to tell a push-in from a still — ffmpeg folds `iw-iw/zoom*p`
> to a constant and renders a perfectly static frame with no error at all. (D49)

> **An absent measurement is not a negative measurement.** A fact carries three states — true,
> false, and *not measured* — and the third must never be spelled as the second. A silent cut
> used to report `duck_seconds: 16.01` of ducking that never happened. (D52)

---

## M10 — Studio surface v2  *(next)*

**Purpose.** Turn the tool surface from *stateless verbs* into a **session-oriented studio** an
agent can hold a conversation with.

**Why this and not something else.** M9 made a single shot able to move, be drawn and be timed.
Nothing yet lets a film be **assembled** from shots that overlap, blend, or come from more than
one take. That is the gap the owner's vision actually names: an external capable agent handed
*(story, timeframe, environment)* that wants to try three takes and keep the best one.

**Delivers.**

| Item | Detail |
|---|---|
| Session tools | `session_open/close/list`, `session_exec`, `session_browser`, with state that survives between calls. |
| Take management | `take_record`, `take_list`, `take_select` — pick the best take; never edit output to fake a better one (I7). |
| Environment tools | `env_up/down/status` over the M8 lifecycle. |
| Streaming | Progress events for long builds (finishes R-G5). |
| Resource exposure | Captures, takes, and the verify report as MCP resources, so an agent can read back what it produced. |
| Budget governance | Wall-clock, token and container budgets declared and enforced — borrowed as a *concept* from OpenMontage. |

**Exit.** An MCP client can open a session against a live environment, attempt a capture three
times, select the best take, assemble a verified video, and read the report back — all by tool
calls, with no shell and no spec editing.

### M10 open questions, for the owner

None of these block the work; each has a default that will be taken if nobody says otherwise.

1. **Transitions (R-D6) are still unbuilt.** M4 listed them, M9 cut between shots without
   blending them. Do they belong in M10 as a per-shot `transition:` field, or with whatever
   needs a compositor? **Default: M10, as a field on the shot** — a session agent assembling
   takes will want to blend them, and a crossfade is a filter, not a compositor.
2. **Multi-track audio beyond narration + score.** One bed, one duck. **Default: not yet** —
   no story has asked for a second bed, and a spec key nothing needs is a key nothing tests.
3. **Act/scene beat metadata** for an agent to reason over. **Default: fold into M10's session
   vocabulary** if it falls out of take management; do not invent it separately.
4. **Should teardown failure become a `Guard` flag, a `verify` check, or both?** Carried over
   from M8. **Default: both** — a `Guard` flag for the refusal at load time and a check for the
   record, since M8 already emits the evidence in `facts.environments[*].teardown`.
5. **`doctor`'s happy path** calls the full `docker_available()` probe (~450–510 ms) rather
   than the cheap `docker_daemon()` (~60 ms) and deferring the container demonstration. Is the
   wall time worth the certainty? **Default: leave it** (D48 records the seam).

### Release bookkeeping, still owed to the owner

- **The `v1.0.0` tag has never been pushed**, and **M7, M8 and M9 all sit under
  `## [Unreleased]`** in [CHANGELOG.md](../../CHANGELOG.md). Folding them back into `1.0.0`
  would make the tag and the release notes disagree.
- **Which version do M7 + M8 + M9 become: `1.1.0` or `1.2.0`?** Three user-visible capability
  milestones landed, which argues for `1.2.0`; none of them broke an existing spec, which
  argues for `1.1.0`. **Default: `1.2.0`** — a minor bump per milestone is the honest reading
  of SemVer for a project with no external consumers yet, and the tag is cheap.
- **PyPI publication remains deferred.**

---

## How to work here

1. Read [AGENTS.md](../../AGENTS.md) — invariants, repo map, gotchas, the commands that must
   keep working. It is the durable contract; this file is the transient one.
2. One phase per branch (`phase/mN-<slug>`), one PR, one merge (`gh pr merge N --merge
   --delete-branch`). Every phase's evidence goes in [HISTORY.md](HISTORY.md) **before** the
   PR is opened, not after it is merged.
3. **Run the two suites before every commit.** They answer different questions:

   ```bash
   python3 -m pytest tests -q                         # full: ~535 s, 610 tests, needs ffmpeg+rsvg
   PATH=/tmp/leanbin python3 -m pytest tests -q      # lean: ~6 s, 531 passed / 79 skipped, no tools
   ```

   The lean run must use exactly that `PATH` — appending `:$PATH` re-exposes the real tools
   and measures nothing. **Never run two pytest processes at once**: they share
   `.pytest-tmp/`.
4. A check that cannot fail is worse than no check, because it reads as assurance. If you add
   one, make it able to fail, and make it fail for a reason a reader would recognise. (D49)
