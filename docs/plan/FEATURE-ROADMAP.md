# FEATURE-ROADMAP.md — vidkit phases

> **What this file is.** The phase-wise feature plan, extending the milestones in the root
> [ROADMAP.md](../../ROADMAP.md) with the owner's *presentation studio* vision.
>
> Root `ROADMAP.md` owns the **requirements** (`R-A1`…`R-H9`) and the **M0–M6** milestones.
> This file owns the **ordering, scope, and exit criteria** for turning vidkit from a
> reliable video engine into a drivable presentation studio. Where the two disagree, this
> file is newer and wins — but the requirement IDs still refer to the root document.
>
> For what is happening now see [PLAN.md](PLAN.md). For what happened see [HISTORY.md](HISTORY.md).

**Last revised:** 2026-10-06 · **Status:** M0 in progress

---

## 0. Where we are and where we are going

**Today** vidkit is a complete, honest, host-free video engine with a usable MCP surface.
It renders a narrated, captioned, verified `.mp4` from a declarative spec, and it refuses to
ship a dishonest cut.

**The owner wants** it to become a **presentation studio**: a standalone MCP server that an
external capable agent can drive to produce software demo videos *and* movies, with
**Playwright**, a **sandboxed terminal**, and **Docker** at its disposal.

**The gap.** Two things stand between here and there, in this order:

1. vidkit cannot be *aimed*. There is no **story** and no **timeframe** — the two inputs the
   north star is defined over. An agent has nothing to hand it.
2. vidkit cannot *show work*. Everything it renders is a static frame or a chart. There is no
   way to record a real terminal session, a real container, or a real multi-step interaction.

Phase **M1** fixes (1). Phases **M7–M9** fix (2). Everything between is making what exists
trustworthy.

---

## 1. Design principles that constrain every phase

These come from the owner's goals and from the invariants in [AGENTS.md](../../AGENTS.md).
A phase that violates one of these is not done, however many checkboxes it ticks.

| Principle | Consequence |
|---|---|
| **P1 — Honest by construction** | Every frame traces to a real capture, a measured dataset, or a declared asset. No mock UI, no invented number, no restaged take. |
| **P2 — The engine never trusts a provider** | Provider output is data, validated and cross-checked, never trusted. A provider is a *source*, not an *authority*. |
| **P3 — MCP-first, never vendored** | Consumers integrate by pointing at a standalone server. No vidkit source inside a consumer repo. |
| **P4 — Sandbox is a capability, not an escape hatch** | Terminal and Docker access must be *declared in the spec*, *bounded by policy*, and *auditable in the verify report*. A studio with unaudited shell access is a liability, not a feature. |
| **P5 — Versatility without dilution** | Movie mode is additive. It must not fork the pipeline or add a second way to do the same thing. |
| **P6 — Cheap to verify, always** | `pytest` stays sub-second for the core. The hello-world fixture stays offline. Any phase that breaks this needs a very good reason. |

---

## 2. Phase map

```
M0  Extract & baseline          ← IN PROGRESS      make it safe to work on
M1  Story & timeframe contract  ← NEXT, P0         make it aimable          ◀ the blocker
M2  Provider & data hardening         P1           make providers trustworthy
M3  Capture v2                        P0           make real UI recordable
M4  Presentation v2                   P0/P1        make output look right
M5  Agent surface                     P0           make it drivable
M6  Hardening & v1.0                  P0/P1        make it shippable
───────────── v1.0 line ─────────────
M7  Executor & sandbox                P0           terminal, files, isolation
M8  Docker & environment lab          P1           real containers on camera
M9  Movie mode                        P1           narrative, not just demo
M10 Studio surface v2                 P1           session-oriented MCP tools
```

Phases **M0–M6** are the root roadmap's, unchanged. Phases **M7–M10** are new and cover the
owner's presentation-studio vision. They are sequenced *after* M6 deliberately — see
[DECISIONS.md](DECISIONS.md) D13.

---

## 3. M0 — Extract & baseline  *(P0)*

**Purpose.** Make it safe to work on. Zero commits exist; nothing is protected.

**Delivers.** `examples/hello-world/` as the offline CI fixture; `LICENSE`; `CHANGELOG.md`;
CI workflow; the first commit.

