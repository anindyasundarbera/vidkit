# PLAN.md — what we are doing right now

> **This file describes only *now* and *next*.** It is rewritten as work progresses.
> For the phase-wise plan see [FEATURE-ROADMAP.md](FEATURE-ROADMAP.md). For what already
> happened see [HISTORY.md](HISTORY.md). For why, see [DECISIONS.md](DECISIONS.md).
>
> Last updated: **2026-10-07** (M8 merged; M9 next).

---

## Where we are

One branch, one PR, one merge per phase. **M0–M8 are merged to `main`. Nothing is in
flight.**

| Phase | What it made true | Landed |
|---|---|---|
| **M0** Extract & baseline | A fresh clone installs, tests, and builds `hello-world` with only `ffmpeg` + `rsvg-convert`; no host terms in the engine. | `bbd1e40` |
| **M1** Story & timeframe | vidkit can be *aimed*: a story identity and a resolved window of time, independently checked by `verify`. | `aa3eb5d` |
| **M2** Provider & data hardening | An offline re-render from persisted snapshots is the default, not an option. | `21a96d4` |
| **M3** Capture v2 | Assert-before-shot, action DSL, takes. | `a824e09` |
| **M4** Presentation v2 | 11 panel kinds, overlays, transitions, still fitting. | `4ffff5c` |
| **M5** Agent surface | The job contract: `--json`, `--progress`, `run ACTION`, four MCP tools, a timeout guard. | `7c548de` |
| **M6** Hardening & v1.0 | Provenance as a first-class action; portability; `1.0.0`. | `6987090` |
| **M7** Executor & sandbox | A spec can declare commands that run in a real PTY inside a declared sandbox, and the film is proven to contain the recording. | `40cf724` |
| **M8** Docker & environment lab | A spec can declare a service, **prove** it is serving, film real commands inside the *same* container, and tear it down unconditionally — with the image recorded by digest. | (this merge) |

Full evidence for each is in [HISTORY.md](HISTORY.md); each phase's reasoning is in
[DECISIONS.md](DECISIONS.md) (D1–D48).

### M8 in one paragraph

`docker` became the third `exec` backend, a declared `environment:` list gained a
bring-up → **hold-and-prove** readiness → run → log-capture → teardown lifecycle, and
`verify.json` grew `facts.environments` (image by **digest**, readiness detail, lifetime,
teardown record) plus a `container` key on every `facts.exec` entry.

**The headline is what did *not* change: the stage list.** M8 added a whole backend and a
resource lifecycle against the same ten stages M7 left, with no new `ExecRequest` field and
no widened `stream()` signature. That was M7's abstraction being tested, and it held — which
makes **P5** ("versatility without dilution") a demonstrated constraint rather than an
aspiration for M9 to inherit.

Two things M8 taught, in the form they will be reused:

> **A capability gate must demonstrate the capability, not observe a precondition of it**
> (D41). `which docker` observes a client; `docker run --rm hello-world` demonstrates that
> something can be confined. Docker has *three* rungs — client, daemon, container — and
> collapsing them into one boolean sends three different problems to one unhelpful sentence
> (D48).

> **A readiness gate that samples once is not a gate.** Postgres answers `pg_isready` at
> ~1.30 s against its *bootstrap* server, which is stopped at ~1.45 s; a real query only
> succeeds from ~1.84 s. Readiness therefore means "succeeded **and kept succeeding** for
> 0.75 s", and the report distinguishes *never answered* from *answered and stopped* (D43,
> defect U).

Nine defects were found and fixed on the way (H–L, S, T, U, plus O/P/Q/R); six were in M8's
own new code and three were pre-existing M7 bugs that only a second backend could expose.

---

## The one thing that still needs the owner

> **Push the `v1.0.0` tag.**

The version is `1.0.0` in all three places (`pyproject.toml`, `vidkit/__init__.py`,
`CHANGELOG.md`). Pushing a tag is the point at which the release becomes a claim to the
world rather than a commit on a branch, and it is the owner's to make. Nothing downstream is
blocked by waiting: M9 reads the *code*, not the tag.

A second owner call sits behind it: **M7 and M8 both sit under `## [Unreleased]` in
`CHANGELOG.md`.** Cutting `1.1.0` is a one-line change; folding them back into `1.0.0` would
mean the tag and the release notes disagree, which is the one thing a CHANGELOG exists to
prevent.

