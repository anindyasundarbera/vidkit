# Your first video from a fresh clone

This walkthrough starts with nothing but a clone and ends with a verified `.mp4` that
reports its own provenance. It uses only the CLI and the MCP server, in that order, and it
never touches the bundled example.

**Time:** about five minutes, most of it `pip` and the first render. **Network:** none after
the install, unless your provider fetches something.

---

## 1. Install

```bash
git clone https://github.com/anindyasundarbera/vidkit
cd vidkit
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
```

`python3`, not `python` — the engine only ever needs the interpreter, and `python` does not
exist on every machine.

Two external binaries do the rendering. On Debian/Ubuntu:

```bash
sudo apt-get install ffmpeg librsvg2-bin
```

The extras are additive and independent: `[capture]` adds Playwright (for filming a real
UI), `[tts]` adds Piper (for a voice), `[mcp]` adds the MCP server. You need none of them
for this walkthrough.

## 2. Check the machine

```bash
vidkit doctor
```

`doctor` with no argument checks the environment and nothing else. It prints one line per
tool with a `[PASS]`/`[FAIL]`, and exits non-zero if a **required** tool is missing. ffmpeg
and rsvg-convert are required; ffprobe, pdftoppm, gs, Playwright, and Piper are optional and
their absence is reported as such.

```bash
vidkit --json doctor | jq '.ok, .tools[] | select(.required==false)'
```

## 3. Scaffold a story

```bash
vidkit init my-story --title "My first video" --days 14 --as-of 2026-10-06
```

That writes five files:

```
my-story/
  video.yaml     the spec
  story.yaml     the story's identity: title, slug, timeframe, owner
  provider.py    a working provider that measures a few real numbers
  narration.md   the script, with the scene headers vidkit parses
  (nothing else — no assets, no cache)
```

It refuses to overwrite anything already present. The story is **runnable as written**: the
next two commands need no edits at all.

## 4. Look before you render

```bash
vidkit plan my-story/video.yaml
```

`plan` prints every scene, its shots, the guards that apply, and the estimated runtime —
without rendering a frame. This is where you catch a spec mistake, not after a render.

```bash
vidkit --json plan my-story/video.yaml | jq '.plan | {scenes, est_seconds}'
```

## 5. Make it yours

Two files actually matter.

**`story.yaml`** is the story's identity — a stable handle your agent can hold, and the
window the cut is about:

```yaml
title: My first video
slug: my-story
timeframe: {start: 2026-09-23, end: 2026-10-06}
owner: you
```

**`narration.md`** is the script. Each scene is a header vidkit parses, with spoken lines in
`**bold**` and `[stage directions]` that are ignored:

```markdown
## Scene 0 — A title · 0:00–0:04

**This is my first vidkit video.**

[hold on the card]

## Scene 1 — What it measured · 0:04–0:10

**Every number on screen came from `provider.py`, not from my typing.**
```

The header's times are a *claim* about the window. `vidkit verify` fails the build if the
narration states something the declared timeframe cannot support — see
[stories-and-timeframes.md](../authoring/stories-and-timeframes.md).

**`provider.py`** is how the numbers get in. It already works; change it when you have real
data:

```python
def datasets(ctx):
    return {"facts": {"rows": [["videos built", str(count)], ...]}}
```

and name it in the spec's `charts:` with a matching `dataset:`. See the
[provider guide](../authoring/provider-guide.md).

## 6. Build

```bash
vidkit build my-story/video.yaml
```

or, with an explicit output directory:

```bash
vidkit build my-story/video.yaml --out ./renders/first
```

You get:

```
my-story/
  story.mp4                    the video
  narration.srt                the captions
  _build/verify.json           "is this honest?" — every acceptance check
  _build/provenance.json       "what is this?" — spec hash, window, tools, when
  _build/data/*.json           the exact datasets that were rendered
  _build/panels/*.svg          the rendered panels
```

The build fails loudly rather than producing a video that breaks its own promises. If it
exits non-zero, `verify.json` says which check and
[troubleshooting.md](../operations/troubleshooting.md) maps the wording to a cause.

## 7. Read what it says about itself

```bash
vidkit verify my-story/video.yaml       # re-run the checks
vidkit provenance my-story/video.yaml   # what made this render
```

`provenance` is the one to keep: it names the spec and its hash, the window, the provider and
its hash, the version and path of every tool that rendered the video, the stages that ran,
and a UTC timestamp. Hand it to anyone who later asks "where did this `.mp4` come from?" —
see [provenance.md](../verification/provenance.md).

## 8. The same loop from an agent, over MCP

Start the server and point a client at it:

```bash
vidkit-mcp --transport stdio          # or: python3 -m vidkit.mcp_server
```

Then everything above is available as one contract. `vidkit_run` takes `{action, story, out}`
and returns a manifest whose keys never change, so a caller branches on `ok` rather than on
which command it happened to invoke.

```
vidkit_run(action="doctor")
vidkit_run(action="init",   story="./my-story", title="My first video", timeframe="14d")
vidkit_run(action="plan",   story="./my-story")
vidkit_run(action="build",  story="./my-story", out="./renders/first")
vidkit_run(action="verify", story="./my-story", out="./renders/first")
vidkit_run(action="provenance", story="./my-story", out="./renders/first")
```

A failure is **data**, never an exception:

```json
{
  "ok": false,
  "failure": {
    "kind": "spec",
    "message": "no video.yaml/spec.yaml inside /tmp/nope",
    "action": "build",
    "hint": "check the folder, or `init` a new story there"
  }
}
```

`vidkit_actions` lists the vocabulary; `vidkit://actions` is the same list as a resource.
`vidkit_docs` fetches any document by name, and `vidkit_docs_index` returns the
machine-readable route table — so an agent can teach itself without a human in the loop. See
[mcp-server.md](../operations/mcp-server.md) and the
[job contract](../operations/job-contract.md).

## 9. Where to go next

| You want to | Read |
|---|---|
| every field of `video.yaml` | [spec-reference.md](../authoring/spec-reference.md) |
| to film a real UI | [capture-guide.md](../capture/capture-guide.md) |
| your own charts | [panels-reference.md](../authoring/panels-reference.md) |
| to understand the stages | [pipeline.md](../foundations/pipeline.md) |
| a known-good pattern to copy | [recipes.md](../guides/recipes.md) |
| to wire an agent in | [mcp-server.md](../operations/mcp-server.md) |
| the bundled offline example | `examples/hello-world/` |