**Exit.** Fresh clone → `pip install -e ".[dev]"` → `pytest` green →
`vidkit build examples/hello-world/video.yaml` succeeds with only `ffmpeg` + `rsvg-convert`;
the host-term grep is empty.

**Task detail: [PLAN.md](PLAN.md).**

---

## 4. M1 — Story & timeframe contract  *(P0)* — **the blocker**

**Purpose.** Give the agent something to aim. This is the single gap that invalidates the
north star.

**Requirements.** R-A1 (story identity), R-A2 (`init`), R-A3 (timeframe), R-A4 (narration
matches timeframe), R-B2 (timeframe threaded to providers), R-F7 (timeframe verify check).

**Delivers, in dependency order.**

1. **`timeframe` in the spec.** `{days, as_of}` and/or `{start, end}`; resolved to a concrete
   window at load; exposed as `ctx.timeframe`. A single resolved object, not two shapes
   floating around.
2. **Threading.** `ctx.timeframe` reaches `provider.datasets(ctx)`. Hard-coded `?days=28`
   strings become forbidden in the reference example — and CI should catch them.
3. **Story identity.** A validated, named artifact (shape decided by owner → D1). This is what
   `{story, timeframe, out}` in R-G3 refers to.
4. **R-F7 verify check.** Parse the window stated in narration/captions and assert it matches
   the spec timeframe. This is the honesty engine applied to the new field: a video that
   *says* "last 28 days" while the spec says 90 **must fail**.
5. **`vidkit init <dir>`.** Scaffold a runnable story: spec + narration + provider stub, with
   timeframe placeholders. This is what makes R-G4 real.
6. **`vidkit plan` prints the resolved timeframe** so a human or agent can see what it is
   about to build.

**Exit.** Two builds of one story with different timeframes produce different, correctly
labelled videos. A story whose narration window disagrees with its spec **fails `verify`**.

**Risks.** Timeframe is a deceptively large change: it touches `spec.py`, `context.py`,
`provider.py`, `assembler.py`, `verify.py`, and the CLI. Do it as one coherent change, not
five small ones.

---

## 5. M2 — Provider & data hardening  *(P1)*

**Purpose.** Make the provider seam trustworthy enough to hand to an agent.

**Requirements.** R-B3 (dataset snapshots), R-B4 (secret contract), R-B5 (deterministic
fallback), R-B1 (plugin loading — already done).

**Delivers.** Snapshotting guaranteed and documented, so `--only panels,clips,render`
re-renders from disk with no network. A documented env/secret contract with a read-only
guarantee. A fallback pattern for model-dependent scenes that cannot hang a build.

**Exit.** `vidkit build --only panels,clips,render` works from persisted data, offline.

---

## 6. M3 — Capture v2  *(P0)*

**Purpose.** Record real product behaviour, not just real product *screens*.

**Requirements.** R-C3 (downloads), R-C4 (artifact rendering), R-C5 (element waits),
R-C6 (take selection), R-C7 (auth), R-C8 (deterministic rendering).

**Delivers.** A `download` action (click → `expect_download` → save real bytes), a
`content`/`artifact` capture that renders real bytes in a page and shoots them, a
`wait_for` action, optional take-selection, and auth/session support.

**Exit.** A spec can capture a real downloaded file and film it, with no bespoke script.

---

## 7. M4 — Presentation v2  *(P0/P1)*

**Purpose.** Stop the output from looking wrong.

**Requirements.** R-D3 (date-proportional axis), R-D4 (overlays), **R-D5 (aspect-preserving
crop — this is a bug fix)**, R-D1/D2 (panels), R-D6 (transitions).

**Delivers.** `still_to_clip` currently uses a bare `scale=W:H`, which **stretches** a
full-page capture to 16:9. That is a silent quality bug and a truthfulness problem: a
distorted screenshot misrepresents the product. Fix it with `scale`+`crop` (or `pad`).
Then: real-date x-axis, overlay/lower-thirds compositing, more panel kinds.

**Exit.** Full-page captures are never stretched; a time series is spaced by real dates; an
overlay renders.

---

## 8. M5 — Agent surface  *(P0)*

**Purpose.** Make the contract driveable by the external agent, which is the stated purpose.

**Requirements.** R-G1 (MCP), R-G2 (`--json` CLI), R-G3 (job contract), R-G4 (`init`),
R-G5 (progress/cancel), R-G6 (structured errors).

