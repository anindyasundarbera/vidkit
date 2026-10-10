# Security

This document tells you how to report a security issue in vidkit, and what we
promise to do about it. vidkit renders videos and drives browsers, terminals,
and Docker containers on your behalf, so a vulnerability here can mean a
vulnerability on the machine that runs it. We take that seriously.

## Supported versions

| Version | Supported |
| ------- | --------- |
| `1.x` (latest) | ✅ |
| `0.x`        | ❌ |

Only the latest released line receives security fixes. If you are on an older
release, upgrade first; a fix will not be backported to an unsupported line.

## Reporting a vulnerability

**Do not open a public issue.** Security reports are handled privately so a fix
can land before the details are public.

1. Email <anindyasundarbera@gmail.com> (or the maintainer address in the git
   history) with the subject `[vidkit] security report`.
2. Include: the affected version, a minimal reproduction (a spec, a provider, a
   command line), and what you believe an attacker could do with it.
3. You will receive an acknowledgement within 5 business days and a substantive
   update within 30 days.

We will credit the reporter unless you ask not to be.

## What we treat as a vulnerability

- Anything that lets a crafted **spec** execute arbitrary code outside the
  declared sandbox, or escape the sandbox (`bubblewrap`/Docker) that `exec`
  steps run in. A spec is plain data (invariant I8) and must never run code.
- Anything that lets an **unauthenticated** HTTP MCP transport reach the agent
  surface (browser drive, command execution, media rendering) from the network.
  The stdio transport is a local process and out of scope; the HTTP transports
  bind loopback by default and refuse non-loopback binds without `--expose`.
- A provider that can make the engine render data it did not actually measure
  (a violation of the "honest by construction" guarantee) — provided the
  provider is a *trusted* module, not an attacker-controlled one. A malicious
  provider is already arbitrary code by design and is out of scope.

## Out of scope

- A malicious **provider** module. Providers are imported Python code (invariant
  I8 limits code execution to the named provider, and no further). If you can
  run arbitrary code as a provider, you already have arbitrary code.
- Denial of service by requesting a very long or very expensive render. vidkit
  is a batch tool; resource limits are a deployment concern.
- Sandbox escapes that require root or an already-compromised kernel.

## Acknowledgements

We are grateful to everyone who reports responsibly. Thank you.
