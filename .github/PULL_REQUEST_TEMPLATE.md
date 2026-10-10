## What

A one-line summary of the change and the problem it solves.

## Why

The motivation. Reference an issue (`#NN`) if there is one, and the invariant
(`AGENTS.md` §2) or decision (`docs/plan/DECISIONS.md`) the change respects —
or, if it touches one, say so plainly and justify it.

## How it was verified

The exact commands and their results, per the evidence rule in `AGENTS.md`:

```bash
python3 -m pytest tests -q        # or the targeted subset
vidkit build examples/hello-world/video.yaml   # if the pipeline changed
```

## Docs

Which documents this changes or invalidates — `docs/modules.yaml` routes the
doc set; `HISTORY.md` is append-only and must carry an entry.
