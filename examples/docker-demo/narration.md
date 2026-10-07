# docker-demo — narration

## Scene 0 — A row goes in · 0:00–0:06

The first command talks to a real Postgres, running in a container the spec declared.

**A container, not an impression of one.** **The database was started from a pinned image.**

## Scene 1 — The same row comes out · 0:06–0:12

The second command runs inside the same container, so it sees what the first one did.

**One environment, used twice.** **A fresh container per command would have shown a different database.**

## Scene 2 — The schema agrees · 0:12–0:18

The container is removed afterwards, on every path, whether the build succeeded or not.

**The environment is torn down in a finally.** **Nothing is left running on the host.**
