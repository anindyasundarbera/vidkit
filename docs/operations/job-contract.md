# The job contract

One call. One manifest. No exceptions for the things you expected.

An external agent — or a shell script under `--json` — should not have to know that
`build` is `run` with no stage filter, or that `verify` is not `plan`. It says what it
wants done (`action`), which story, which window, and where the output goes, and it gets
back the same document whatever happened.

```
vidkit run ACTION --story DIR [--out DIR] [--timeframe W] [--refresh]
vidkit --json VERB ARGS…          # the same document, from any command
```

## The call

| Argument | Meaning |
|---|---|
| `action` | `plan`, `build`, `capture`, `tts`, `verify`, `doctor`, `init` |
| `story` | the story **folder** (its `video.yaml` is found inside) or a spec file |
| `out` | where the run writes (default: the story folder) |
| `timeframe` / `as_of` | override the window in `video.yaml` / `story.yaml` |
| `refresh` | ask the provider again instead of trusting the on-disk snapshot |
| `only` / `from_stage` | narrow a rendering action to some stages (mutually exclusive) |
| `on_progress` | receive one line of the run's own log as it happens |

`action` and `story` are always worth passing. `plan` on a story you cannot build yet is
the recommended first call: it costs no render time and names the missing pieces.

## The manifest

**Every** job returns the same base keys, so a caller can read them before it knows whether
the job worked:

| Key | Type | Meaning |
|---|---|---|
| `action` | str | what was asked for |
| `ok` | bool | did it finish and pass |
| `story`, `out`, `spec` | str? | resolved absolute paths (the spec is found, not guessed) |
| `timeframe` | obj? | the resolved window, with `source` = `spec` / `story` / `override` |
| `artifacts` | obj | path / bytes / non-empty-ok, per artifact — a name is not evidence |
| `report` | obj? | the verification report, when one was produced |
| `timeline` | list | measured per-scene spans (start, end, seconds, words) |
| `failure` | obj? | see below |
| `progress` | obj | `{steps: [...], seconds}` — the run's own account of itself |
| `vidkit` | str | the version that produced this manifest |

An action adds its own keys on top — `plan` grows `plan`, `doctor` grows `doctor`, `init`
grows `created` — but never removes or renames a base key.

Two details are deliberate:

- **`spec` is resolved before the run.** A story folder may hold `video.yaml` or
  `spec.yaml`; the manifest names the one that was actually used, so an agent never has to
  re-derive it from the output paths.
- **`timeframe` is recorded even when the job then refuses.** A failed job still answers
  "which window was that about?", which is often the first thing a caller needs to know.

## Refusals

Nothing raises for an expected refusal. "You gave me no story", "that folder has no
`video.yaml`", "there is a snapshot but it answers a different window" — all come back as
`ok: false` plus a `failure` block, because an agent should never have to tell *vidkit said
no* apart from *vidkit crashed*.

```json
"failure": {
  "kind": "tool",
  "message": "no video.yaml/spec.yaml inside /tmp/story",
  "action": "plan",
  "story": "/tmp/story",
  "hint": "check the folder, or `init` a new story there"
}
```

| `kind` | Means | What to do |
|---|---|---|
| `tool` | the call is wrong, or a required tool is missing | fix the call, or `doctor` |
| `spec` | the story's `video.yaml` is wrong | `doctor`, then the spec reference |
| `vidkit` | an engine-level refusal (an unknown stage, a stale snapshot) | read `message`; `progress` has the run's own account |
| `missing` | there is genuinely nothing to work on (no render to verify) | build first, or point `out` at a previous run |
| `verification` | it built, and the acceptance checks said no | read `report.checks` |
| `usage` | a command that is not a job was handed `--json` | use the action vocabulary, or the command's own output |

`hint` is advice, not a stack trace: it names the next command worth running. Read it before
reading `message` if you are an agent — it is written for exactly that.

## Exit codes (`--json` and `vidkit run`)

| Code | Meaning |
|---|---|
| `0` | done; if a report was produced, it passed |
| `1` | refused — `ok: false`, read `failure` |
| `2` | it ran and produced output, but a **verification check failed** |

The code is a summary; the manifest is the answer. Branch on `ok` and read `failure` — the
exit code exists so a shell pipeline can notice without parsing JSON.

## Progress

`progress.steps[]` is the pipeline's own narration, captured as data: each step has a
`name`, a `kind` (`stage` / `check` / `warn` / `log`), an `ok` flag, a `detail` and a
`seconds`. It is recorded whether or not anybody was watching.

- **CLI.** `--progress` streams the same lines to **stderr**, leaving stdout pure JSON, so
  `vidkit --json build video.yaml --progress | jq .ok` works. Without `--progress` nothing
  is streamed and the manifest keeps the record — a pipe stays clean either way.
- **MCP.** `vidkit_run(…, progress=true)` streams to the server's stderr. A stdio transport
  has one stdout channel and it belongs to the protocol, so a tool never prints there.

A caller cannot subscribe to a job in a *different* process, and `progress` is not a poll
endpoint: it describes the run you are waiting for. Closing the client (stdio) or
disconnecting ends a build; over MCP, `vidkit_run(timeout=…)` bounds the call so a long
render comes back as a refusal instead of hanging the client.

## See also

- [CLI reference](cli-reference.md) — the verbs and flags
- [MCP server](mcp-server.md) — the same contract as tools
- [Troubleshooting](troubleshooting.md) — a `failure.message` to a cause
