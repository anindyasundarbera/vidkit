# OPENMONTAGE.md — integration assessment (frozen)

> **Frozen research record.** Written 2026-10-06. Findings are timestamped and cited so they
> can be re-verified rather than re-researched. If you need current numbers, re-run the
> commands in §7 and append a new dated section — do not silently edit the findings below.
>
> **Subject:** `calesthio/OpenMontage`
> **Question asked:** *"Can vidkit implement or integrate OpenMontage to increase its
> capability? Or is OpenMontage alone sufficient?"*

---

## 1. Verdict, in one paragraph

**Integrate: no. Learn from: yes.** OpenMontage is a genuinely impressive and extremely
popular agentic video-production *system* — but it is a **system, not a library**. It has no
MCP server, no public Python API, no console entry points, and its architecture explicitly
forbids being driven programmatically. There is nothing to import and nothing to call. It is
also **AGPL-3.0**, so copying its code would relicense vidkit. Its value to vidkit is as a
**design reference**, not a dependency.

**Is OpenMontage alone sufficient for the owner's goal?** No. It solves a different problem
(*generate a montage from a prompt, using generative models*) than vidkit solves (*prove that
this software, in this environment, on this timeframe, actually does what the video says*).
It also has **zero** sandbox / terminal / Docker infrastructure, so it does not even cover
the owner's stated capability goal.

---

## 2. Project identity

| Field | Value | How verified |
|---|---|---|
| Repo | `calesthio/OpenMontage` | — |
| Licence | **AGPL-3.0** | `gh api repos/calesthio/OpenMontage --jq .license.spdx_id` |
| Primary language | Python | same call |
| Stars | 64,605 | same call |
| Size | 77,018 KB | same call |
| Last push | 2026-10-03 | same call |
| Self-description | *"The first open-source, agentic video production system."* | README |

**Note the popularity.** 64k stars and a 2026-10-03 push date mean this project is moving
fast and is well-resourced. Any architectural claim here should be re-verified before it is
relied on — that is exactly why this file is dated and evidence-tagged.

---

## 3. Why it cannot be integrated

### 3.1 No MCP server

```
gh api "search/code?q=mcp+repo:calesthio/OpenMontage+language:Python" --jq .total_count
→ 0
```

Its own MCP feature request is still open. vidkit's entire integration story (P3) is
MCP-first; OpenMontage has nothing on that surface to point at.

### 3.2 No public API and no entry points

- No `console_scripts` / no `[project.scripts]`.
- The only documented ways to run it are `python -m backlot` (a FastAPI storyboard UI) and
  `render_demo.py` (a Remotion renderer demo).
- The README's own guidance to agents is to run *ad-hoc inline Python*:

  ```python
  python -c "from tools.tool_registry import registry; import json; \
             registry.discover(); print(json.dumps(registry.support_envelope(), indent=2))"
  ```

  That is a **documented internal import**, not a supported interface. Depending on it means
  depending on private module paths in a fast-moving AGPL repo.

### 3.3 Its architecture forbids programmatic orchestration *by design*

The README is explicit: *"Do not improvise the production workflow"*, and the project's
**Rule Zero** is that **the agent *is* the control plane** — pipelines are selected and
driven by a conversational agent reading skill Markdown, not by a calling program.

This is not an oversight that a wrapper could paper over. It is the design thesis. Adopting
it would delete vidkit's reason to exist (see [DECISIONS.md](DECISIONS.md) D9 and D12).

### 3.4 Zero sandbox / terminal / Docker infrastructure

```
gh api "search/code?q=docker+repo:calesthio/OpenMontage+language:Python"     → 0
gh api "search/code?q=sandbox+repo:calesthio/OpenMontage+language:Python"    → 2
gh api "search/code?q=container+repo:calesthio/OpenMontage+language:Python"  → 4
gh api "search/code?q=bubblewrap+repo:calesthio/OpenMontage+language:Python" → 0
gh api "search/code?q=asciinema+repo:calesthio/OpenMontage+language:Python"  → 0
```

The handful of `sandbox`/`container` hits are incidental (isolation mentions in
generation pipelines), not an execution sandbox. There is a `TerminalScene.tsx` in the
Remotion composer — but it is a **synthetic typing animation**, i.e. a *fake* terminal
being made to look real.

> **Caveat on the `pty` search.** A code search for `pty` returns 75 hits, but GitHub code
> search matches substrings: filtering out paths containing `empty` alone drops the count to
> 30, and the remainder are ordinary words containing those three letters (e.g. `encrypt`).
> It is recorded here so nobody re-runs that search and mistakes the number for PTY
> infrastructure. **No pseudo-terminal execution and no terminal-recording dependency was
> found in the tree.**

**Consequence for the owner's goal:** the sandboxed-terminal + Docker capability is
**greenfield either way**. It is not a reason to adopt OpenMontage, and not a reason to
reject it. It is simply work vidkit has to do itself.

---

## 4. Marketing vs. source (read the code, not the badges)

Claims in the README do not match the source tree. This matters because a decision based on
the README would be a decision based on fiction — the same failure mode as vidkit's own stale
`ROADMAP.md` §3.