**Delivers.** The `{story, timeframe, out}` job contract returning an artifact manifest;
`--json` on every CLI command; progress and cancellation for long builds; structured,
actionable errors. Note that `mcp_server.py` **already exists** with 10 tools despite the
root roadmap claiming it was never written — M5 is completion, not greenfield.

**Exit.** An MCP client can `init → build → verify` a story purely from tool calls; the same
is possible from a shell with `--json`.

---

## 9. M6 — Hardening & v1.0  *(P0/P1)*

**Purpose.** Ship it.

**Requirements.** R-H5 (docs), R-H6 (portability), R-F8 (provenance), R-H8/H9 (release).

**Delivers.** A provenance manifest (dataset source, spec hash, tool versions, build time),
a portability pass, release tag `v1.0.0`, changelog, optional PyPI.

**Exit.** A fresh clone can produce a verified video for a **new story + timeframe** using
only the docs, via both CLI and MCP.

---

## ─────────── v1.0 line ───────────

Everything below is the owner's presentation-studio vision. It is sequenced after v1.0
because it depends on the story/timeframe contract (M1) and the capture substrate (M3).
Building it earlier means sandboxing a pipeline that cannot yet be aimed, and recording
terminals for demos that cannot yet be specified. See [DECISIONS.md](DECISIONS.md) D13.

---

## 10. M7 — Executor & sandbox  *(P0)*

**Purpose.** Let vidkit record **real work in a real terminal**, safely.

**Why this shape.** The owner's instinct was to give vidkit shell access. The right primitive
is not "shell access" — it is a **declared, bounded, auditable execution environment**. An
`Executor` protocol with pluggable backends keeps the trust boundary explicit, and makes the
sandbox a property of the *spec*, which `verify` can then attest to.

**Delivers.**

| Item | Detail |
|---|---|
| `Executor` protocol | `run(cmd) → {stdout, stderr, exit_code, duration}`; `stream(cmd)` for live output. |
| Backends | `local` (no isolation, dev only), `bubblewrap` (Linux namespaces, no daemon), `docker` (delegates to M8). |
| Spec surface | A scene shot kind `exec:` declaring the command, the backend, which streams to record, and the expected exit code. |
| PTY recording | Record an authentic terminal via a **PTY** and render it as a real terminal — `asciinema` cast → `xterm.js`, or direct frame capture. |
| Policy | Declared working dir, env allow-list, timeout, output caps, and a **hard prohibition on network unless declared**. |
| Audit | Every executed command lands in `verify.json` — command, exit code, duration, truncation. |

**Why PTY + asciinema rather than faking it.** The alternative — animating a synthetic
terminal like OpenMontage's `TerminalScene.tsx` — produces a *plausible* terminal, not a
*real* one. That is exactly the fabrication invariant I7 forbids. A recorded PTY is
authentic evidence, and it is cheaper to build than a convincing fake.

**Exit.** A spec can declare a command, run it in a sandbox, and the finished video shows the
real output, with the command and exit code attested in `verify.json`. A non-zero exit fails
the build unless the spec explicitly expects it.

---

## 11. M8 — Docker & environment lab  *(P1)*

**Purpose.** Film a real environment — a service starting, a dependency installing, a
container's logs — not a description of one.

**Delivers.** A `docker` Executor backend; a spec surface for an environment lifecycle
(`compose up` → run → tear down); capture of container logs and service health as panel
data; deterministic teardown so a failed build never leaks containers; and recording the
environment's real versions into the provenance manifest.

**Exit.** A spec can bring up a declared environment, film real activity inside it, tear it
down unconditionally, and prove the environment's identity in `verify.json`.

**Risks.** This is the phase where a bug can affect the *host*, not just the output.
Containers must never mount the Docker socket into the sandbox, must run unprivileged, and
must have a hard timeout with forced teardown on every exit path.

---

## 12. M9 — Movie mode  *(P1)*

**Purpose.** Make vidkit versatile — able to tell a story, not only demonstrate a product.

**Why it is additive, not a fork.** A movie is a video whose stills come from declared
artwork instead of captures, whose audio includes score and sound, and whose timing is
emotional rather than informational. The spec surface grows; the pipeline does not change.

**Delivers.**

