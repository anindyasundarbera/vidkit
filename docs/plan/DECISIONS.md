# DECISIONS.md — decision log

> **Append-only ADR log.** Never rewrite or delete an entry. If a decision is reversed, add a
> new entry that supersedes the old one and mark the old one `SUPERSEDED BY Dxx`.
>
> Format: **Context → Decision → Alternatives → Consequences.**
>
> For *what* we are doing see [PLAN.md](PLAN.md) and [ROADMAP.md](FEATURE-ROADMAP.md). For *what
> happened* see [HISTORY.md](HISTORY.md).

---

## D1 — Story identity manifest shape

**Status:** DECIDED 2026-10-06 — **option C (both)**, owner's choice.
**Context:** M1 needs a durable, named "story" artifact. Today a story is implied by a
folder of files (`video.yaml` + `narration.md` + `provider.py`) with no declaration.

**Options.**

| Option | Pro | Con |
|---|---|---|
| **A. Folder convention only** | Zero new syntax; nothing to keep in sync. | Implicit. An agent cannot validate it, and renaming a folder breaks identity. |
| **B. Explicit `story.yaml`** | Validatable, self-describing, carries title/timeframe default/owner. | A second file to keep consistent with the spec — a new drift risk. |
| **C. Both** — optional `story.yaml`, convention fallback | Backwards compatible; strict mode when present. | Two code paths — the kind of thing that can rot. |

**Decision:** **C**. A story is a *folder* by convention, and may *additionally* declare
itself with `story.yaml`. Both are supported; an agent that has never seen the repo can still
consume any folder, and one that wants validation gets it when the manifest is present.

**Alternatives rejected:** A alone (nothing for an agent to validate against, and folder
renames silently change identity); B alone (breaks every existing story and every
`examples/` fixture).

**Consequences:** Implemented as *one* code path — `load_spec` synthesises a story identity
from the folder when `story.yaml` is absent, so there is no parallel branch to drift.
`vidkit init` (M1) writes a manifest; a present manifest is validated strictly.

---

## D2 — Spec format stays YAML

**Status:** DECIDED 2026-10-06.
**Context:** A spec is a tree of typed dataclasses. Could be JSON, TOML, or Python.

**Decision:** YAML, permanently.

**Alternatives:** *JSON* — no comments, and narration-adjacent fields get noisy. *TOML* —
flat-friendly, bad at the nested scene/shot lists vidkit uses. *Python DSL* — maximum power,
but a spec becomes code: unvalidatable, unsnapshottable, and a security surface if an agent
writes it.

**Consequences:** specs stay plain data (invariant I8) — diffable, hashable, snapshottable,
and safe for an agent to author. We accept YAML's ambiguities and mitigate them with strict
validation in `_validate()`.

---

## D3 — Timeframe representation

**Status:** DECIDED 2026-10-06 — **option C (both)**, owner's choice.
**Context:** Windows are hard-coded in provider URL strings today. M1 must introduce a real
timeframe.

**Options.**

| Option | Example | Pro | Con |
|---|---|---|---|
| **A. Relative** | `{days: 28, as_of: 2026-10-06}` | Matches how users think ("last month"); providers take it directly. | Not reproducible later without pinning `as_of`; awkward for academic/historical windows. |
| **B. Absolute** | `{start: 2026-09-08, end: 2026-10-06}` | Unambiguous, hashable, reproducible. | "Last 28 days" must be computed by the author. |
| **C. Both**, one resolved | either form → one resolved `{start, end}` | Author convenience + engine determinism. | Slightly more parsing. |

**Decision:** **C**. Both spellings are accepted and resolve to a single `{start, end}`.
`as_of` defaults to the spec's own date and is **recorded in the provenance manifest**, so a
relative spec is still reproducible after the fact. A build never silently means a different
window than it did yesterday.

**Alternatives rejected:** A alone (unreproducible once "today" moves — an honesty hole);
B alone (forces every author and every agent to hand-compute windows).

**Consequences:** `ctx.timeframe` exposes one shape. `verify` (R-F7) checks the window stated
in narration against the resolved window, so a mismatch fails the build.

---

## D4 — Engine stays host-agnostic

**Status:** DECIDED (pre-existing, reaffirmed 2026-10-06).
**Context:** `vidkit/` contained host-specific knowledge about the OneAquaHealth project.

**Decision:** No host term, URL, port, or path may appear in `vidkit/` code. Hosts supply a
folder with a spec, narration, and an optional `provider.py`.

**Alternatives:** A `vidkit-plugins` package exposing host hooks; a config file naming the
host. Both put host knowledge one layer deeper without removing it.

**Consequences:** invariant I1. Enforced by `grep` in CI ([AGENTS.md](../../AGENTS.md) §4).
Two comment-level host references remain and are [PLAN.md](PLAN.md) M0 task 14.

---

## D5 — Story lives in the consumer repo; MCP-only integration

**Status:** DECIDED (pre-existing, reaffirmed 2026-10-06).
**Context:** Where do stories live — inside vidkit, or in the consuming repo?

**Decision:** In the **consumer repo**. vidkit never vendors a consumer's story, and
consumers never vendor vidkit. Integration is by pointing a client at the standalone MCP
server.

**Alternatives:** A monorepo with `vidkit/` + `stories/` — convenient, but it makes vidkit
own content it cannot maintain, and breaks the extraction runbook in root `ROADMAP.md` §5.

**Consequences:** invariant I9. There is **no** in-tree story: `examples/oneaquahealth/` was
removed on 2026-10-06 (Q2 answered — it moves to the OneAquaHealth repo), and `examples/hello-world/`
is a fixture, not a story.

---

## D6 — Assert-before-shot aborts the build

**Status:** DECIDED (pre-existing).
**Context:** A capture can silently grab an error page or a loading spinner.

**Decision:** A capture may declare `assert` actions; if any fails, the **build aborts** — it
does not record the failure and continue.

**Alternatives:** Warn-and-continue (produces a video that lies), or retry-then-continue
(hides flakiness).

**Consequences:** invariant I2. Flaky environments fail loudly, which is the point.

---

## D7 — Document set shape: 6 files, 4 in `docs/plan/`

**Status:** DECIDED 2026-10-06.
**Context:** Conversational findings are lost to context compaction. Durable state must have
a home before work resumes. Root `ROADMAP.md`'s own §3 "current state" table had already gone
stale and misled research — the same failure at a smaller scale.

**Decision:** Five documents under `docs/plan/`, alongside the root `AGENTS.md`:

| File | Mutability | Question it answers |
|---|---|---|
| `AGENTS.md` | stable | *What are the rules?* |
| `docs/plan/PLAN.md` | **rewritten** each phase | *What right now?* |
| `docs/plan/HISTORY.md` | **append-only** | *What already happened?* |
| `docs/plan/FEATURE-ROADMAP.md` | revised per phase | *In what order, and why?* |
| `docs/plan/DECISIONS.md` | **append-only** | *Why this and not that?* |
| `docs/plan/OPENMONTAGE.md` | **frozen**, dated | *What did we find out about X?* |