| README claim | What the tree contains |
|---|---|
| "100+ tools" | 53 named tools; 188 `.py` files |
| "700+ skills" | 139 `SKILL.md` + 157 `skills/*.md` + 1,268 files under `.agents/skills/` (largely vendored third-party) |
| "12 pipelines" | 13 YAML pipeline definitions |
| — | 75,000 KB repo, 2,601 paths, 2,143 files |

The numbers are not wildly false — they are inflated by counting vendored and generated
material. But the inflation is systematic enough that **the README is not a reliable
specification**.

---

## 5. The AGPL-3.0 boundary

OpenMontage is **AGPL-3.0**. vidkit is **MIT** (declared in `pyproject.toml`; the `LICENSE`
file itself is still missing — see [PLAN.md](PLAN.md) M0 task 8).

| Action | Consequence |
|---|---|
| Calling an **unmodified installed** OpenMontage as a **subprocess** | The safe separation. Two programs, two licences. Still requires care — AGPL's network clause is about *providing the software over a network*, so vidkit must not ship or serve OpenMontage's code. |
| `import tools.*` or `import lib.*` | vidkit becomes a derivative work → **AGPL-3.0 applies to vidkit**. |
| Vendoring / copying source files | Same. |
| Copying skill Markdown into vidkit | Copyright applies to that Markdown. Not permitted. |
| Reading the design and re-implementing in vidkit's own words/code | **Ideas are not copyrightable.** This is what we recommend. |

**Recommendation: zero code reuse. Concepts only.**

---

## 6. Concepts worth borrowing

These are the genuinely good ideas, restated as vidkit-shaped work. None of them require
any OpenMontage code.

| Concept | What OpenMontage does | What vidkit should do |
|---|---|---|
| **Capability envelope** | `registry.support_envelope()` reports what the current install can actually do given available keys/tools. | vidkit already has `vidkit doctor` and is honest by construction — extend the doctor report into a machine-readable capability manifest an agent can query before planning. |
| **Selector pattern** | Every provider choice is scored across 7 dimensions with an auditable decision log. | Applies directly to vidkit's capture/executor backends: choose `local`/`bubblewrap`/`docker` by declared policy and **log why**. |
| **Pipeline-as-data** | Production flow lives in YAML, not code. | vidkit's spec *is* this, already. Validation: keep it that way — do not let M7/M8 push policy into Python. |
| **JSON-Schema artifacts** | Stage outputs are schema-typed, so an agent can validate what it got. | vidkit's `verify.json` and the M5 artifact manifest should be schema-published. |
| **Cost governance** | Token/API cost is tracked per production and shown before committing. | vidkit has no monetary cost, but **wall-clock, container, and token budgets** are the same primitive — adopt for M10 (R-G5). |
| **Multi-point self-review** | ffprobe validation, frame sampling, audio-level analysis, promise verification, subtitle checks. | vidkit's `verify` already does most of this. The *"delivery promise verification"* — did the video deliver what the brief asked — is the interesting one, and is essentially vidkit's M1 R-F7 timeframe check. |
| **Reference-video ingestion** | Paste a YouTube/Reel/TikTok link → transcript, pacing, scene, style analysis → concepts. | Out of scope for vidkit. Interesting future direction, not a phase. |

---

## 7. How to re-verify this document

```bash
gh api repos/calesthio/OpenMontage \
  --jq '{license:.license.spdx_id,stars:.stargazers_count,pushed:.pushed_at,size:.size}'

for q in mcp docker sandbox container bubblewrap asciinema console_scripts; do
  printf '%-16s ' "$q"
  gh api "search/code?q=$q+repo:calesthio/OpenMontage+language:Python" --jq .total_count
done

curl -sL https://raw.githubusercontent.com/calesthio/OpenMontage/main/AGENT_GUIDE.md | head -80
curl -sL https://raw.githubusercontent.com/calesthio/OpenMontage/main/PROJECT_CONTEXT.md | head -80
```

**Search caveat.** GitHub code search matches substrings and is not exhaustive
(`pty` → `empty`, `encrypt`). Treat a *positive* count as a lead to inspect, and a *zero*
count as strong but not absolute evidence of absence. Rate limits apply — the calls above
were limited on the second run.

---

## 8. What this means for vidkit's roadmap

1. **Do not adopt OpenMontage's control model.** "The agent is the control plane" is the
   opposite of vidkit's design, which is *the spec is the control plane and the engine is
   honest*. This is [DECISIONS.md](DECISIONS.md) D12.
2. **Do not schedule an integration phase.** There is nothing to integrate. There is no
   M-openmontage.
3. **Keep the sandbox work in-house.** [ROADMAP.md](FEATURE-ROADMAP.md) M7–M8, with a PTY-recorded
   *real* terminal rather than a synthetic animation.
4. **Do borrow the six concepts in §6** — each maps onto a phase that already exists, so
   none of them adds a phase.
5. **Re-read this file before any future "should we use X?" decision.** The pattern here —
   *popular repo, confident README, no library boundary, incompatible licence* — will recur.
