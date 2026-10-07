# Provenance — what a build is

`verify.json` answers **"is this honest?"** `provenance.json` answers **"what is this?"**
Every build writes both, to the same `OUT/_build/` directory, because a `.mp4` found a year
later needs an author as much as it needs a clean bill of health.

## What it records

Every field is measured, never assumed.

| Field | What it is |
|---|---|
| `schema` | the shape's version; a reader refuses a record it does not understand |
| `vidkit`, `runtime` | the engine's version, and the Python/platform/machine it ran on |
| `action` | which job wrote it (`build`, `capture`, `tts`, ...) |
| `story`, `spec`, `spec_sha256` | which story, which file, and that file's bytes |
| `spec_sha256` | the *short* sha256 of `video.yaml` — edit the spec and the hash moves |
| `provider`, `provider_sha256` | the provider module, and a hash of its source |
| `timeframe` | the resolved window, with `source` (`spec`, `story`, `override`) and label |
| `tools` | each of `ffmpeg`, `ffprobe`, `rsvg-convert`, `pdftoppm`, `gs`: present?, version, path |
| `stages` | the pipeline stages that actually ran, in order |
| `datasets` | dataset name → sha256 of the snapshot it was rendered from |
| `degraded` | dataset name → why it was not live (R-B5) |
| `started_at`, `built_at`, `seconds` | UTC timestamps and the measured wall clock |

A tool that is missing is recorded as `"present": false` rather than omitted. "We did not
check" and "it was not there" are different facts, and only the second one is useful later.

## Reading it

```bash
vidkit provenance SPEC [--out OUT]        # prose
vidkit --json provenance SPEC             # the same record, as JSON
vidkit --json run provenance --story DIR  # the job manifest carrying it
```

and over MCP, `vidkit_provenance` (or `vidkit_run` with `action: "provenance"`).

All four surfaces read the same file the build wrote. None of them derives a record from
the current state of the tree — a record assembled at *read* time would describe today
while appearing to describe last week's build, which is the fabrication the engine
refuses everywhere else.

## Where a verify touches it

`vidkit verify` **reads** `provenance.json`; it never writes one. Its job is to describe a
build somebody else made, and inventing a fresh identity for that build would be
dishonest. The record therefore always reports `action: "build"` even when read from a
verify, and `report.facts.provenance` carries a copy of the identifying fields (version,
spec, hash, when, tool versions) so a single `verify.json` is enough to say which build it
describes.

A verify on a tree with no provenance gets `provenance: null` in its manifest, and the
acceptance checks still run. Provenance is a *fact*, not a check: its absence does not fail
a build that never happened.

## Refusals

| Situation | What happens |
|---|---|
| no `provenance.json` yet | the read returns `null`; the `provenance` action returns `ok: false` with a hint to run `build` first |
| the file is truncated or is not JSON | the read returns `null` — never a half-parsed guess |
| `schema` is not the one this vidkit knows | the read returns `null`; a record from a future vidkit is not misread as a current one |

## Why not just put this in `verify.json`

They change for different reasons. Verification is a judgement about *this* build's claims
and is re-run whenever the checks are; provenance is a fact about *which* build this is and
is written once, by the build itself. Merging them would mean a re-verify rewrites the
build's identity, which is exactly the drift this module exists to prevent.
