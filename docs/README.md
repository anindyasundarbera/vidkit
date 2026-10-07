# vidkit documentation — module router

This directory is written **for agents first** and humans second. Docs are grouped into
**modules**; this page is the router. Pick the module that matches your task, then read its
docs in order.

A machine-readable copy of this map lives in [`modules.yaml`](modules.yaml) — agents should
read that rather than this prose.

```
docs/
  README.md          ← you are here (the router)
  modules.yaml       ← machine-readable route table
  foundations/       mental model + stage machine + internals
  authoring/         write the spec, provider, panels, narration
  capture/           record real UI and assert it
  verification/      the acceptance checks
  operations/        run it, diagnose it, expose it (MCP), extract it
  guides/            copy-paste recipes
  plan/              where the project is going, what happened, and why
```

## Route table

| Module | Read it when you need to… | Docs (in order) |
|---|---|---|
| **[foundations/](foundations/)** | understand the model before anything else | [concepts](foundations/concepts.md) → [pipeline](foundations/pipeline.md) → [architecture](foundations/architecture.md) |
| **[authoring/](authoring/)** | write or change a `video.yaml`, `provider.py`, panel, or script | [spec-reference](authoring/spec-reference.md) → [provider-guide](authoring/provider-guide.md) → [panels-reference](authoring/panels-reference.md) → [narration-and-captions](authoring/narration-and-captions.md) |
| **[capture/](capture/)** | script a screen recording and assert the live state | [capture-guide](capture/capture-guide.md) |
| **[verification/](verification/)** | understand the checks and `verify.json` | [verification](verification/verification.md) |
| **[operations/](operations/)** | run, diagnose, expose, or extract the tool | [cli-reference](operations/cli-reference.md) → [job-contract](operations/job-contract.md) → [mcp-server](operations/mcp-server.md) → [troubleshooting](operations/troubleshooting.md) → [extracting-to-new-repo](operations/extracting-to-new-repo.md) |
| **[guides/](guides/)** | copy a known-good pattern | [recipes](guides/recipes.md) |
| **[plan/](plan/)** | know where the project is going, what already happened, and why a choice was made | [PLAN](plan/PLAN.md) → [FEATURE-ROADMAP](plan/FEATURE-ROADMAP.md) → [HISTORY](plan/HISTORY.md) → [DECISIONS](plan/DECISIONS.md) → [OPENMONTAGE](plan/OPENMONTAGE.md) |

## Routing by task

| I want to… | Module → doc |
|---|---|
| Understand what vidkit is | [foundations/concepts.md](foundations/concepts.md) |
| Know what each pipeline stage does | [foundations/pipeline.md](foundations/pipeline.md) |
| Modify vidkit's internals or add an extension point | [foundations/architecture.md](foundations/architecture.md) |
| Write or validate a spec | [authoring/spec-reference.md](authoring/spec-reference.md) |
| Connect vidkit to my data | [authoring/provider-guide.md](authoring/provider-guide.md) |
| Draw a chart/panel | [authoring/panels-reference.md](authoring/panels-reference.md) |
| Write the script / control captions | [authoring/narration-and-captions.md](authoring/narration-and-captions.md) |
| Record the product UI | [capture/capture-guide.md](capture/capture-guide.md) |
| Read a failing `verify.json` | [verification/verification.md](verification/verification.md) |
| Run it from a shell | [operations/cli-reference.md](operations/cli-reference.md) |
| Drive it from an IDE/agent (MCP) | [operations/mcp-server.md](operations/mcp-server.md) |
| Drive it from a script or an agent, whichever | [operations/job-contract.md](operations/job-contract.md) |
| Fix an error message | [operations/troubleshooting.md](operations/troubleshooting.md) |
| Lift vidkit into its own repo | [operations/extracting-to-new-repo.md](operations/extracting-to-new-repo.md) |
| Copy a working pattern | [guides/recipes.md](guides/recipes.md) |
| Know where the project is going / why | [plan/](plan/) |

## Suggested reading order

- **First contact (human):** [foundations](foundations/) → [authoring](authoring/).
- **First contact (agent):** `foundations/concepts` → `authoring/spec-reference` →
  `operations/mcp-server`, then the module for the task.

## How agents resolve a doc

`vidkit_docs` (MCP) and `vidkit docs` (CLI) take a **bare name** and resolve it through
`modules.yaml`, so a doc is reachable by its stem regardless of its module folder:

- `concepts` → `foundations/concepts.md`
- `spec-reference` → `authoring/spec-reference.md`
- `mcp-server` → `operations/mcp-server.md`
- `job-contract` → `operations/job-contract.md`

Calling with **no name** returns this index. Module-qualified names
(`authoring/spec-reference`) and explicit paths also resolve.

## What vidkit is, in one paragraph

vidkit turns a **declarative spec** plus a **data provider** into a narrated,
captioned screen-recording video. It captures real UI with Playwright (asserting the
on-screen state before it screenshots), draws charts from your live data, synthesizes
one audio file per scene, sizes each video segment from that audio, and muxes the result
with burned-in captions. It then **verifies** the result against the promises the spec
made and fails the build if any promise is broken.

## What vidkit can and cannot do

**Can**
- Capture real browser UI at a chosen size/scale, with a scripted interaction sequence.
- Assert the captured state (e.g. a mode indicator reads *live*) and abort otherwise.
- Draw panels from arbitrary JSON via built-in kinds or provider-registered kinds.
- Synthesize narration locally per scene (Piper) or fall back to a silent, estimated cut.
- Keep audio and video in sync by making measured audio the master clock.
- Produce a readable SRT and burn it in.
- Enforce runtime windows and content guards (banned/required phrases), then report.

**Cannot**
- Generate product UI. It captures what runs; it never fabricates an interface.
- Understand your domain. It has no idea what is true — that lives in your provider.
- Guarantee semantic correctness of narration text. It checks *presence* of required
  phrases and *absence* of banned ones; it cannot judge meaning (see
  [`verification.md`](verification/verification.md)).
- Replace human review of the final cut.

## Non-goals (deliberate)

- No timeline editor, no NLE, no keyframed motion. Video is a sequence of stills/clips
  joined by `-c copy`, optionally with a slow Ken-Burns push.
- No cloud services, no API keys, no telemetry. Everything runs locally.
- No database, no daemon. Each command is a one-shot process.

## Conventions used in these docs

- **`SPEC`** = the path to a `.yaml`/`.json` spec file. **`ROOT`** = the folder containing it.
- "**scene**" = one narration block with one or more **shots**. "`{n: 3}`" = scene index 3.
- Paths in a spec are resolved against `ROOT`, then `ROOT/..`, then the current directory.
- Code blocks marked `example` are runnable; those marked `shape` describe data.
- Where behaviour is a *guarantee*, the doc says so explicitly and cites the module.