**Alternatives:** One big `PLAN.md` (the mutability rules conflict — a doc cannot be both
rewritten and append-only); a `docs/adr/` per-decision directory (correct but heavy at this
project's size); GitHub Issues (external, and the repo has no remote yet).

**Consequences:** Each file has one mutability rule, stated in its own header. The plan
module is registered in `docs/modules.yaml` so `vidkit docs` can route to it. The roadmap is
named `FEATURE-ROADMAP.md`, **not** `ROADMAP.md`: `_doc_routes()` maps bare stems first-wins
across modules, so a `docs/plan/ROADMAP.md` would have silently shadowed the root
`ROADMAP.md` that owns the requirement IDs.

---

## D8 — Docs are routed, not scattered

**Status:** DECIDED (pre-existing, extended 2026-10-06).
**Context:** `docs/` has 15 documents across 6 modules and a machine-readable route table.

**Decision:** Every document belongs to a module in `docs/modules.yaml` with a human and an
agent entry point. `docs/plan/` becomes a module.

**Alternatives:** A flat `docs/` (unnavigable at this size), or README-only routing (what the
project already rejected).

**Consequences:** `vidkit docs` and the MCP `vidkit_docs` tool can reach every document
without a filesystem walk. Adding a document means editing the route table — deliberate
friction that keeps the table true.

---

## D9 — Do not integrate OpenMontage

**Status:** DECIDED 2026-10-06.
**Context:** The owner asked whether vidkit can implement or integrate
`calesthio/OpenMontage`.

**Decision:** **No integration. No code reuse. No vendoring.** Concepts only.

**Evidence:** [OPENMONTAGE.md](OPENMONTAGE.md) — no MCP server (0 code hits), no public API,
no entry points, architecture explicitly forbids programmatic orchestration, AGPL-3.0.

**Alternatives considered and rejected.**

| Alternative | Why rejected |
|---|---|
| Import `tools.*` / `lib.*` as a library | No stable interface; and it would relicense vidkit to AGPL-3.0. |
| Shell out to a wrapper script we maintain | We would be maintaining a compatibility shim against a 64k-star repo moving daily — a permanent tax with no payoff. |
| Fork it | AGPL fork + 2,600-path tree to maintain. Absurd for a single maintainer. |
| Drop vidkit and use OpenMontage alone | It does not solve the owner's problem: it produces *plausible* videos, vidkit produces *proven* ones. And it has no sandbox/terminal/Docker capability either. |
| Copy just the skill Markdown | Copyright applies to the Markdown. Ideas are not copyrightable; text is. |

**Consequences:** no OpenMontage phase exists in [ROADMAP.md](FEATURE-ROADMAP.md). Six concepts are
borrowed into phases that already exist (§6 of OPENMONTAGE.md). The AGPL boundary is
documented so a future contributor does not cross it by accident.

---

## D10 — MCP-first is the only integration surface

**Status:** DECIDED (pre-existing, reaffirmed 2026-10-06).
**Context:** An external agent must be able to drive vidkit.

**Decision:** The **standalone MCP server** is the primary surface. The CLI is the secondary
surface and must reach parity (R-G2). No library-import integration is offered or supported.

**Alternatives:** Publish `vidkit` as an importable library — tempting, but it exposes the
internal dataclasses as a public API, and every consumer upgrade becomes a compatibility
problem. A subprocess-the-CLI surface is a subset of MCP and buys nothing.

**Consequences:** invariant I9. M5 completes the MCP surface. Every CLI command needs `--json`
so an agent has a non-MCP path.

---

## D11 — The hello-world fixture is offline, measured, and silent

**Status:** DECIDED 2026-10-06.
**Context:** M0's exit criterion needs a build that runs in CI with no network, no API keys,
and no TTS engine.

**Decision:** `examples/hello-world/` uses `voice.engine: none` and
`guard.require_audio: false`, and its provider **measures the repo** rather than hard-coding
numbers.

**Alternatives:** *A recorded WAV* — binary in git, and it would desync whenever narration
changed. *A hosted TTS in CI* — keys, cost, flakiness. *Hard-coded numbers* — the fixture
would start lying the moment the code changed, which is precisely the failure vidkit exists
to prevent.

**Consequences:** the fixture exercises the pipeline, the panel renderers, captions, and
`verify` — offline, in under a second of test time. Requires the `guard.require_audio` engine
change recorded in [HISTORY.md](HISTORY.md). A silent cut is now a declared PASS rather than
an impossible FAIL, which sharpens invariant I6 instead of weakening it.

---

## D12 — The spec is the control plane; the agent is a driver

**Status:** DECIDED 2026-10-06.
**Context:** OpenMontage's Rule Zero is *"the agent IS the control plane"* — production flow
lives in an agent conversation, guided by skill Markdown.

**Decision:** vidkit inverts this. **The spec is the control plane.** The agent *authors* a
spec and the engine executes it deterministically. The agent does not improvise the pipeline
at render time.

**Alternatives:** Adopt Rule Zero — maximum flexibility, but it destroys reproducibility,
makes `verify` meaningless (there is nothing to verify against), and breaks invariant I8.
A hybrid (agent steers mid-build) — the same objection, plus non-determinism during a build.
For the M10 session model, an agent *may* interact with an environment and *select takes*, but
the **assembly** is still spec-driven.

**Consequences:** this is vidkit's differentiator and the reason it exists alongside
OpenMontage rather than instead of it. Do not erode it for flexibility.

---

## D13 — Sandbox and Docker come after the story/timeframe contract

**Status:** DECIDED 2026-10-06.
**Context:** The owner's headline capability request is Playwright + sandboxed terminal +
Docker. It is tempting to start there.

**Decision:** Sandbox work is [ROADMAP.md](FEATURE-ROADMAP.md) **M7–M8**, sequenced after M1 (story
and timeframe) and after the M6 v1.0 line.

**Alternatives:** Build the sandbox first — it is the most visible capability and the most
fun. Rejected because a sandbox with nothing to aim at produces demos that cannot be
specified: every recording would be an ad-hoc script whose output no spec describes, which
violates invariant I8 and makes `verify` vacuous.

**Consequences:** the capability arrives later than the owner may want it, but it arrives
*declared in a spec* — bounded, reproducible, and attested in `verify.json`. A sandbox bolted
on without the contract would have to be rebuilt once M1 landed.

---

## D14 — Movie mode is additive, not a fork

**Status:** DECIDED 2026-10-06.
**Context:** The owner wants vidkit to "create movies when controlled by an external capable
agent", while remaining a demo-video engine. Two pipelines would be the obvious answer.

**Decision:** Movie mode ([ROADMAP.md](FEATURE-ROADMAP.md) M9) **extends the spec surface only**. It
must reuse the same 9 stages. **If movie mode needs a tenth stage, the design is wrong.**

**Alternatives:** A parallel movie pipeline — two code paths, two bug surfaces, and the
honesty invariants would have to be re-implemented and re-verified on the second path. A
film-specific fork of the repo — same objection, permanent.

**Consequences:** the invariants apply to films unchanged. A film cannot be "artistic licence"
for a distorted still or an undeclared silent cut. If a genuine need for a tenth stage
appears, it is a signal to revisit the stage decomposition — not to fork.

---

## D15 — Terminal footage is recorded, never animated

**Status:** DECIDED 2026-10-06.
**Context:** OpenMontage synthesises terminal output with a React component
(`TerminalScene.tsx`) — a *fake* terminal. The natural shortcut is to copy that approach.

**Decision:** vidkit records a **real PTY**. The command, its exit code, and its duration are
attested in `verify.json`.

**Alternatives:** A synthetic terminal animation — cheaper, fully controllable, and it
**lies**. A screenshot of a terminal — honest but not a *recording*, and it cannot show
process. A screen recording — heavy, non-deterministic, captures unrelated windows.

**Consequences:** invariant I7 holds on the new surface. A non-zero exit fails the build
unless the spec declares it expected. Fonts must be pinned or the recording is not
reproducible — a real constraint that must be solved in M7.

---

## D16 — Nothing is fabricated; unverifiable output is not emitted

**Status:** DECIDED (pre-existing, restated 2026-10-06).
**Context:** Every "video generation" tool faces the temptation to smooth over gaps with a
placeholder, a mock, or a restaged take.

**Decision:** Every frame traces to a **real capture**, a **measured dataset**, or a
**declared asset**. If vidkit cannot produce the honest thing, it **fails the build** rather
than emitting something plausible. The only exception is a failure that the spec explicitly
declares expected.

**Alternatives:** Warn-and-continue — produces a lying video, which is the exact product
vidkit is built to avoid. Placeholder frames — same. Silent retry — hides flakiness until it
matters.

**Consequences:** invariants I2, I3, I6, I7. This is the reason vidkit exists next to
OpenMontage; if it is ever relaxed, vidkit becomes a worse OpenMontage.

## D17 — A floating window may be described but never dated

**Status:** DECIDED 2026-10-06 (M1).
**Context:** A relative timeframe (`{days: 28}`) with no `as_of` resolves against whatever
"today" is when the build runs. The resolved dates are therefore *not* knowable at authoring
time — and if the narration states them anyway, the video is wrong the day it is rebuilt.

**Options.**

| Option | Pro | Con |
|---|---|---|
| **A. Require `as_of`, always** | Nothing floats, so nothing is ambiguous. | Every hand-written spec must carry a date it may not care about; `{days: 7}` is a perfectly honest request. |
| **B. Allow floating windows; let narration say whatever** | Simplest. | The video silently becomes wrong when the window moves. This is the dishonesty vidkit exists to prevent. |
| **C. Allow a floating window, but forbid narration from stating dates** | `{days: 7}` stays convenient; the resulting video is *always* true. | One more rule to learn. |

**Decision:** **C**. A relative window with no `as_of` resolves and is flagged `floating`.
`_validate_timeframe` reads the narration and **refuses at load** any stated window while the
window floats. The narration may still state the *duration* — "the last 28 days" is a claim
about a length, and it is checked; "28 days to 6 October" is a claim about dates, and it is
not available. Pinning `as_of` unfloats the window and dates become permitted.

**Alternatives rejected:** A alone (needless friction for the common `{days: 7}` case); B
(silently stale output — the exact failure mode P1 forbids).

**Consequences:** `Timeframe.floating` is part of the public contract. `spec-reference.md` and
`stories-and-timeframes.md` document the rule. The failure is raised at *load*, before any
capture or render, so a floating window with dated narration costs nothing to discover.

---

## D18 — `vidkit init` writes a story that must build and verify unedited

**Status:** DECIDED 2026-10-06 (M1).
**Context:** R-A2 and R-G4 want a scaffolded starting point. The failure mode of every
scaffolder is a template that is *nearly* right — it parses but fails the first real command,
so the new user's first experience is an error they did not cause.

**Decision:** The scaffold is a **test fixture, not a template**. It writes four files
(`story.yaml`, `video.yaml`, `narration.md`, `provider.py`) and the contract is that the
result builds and verifies clean with **no edits**. Anything that would make it fail its own
checks is a bug in the scaffold, not a step in the user's onboarding. It refuses to overwrite
existing files, so it can never destroy work.

**Consequences:** CI runs `vidkit init` into a scratch directory and builds it on every push,
so the scaffold cannot rot silently. This is how three scaffold bugs were caught during M1:
ASCII punctuation that the narration parser rejects, and a runtime window guessed from
`tf.days` instead of from the narration's own word count. The scaffold now derives its bounds
from the same 2.5 words/sec constant the silent-cut path uses, so the file it writes and the
runtime it gets agree.

---

## D19 — A narration/spec disagreement is `verify`'s job, not `load`'s

**Status:** DECIDED 2026-10-06 (M1).
**Context:** M1 has two ways narration can be at odds with the spec's window, and it would be
tidier to catch both in one place.

**Decision:** Split them, by what each stage can *prove*.

| Situation | Caught at | Why there |
|---|---|---|
| Narration states dates while the window **floats** | `load_spec` | Provably impossible. No rendering can make it true, so the cheapest correct answer is to refuse before spending time. |
| Narration states a window that **disagrees** with a pinned window | `verify` | Only provable against the finished artifact. The claim may come from the narration *or* from burned-in captions, and captions come from rendered frames. |

**Alternatives rejected:** everything at `load` — misses caption-borne claims, which the
engine only knows after it has drawn them. Everything at `verify` — wastes a full build on a
spec that can never be right.

**Consequences:** two documented error paths, one R-F7 check, and one rule for the reader:
if it is *impossible*, fix the spec; if it is *inconsistent*, fix the narration.

---

## D20 — Secrets are declared, resolved from the environment, and masked everywhere

**Status:** DECIDED 2026-10-06 (M2).

**Context:** An agent that can run arbitrary provider code will eventually be handed a token.
The engine must be able to *name* what a build needs without ever revealing it.

**Decision:** Secrets are declared, never inferred; read from the process environment only;
masked in every string the engine emits.

- A need is declared in two places that are merged, not either/or: the spec's
  `provider.secrets` (so `doctor` and `plan` work without importing provider code) and the
  module's `secrets()` (so a provider can declare a need it only discovers at runtime).
- `resolve()` treats an **empty string as unset** — an exported-but-empty variable is the most
  common CI misconfiguration and must not look like a working build.
- `Secrets.redact()` masks by **longest value first**, so a short token that happens to be a
  prefix of a longer one cannot leak the tail, and it is applied to *provider exception text*
  as well as engine messages.
- `get()` never raises; `[...]` and `require_secret()` do, naming the variable but not its
  value. `describe()` prints `NAME  set (43 chars)` or `NAME  NOT SET — required`.
- `spec.provider.write_back` is refused at load: the engine never writes to a source system.

**Alternatives rejected:** inference from `os.environ` (a provider could then read anything the
host happens to export); a `.env` loader (a second source of truth, and an easy way to commit a
secret); printing values behind a `--verbose` (a screenshot of `doctor` is a leak).

**Consequences:** `doctor` fails on a missing required secret; a redaction bug is a
security-class bug and gets the same treatment as a fabrication bug.

---

## D21 — A snapshot records the *request* it answers, not just the data

**Status:** DECIDED 2026-10-06 (M2).

**Context:** M2's exit criterion is that `--only panels,clips,render` re-renders offline.
Done naively, that means any on-disk dataset is fair game for any build.

**Decision:** `_build/data/_snapshot.json` records `{provider, provider_sha256, timeframe}`
alongside a hash per dataset. A stage about to reuse datasets compares its own request against
that record and **refuses** when it differs, naming the changed field:

```
vidkit: error: dataset snapshot is stale: the window changed (2026-08-01 to 2026-09-30
(61 days) -> 2026-09-07 to 2026-10-06 (30 days)) — re-run the `data` stage (drop it from
--only, or pass --refresh) to fetch it again
```

- The key is deliberately narrow: provider identity, provider *source*, and the resolved
  window. Cosmetic changes (a chart title, a label) must **not** force a refetch.
- `--refresh` re-adds the `data` stage; a plain build that selects `data` ignores the check
  (it is about to overwrite the snapshot anyway).
- A missing or corrupt snapshot is refused with the path named, never silently refetched — the
  whole point of the offline path is that it does not touch the network. **CI proves this with
  a canary**: the probe provider appends to a file every time it runs, so "the source was not
  touched" is a fact about the filesystem rather than a reading of the log.

**Alternatives rejected:** trust-on-first-write (reproduces D16's failure mode with a green
verify); hash every input including the spec (a typo in a caption would refetch the source);
record only a timestamp (cannot distinguish "stale" from "correct").

**Consequences:** an honest offline re-render is the *default*, not an option to remember.

---

## D22 — Degradation is declared in advance, recorded, and only fatal by request

**Status:** DECIDED 2026-10-06 (M2).

**Context:** A provider reaches a live system. Sometimes the system is down. The engine needs an
outcome that is neither a hang, nor an invented number, nor a hard failure.

**Decision:** A provider may raise `SourceUnavailable` and return a value it *declared* in
advance via `fallback_for(name, ctx)` or `fallbacks(ctx)`. If it does not, the build fails.

- A fallback **used** is recorded: the dataset goes into `ctx.degraded[name] = why`, which
  reaches `verify.json` as `facts.degraded`.
- `guard.require_live_data: true` makes any recorded degradation a `verify` failure.
- The default is `false`, because a provider that *synthesizes* its own series (hello-world's
  does) is not degraded — it is authored. A provider that reads a live system should set it.
- The exception keeps its message but is redacted before it reaches the log, so an outage
  message cannot carry a token into a build log.

**Alternatives rejected:** a silent `except` returning a default (indistinguishable from a
real result, and D16 calls that a fabrication); always failing on outage (turns a transient
network blip into a broken CI run); a `--allow-degraded` flag (easy to leave on, and invisible
in the artifact).

**Consequences:** "this number came from yesterday's cache" is a *fact in the report*, not a
secret known to the operator.

---

## D23 — An artifact is filmed as itself, or not at all

**Status:** DECIDED 2026-10-07 (M3).

**Context:** Some of the most convincing evidence a product can show is not in the DOM: a
downloaded CSV, a generated invoice, an exported PDF. M3's exit criterion is literally "capture
a real downloaded file and film it". The easy implementation films a *page* the download URL
happens to render, or drops the bytes into a styled template — both produce a picture that is
*about* the file rather than *of* it.

**Decision:** `captures[].artifact: <name>` films the bytes **themselves**, and every step that
could substitute something prettier is a refusal instead.

- `artifact:` and `url:` are mutually exclusive; both are load-time errors.
- An `artifact:` that no `download` action in the spec produces is rejected by `load_spec`.
- Artifact captures are ordered **after** every URL capture, so the producer always runs first.
- The producer must have written it *this run*: a file left over from an earlier build is not
  evidence, so the resolver only sees the artifacts the current run recorded.
- The bytes are **sniffed** (`%PDF-`, a PNG/JPEG magic, text that parses as delimited rows). If
  the content does not match the claimed kind, the build stops: `its bytes are not recognisable
  as a <kind>`. A wrong 200-page error page saved as `report.pdf` cannot be filmed as a report.
- A PDF is **rasterised** through `pdftoppm`, falling back to `gs`. If neither is installed the
  build refuses with a sentence naming both — never a placeholder frame, and never a caption
  that says "PDF" over an empty box.
- Empty and oversized (> 8 MB) files are refused, and the artifact name is defended against
  path traversal: a capture cannot name `../../etc/passwd`.
- `verify` closes the loop: `filmed artifacts are real files`, emitted **only** when the spec
  declares an artifact capture.

**Alternatives rejected:** film the download URL in a new page (depicts the *source*, not the
download, and often requires the session the click already had); render the bytes into a styled
template (a fabrication — it is vidkit's design, not the product's output); accept any file that
exists (a stale or truncated file passes); let a missing rasteriser fall back to showing the
file's name and size as text (a screenshot of a filename is not the document).

**Consequences:** "this shot is the file the product produced" becomes a checked fact. The cost
is a hard dependency on `poppler-utils` or `ghostscript` for PDF artifacts — a refusal the user
can act on, rather than a silent degradation.

---

## D24 — A take is named, and promoting one is explicit

**Status:** DECIDED 2026-10-07 (M3).

**Context:** Recorded flows vary. A capture that raced a spinner on take one may be perfect on
take two. Re-authoring the spec to retry is bad; silently overwriting the good take with a
worse retry is worse.

**Decision:** `captures[].take: N` (default `1`, `>= 1` enforced at load) names the take to
record. Each capture records `_capture/<name>-take-N.png` and is registered as a still under
that name; there is **no** automatic promotion and **no** predicate language.

- Re-running capture with a higher `take` writes a new file; the previous take stays on disk.
- Changing the number *is* the promotion. Nothing is deleted, so a bad promotion is reversible.
- A `take < 1` is a load-time error, because take zero reads like "the take before the first"
  and would be a silent off-by-one in the filename.

**Alternatives rejected:** a `take: best` predicate over a scoring function (an unverifiable
notion of "best" — D16's failure mode, arriving through the back door); keep-the-latest (loses
the take you wanted to compare against); a `--promote` flag on the CLI (hidden state that the
spec does not describe, so a rebuild cannot reproduce it).

**Consequences:** a take is a *file*, so the spec plus the disk describe the build completely.
The cost is that the promoted take must be stated in the spec — which is also the guarantee.

---

## D25 — A login form is filmed only on purpose

**Status:** DECIDED 2026-10-07 (M3).

**Context:** M3 added session reuse (`storage_state`) so a capture can reach a signed-in page,
and a capture that fills a form is just a `fill` action. But a `fill` into a password field is
how a recording accidentally leaks a credential onto a frame that will be published.

**Decision:** Two distinct, explicit paths, and nothing in between.

- **`vidkit auth URL`** opens a headed browser, you sign in by hand, and the cookies are
  written to a Playwright storage state that captures reuse via `storage_state:`. vidkit never
  sees the password. It *does* see a credential-bearing file, and says so on every run;
  `vidkit init` writes `.auth/` into the story's `.gitignore`.
- **`allow_login: true`** is required for a capture that fills a password-shaped field (or
  clicks a login/submit control on a page with one). It is a declaration that the login **is**
  the scene, and it is per capture, not per spec.
- Absent the flag, such a capture is refused **at load time**, before a browser opens:
  `fills a password field — record a session first`.
- An `allow_login` capture is still subject to every other refusal: it must assert the state
  it claims, and it cannot film an artifact that is not there.

**Alternatives rejected:** allow it and rely on review (the whole point of an assertion-checked
build is that review happens *before* the frames are rendered); a `--allow-login` CLI flag
(invisible in the artifact, so the published spec would not describe what it filmed); ban it
outright (a product tour legitimately begins with its sign-in experience, and banning a
capability pushes the author to a bespoke script outside every guarantee).

**Consequences:** the failure mode this guards against — a password on a published frame — is
now structurally impossible without a line in the spec saying it was intended.

---

## D26 — An overlay is drawn over a shot, never instead of one

**Status:** DECIDED 2026-10-07 (M4).

**Context:** M4 added `scenes[].overlay`, a banner or image composited over a shot. The obvious
next convenience — "this scene has no footage, just show the banner" — is exactly the failure
mode the project exists to prevent: a published frame whose content came from a spec string
rather than from anything that actually happened.

**Decision:** An overlay is **decoration on evidence**. A scene with an `overlay` still needs
exactly one of `still:`/`capture:`/`chart:`, and the overlay is composited on top of the
finished take. The renderer enforces the same instinct: a `progress` panel draws *named
stages* and never an invented percentage; a `comparison` panel draws both sides with the same
geometry and type so only content can differ; a `quote` panel requires `who:`, because an
unattributed quotation is not checkable. `overlay.fade` is clamped to a third of the scene so
a declared overlay can never render as nothing.

**Alternatives rejected:** allow an overlay-only scene (it would make the "no fabricated
frames" invariant unenforceable, since the frame would have no provenance to check); allow an
overlay to *replace* a failed capture (the honest response to a failed capture is a failed
build — `capture.py` already aborts).

**Consequences:** every rendered frame still traces to a capture, a still, or a computed
dataset. A spec author who wants a title card writes a `still:` — a declared graphic asset,
which is a different and checkable claim from "something happened".

---

## D27 — A still is fitted, never stretched

**Status:** DECIDED 2026-10-07 (M4).

**Context:** `still_to_clip` scaled to `project.size` with a bare `scale=W:H`, which stretches.
A full-page capture is 1280×3000-ish; letterboxed or cropped it is legible, stretched it is a
misrepresentation of the layout the product actually has.

**Decision:** `shots[].fit` is `cover` (default) or `contain`, and there is no third value.

- **`cover`** scales to fill and centre-crops the overflow. No bars, no distortion, but the
  vertical extremes of a tall page are off screen. It is the default because most footage is
  a viewport-shaped screenshot, where `cover` is exact.
- **`contain`** scales to fit and letterboxes with a flat colour. Nothing is hidden, and the
  bars honestly admit the source is not the frame's aspect.
- Neither ever invents pixels, and neither is "stretch". Choose `contain` when the *whole*
  document body is the claim — a full CSV, a PDF page.
- New check `frames are the declared size` reads the geometry back off the produced file, so a
  fitting regression cannot pass by looking plausible.

**Alternatives rejected:** make `contain` the default (letterboxing every ordinary screenshot
adds bars that say nothing true); a `stretch` option (there is no honest use for one);
per-shot crop rectangles (a footgun that lets a spec frame any arbitrary sub-region as if it
were the page).

**Consequences:** a `fit` mistake is visible on screen — bars, or a cut-off edge — which is the
point. The verify check turns a silent regression into a build failure.

---

## D28 — A transition is a beat, and it never changes the runtime

**Status:** DECIDED 2026-10-07 (M4).

**Context:** M4 added `project.transition` (`cut`|`fade`|`wipe`|`slide`) and `transition_seconds`.
A dissolve *overlaps* two takes. Naively concatenating padded clips makes the finished film
longer by `transition_seconds` per junction, so the pictures drift later and later behind the
voice — a lie about timing, and precisely the failure I5 ("measured audio is the master
clock") exists to forbid.

**Decision:** A transition is a beat **between** two states, not a shot of its own — hence the
0.05–2.0 s cap and the refusal wording. The engine lays the whole run out as a plan before
rendering anything (`_clip_plan`), and the **outgoing** take of each junction carries the extra
`transition_seconds`. The dissolve therefore consumes exactly the time it adds, the total
runtime is unchanged, and narration stays the master clock. The four transitions are four
different claims — `cut` a changed state, `fade` an overlap, `wipe` a replacement at a definite
instant, `slide` a movement — so the choice is content, not decoration. `cut` stays a stream
copy; anything else builds an `xfade` chain.

**Alternatives rejected:** pad the *incoming* clip (drops the next picture in `s` early —
measured: the new colour is on screen at 1.9 s instead of 2.0 s, which is the drift this whole
entry is about); let the runtime grow and re-time the SRT to compensate (the SRT is built from
measured spans; stretching it to cover a video-track mismatch would make the captions wrong
instead of the pictures); a free-form transition duration (a 5-second dissolve is a scene, and
calling it a transition would hide that no such scene was filmed).

**Consequences:** the exit criterion is checkable — `test_a_transition_never_changes_the_runtime`
asserts the finished track equals the measured narration for all three non-cut transitions. A
long transition can no longer paper over a change the spec has no footage for.

---

## D29 — A job answers with a manifest, and never raises for an expected refusal

**Context.** M5 has to hand vidkit to an agent that did not write it. Every existing entry
point answers differently: `run()` returns an `Assets`, the CLI prints prose or a small JSON
summary, the MCP tools raise `ToolError`, `plan` returns a report, `doctor` returns a
verdict. An agent choosing among them has to learn eight shapes and guess the order.

**Decision.** There is one call — `{action, story, out}` — and it returns **one document**
whose *base keys are always present* (`action, ok, story, out, spec, timeframe, artifacts,
report, timeline, failure, progress, vidkit`), whatever happened. An action may add keys
(`plan`, `doctor`, `created`); it may never remove or rename one. An expected refusal — "no
story given", "that folder has no video.yaml", "the snapshot answers a different window" —
comes back as `ok: false` plus a `failure` block with a `kind` and a `hint`. It does not
raise. A refusal still records the window that was *asked* for, because "which window was
that about?" is the first thing a caller needs after a failure.

**Alternatives rejected:** letting expected refusals raise and asking callers to catch them
(an agent then has to tell "vidkit said no" apart from "vidkit crashed" — and it cannot, from
a message string); a different result shape per action (that is the thing being fixed);
returning a bare error on stdout with a non-zero exit (loses `spec`, `timeframe`, `progress`
— the parts that make a failure diagnosable).

**Consequences:** `vidkit run` and `--json` share one serializer, and `_COMMAND_ACTION` maps
verb → action so they cannot drift. Exit code follows `ok` (`0` done, `1` refused, `2` ran and
did not verify). The base-key set is asserted in `tests/test_job.py::BASE_KEYS`, so a future
action that forgets a key fails a test rather than a caller.

---

## D30 — Progress is the pipeline's own narration, delivered only through a hook

**Context.** Long builds need to say what they are doing. The pipeline already does: every
stage prints `[vidkit] …` lines to stdout. The obvious implementation is a second progress
channel — callbacks threaded through every stage — which is a second account of the run that
can drift from the first.

**Decision.** A job captures **stdout for the duration of the block** and turns each whole
line into a step (`{name, kind, ok, detail, seconds}`), classified (`stage` / `check` / `warn`
/ `log`) so a caller can render stages and checks differently without parsing text. That
record is always in the manifest; it reaches a terminal **only** if the caller supplied a
hook. `run_job` therefore has no `echo` parameter: the *only* way a run's log leaves it is
`on_progress`. The CLI passes one that writes to stderr under `--progress`; the MCP server
passes one that writes to stderr; the plain `vidkit run` passes one only when stdout is a
terminal.

**Alternatives rejected:** a second callback channel per stage (drift, and every stage
changes); letting the log out on stdout as well as through the hook (a stdio MCP transport
has one stdout channel and it belongs to the protocol — this is the existing `stdout_to_stderr`
rule, restated); an `echo` flag on `run_job` (tried and removed: it broke under pytest's
captured stdout, and it makes the log *optional* rather than *redirectable*).

**Consequences:** `--json` stays pipeable by construction, not by discipline. A caller cannot
poll a job in another process — progress describes the run you are waiting for — so over MCP
a bounded `timeout` on `vidkit_run` is how a client stops a runaway build getting a refusal
rather than a hang.

---

## D31 — Provenance is written by the build and only read by everything else

**Status:** DECIDED 2026-10-07 (M6).

**Context.** A `.mp4` found on disk a month later is an assertion with no author. R-F8 asks
for the build's identity — what it was made from and what made it. The obvious shortcut is to
compute it wherever it is needed: `vidkit verify` already loads the spec, probes the tools,
and has the output path, so it could assemble the record itself and write it beside
`verify.json`. That is exactly wrong. A record composed at *read* time describes the tree as it
is *now* — the spec as edited since, the ffmpeg that happens to be installed today — while
appearing to describe the build it was handed. It is a fabricated provenance for someone
else's build, which is D16's failure mode arriving through the back door.

**Decision.** `assembler.run` writes `OUT/_build/provenance.json` for **every** rendering
action, and `verify` — like `vidkit provenance`, the `provenance` job action, and
`vidkit_provenance` — **reads** it. Nothing else ever writes it.

- `Provenance.read` returns `None` on a missing file, unparseable JSON, or a `schema` it does
  not know. It never returns a half-parsed guess, so a caller cannot act on a misread record.
- A verify copies the identifying fields into `report.facts.provenance` and keeps
  `action: "build"` — it reports the build it looked at, not itself.
- Provenance is a **fact, not a check**. Its absence does not fail a build, and a verify on a
  tree with no record still runs every acceptance check.
- A tool that is missing is recorded with `present: false` rather than omitted. "We did not
  check" and "it was not there" are different facts, and only the second one is useful later.
- Timestamps are UTC and the elapsed time is the measured wall clock, so the record answers
  "how old is this?" without needing the reader's timezone.

**Alternatives rejected:** fold it into `verify.json` (a re-verify would then rewrite the
build's identity — the drift this exists to prevent); compute it on demand at read time (the
fabrication above); write it from the CLI/MCP layer per verb (four writers, four chances to
disagree, and `--json run build` would differ from `vidkit build`); record only the tools that
are present (silently converts "not looked for" into "not needed").

**Consequences:** the record is reproducible from the build alone, and the framing is fixed:
`verify.json` answers **"is this honest?"**, `provenance.json` answers **"what is this?"**.
The cost is one more file in `_build/` on every render, and a `verify` that can honestly say
`provenance: null` when there is no build to describe.

---

## D32 — Platform support is stated, not implied

**Status:** DECIDED 2026-10-07 (M6).

**Context.** R-H6 asks for a portability pass. The honest content of one is a *policy*, not a
promise: the engine is developed and CI-tested on Linux, some tools are Linux-first, and one
mechanism — the `SIGALRM` run timeout — does not exist on Windows at all. Claiming "cross
platform" without saying which parts are tested would be the same class of error as an
unverified `verify.json`.

**Decision.** Support is tiered and written down, in
[`docs/operations/troubleshooting.md`](../operations/troubleshooting.md):

- **Linux — tested.** Every CI job runs here, including the two render jobs.
- **macOS — supported, untested by CI.** The code paths are platform-neutral, Chrome discovery
  covers both `chrome-mac` and `chrome-mac-arm64` and the `/Applications` bundles, and the
  Playwright cache paths are searched per platform. The default theme's font families do not
  ship with Windows or macOS; the docs say which and what to set instead.
- **Windows — best-effort, not tested.** No POSIX-only call is on the build path; `Shell`
  passes argv lists, never a shell string, so there is no `/bin/sh` dependency to port.
- The one real degradation is named rather than hidden: `signal.setitimer` does not exist on
  Windows, so the MCP run timeout is **not installed** there and a job is unbounded. The
  manifest still reports what the job did, and the docs say so in a table row of its own.

**Alternatives rejected:** claim full cross-platform support (unverifiable, and the timeout
gap would surface as a hung client rather than a documented limit); drop the timeout on all
platforms for symmetry (removing a working guard from the tested platform to match an
untested one is backwards); add a thread-based timeout for Windows (a new concurrency
mechanism, and one that cannot interrupt the pipeline's subprocess work anyway).

**Consequences:** a user on macOS or Windows knows exactly what is and is not promised, and
a future portability bug has a documented baseline to be measured against.

---

## Index

| ID | Title | Status |
|---|---|---|
| D1 | Story identity manifest shape — **both** | DECIDED |
| D2 | Spec format stays YAML | DECIDED |
| D3 | Timeframe representation — **both** forms | DECIDED |
| D4 | Engine stays host-agnostic | DECIDED |
| D5 | Story lives in the consumer repo; MCP-only | DECIDED |
| D6 | Assert-before-shot aborts the build | DECIDED |
| D7 | Document set shape: 6 files | DECIDED |
| D8 | Docs are routed, not scattered | DECIDED |
| D9 | Do not integrate OpenMontage | DECIDED |
| D10 | MCP-first is the only integration surface | DECIDED |
| D11 | hello-world is offline, measured, and silent | DECIDED |
| D12 | The spec is the control plane | DECIDED |
| D13 | Sandbox and Docker come after the timeframe contract | DECIDED |
| D14 | Movie mode is additive, not a fork | DECIDED |
| D15 | Terminal footage is recorded, never animated | DECIDED |
| D16 | Nothing is fabricated | DECIDED |
| D17 | A floating window may be described but never dated | DECIDED |
| D18 | `vidkit init` writes a story that must build and verify unedited | DECIDED |
| D19 | A narration/spec disagreement is `verify`'s job, not `load`'s | DECIDED |
| D20 | Secrets are declared, env-resolved, and masked everywhere | DECIDED |
| D21 | A snapshot records the request it answers, not just the data | DECIDED |
| D22 | Degradation is declared, recorded, and only fatal by request | DECIDED |
| D23 | An artifact is filmed as itself, or not at all | DECIDED |
| D24 | A take is named, and promoting one is explicit | DECIDED |
| D25 | A login form is filmed only on purpose | DECIDED |
| D26 | An overlay is drawn over a shot, never instead of one | DECIDED |
| D27 | A still is fitted, never stretched | DECIDED |
| D28 | A transition is a beat, and it never changes the runtime | DECIDED |
| D29 | A job answers with a manifest, and never raises for an expected refusal | DECIDED |
| D30 | Progress is the pipeline's own narration, delivered only through a hook | DECIDED |
| D31 | Provenance is written by the build and only read by everything else | DECIDED |
| D32 | Platform support is stated, not implied | DECIDED |
| D33 | Execution is a declared environment, not shell access | DECIDED |
| D34 | A recording is filmed through a PTY, never a pipe | DECIDED |
| D35 | The sandbox is `bwrap`, and a refusal is a result | DECIDED |
| D36 | The network needs two permissions, and the refusal names the missing one | DECIDED |
| D37 | The engine chooses the interpreter; the spec only chooses a form | DECIDED |
| D38 | The screen model is hand-rolled; `pyte` is not a dependency | DECIDED |
| D39 | A recording keeps its measured pace; only the last frame is a remainder | DECIDED |
| D40 | An attestation must be emitted when it passes, and a `null` means one thing | DECIDED |
| D41 | A backend is available when it *runs*, not when it is installed | DECIDED |
| D42 | Docker is a confining backend, and the set of confining backends lives in the engine | DECIDED |
| D43 | Readiness must hold, not merely answer once | DECIDED |
| D44 | One environment is one container, addressed through one binding keyed by the command label | DECIDED |
| D45 | Teardown is unconditional and idempotent, and its record is evidence | DECIDED |
| D46 | The engine owns the rule for "which environment does this command run in" | DECIDED |
| D47 | A container is told what it needs; the client's `HOME` must not leak into the film | DECIDED |
| D48 | A capability report names the rung that is missing, not that the capability is absent | DECIDED |
| D49 | A declaration is not a measurement: a check that cannot fail is not a check | DECIDED |
| D50 | The engine draws a picture from words, so a film needs no artwork it did not ship | DECIDED |
| D51 | A film's clock is declared; a demo's clock is measured | DECIDED |
| D52 | An absent measurement is not a negative measurement | DECIDED |
| D53 | A side effect that already happened cannot be denied | DECIDED |
| D54 | A take is kept, not re-shot: selection survives the render | DECIDED |
| D55 | The event loop is not a place to block: blocking tools are offloaded | DECIDED |
| D56 | An unknown spec key is an error, not a comment | DECIDED |
| D57 | A test that does not await an async tool does not test anything | DECIDED |
| D58 | Every input to a transition is normalised to one timebase | DECIDED |
| D59 | The MCP SDK range ends at the last supported major | DECIDED |

---

## D33 — Execution is a declared environment, not shell access

**2026-10-08.** Context: M7.

The instinct that began this work was "give vidkit shell access". That phrasing has no trust
boundary in it — it names a capability without naming its limits, and an agent driving a
studio needs to be told what it is allowed to do, not what it can do.

**Decision.** vidkit executes nothing that the spec has not declared. An `exec:` block names
each command, its backend, its working directory, its environment, its timeout, whether it
may reach the network, and which extra roots it may read. `ExecRequest` is the runtime's
type and carries only things that can be honoured; `spec.Exec` is the author's type and
carries what a *shot* needs. Nothing reaches into the runner from the spec.

**Alternatives.** (a) A general shell tool on the MCP server — rejected: it makes the server's
blast radius the host's, and it makes the video's provenance impossible to state. (b) A shell
tool off by default and enabled by an env var — rejected: the permission then lives outside
the artifact, so the same spec renders differently on two machines with no record of why.

**Consequences.** A spec is the complete statement of what a build does — which is what makes
`provenance.json` able to say what made a film. Adding a capability (a Docker container, say)
means adding a *declaration* to the spec language, not a flag to the runner.

---

## D34 — A recording is filmed through a PTY, never a pipe

**2026-10-08.** Context: M7, invariant I7.

This is the decision the whole stage exists for. A program checks `isatty` and changes what it
prints when it is not on one: progress bars collapse to a final line, colour is dropped,
prompts are suppressed, and line buffering changes what arrives when. A recording made off a
pipe is a transcript the program never produced.

**Decision.** Commands run on a real pseudo-terminal (`pty.fork()`), with a declared window
size set on it. Output is read with `select()`, timed by `time.monotonic()`, and written to
both the frame renderer and the `.cast` from the same in-memory event list.

**Alternatives.** (a) `subprocess.PIPE` — rejected: it is cheaper, it passes every test that
only checks the exit code, and it makes a *plausible* terminal rather than a *real* one.
(b) Recording with `script(1)` and post-processing — rejected as a dependency on a second
process's quirks when `pty` is in the standard library.

**Consequences.** The PTY is load-bearing, not cosmetic: `test_run_is_handed_a_real_terminal_not_a_pipe`
uses `tty >/dev/null` to pin it, and any future refactor to a pipe fails that test rather than
quietly changing what the audience sees.

---

## D35 — The sandbox is `bwrap`, and a refusal is a result

**2026-10-08.** Context: M7, R-E2.

**Decision.** The default backend is `bwrap(1)`: `--unshare-all`, `/usr` and its friends
mounted read-only, the repo bind-mounted as the working directory, and the network unshared
unless asked for. `local` exists and must be declared. `docker` is reserved for M8.
`resolve_backend()` refuses a name the host does not have, and `check_policy()` runs *before*
anything starts, so a spec that cannot be honoured says so while the camera is still off.

**A refusal is a result, not an exception.** It carries `refused=` with the reason and
`exit_code=126`, and the build continues. An unrun command is then reported by the same
`every declared command ran` check that reports a crashed one.

**Alternatives.** (a) `firejail` — not present on the CI runner. (b) Raising `ToolError` —
rejected: an agent driving the studio needs a machine-readable reason far more than it needs a
traceback, and a build that dies halfway leaves no `verify.json` to explain itself.

**Consequences.** `bwrap` may be present where the render toolchain is not (CI's `pytest`
jobs are exactly this case), so exec tests are split: policy and renderer are pure Python,
anything that starts a process is `@pytest.mark.needs_render`.

---

## D36 — The network needs two permissions, and the refusal names the one that is missing

**2026-10-08.** Context: M7, R-E3.

**Decision.** A *command* may say `network: true`, and the *spec's* `exec.allow_network` says
whether that is on the table at all. Either alone is not enough. The refusal text names
`exec.allow_network` specifically, because there are two ways to fix it and the author has to
be told which layer they are standing in.

**Alternatives.** A single switch on the step — rejected: it makes the widened permission
invisible at the top of the file, which is where a reader looks to ask "what can this build
reach?".

**Consequences.** Widening the network for one command is a visible, greppable edit to the
spec's `exec:` block, and `provenance.json` can record it.

---

## D37 — The engine chooses the interpreter; the spec only chooses a *form*

**2026-10-08.** Context: M7, R-E1.

**Decision.** `cmd:` written as a **string** is a shell script and runs under
`["/bin/sh", "-c"]`. `cmd:` written as a **list** is an argv and runs directly. A `shell:` field
is explicitly refused. `ExecRequest.cmd` is always a list, and `argv()` exists to hand the
concrete argv to the runner.

**Alternatives.** Letting the spec name the interpreter — rejected: it turns "what is filmed"
into "what is installed", makes a spec non-portable for no expressive gain, and creates a
path from the spec to an arbitrary binary. A shell script is a legitimate thing to film; the
point is that the engine decided to run one, and the two forms make that decision visible in
the spec's own syntax.

**Consequences.** The convenient form announces that it is a shell script; the safe form is
the default one.

---

## D38 — The screen model is hand-rolled; `pyte` is not a dependency

**2026-10-08.** Context: M7, R-E4.

**Decision.** `vidkit/terminal.py` implements the ANSI/CSI subset a terminal recording
actually uses: SGR colour and attributes, cursor positioning, erase-in-line modes 0/1/2,
scrolling at the bottom margin, tab stops, and 8-bit-safe UTF-8 decoding. Unknown CSI
sequences are dropped silently. `pyte` was evaluated and rejected.

**Alternatives.** `pyte` — a mature, correct library. Rejected for three reasons: it is an
extra runtime dependency for the *core* engine, which currently needs only PyYAML; the
subset needed here is small enough to specify; and the parts that matter most (how a
half-written escape at a buffer boundary behaves, what happens to a carriage return over a
longer line) are exactly the parts a *test* should pin by name rather than inherit.

**Consequences.** Two behaviours are pinned as-is with their reasoning written down, because
they surprise people: `\r` does not erase a longer previous line without a following
`\x1b[K`, and `replay_events(every=1.0)` on events at 0.0/2.5/3.0 snapshots only 0.0 and 2.5 —
which is *why* the assembler appends the final screen itself.

---

## D39 — A recording keeps its measured pace; only the last frame is a remainder

**2026-10-08.** Context: M7, defect C.

**Decision.** Interior frames of a recording are held for the spans **measured** between them.
The final frame is held for whatever time is left in the shot. If the interior spans overrun
the take, they are compressed by a reported factor and the build **warns** — because a
screencast that quietly plays at 2x is a film claiming a four-second build took half a second.

**Alternatives.** (a) Divide the shot evenly across the frames — rejected: it destroys the
timing the recording was made to capture, which is the whole evidence value of M7.
(b) Re-time silently — rejected on invariant grounds.

**Consequences.** `_exec_span` returns `paths`, `held` and `speed`, index-aligned. The
index-alignment is itself a fixed defect: an earlier form returned the two lists with
different lengths, handing ffmpeg a duration for a frame that did not exist.

---

## D40 — An attestation must be emitted when it passes, and a fact must not use `null` for two meanings

**2026-10-08.** Context: M7, defects E and F.

**Decision.** Two rules about `verify.json`, both general:

1. **A check that applies is emitted whether it passes or fails.** `every declared command
   ran` used to be added to the report only on failure, which made a *passing* report
   indistinguishable from a check that never applied. An attestation that exists only as an
   absence attests to nothing.
2. **A `null` must mean one thing.** `facts.exec[].playback` was `null` both for a recording
   replayed at 1.0x as a single held screen *and* for one never shown as a take. The report
   now carries `frames` too, so the two read differently.

**Alternatives.** Documenting the ambiguity — rejected. The file exists to be read by a
machine and by a stranger; a distinction that lives only in the source is not in the artifact.

**Consequences.** This is the same error twice at two levels — a claim that can only be
verified by reading the implementation. Any new check is now expected to state its success
case, and any new fact is expected to distinguish "none" from "not measured".

---

## D41 — A backend is available when it *runs*, not when it is installed

**2026-10-08.** Context: M7, defect G, found while fixing PR #7's CI.

**Decision.** `bubblewrap` counts as available only if a probe **actually starts a sandbox**
on this host. The probe runs the engine's own `_bwrap_argv` around `/bin/true`, costs 14.1 ms,
and is memoised per process. `resolve_backend()` refuses on the probe's answer, and
`doctor`'s `available` field reports it. `doctor` answers the question with **or without a
spec**, and separates two fields on purpose: `available` is "can this host sandbox?", `ok` is
"does the spec's declaration work here?".

**Alternatives.**

- *Ask `shutil.which("bwrap")`* — rejected, and this was the bug. On Ubuntu 24.04 the binary
  is present and every invocation fails with `setting up uid map: Permission denied`, so a
  presence check answers `True` to a question whose true answer is `False`. That is not a
  conservative approximation; it is the false claim invariant I7 forbids, arriving through an
  environment check instead of a rendered frame.
- *Silently downgrade to `local`* — rejected outright. `verify`'s `commands ran sandboxed`
  check reads `result.backend`, so a silent downgrade would make that check **pass** while
  the command ran unconfined. A true film and a false attestation.
- *Fix CI only (install the sysctl, leave the engine alone)* — rejected. It would have left
  every Ubuntu 24.04 user with a `doctor` that says the sandbox is fine, a build that dies
  with a `SpecError` mid-render, and no way to tell a missing binary from a kernel that will
  not cooperate. CI was the messenger, not the problem.
- *Probe the whole pipeline instead of one command* — rejected on cost: ~2 s, which is too
  slow for `doctor`. `/bin/true` under the real mount layout exercises exactly the capability
  the pipeline needs.

**Consequences.** A user-visible `doctor` line and a ~14 ms subprocess in it. The load-time
refusal is unchanged in kind and better in message: *missing* and *cannot start* now read
differently, and the latter names the `sudo sysctl -w
kernel.apparmor_restrict_unprivileged_userns=0` workaround. `tests/conftest.py` gains a
`needs_sandbox` marker applied independently of `needs_render`, and CI carries a sysctl step
with a gate that calls the probe rather than looking for a file.

**The general rule, because this will recur:** *when a capability gate decides whether an
honest build is possible, it must demonstrate the capability, not observe a precondition of
it.* The same question will be asked of Docker in M8, and the answer there must be a
`docker run --rm hello-world`, not a `which docker`.

---

## D42 — Docker is a *confining* backend, and the set of confining backends lives in the engine

**2026-10-09.** Context: M8, found while wiring `backend: docker` into the `commands ran
sandboxed` check.

**Decision.** `vidkit/exec.py` exports `CONFINING_BACKENDS = frozenset({"bubblewrap",
"docker"})`, and `verify.py` reads it (`from . import exec as exec_mod`) instead of naming a
backend. The check's question is "did every command run *confined*?", and the engine is the
only module that knows what confinement means.

**Alternatives.**

- *Hard-code `backend != "local"`* — rejected. It is right today by accident: the field is an
  enum of backends, not a taxonomy of boundaries, and the next unconfined backend (`host`,
  `none`) would silently pass a check whose whole purpose is to fail in that case.
- *Hard-code `{"bubblewrap", "docker"}` in `verify.py`* — rejected. Two lists in two files is
  a drift waiting for exactly the release where nobody re-reads the verifier.
- *Ask the `ExecResult` whether it was confined* — appealing, but it lets a result assert its
  own honesty. The verifier should classify from the declaration + engine knowledge, not from
  a field the runner supplied.

**Consequences.** A container counts as confined for `commands ran sandboxed`, which is a
*stronger* claim than the bubblewrap path: the command sees the image's own filesystem, its
own PID namespace, and the project as a **read-only** bind. The honesty rules of D35 are
unchanged — a spec that says `backend: local` still says so in plain words and still fails
`require_sandbox`. Adding a backend now means one edit, in the one place that knows.

---

## D43 — Readiness must *hold*, not merely answer once

**2026-10-09.** Context: M8, defect I, measured directly against `postgres:16-alpine`.

**Decision.** `ready:` (`READY_HOLD = 0.75 s`) is not a single successful sample. Nothing runs
until the declared readiness argv has succeeded on **every** attempt for a continuous
0.75 s. A single success that is not sustained is a *distinct, named* outcome — "the
readiness command answered once, then stopped holding" — not a generic timeout.

**Alternatives.**

- *One successful sample* — rejected, and this is the defect. Measured timings for
  `pg_isready -U postgres` against a fresh `postgres:16-alpine`:

  | t (s) | what is true |
  |---|---|
  | ~1.30 | `pg_isready` exits 0 — but against the **bootstrap** server |
  | ~1.45 | the bootstrap server is **stopped**, the real one not yet up |
  | ~1.84 | a real `SELECT 1` first succeeds |

  A one-shot gate opens a window of roughly 150 ms in which it declares a service ready and a
  command that then runs gets a database that is going down. This is exactly the failure the
  whole project exists to prevent: the film would show a connection error, or worse, would
  show a *success* against a server that no longer exists by the time the take is filmed.
- *Parse the container's own health/`logs`* — rejected: it makes vidkit's gate depend on the
  image's healthcheck conventions, and the image that matters most declares nothing.
- *Sleep a fixed 2 s after the first success* — rejected as a magic number that is wrong on
  a slow runner and wasteful on a fast one.

**Consequences.** Every docker build spends at least 0.75 s in the gate, ~2.6 s for the
Postgres fixture including the container start. The report carries `ready_detail` in three
recognisable shapes — held, "answered once then stopped holding", and never answered — so a
user can tell a service that never came up from one that came up and fell over, and the
second is what a retry loop would have hidden. The rule is stated for authors in
[exec-guide.md §10](../capture/exec-guide.md).

---

## D44 — One environment is one container, and a command addresses it through one binding keyed by the command label

**2026-10-09.** Context: M8, defects S and the binding refactor.

**Decision.** An `environment:` declaration starts **one** container per build. Every
`backend: docker` step naming it is `docker exec`'d into that same container, and the mapping
from a step to its container is held in **one** binding table keyed by the command's **label**
— never by the environment name, and never recomputed. The readiness probe, the command
itself, and the log capture all resolve their target through it.

**Alternatives.**

- *One container per step* — rejected. The most valuable demo in this product's category is
  "write a row in step 1, read it back in step 2". With one container per step that claim is
  false, and it would be false in a way that *looks* like it worked, because both steps would
  succeed against two private databases. That is a fabricated narrative produced by an
  infrastructure choice.
- *Key the binding by environment name* — rejected: two steps may legitimately share one
  environment, so an environment-keyed table cannot answer "which container is this command's
  container" for the second step without a lookup, and any lookup is a second chance to
  disagree with the first.
- *Resolve the container at each use site* — rejected: defect S (`docker docker exec …`) was
  precisely a use site that composed its own argv and did not go through the one builder.

**Consequences.** `report.facts.exec[].container` makes the sharing **visible**: a reader can
confirm from the artifact alone that step 2 ran in step 1's container, rather than trusting
that it did. `_docker_argv` is the single argv builder; `bind_step(label, state)` is the single
binding; `bind_step(label, state)` is the only way to populate it, and
`unbind_environments()` is called from exactly one place, after the last step.

---

## D45 — Teardown is unconditional and idempotent, and its record is evidence

**2026-10-09.** Context: M8, defect K (a leaked container) and the double-removal defect.

**Decision.** The environment lifecycle is one `try/finally` around the whole exec stage. An
environment is recorded as **started** *before* readiness is awaited, so a container that
came up and never became ready is still stopped. Teardown runs on every exit path — success,
refusal, exception — and is written into `facts.environments[].teardown` as
`{attempted, stopped, removed, detail}`. A second teardown pass is a **no-op that returns the
first record unchanged**, and the "removed" line is emitted only when the container was not
already removed. Containers are **not** started with `--rm`.

**Alternatives.**

- *Rely on `docker run --rm`* — rejected. `--rm` removes the container when it **exits**,
  which is not when the build decides it is done; a crash leaves the process table clean and
  the container gone, so a *failed* build looks tidier than a successful one and the
  post-mortem has nothing to inspect. It also makes "removed" unattributable to vidkit.
- *Record teardown only when it succeeds* — rejected. Invariant I7: "we did not check" and
  "it was not there" must read differently. `attempted: false` with a reason is a fact worth
  having; a missing key is not.
- *Tear down only on the happy path* — this was defect K. The failure mode is the one where
  it matters most: a container whose readiness never held is precisely the container a user
  needs to inspect, and precisely the one a happy-path-only `finally` leaves running.

**Consequences.** The exec stage gained one nesting level. `environment_down()` and
`capture_logs()` are idempotent by contract. The `docker-probe` CI job asserts
`docker ps -a --filter name=vidkit-` is empty afterwards, which is a stronger check than
reading the report: it verifies the report's claim rather than repeating it.

---

## D46 — The engine owns the rule for "which environment does this command run in"

**2026-10-09.** Context: M8. `verify.json`'s `facts.exec[]` had no `container` key while
`provenance.json` did, because the two wrote it from two separate walks of `exec.steps[]`.

**Decision.** `Spec.exec_environment(label)` is the single definition. The provenance writer
(`assembler._env_of`) and the verifier (`verify._container_of`) both read it; neither walks
the step list itself. `_container_of` further reads the **live** `assets.environments` state
rather than the spec, because the question is "which container did this command actually run
in", and only the build knows that.

**Alternatives.**

- *Two walks* — this was the defect: two implementations of one rule, and they had already
  diverged. One of them was silent, because an absent key reads exactly like "no container".
- *Have `verify` read `provenance.json`* — rejected. A verify that trusts the build's own
  record cannot detect a build that recorded the wrong thing; and a stale `provenance.json`
  from an earlier build would be read as this build's.
- *Have the runner put `container` on `ExecResult`* — rejected: `provenance` needs the
  *environment*, and `verify` needs the *container*; deriving both from one authoritative
  rule beats adding a third field each one interprets.

**Consequences.** An unknown label returns `""` rather than raising — a fact about a command
that was never started is "no container", which is answerable, not an error. Two tests pin
the rule from both sides (`test_a_docker_step_that_was_never_started_reports_no_container`,
`test_a_spec_says_once_which_environment_a_command_runs_in`).

---

## D47 — A container does not inherit the host environment, and the client's environment must not leak into the film

**2026-10-09.** Context: M8, defect T and the `~/.docker/config.json` warning.

**Decision.** Two separate rules about environment, both applied deliberately:

1. **What the run needs, the run is told.** `docker exec` does not inherit the client's
   environment, so `_docker_argv` emits `-e` for every entry of the same `_env_for(req, cwd,
   "docker")` mapping the host path uses. `PATH`, `LANG`, `LC_ALL`, `TERM`, `COLUMNS`, `LINES`
   and the declared `env:` all cross the boundary explicitly.
2. **What the container should not see, the *client* is not told.** `HOME` is **removed** from
   the docker client's own environment. With it set, the client read
   `/root/.docker/config.json`, was denied, and printed `WARNING: Error loading config file`
   — onto the very PTY being filmed. The container still resolves `/root` from its own
   `/etc/passwd`, because the process that needs `HOME` is the container's shell, not the
   client.

**Alternatives.**

- *Forward nothing and let the container's image define its environment* — rejected: the
  film then has no `TERM`/`COLUMNS`/`LANG`, so colours, wrapping and the locale would all
  differ from every other take in the video, and the two paths would not be comparable.
- *Forward `os.environ` wholesale* — rejected: it is the opposite defect, and a container is
  the one place where the boundary is cheap to hold.
- *Keep `HOME` and silence the warning with a flag* — rejected: there is no such flag, and
  the general rule is better than a workaround. Nothing on the filmed screen should be the
  *tooling's* output. A warning that appears only on the docker path is a signal that the two
  paths differ, and it would be presented to a viewer as the program's own words.

**Consequences.** Every docker run passes its environment explicitly on both sides of the
boundary, and the filmed PTY carries only what the declared command produced. Verified by
rebuilding `examples/docker-demo` and grepping the build log and the recordings for
`Error loading config file`.

---

## D48 — A capability report names the rung that is missing, not that the capability is absent

**2026-10-09.** Context: M8. `doctor` must answer "can this host run my video", and Docker
that answer has three independent failure modes.

**Decision.** `doctor` reports the three Docker questions **separately**, as
`rungs: {client, daemon, container}`, and the container rung is *demonstrated* by
`docker run --rm hello-world` per the rule of D41. The refusal names the first rung that
fails, in its own words.

**Alternatives.**

- *One boolean, `docker_available`* — rejected. `which docker` missing is an install; a
  daemon that is not running is a service to start; a missing `hello-world` is a pull. One
  boolean sends three different fixes to the same unhelpful sentence, and the third is the
  one users will hit on a fresh machine with the client installed.
- *Probe only the daemon (`docker info`, ~60 ms) and defer the container* — **considered and
  not taken**, on cost grounds. The full ladder measured **0.51 s** against a memoised
  14 ms bubblewrap probe, which is a real but acceptable price for a pre-flight check whose
  entire purpose is to be believed. `doctor` costs **0.12–0.19 s** with a spec; it did not
  become a slow command. The seam is deliberately kept: `docker_daemon()` exists and is
  cheap, so this decision can be revisited without rewriting the probe.
- *Reuse `resolve_backend()`'s single answer* — rejected: `resolve_backend` answers for one
  step's declared backend, while `doctor` answers for the host.

**Consequences.** `doctor` prints a docker row with a `rungs` block, and `_sandbox_needs()`
carries the same structure so the CI gate can name the rung. The **same three rungs are what
the local `docker-probe` job's capability ladder walks in order**, which is why the job
prints its own ladder before it gates on the engine's answer: a failure in CI says which rung
broke.

---

## D49 — A declaration is not a measurement, and a check that cannot fail is not a check

**2026-10-10.** Context: M9. M9's headline claim is that a *film* — a cut with no capture, no
provider and no browser — is still honest, because every picture is either declared artwork
the author shipped or a picture the engine drew from declared words. Verifying that claim
turned up a check that assumed its own conclusion.

**Decision.** A check about what a picture **did** measures the picture. `every camera move is
accounted for` decodes a real frame from near the head of each moving clip and one from near
its tail (`frame_rgb`, 64×36), differences them, and records the result as `mae` on that
shot's `facts.motion` row. `MOVE_MAE = 0.10` is the threshold. A clip that cannot be read or
decoded **fails** the check: a measurement that did not happen is not a measurement of zero.

**The defect, exactly.** The check it replaced read:

```python
rep.add("camera moves are declared", len(moved) == len([r for r in artwork if r.get("motion")]), …)
```

where `moved` *was* that filter. It compared a value with itself. It could not fail, it could
not detect anything, and it appeared in the report of every film claiming that the camera
moves were verified. Its sentence — *"5 of 6 shot(s) move"* — was a restatement of the spec
wearing the clothes of a result.

**Alternatives.**

- *Delete the check* — rejected. A reader of a green report cannot tell a check that passed
  from a check that was never run, so removing it would quietly remove the claim too.
- *Check the filterchain string* — rejected: that is the declaration again, one layer further
  from the picture. ffmpeg folds `iw-iw/zoom*p` to a constant and renders a perfectly static
  frame with no error, so the string proves nothing about the frames.
- *Compare against a stored reference frame* — rejected as a different, weaker claim: it tests
  that the clip matches an expected file, not that the camera moved.

**Consequences.** The measurement cost 12 `ffmpeg` invocations (~5.3 s) on the exit proof, and
it immediately found a real defect **in the fixture**: `movie-demo` scene 2 pans over a flat
`solid: "navy"`, so the picture does not change by a single pixel. That shot is kept, and the
spec now says why — it is the only shot in the film that proves the report distinguishes a
declaration from a measurement, because it is the only one whose `mae` is `0.0` while its
declaration is non-empty. The check passes; the report says *"4 of 5 declared move(s) change
the picture; 1 over a field with nothing in it to reveal"*. Two more instances of the same
class were found in M9 and are recorded as D52.

---

## D50 — The engine draws a picture from words, so a film needs no artwork it did not ship

**2026-10-10.** Context: M9. A film with no browser and no captures has nothing to photograph.
The alternative was to require the author to ship a PNG for every frame.

**Decision.** Two new shot kinds. `card:` renders a title card **from the shot's own words** —
`kicker`, a rule, a wrapped body, and an optional scrim over a `backdrop:` that is resolved and
checked *at load time*, so a card cannot silently render over nothing. `solid:` is one flat
field. Both are drawn by `card.py` in pure SVG, rasterised by the same `rsvg-convert` the rest
of the engine uses, and both are classified in `verify.SHOT_SOURCES` as **declared asset** —
the same class as a `still:`, because that is what they are: pictures the author asked for by
writing them down, not pictures of anything that happened.

**Alternatives.**

- *Require a PNG per card* — rejected: it puts a drawing tool between the author and a title
  screen, and a film whose words are in the spec should not need a screenshot of those words.
- *Render text with ffmpeg's `drawtext`* — rejected: no wrapping, no layout, font-dependent
  metrics, and no way to test the result without pixels.
- *Call the card a new source class* — rejected: it would let a report claim a source that is
  neither live, nor measured, nor declared, which is the vocabulary the honesty claim rests on.

**Consequences.** The default theme lives in `svg.py`, the card layout in `card.py`, and the
font metric problem is solved by being deliberately measure-free: the wrap width is derived
from the font size rather than asked of a font, because the engine cannot ask a font its
metrics without pulling in a text shaper, and a card that wraps one word early is a smaller
failure than one that runs off the frame. `svg.document()` declares `xmlns:xlink`; rsvg
resolves an **absolute** href silently and renders an **empty frame** for a relative one.

---

## D51 — A film's clock is declared; a demo's clock is measured

**2026-10-10.** Context: M9, and the tension with I5 ("measured audio is the master clock").

**Decision.** `seconds:` is accepted on a **scene** and on a **shot**. When at least one
length is declared, `facts.timing_source` is `"spec"` and the voice is **cut to the spec**;
when no length is declared, the measured voice remains the master clock and `timing_source` is
`"audio"`. The check `shot timing is expressed, not measured` fails only when the report would
be *ambiguous* about which rule was used. `plan_shots(spec, audio)` is the single timing rule,
read by both the renderer and `vidkit plan`, so the plan cannot disagree with the film it
predicts.

**Alternatives.**

- *Keep I5 absolute* — rejected as a misreading. I5 exists so lengths are never *estimates*
  presented as measurements. A declared length is not an estimate; it is a decision, and a
  film is a series of decisions. What I5 forbids is the third thing: an estimate wearing a
  measurement's clothes.
- *Infer the clock from whether audio exists* — rejected: a scored silent film has audio and no
  voice, and an unscored captioned film has neither. The spec must say.
- *Let the estimator and the assembler keep separate copies of the rule* — rejected, and this
  is the bug that was found: `vidkit plan` predicted lengths the renderer did not produce. One
  rule, two readers.

**Consequences.** A demo's behaviour is unchanged (no `seconds:` anywhere → `timing_source:
"audio"`), so I5 is not weakened for the case it was written for. Every declared length is
named in the check's `detail`, so a reader can see the film's clock rather than infer it.

---

## D52 — An absent measurement is not a negative measurement

**2026-10-10.** Context: M9. Three separate honesty defects in one milestone, all the same
shape: a report saying something it had not established.

**Decision.** A fact carries **three** states, not two: the thing is true, the thing is false,
and the thing was not measured — and the third must never be spelled as the second. Verify
publishes `narration_spans` only when **every** scene has a real wav file on disk; otherwise it
publishes `narration_estimate`, named as an estimate. `Ffmpeg.mix()` **returns** a `MixResult`
describing what it did, and verify reports that, so `ducked` is `True` (ducked under measured
spans), `False` (played alone) or `null` (never reached the mix) and the three read differently.

**Alternatives.**

- *Default a missing measurement to zero / to `false`* — rejected: this is the defect. A silent
  cut reported `duck_seconds: 16.01` of ducking that never happened, because the spans were
  recomputed from the spec rather than reported by the mix.
- *Publish both the estimate and the spans* — rejected: one field with two meanings is how the
  original defect happened, and a consumer cannot tell which it holds without a second rule.
- *Raise instead* — rejected: a silent cut is a declared, legal film (I6), and an estimate is
  the honest answer for it, not an error.

**Consequences.** Machine consumers read one field or the other and never the same field two
ways. `narration_estimate` is one entry per scene of the word count divided by
`_FALLBACK_WPS = 2.5`, and the check `declared score is in the mix` branches on
`ducked is True` / `is False` / else. See
[docs/verification/verification.md](../verification/verification.md).

---

## D53 — A side effect that already happened cannot be denied

**2026-10-11.** Context: M10.

`tool_browser_open` did this:

```python
browser, context, page = studio.browser_open(session, url)   # opens a real browser
return {**state, "session": sess.id}                          # raises: 'tuple' object is not a mapping
```

The browser was open. The caller was told the call failed. Worse, `session_open` accepted four
parameters, **dropped all four**, and returned success — a call that changed nothing said it had
changed something. Both defects share a shape: the tool's *report* and the tool's *effect*
disagreed, and the report is what the caller acts on.

**Decision.** A tool resolves every argument it accepts, and it never raises **after** it has
changed the world: either the effect happens and is reported, or nothing happens and the refusal
is reported. Where an operation is long enough to be interrupted, the tool reports what *did*
happen (partial progress and the step it stopped at) rather than an exception that erases it.

**Alternatives.**

- *Let the exception propagate* — rejected: it is not wrong about the failure, it is wrong about
  the state. The caller retries an operation that has already happened.
- *Roll back on failure* — rejected in general: a browser tab, an appended record and a started
  container cannot be un-happened in a way that is more truthful than saying so. Roll back only
  where the rollback is itself the recorded evidence (D45's teardown).
- *Accept extra `**kwargs`* — rejected: that is how four parameters went missing. An accepted
  parameter must be read.

**Consequences.** Every tool resolves its arguments explicitly and is audited for it — all 34
were re-audited when `session_open` was found. `browser_open` returns the page state *and* the
session id, and refuses before opening rather than after.

---

## D54 — A take is kept, not re-shot: selection survives the render

**2026-10-11.** Context: M10.

`capture.capture_all` re-shot every declared capture at build time. So an agent that filmed
three takes, selected the best one, and then built the film got the **first** take — the
selection was a record about a file the build never read. Proven directly:

```
base before select 64378b9e8191
select_take        5b54a53e53bd
base after build   ce0423787238      <- not the selected take
```

**Decision.** A selection is part of the build's input, not a note about a past attempt.
`Context.selections` records it; `Context.selected_take(capture)` reads it; `capture_all`
**keeps the promoted file** instead of re-shooting when the take is already selected; and
`studio.select_take` updates an already-live `Context` so the choice is not lost between the
tool call and the build. The film is then *measured* to contain the kept take (the `studio-probe`
job decodes the delivered `.mp4`'s middle frame).

**Alternatives.**

- *Re-shoot and compare* — rejected: a capture is not deterministic (it films a running
  product), so "re-shoot and take the closest" silently substitutes a *different* take.
- *Store the selected bytes at selection time into the output* — rejected: it edits the output,
  which is I7's prohibition, and it hides which file the renderer actually read.
- *Make selection a build-time argument* — rejected: the selection outlives a single build, and
  an agent may build repeatedly while choosing.

**Consequences.** **The promotion copies take N over the bare name**, so after it the two files
hold identical bytes and comparing them is a check that cannot fail. The regression test
therefore compares the promoted bytes against **take 2's own pre-promotion digest** and asserts
inequality against take 1's. `list_takes` re-hashes every file on every call, so the digest in a
record is a live measurement. See D53 and D57 for the same defect class.

---

## D55 — The event loop is not a place to block: blocking tools are offloaded

**2026-10-11.** Context: M10.

FastMCP runs a **sync** tool on the loop thread. This was not assumed; a probe printed the
thread name from both a sync and an async tool body and both said `MainThread`. Playwright's sync
API refuses to run there —

```
Error: It looks like you are using Playwright Sync API inside the asyncio loop.
```

— and it refuses **before** doing anything. So every browser and capture tool was dead over MCP,
always, on every machine, and nothing in the suite noticed because the tests called the plain
functions rather than the wire.

**Decision.** A tool that blocks becomes `async def` and runs its blocking body on a **dedicated
worker thread** via `vidkit/_loop.py` (`Worker`, `offload`, `session`): one thread per live
session, so a browser and its page stay on the thread that created them. **The one deliberate
exception is `tool_run`**, which stays sync because `_deadline` needs a main-thread `SIGALRM` —
and because its ceiling is therefore conditional, it reports `timeout_enforced` as a tri-state
and names the reason, rather than claiming a guarantee it cannot make (D52).

**Alternatives.**

- *Use Playwright's async API* — rejected: the whole capture layer is written against the sync
  API, and the async rewrite would spread through `capture.py`, `terminal.py` and every test.
- *Run everything in a subprocess* — rejected: sessions own live state (a page, a container),
  and a subprocess cannot hold a page object across calls.
- *A thread pool with no affinity* — rejected: a Playwright page must be driven from the thread
  that created it.

**Consequences.** A registration closure is correct **if and only if** it awaits when it wraps a
coroutine. Three defects came from violating that in both directions, one of them an
*assignment* (`result = tool_session_exec(...)`) that no `return tool_x(` regex catches.
`tests/test_mcp.py` now AST-scans every closure in both directions. See D57.

---

## D56 — An unknown spec key is an error, not a comment

**2026-10-11.** Context: M10.

`load_spec` read exactly the keys it knew and never looked at the rest. It read
`raw.get("captures")` and nothing named `capture`. So a spec could contain a top-level
**`capture:`** block — a plausible singular spelling — and the loader would **discard it
silently**, then fail later with an error naming the *scene* while the actual fault was a key two
levels up that no one had mentioned.

**Decision.** The set of legal top-level keys is named in `_SPEC_KEYS` and checked at load, and
an unknown key is refused **by name**. The captures map is `captures:` (plural, top level); the
per-shot key is `capture:` (singular), and the error says so when a top-level `capture:` appears.

**Alternatives.**

- *Warn and continue* — rejected: a warning on a stderr nobody reads is indistinguishable from
  silence, and this loader has no other place to report it.
- *Accept aliases (`capture`/`captures`)* — rejected: two spellings that mean different things
  is how the confusion arose; one key with one meaning is the honest interface.
- *A JSON Schema for the whole spec* — deferred, not rejected: it would be better, and it is a
  larger change than the defect warrants today.

**Consequences.** The check immediately found **four of the author's own tests** writing
top-level `capture:` — tests that had been **green for the wrong reason**, because the block
they were testing was being thrown away. Adding a spec key now means adding it to `_SPEC_KEYS`,
which is a deliberate act rather than an omission. See D15/D16 for the same class.

---

## D57 — A test that does not await an async tool does not test anything

**2026-10-11.** Context: M10.

Making the tools `async` (D55) turned a whole class of existing tests into **assertions that
cannot fail**:

```python
tool_provenance(spec)                       # returns a coroutine, runs nothing
assert manifest["provenance"] == "tool"    # compares dict to coroutine: always False -> or...
with pytest.raises(ToolError):
    tool_build(spec)                       # no exception is ever raised
```

Two were found in `tests/test_provenance.py` and `tests/test_providers.py`. Both were green. Both
meant nothing. A third of the same kind, found earlier in this phase, compared a *promoted take
file against itself* (D54) — a different mechanism for the same result.

**Decision.** Three rules, all enforced by tests rather than by intention:

1. `tests/test_mcp.py::test_no_test_calls_an_async_tool_without_awaiting_it` **AST-scans every
   `tests/test_*.py`** and fails on a bare call to a known async tool as a statement or an
   assignment.
2. `tests/test_mcp.py`'s structural scan pins every registration closure against the coroutine
   it wraps, in **both** directions.
3. A check whose subject is a fact about a *picture* decodes the picture. There is no other way
   to tell a push-in from a still (D49).

Note **`anyio.run(fn, *args)` does not forward keyword arguments** — `TypeError: run() got an
unexpected keyword argument 'from_stage'`. Wrap in a lambda.

**Alternatives.**

- *A convention in the docs* — rejected: the convention existed and was violated twice in one
  phase, because the failure mode is silent and the test stays green.
- *Make the tools sync again* — rejected: D55.
- *A lint rule outside pytest* — rejected here: the suite must refuse the bug even when run
  alone, and a contributor may not run the linter.

**Consequences.** The class cannot return unnoticed. The AST scan is deliberately crude — it
errs toward flagging — and a new async tool must be added to its list of names, which is the
point: the list is the inventory of things that can be silently skipped.

---

## D58 — Every input to a transition is normalised to one timebase

**2026-10-11.** Context: M10.

Per-shot `transition:` (R-D6) was the last item M4 listed and M9 cut out. Implementing it
produced ffmpeg's own error, which named the cause exactly:

```
First input link main timebase (1/1000000) do not match the corresponding second input link
xfade timebase (1/12800)
```

`concat=n=2` gives its **output** the timebase of its **first** input. So the first junction
decided what every later `xfade` had to match, and **any hard cut preceding a dissolve** aborted
the render. It was not a dissolve bug; it was a cut-then-dissolve bug, which is the common case.

**Decision.** `Ffmpeg.concat_with_transitions` normalises **every** input with `settb=AVTB`
before it is joined or blended, not merely the second one. The regression test renders all five
junction kinds (cut-then-fade, fade-then-cut, dissolve-then-dissolve, a three-shot chain, and a
transition into the last shot) and asserts each is exactly **6.000 s** — the sum of its shot
lengths.

**Alternatives.**

- *Normalise only the second input* — this was the first attempt, and it is what the error
  message invites. Rejected once the mechanism was understood: the problem is the *output* of
  the previous junction, whichever input supplied its timebase.
- *Render each junction to an intermediate file and concat those* — rejected: an extra encode
  generation, and it hides the actual constraint.
- *Set `-vsync`/`-r` on the output* — rejected: it constrains the output, not the links, and the
  links are what disagree.

**Consequences.** A transition is now additive: a junction renders at the sum of its shot
lengths, verified rather than assumed. Anything else that consumes two streams and produces one
should be read with the same suspicion — the timebase belongs to the *output*, and a downstream
filter inherits it.

---

## D59 — The MCP SDK range ends at the last supported major

**2026-10-07.** Context: M10.

The MCP extra originally declared `mcp>=1.20`, which also admitted 2.x. That was not a safe
open-ended range: the server imported `FastMCP`, which 2.x renamed to `MCPServer`, and the
studio's protocol tests used a helper removed in 2.x. CI resolved 2.3.0 while local development
used 1.27.2, so the declared range was broader than the code and test evidence.

**Decision.** Support both MCP SDK 1.x and 2.x, and declare `mcp>=1.20,<3`. The server adapts
the app class, context, settings, and result shapes that differ between those majors. The
protocol-level test suite has been run against 1.27.2 and 2.3.0. Do not admit a future major
until its API changes are exercised and adapted.

**Alternatives.**

- *Pin to `mcp<2`* — rejected: the 2.x compatibility path is implemented and proven, and
  excluding it would discard supported behavior.
- *Leave the dependency unbounded* — rejected: a future breaking major would again install
  successfully while making the standalone server unusable.

**Consequences.** The project keeps compatible 1.x installations and accepts 2.x, while
dependency resolution refuses an unreviewed 3.x release instead of presenting it as supported.
