# Executing real commands

vidkit can film **real work in a real terminal**. You declare a command, the build runs it
inside a bounded sandbox, records the terminal byte-for-byte, and the finished video shows
what actually happened — not an animation of what would have happened.

This is the same promise as [capture](./capture-guide.md), applied to the shell instead of
the browser: the frame is evidence, and the evidence is checked.

---

## 1. The two-line version

```yaml
exec:
  steps:
    - label: test
      cmd: "pytest -q"

scenes:
  - n: 0
    shots:
      - {exec: test, effect: hold}
```

`vidkit build video.yaml` runs `pytest -q` under `bwrap(1)`, records it, and renders the
recording. `verify.json` gains a `commands` section naming the command, its exit code, its
duration, and the backend it ran in.

---

## 2. What "recorded" means

vidkit opens a **real PTY**, not a pipe. The distinction is not cosmetic. A program that
calls `isatty()` changes what it prints — progress bars collapse, colours vanish, prompts
are suppressed, `git` stops paginating. Recording a pipe would produce a transcript **no
terminal ever displayed**, which is a fabrication in the sense I7 forbids. The recording is
what a human at that terminal would have seen.

The recording is stored as an **asciinema cast** (`.cast`) beside the spec's other build
output, and redacted before it lands on disk. `vidkit` replays it through
[`vidkit.terminal`](../modules.yaml), a small CSI parser that reconstructs the screen at
each moment and renders it to SVG. Nothing about the screen is authored by you.

---

## 3. The `exec:` block

```yaml
exec:
  allow_network: false        # default: no command may reach the network
  max_timeout: 300            # default: no command may declare more than this
  steps:
    - label: test             # required; the only handle a shot has
      cmd: "pytest -q"        # required; string = shell script, list = argv
      cwd: "."                # relative to the spec's directory
      backend: bubblewrap     # bubblewrap | local
      network: false          # asks to open the network; see §5
      timeout: 60             # must be <= max_timeout
      expect_exit: [0]        # a build passes if the exit code is in this list
      env: {CI: "1"}          # added to a fixed base environment
      reads: ["/srv/data"]    # extra read-only mounts
      cols: 100               # recorded terminal width
      rows: 30                # recorded terminal height
```

### `cmd`: script or argv, never a surprise

`cmd:` has exactly two forms, and the difference is deliberate:

| You write | vidkit runs | What it means |
|---|---|---|
| `cmd: "pytest -q"` | `["/bin/sh", "-c", "pytest -q"]` | **You are declaring a shell script.** Pipes, `&&`, globs and `$VAR` all work. |
| `cmd: ["pytest", "-q"]` | `["pytest", "-q"]` | **You are declaring an argv.** No shell, no expansion, no quoting bugs. |

There is no `shell:` field, on purpose. If you want a different interpreter, say so with a
list: `cmd: ["/bin/bash", "-c", "…"]`. A third spelling would only make it possible to be
unclear about what runs.

### `expect_exit`: a failure can be declared

```yaml
- label: broken
  cmd: "pytest --nonsense"
  expect_exit: [4]
```

A non-zero exit fails the build **unless** the spec said it would happen. That is the
honest way to film an error message: you are asserting the error is the point, rather than
pretending a failing command succeeded. `verify` checks that the observed code is in the
declared list.

### `at`: which second of the recording a shot shows

A command that runs for eight seconds is more interesting at second six than at second one.
A shot may name a moment:

```yaml
- {exec: test, effect: hold, at: 6.0}
```

vidkit keeps the recorded frames up to that second and holds the one the screen had settled
on. With no `at:`, the shot ends on the final screen.

---

## 4. Backends, and the honest default

| Backend | Isolation | When |
|---|---|---|
| `bubblewrap` | Linux user/mount/PID/network namespaces via `bwrap(1)`. System roots are mounted **read-only**; only the working directory is writable. No daemon, no root. | the default |
| `local` | none — the command runs unconfined on this host | when you genuinely need the host, and say so |

`bubblewrap` is the default because it is a single unprivileged binary. If the sandbox
cannot run, `vidkit plan` says so at **load time** rather than failing once the camera is
rolling. There are two ways it can fail, and they are not the same failure:

```
a: the spec declares `backend: bubblewrap`, but the sandbox cannot run on this host:
   bwrap(1) is not on PATH. Fix the environment, or declare `backend: local` to say
   honestly that the command runs unconfined here.
```

```
a: the spec declares `backend: bubblewrap`, but the sandbox cannot run on this host:
   bwrap: setting up uid map: Permission denied — the kernel is refusing unprivileged
   user namespaces, which on Ubuntu 24.04 is the AppArmor restriction. Lift it with
   `sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0`, or declare
   `backend: local` to run unconfined on purpose.
```

The second is the one worth knowing about, because it looks like a broken install and is
not: `bubblewrap` is present and correct, and the kernel will not let it make a namespace.
`vidkit doctor` reports it directly, along with the workaround, and **`available: false` in
its `backends` block means "cannot run", not "not found"** — the check actually starts a
sandbox around `/bin/true` rather than looking for the binary.

### Read is wide, write is narrow

Inside the sandbox the command can read `/usr`, `/bin`, `/lib` and friends, and can write
only inside the working directory, which is bound at `/work`. A command may therefore load
a library and may **not** edit the repository it was run from.

---

## 5. Two layers of network permission

Network is off unless two separate things are true:

1. the **command** says `network: true`, and
2. the **spec** says `exec.allow_network: true`.

If the command asks and the spec has not allowed it, the build is refused at load time with
a message that names the field you have to widen:

```
curl: the command declares `network: true` but the spec's `exec.allow_network` is
false — a command that reaches the network is a promise about a machine, so widen
the spec deliberately rather than by accident
```

The two layers exist so that adding one network command cannot silently widen a build that
was supposed to be offline.

---

## 6. What the guard promises

```yaml
guard:
  require_sandbox: true          # default true
  require_exec_success: true     # default true
```

`require_sandbox` defaults to **true**, which means a spec that runs commands is claiming by
default that they were contained. Running unconfined is therefore an act of writing
(`backend: local` plus `require_sandbox: false`), never an omission. A silent unconfined run
is a bug in the spec, not a setting.

---

## 7. What `verify.json` records

Every declared command lands in the report:

| Check | Fails when |
|---|---|
| every declared command ran | a step was declared and never executed |
| every command exited as declared | an observed exit code is not in `expect_exit` |
| commands ran sandboxed | a command ran under `local` while `require_sandbox` is true |

Alongside the checks, the `commands` section of the report carries the argv, the resolved
working directory, the backend, the exit code, and the measured duration. Secrets found in
the environment are redacted, and the redaction is **length-preserving** so the cast stays
playable.

---

## 8. What this is not

- **Not a shell tool.** vidkit does not accept a command at build time from an agent. Every
  command is written in the spec, reviewed like any other line of the spec, and re-checked
  at load.
- **Not a general job runner.** The output caps (256 KiB per stream) and the `max_timeout`
  ceiling exist so that a runaway command cannot fill a disk or hold a build hostage.
- **Not interactive.** There is no way to answer a prompt. A command that waits on stdin
  will time out, and the timeout is recorded honestly as `timed_out`.

---

## 9. Troubleshooting

| Message | Cause | Fix |
|---|---|---|
| `bwrap(1) is not on PATH` | bubblewrap not installed | install it, or declare `backend: local` **and** `guard.require_sandbox: false` |
| `setting up uid map: Permission denied` / `Failed RTM_NEWADDR` | bubblewrap is installed, but Ubuntu 24.04's AppArmor rule denies unprivileged user namespaces | `sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0`, or `backend: local` |
| `the command declares network: true but the spec's exec.allow_network is false` | one-layer permission | add `exec.allow_network: true` if the network really is required |
| `timeout 600s exceeds the spec's exec.max_timeout of 300s` | a command outlives the policy ceiling | raise `exec.max_timeout`, or lower the command's `timeout` |
| `working directory does not exist` | `cwd:` is relative to the spec's directory | fix the path; the loader checks it before the build |
| `exec step 'x' is not declared` | a shot names a label no step defines | check spelling — labels are the only handle a shot has |
| `declares no exec: steps` | a shot uses `exec:` but the spec has no `exec:` block | add the block |
| the video shows one blank frame | the recording was empty | the command produced no output; check the cast beside the build |
