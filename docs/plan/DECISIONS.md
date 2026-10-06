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
