# vidkit as an MCP server

vidkit ships an [MCP](https://modelcontextprotocol.io) server so an agent can plan, build,
inspect, and verify videos through tool calls — no shell required.

## Run it

```bash
vidkit-mcp                                      # stdio (default; for IDE clients)
python -m vidkit.mcp_server                     # same, without the console script
vidkit-mcp --transport streamable-http --port 8765   # long-lived HTTP
vidkit-mcp --transport sse --port 8765               # SSE (legacy)
```

Requires the extra: `pip install "vidkit[mcp]"` (i.e. `mcp>=1.20`).

## Tools

Every tool takes an optional `spec` (path to a `.yaml`/`.json` spec; omit for the default) and
returns JSON.

| Tool | Arguments | Returns |
|---|---|---|
| `vidkit_run` | `action`, `story?`, `out?`, `timeframe?`, `as_of?`, `refresh?`, `title?`, `slug?`, `only?`, `from_stage?`, `progress?`, `timeout?` | a **job manifest** — the one call that covers all seven actions |
| `vidkit_actions` | — | the action vocabulary and the stages each action runs |
| `vidkit_init` | `story`, `title?`, `slug?`, `timeframe?`, `as_of?` | a scaffolded, runnable story directory |
| `vidkit_capture_plan` | `spec?` | what the captures will film, in order, without filming it |
| `vidkit_doctor` | `spec?` | environment tool status + spec sanity |
| `vidkit_plan` | `spec?` | scenes, shots, guards, estimated runtime (no render) |
| `vidkit_build` | `spec?`, `out?`, `only?`, `from_stage?`, `refresh?`, `progress?` | output path, captions, clip count, verification report |
| `vidkit_tts` | `spec?`, `out?` | per-scene narration audio + measured timings |
| `vidkit_capture` | `spec?`, `out?` | the recorded takes and artifact stills (real UI, real files, with assertions) |
| `vidkit_verify` | `spec?`, `out?` | re-run the acceptance checks on the last render |
| `vidkit_verify_report` | `spec?`, `out?` | the persisted `verify.json` (no re-check) |
| `vidkit_panel_kinds` | — | the built-in panel kinds a chart may use |
| `vidkit_docs` | `name?` | the docs **module router**, or a named document's Markdown (module-routed) |
| `vidkit_docs_index` | — | the machine-readable module route table (`docs/modules.yaml`) |

### Which call should an agent use?

`vidkit_run` is the contract: it takes `{action, story, out}` and returns a manifest whose
keys never change, so a caller can read `ok` and `failure` without knowing vidkit. The
individual tools (`vidkit_plan`, `vidkit_build`, ...) remain for a client that already knows
exactly which step it wants, and they answer in their own leaner shapes.

```python
vidkit_actions()                                   # what can I ask for?
vidkit_run("plan",  story="./my-story")            # what would be built?
vidkit_run("build", story="./my-story", out="./video")
vidkit_run("verify", story="./my-story", out="./video")
```

Two differences worth knowing: `vidkit_run` **never raises for an expected refusal** -- "no
story given", "that folder has no video.yaml", "the snapshot answers a different window" all
come back as `ok: false` plus a `failure` block -- while the individual tools raise a tool
error for the same conditions. And only `vidkit_run` reports `progress` as data.

`vidkit_run(timeout=...)` bounds the call in seconds (default `1800`, or the
`VIDKIT_RUN_TIMEOUT` environment variable; `0` disables it). A build that overruns is
refused with a manifest rather than leaving the client hanging. Where the platform has no
`SIGALRM` (a non-main thread) the bound is not installed and the call runs as before.

The job contract has its own page: [Job contract](job-contract.md) -- the manifest keys, the
failure vocabulary, the exit codes.

`only` accepts stage names: `data, panels, stills, capture, narration, clips, concat, render,
verify`. `from_stage` runs that stage *and everything after it* — `only` and `from_stage`
together are refused. `refresh: true` re-adds the `data` stage, so the source is asked again
instead of reusing the on-disk snapshot; without it a `data`-skipping build re-renders from
the snapshot and **refuses** when the snapshot answers a different provider or window (R-B3,
see [the provider guide](../authoring/provider-guide.md#datasets-snapshots-and-staleness)).

## Resources

| URI | Contents |
|---|---|
| `vidkit://actions` | the action vocabulary: what each `vidkit_run` action does, as data |
| `vidkit://docs/index` | the documentation **module router** (table of contents) |
| `vidkit://docs/modules` | the machine-readable module route table |
| `vidkit://docs/{name}` | a named document as Markdown, module-routed (e.g. `vidkit://docs/spec-reference`) |

### Docs routing

Docs are organised into modules (`docs/foundations/`, `docs/authoring/`, …) and routed by
`docs/modules.yaml`. `vidkit_docs` accepts a **bare stem** (`concepts`, `spec-reference`),
a **module-qualified** name (`authoring/spec-reference`), or a path — so an agent never
needs to know the folder. Call it with no name to get the router; call
`vidkit_docs_index` for the structured module map (and suggested reading order).

## Suggested agent flow

```
vidkit_run("doctor")              → is the environment ready?
vidkit_run("init", story=DIR)     → scaffold a story that builds unedited
vidkit_run("plan", story=DIR)     → what will be built, and how long?
vidkit_docs("concepts")           → understand the model before editing a spec
vidkit_run("build", story=DIR)    → render (returns the verification report)
vidkit_run("verify", story=DIR)   → re-check after a manual edit
```

That is the whole loop, and every step is `vidkit_run` with a different `action` — the
argument shape never changes, so an agent that has one call implemented has all of them.

When a run fails, `failure.message` names the failing stage/step and `failure.hint` names the
next command worth running; `vidkit_docs("troubleshooting")` maps the message to a cause and
a fix. With `progress=true` the same lines arrive on stderr as they happen, which is how you
tell a slow build from a stuck one.

## Registering with a client

### VS Code (workspace)

`.vscode/mcp.json`:

```json
{
  "servers": {
    "vidkit": {
      "type": "stdio",
      "command": "${workspaceFolder}/.venv/bin/python",
      "args": ["-m", "vidkit.mcp_server"],
      "env": { "PYTHONPATH": "${workspaceFolder}/vidkit" }
    }
  }
}
```

### Other MCP clients (Claude Desktop, Claude Code, …)

`.mcp.json` / `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "vidkit": {
      "command": "/path/to/.venv/bin/python",
      "args": ["-m", "vidkit.mcp_server"],
      "env": { "PYTHONPATH": "/path/to/vidkit" }
    }
  }
}
```

If vidkit is **installed** (`pip install vidkit[mcp]`), drop the `env`/`PYTHONPATH` and use
`"command": "vidkit-mcp", "args": []`.

### HTTP

Start `vidkit-mcp --transport streamable-http --port 8765`, then point the client at
`http://127.0.0.1:8765/mcp`.

## Design notes

- The work lives in plain `tool_*` functions (data in, data out) that never print or exit, so
  they are reusable and unit-tested. `build_server()` only wraps them as MCP tools/resources
  via the SDK's `FastMCP` high-level server.
- Tool schemas are inferred from type hints, so function signatures are the single
  source of truth.
- All paths are resolved to absolute paths; `spec` is optional, defaulting to the
  alphabetically first `examples/*/video.y*ml` under the repo root (`examples/hello-world`
  today).
- Expected failures raise `ToolError`, which the MCP layer reports as a tool error with the
  message — no stack traces reach the client.

## Testing

```bash
PYTHONPATH=vidkit python -m pytest vidkit/tests/test_mcp.py -q
```

The tests exercise the tool functions directly and, when `mcp` is installed, the server's
tool/resource registration and a tool-call round-trip.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `The MCP server needs the 'mcp' package` | extra not installed | `pip install "vidkit[mcp]"` |
| Client shows the server as failed | wrong `command`/`PYTHONPATH` | use an absolute python path and `PYTHONPATH` to the vidkit folder |
| `no spec given and no spec found` | no default spec | pass `spec`, or `story` to `vidkit_run` |
| A `vidkit_run` call returns `ok: false` | expected refusal, not a crash | read `failure.kind` and `failure.hint` |
| Tools appear but builds fail | environment | call `vidkit_doctor` first |
