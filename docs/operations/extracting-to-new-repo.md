# Extracting vidkit to its own repository

> **Status: the extraction has happened.** This repo *is* the standalone project. This
> document is kept as (a) the record of how the split was designed, and (b) the checklist for
> the **remaining OneAquaHealth-side** work — moving the story out of OAH and pointing it at
> this package. Steps 1–6 and the post-extraction checklist below are **done here** and are
> listed as history; steps 7 and the "Known couplings" section still describe work in the
> OAH repo. See [`../plan/HISTORY.md`](../plan/HISTORY.md) for what was actually executed.

vidkit was developed inside the OneAquaHealth repo but was designed to be lifted out. This
document is the checklist for turning `vidkit/` into a standalone project, plus the
generic-first refactors worth doing at the same time.

## What is already self-contained

- **No imports of the host project.** Nothing in `vidkit/` imports OneAquaHealth code.
  The coupling is one-directional: a *story* provider imports the host, and the example
  spec points at host paths.
- **No hard-coded host paths** in the library. Paths come from the spec and the `Context`.
- **Packaging is ready**: `pyproject.toml` defines the package, extras, console script, and
  pytest config.
- **Tests are pure** and run without external tools.

So the library can move as-is. The only repo-specific artifacts are the example and a couple
of example-only couplings.

## Step 1 — copy the library *(done)*

```bash
# from the OneAquaHealth repo root
mkdir -p /tmp/vidkit-extract
cp -r vidkit/vidkit          /tmp/vidkit-extract/
cp -r vidkit/tests           /tmp/vidkit-extract/
cp    vidkit/pyproject.toml  /tmp/vidkit-extract/
cp    vidkit/README.md       /tmp/vidkit-extract/
cp -r vidkit/docs            /tmp/vidkit-extract/
cp    vidkit/.gitignore      /tmp/vidkit-extract/
```

Do **not** copy `.out/`, `__pycache__/`, or `.pytest_cache/` (the `.gitignore` covers them).

## Step 2 — decide what to do with the example *(decided and executed)*

The OneAquaHealth example was the best onboarding material, but it depended on the host — and
a story belongs to the repo that owns its data. The **decision was to remove it** from here
and ship a self-contained `examples/hello-world/` instead (Step 5).

What happened: `examples/oneaquahealth/` was deleted from this repo on 2026-10-06 and backed
up to `~/Projects/oneaquahealth-story-backup/` for its eventual move into the OneAquaHealth
repo. `examples/hello-world/` is now the only example, and it is host-free.

## Step 3 — generic-first refactors *(done — see the table for what changed)*

These small changes remove the last host-specific fingerprints from the library. They are
optional but improve the standalone story.

| Change | Where | Why |
|---|---|---|
| Grep the library for host strings (`oneaquahealth`, `oah`, `yam`, `fhir`, `video/_capture`) | `vidkit/vidkit/**` | the library should contain none; move any you find into the example |
| Make the example's voice path configurable | `examples/oneaquahealth/video.yaml` | it currently points into the host's `video/_capture/voices` |
| Add `examples/hello-world/` | new | a zero-dependency smoke test for new users |

Verify the library is clean:

```bash
grep -rniE "oneaquahealth|oah_|yam-|fhir" vidkit/vidkit/ || echo "library is host-free"
```

## Step 4 — initialise the repo *(done, 2026-10-06)*

```bash
cd /tmp/vidkit-extract
git init
# a permissive license for a tool meant to be reused:
printf 'MIT License\n\nCopyright (c) %s\n' "$(date +%Y)" > LICENSE   # replace with full text
git add . && git commit -m "Initial import of vidkit"
```

Suggested additions for a standalone repo:

```
.
├── vidkit/            (the package)
├── tests/             (unit tests)
├── docs/              (this documentation set)
├── examples/
│   └── hello-world/   (self-contained; the only example)
├── pyproject.toml
├── README.md
├── LICENSE
├── CHANGELOG.md
└── .github/workflows/ci.yml
```

## Step 5 — add a self-contained smoke example *(done — `examples/hello-world/`)*

So `vidkit` can be exercised with **zero external services**. `examples/hello-world/`:

`video.yaml`
```yaml
project: {title: "Hello vidkit", slug: hello, output: hello.mp4,
          min_seconds: 1, max_seconds: 30}
voice: {engine: none}
narration:
  inline: {0: "Hello from vidkit. This video was built from a spec."}
scenes:
  - n: 0
    shots: [{still: card.svg}]
guard:
  required: ["vidkit"]
```

`card.svg` — a minimal 1920×1080 card. Then:

```bash
vidkit build examples/hello-world/video.yaml --out /tmp/hello
```

This exercises spec loading, stills, clips, concat, render, and verify with no browser, no
TTS, and no network.

## Step 6 — CI *(done — `.github/workflows/ci.yml`, jobs `test` and `build-example`)*

`.github/workflows/ci.yml` (sketch):

```yaml
name: ci
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.12"}
      - run: sudo apt-get update && sudo apt-get install -y ffmpeg librsvg2-bin
      - run: pip install -e ".[dev]"
      - run: pytest -q
      - run: |
          vidkit doctor
          video=${{ runner.temp }}/out
          vidkit build examples/hello-world/video.yaml --out "$video"
          test -f "$video/hello.mp4"
```

The unit tests need no binaries; the smoke build needs `ffmpeg` + `rsvg-convert` only.

## Step 7 — point the OneAquaHealth story back at the new package

> **Not done — this is the remaining OAH-side work.** When the story is moved into the OAH
> repo (it is preserved at `~/Projects/oneaquahealth-story-backup/`), point it at the
> installed package:

```bash
pip install -e /path/to/vidkit            # or: pip install vidkit
```

Then the moved story's `video.yaml` and `provider.py` work unchanged, since they import
`vidkit`, not a local path.

## Versioning contract

Decide one of:

- **Published package only (chosen)** — the story repo keeps only the story and depends on
  the installed `vidkit`. Cleanest, and it is what this repo's `ROADMAP.md` §1 records as the
  decision of record.
- **Vendored** — keep the library in-repo and re-sync from upstream. Then record the version
  so drift is visible. Explicitly *not* chosen: it re-vendors source into a consumer.

The library's public surface to keep stable: `load_spec`, `Context`, `panels.register`,
`panels.render`, `narration.parse_scene_script`, `narration.build_srt`, `assembler.run`,
`verify.verify_output`, and the `PanelDoc`/svg helpers. Changes there are breaking.

## Post-extraction checklist — **all green, 2026-10-06**

- [x] `vidkit/` contains no host-specific strings — `grep -rniE "oneaquahealth|oah_|fhir"` → 0
- [x] `pip install -e .` succeeds and `vidkit doctor` runs
- [x] `pytest -q` passes (44 tests, no external tools)
- [x] `vidkit build examples/hello-world/video.yaml` produces a verified mp4 with no network
- [x] `docs/` links resolve (relative links between docs) — 0 broken links
- [x] `README.md` links to `docs/`
- [x] LICENSE added (MIT)
- [x] CI green — `.github/workflows/ci.yml`
- [ ] The OneAquaHealth story builds against the installed package *(after the OAH move)*

## MCP server

vidkit ships an MCP server (`vidkit/mcp_server.py`, console script `vidkit-mcp`). Once the
package is installed, a client needs no repo checkout:

```json
{
  "servers": {
    "vidkit": { "type": "stdio", "command": "vidkit-mcp", "args": [] }
  }
}
```

Add the `mcp` extra (`pip install "vidkit[mcp]"`) and list it in the repo's optional
dependencies. See [`mcp-server.md`](mcp-server.md) for the full surface.

**One portable detail to preserve:** the server redirects Python-level stdout to stderr while
tools run (`mcp_server.stdout_to_stderr`). If you refactor that away, chatty library output
will corrupt the JSON-RPC channel over stdio. There is a regression test for it.

## Known example-only couplings to carry over

- `examples/oneaquahealth/provider.py` imported `oah_ingestion` modules (in `_ingest_sample`)
  and read `demo/sample_iot_telemetry.json` from the host repo.
- `examples/oneaquahealth/video.yaml` set `voice.model` to a path inside the host repo and
  URLs on `127.0.0.1:8000`/`:8090`.
- The example's `assets/*.svg` were authored for that story.

None of these belonged in the library; all are fine in a story that documents its
prerequisites. They are now gone from this repo along with the example.