PyPI publication stays **deferred** ([FEATURE-ROADMAP.md](FEATURE-ROADMAP.md) §9) — tagging
and publishing are different visible acts and only the first was asked for.

---

## Next: M9 — Movie mode  *(P1)*

Branch **`phase/m9-movie-mode`** off this merge. See
[FEATURE-ROADMAP.md](FEATURE-ROADMAP.md) §12. **Purpose:** make vidkit able to *tell* a
story, not only demonstrate a product.

### What the gap actually is

Three things, separable enough to land one at a time:

1. **Stills do not move, and there are no stills that were never a screenshot.** A movie is
   mostly *declared artwork* — a title card, a photograph, a plate of texture — held, panned,
   dissolved into the next. Today a still is a capture or a file, fitted to the frame; there
   is no pan, no cross-dissolve, no sequence.
2. **Audio is narration or nothing.** `tts.py` produces per-scene WAVs and
   `ffmpeg.mux_captioned` muxes them. There is no score, no ambience, no per-scene gain, and
   nothing that **ducks** music under a spoken line. A film scored by mixing a track at a
   fixed volume is a film where the voice is buried at the chorus.
3. **Shot length is arithmetic.** Duration is divided by weight. There is no way to say
   "hold this for four seconds", "change on the beat", or "let the last frame breathe".

### The shape, before any code

Everything here is an **addition to the spec surface** and, per **P5**, must reuse the ten
stages that already exist — `data, panels, stills, capture, exec, narration, clips, concat,
render, verify`. If a feature appears to need an eleventh, the design is wrong and gets
rethought before it is built. The M8 precedent says this is achievable: a backend *and* a
resource lifecycle fitted inside ten.

In the order they should land — each independently verifiable:

1. **Stills that are composed, not just fitted.** A `still` gains a *motion* (`hold`, `pan`,
   `zoom`, a direction and a span) and a *kind* that is not a screenshot — a title card, a
   solid, a declared image with typography. The frame renderer already produces SVG per
   frame; motion is a transform in that SVG, not a new stage. **The honesty rule does not
   relax:** a movie still is *declared artwork*, and `verify` must be able to say so, exactly
   as it says "live capture" or "drawn from data".
2. **Shot timing expressed, not derived.** An explicit `seconds:` on a scene or a shot wins
   over duration-by-weight; absent, today's behaviour is unchanged. Beats and musical
   alignment are a *later* refinement of the same field and should not be designed now.
3. **A real audio mix.** A second `ffmpeg` path that takes N inputs, applies per-scene gain,
   and ducks the music bus under each narration span using narration's *measured* spans —
   which I5 ("measured audio is the master clock") already computes. This is a change to
   `ffmpeg.py` at the `clips`/`concat` boundary; it is not a stage.

### The risks, named now

- **This is the phase where output gets *artistic*, and artwork is where honesty rots.** A
  Ken Burns pan over a fabricated screenshot is still a fabricated screenshot. Every
  movie-mode feature must state which of the three honest sources it draws from — live
  capture, measured data, declared asset — and `verify` must check it. Adding `motion:` must
  not create a fourth category of "rendered from nothing".
- **The audio mix is where the master clock can break.** I5 says measured audio is the clock.
  Ducking introduces a second audio path, and it is very easy to make the mix authoritative
  over narration's measured spans rather than derived *from* them. The spans come first; the
  mix follows.
- **`verify` must keep getting cheaper to trust, not more expensive.** Three new fact classes
  (motion, timing source, audio mix) means three more chances for a check to be emitted only
  on failure — the defect already fixed twice (E and F). The rule stands: **a check that
  passes must be written down.**
- **No new dependency without a stated reason.** `pyte` was refused in M7; an audio-mix
  library should be refused here too, because `ffmpeg` already does it.

### Exit

> A spec with **no captures and no provider at all** renders a scored, captioned short film
> from declared artwork, with expressed timing, and `verify` passes on it — movie mode is
> provably additive, and the pipeline is still ten stages.

---

## After M9

**M10 — Studio surface v2** (§13): stateless verbs become a session an agent can hold open
and try several takes against — `session_open/close/list`, `session_exec`, take management,
environment tools over M8's lifecycle, and progress streaming.

One branch, one PR, one merge each — as M0–M8 were done.