| Item | Detail |
|---|---|
| Richer still kinds | Image sequences, Ken Burns pans, transitions, titles with typography control. |
| Audio beds | Music/ambience under narration, with **ducking** and per-scene gain — mixed, not muxed blindly. |
| Multi-track audio | Narration, score, and effects as separate tracks the spec can address. |
| Shot timing | Explicit durations, beats, or musical alignment, instead of duration-divided-by-weight. |
| Narrative shape | Act/scene beats with continuity metadata for an agent to reason over. |

**Exit.** A spec with no captures and no provider at all renders a scored, captioned short
film with real assets, and `verify` passes on it.

**Constraint (P5).** Movie mode must reuse the same 9 stages. If it needs a tenth stage, the
design is wrong and should be rethought before it is built.

---

## 13. M10 — Studio surface v2  *(P1)*

**Purpose.** Turn the tool surface from *stateless verbs* into a **session-oriented studio**
an agent can hold a conversation with.

**Why.** `vidkit_build` is a one-shot verb. An agent making a five-minute demo wants to open
a session against an environment, poke at it, try several takes, keep the best, and assemble
the result — without re-establishing the environment each call.

**Delivers.**

| Item | Detail |
|---|---|
| Session tools | `session_open/close/list`, `session_exec`, `session_browser`, and state that survives between calls. |
| Take management | `take_record`, `take_list`, `take_select` — pick the best take; never edit output to fake a better one (I7). |
| Environment tools | `env_up/down/status` over the M8 lifecycle. |
| Streaming | Progress events for long builds (finishes R-G5). |
| Resource exposure | Captures, takes, and the verify report as MCP resources, so an agent can read back what it produced. |
| Budget governance | Wall-clock, token, and container budgets declared and enforced — borrowed as a *concept* from OpenMontage. |

**Exit.** An MCP client can open a session against a live environment, attempt a capture
three times, select the best take, assemble a verified video, and read the report back —
all by tool calls, with no shell and no spec editing.

---

## 14. Cross-phase risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| **The repo is destroyed before the first commit** | Low but catastrophic | M0 task 16 is the highest-value single action in this document. Commit early. |
| Docs drift from reality (ROADMAP §3 already did) | High | The evidence rule in [AGENTS.md](../../AGENTS.md) §5.1; PLAN.md is rewritten each phase, HISTORY.md appended. |
| Timeframe leaks back into provider strings | High | R-B2 threading + the R-F7 verify check. |
| Sandbox built before it can be aimed | Medium | M7 is gated behind M1. [DECISIONS.md](DECISIONS.md) D13. |
| Sandbox becomes an unaudited escape hatch | Medium | P4: declared in spec, bounded by policy, attested in `verify.json`. |
| Vendor lock-in to any external tool (incl. OpenMontage) | Medium | P3 + the AGPL boundary in [OPENMONTAGE.md](OPENMONTAGE.md). |
| Movie mode forks the pipeline | Medium | P5: no tenth stage. |
| `default_spec()` silently changes which example is built | Medium | M0 task 12 — pin or assert it. |
| Single-maintainer bus factor | Medium | Docs set + CI + these plan documents. |

---

## 15. Mapping to the root roadmap's requirements

Every requirement in the root `ROADMAP.md` §2 has a home:

| Req | Phase | Req | Phase | Req | Phase |
|---|---|---|---|---|---|
| R-A1 | M1 | R-C8 | M3 | R-F6 | M4 → done |
| R-A2 | M1 | R-D1 | M4 | R-F7 | **M1** |
| R-A3 | **M1** | R-D2 | M4 | R-F8 | M6 |
| R-A4 | M1 | R-D3 | M4 | R-G1 | M5 |
| R-A5 | M0 → done | R-D4 | M4 | R-G2 | M5 |
| R-B1 | done | R-D5 | **M4 (bug)** | R-G3 | M5 |
| R-B2 | **M1** | R-D6 | M9 | R-G4 | M1/M5 |
| R-B3 | M2 | R-D7 | done | R-G5 | M10 |
| R-B4 | M2 | R-E1–E4 | done | R-G6 | M5 |
| R-B5 | M2 | R-E5 | done | R-H1–H5 | M0 |
| R-C1 | done | R-E6 | M6 | R-H6 | M6 |
| R-C2 | done | R-F1–F5 | done | R-H7 | **M0** |
| R-C3–C7 | M3 | R-H8/H9 | M6 | | |
