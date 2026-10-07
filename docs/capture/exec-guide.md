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
recording. `verify.json` gains an `exec` section naming the command, its exit code, its
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
      backend: bubblewrap     # bubblewrap | docker | local
      environment: db         # required by, and only honoured by, `backend: docker`
      network: false          # asks to open the network; see §5
      timeout: 60             # must be <= max_timeout
      expect_exit: [0]        # a build passes if the exit code is in this list
      env: {CI: "1"}          # added to a fixed base environment
      reads: ["/srv/data"]    # extra read-only mounts
      cols: 100               # recorded terminal width
      rows: 30                # recorded terminal height
```

A spec may also declare **environments** — services a command runs inside. They are a
property of the `exec` stage rather than a stage of their own, and they are covered in
§10:

```yaml
environment:
  - name: db
    image: postgres:16-alpine
    command: ["postgres", "-c", "fsync=off"]
    env: {POSTGRES_PASSWORD: demo}
    ports: ["5432:5432"]
    volumes: ["./seed.sql:/docker-entrypoint-initdb.d/seed.sql"]
    ready: [pg_isready, -U, postgres]
    ready_timeout: 90
    timeout: 180
    network: false
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
| `docker` | a container from an image the spec declares. Its own filesystem, its own PID namespace, no view of the host beyond the read-only project bind. | when the command needs a **service** — a database, a broker, a second machine — and needs it to survive across commands; see §10 |
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

Alongside the checks, the `exec` section of the report carries the argv, the resolved
working directory, the backend, the container it ran in, the exit code, and the measured
duration. Secrets found in the environment are redacted, and the redaction is
**length-preserving** so the cast stays playable.

The report also carries an `environments` section — one entry per declared environment, with
the image **by digest**, whether it became ready and for how long, how long it lived, and how
it was torn down. See §10.

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
| `docker(1) is not on PATH` | no Docker client | install it; the error names the rung that failed |
| `the docker daemon does not answer` | Docker installed, no daemon | start it — this is a service to start, not an install |
| `the image could not be pulled` | the image name is wrong, or there is no network | check the tag; a digest is recorded in the report |
| `is not a terminal` / exit 125 | Docker was asked for a TTY with no stdin to attach it to | a vidkit bug, not a spec bug — please report it |

---

## 10. Environments: services a command runs inside

An `exec` step runs *a command*. Some commands need something to talk to — a database with a
row in it, a broker with a queue, a second machine with a broken resolver. Declaring that
thing as an **environment** is what makes the difference between filming a program and
filming a system.

```yaml
environment:
  - name: db
    image: postgres:16-alpine
    env: {POSTGRES_PASSWORD: demo, POSTGRES_DB: demo}
    ready: [pg_isready, -U, postgres]
    ready_timeout: 90
    timeout: 180

exec:
  steps:
    - {label: write, cmd: [...], backend: docker, environment: db}
    - {label: read,  cmd: [...], backend: docker, environment: db}
```

Both steps run **inside the same container**. That is the whole point: a `read` that runs in a
*new* container would find an empty database, and the video would be a claim about a system
that never existed. `verify.json` records the container name on every command so the
sharing is visible rather than assumed.

### The lifecycle

1. **start** — one container per environment, created from the image, labelled so that a
   leaked one can be found and removed by name.
2. **await readiness** — see below.
3. **bind** — each declared command is bound to the environment it named, so the command, its
   readiness probe, and its log capture all address the same container.
4. **run** — every `backend: docker` step is `docker exec`'d into it.
5. **capture logs** — `docker logs` is the container's recorded output, kept beside the cast.
6. **teardown** — in a `finally`, so a failed check, a crash, or an interrupt still removes
   it. Teardown is reported, not assumed: `verify.json` says whether the container was
   stopped and removed, and with what detail.

### Readiness must *hold*

`ready:` is an argv (never a shell line) that vidkit runs inside the container until it
succeeds. One success is **not** enough. A container that has just started often answers
before it is actually serving — Postgres is the canonical example: `pg_isready` returns 0 at
~1.3 s against the *bootstrap* server, which is shut down at ~1.45 s, and a real `SELECT 1`
only succeeds from ~1.84 s. A readiness gate that sampled once would declare the database up
and hand the next command a server on its way down.

vidkit therefore requires the command to succeed **and keep succeeding for 0.75 s**
(`READY_HOLD`). The report distinguishes the two failure shapes, because they mean different
things:

| `ready_detail` says | What happened |
|---|---|
| *answered for 0.98s without a single failure* | ready, and the hold is a measured fact |
| *answered once, then stopped holding … its last try exited 1* | the service was there and went away — the exact bootstrap-server trap |
| *nothing became ready within 90s* | it never answered at all |

### Rules that keep it honest

- **The environment's own environment is the environment's.** A container does **not**
  inherit the host's `PATH`, `HOME`, `LANG` or `PS1`; it gets the image's, plus exactly what
  the spec declared. vidkit removes `HOME` from the *client's* environment for the same
  reason in reverse — otherwise the client's unreadable `~/.docker/config.json` prints a
  warning, and that warning would be filmed as if the container had said it.
- **A command, its readiness probe, and its logs all address the same container.** Otherwise
  the gate would be gating something else.
- **The project is bound read-only.** A command cannot edit the repository it was filmed
  from. Writes belong in `/tmp` or a declared volume.
- **No network unless the environment asks.** `--network none` is the default.
- **`--rm` is deliberately absent.** A self-removing container cannot be asked for its logs
  afterwards, and the logs are evidence.
- **An environment nothing references is refused at load time** — not warned about. A
  container that starts and is torn down without appearing in any frame would be work done
  for nothing, and would put a service on the machine for no reason.
- **The image is identified by digest** in the report. A tag is a name that can move; the
  digest is what actually ran.

### What "sandboxed" means for a container

`backend: local` still means unconfined, and `require_sandbox: true` still fails it. But
"confined" is not a synonym for `bubblewrap`: a container has the image's own filesystem, its
own PID namespace, and no view of the host beyond the read-only bind, which is a *stronger*
boundary than namespaces around a host process. The verifier reads the set of confining
backends from the engine rather than spelling one name, precisely so that a Docker run is
not reported as a lie.

Docker is probed by **running** a container, never by looking for the binary: a client on
`PATH` with a dead daemon is a client that cannot confine anything. `vidkit doctor` reports
the three Docker questions separately, because they have three different fixes:

```
docker       client:  /usr/bin/docker
             daemon:  daemon answers (server 29.7.2)
             container: `docker run --rm hello-world` succeeded
```

### What this is not, again

- **Not a Docker socket on the sandbox.** vidkit drives Docker from the *host* side; nothing
  it films ever sees `/var/run/docker.sock`.
- **Not a compose replacement.** There is no dependency graph, no scaling, no healthcheck
  DSL. One environment is one container, and the commands that name it share it.
- **Not a way to reach the host network.** `ports:` publishes to the host on purpose; a step
  that only talks to the container needs no port at all, and the demo example declares none.
