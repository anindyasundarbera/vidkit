"""The secret contract (R-B4).

A provider often needs credentials to reach its data source. Those values are
the one thing in a build that must never end up on screen, in a log, in a
snapshot, or in a report. This module makes that a property of the *engine*
rather than a rule every provider has to remember:

* a need is **declared** — by the spec's ``provider:`` block, by the provider
  module's ``secrets()``, or both;
* values are resolved from the environment only, never from a file vidkit
  writes;
* anything the engine prints goes through :meth:`Secrets.redact`, so a value
  that leaks out of a provider's exception message is masked before it is
  shown.

vidkit is **read-only** by contract. A provider that declares it writes back to
its source system is refused at load time (``write_back: true``) — the guarantee
is worth more than the convenience.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from .errors import SpecError

#: What a redacted value is replaced with. Never make this look like a secret.
REDACTED = "***"


@dataclass
class SecretNeed:
    """One declared need: a variable name, whether it is mandatory, and why."""

    name: str
    required: bool = True
    why: str = ""

    def label(self) -> str:
        kind = "required" if self.required else "optional"
        return f"{self.name} ({kind})" + (f" — {self.why}" if self.why else "")


@dataclass
class Secrets:
    """The declared needs, and what the environment had to say about them.

    Constructed empty and filled in two passes — first from the spec (which is
    read before anything else), then from the provider module once it is loaded.
    A name declared twice keeps the *strictest* requirement and the first
    explanation that was given.
    """

    needs: dict[str, SecretNeed] = field(default_factory=dict)
    values: dict[str, str] = field(default_factory=dict)
    checked: bool = False

    # -- declaration ------------------------------------------------------- #
    def declare(self, names, *, required: bool = True, why: str = "") -> None:
        """Register one or more needs. Accepts a str, a list, or a mapping."""
        if isinstance(names, str):
            pairs = {names: why}
        elif isinstance(names, dict):
            pairs = dict(names)
        else:
            pairs = {str(n): why for n in names}
        for name, note in pairs.items():
            name = str(name).strip()
            if not name:
                raise SpecError("a secret name cannot be empty")
            old = self.needs.get(name)
            if old is None:
                self.needs[name] = SecretNeed(name, required, str(note or ""))
            else:
                # a name declared twice is as strict as the strictest voice
                old.required = old.required or required
                if not old.why and note:
                    old.why = str(note)

    def resolve(self, env: dict[str, str] | None = None) -> "Secrets":
        """Read the declared names from the environment. Idempotent."""
        env = os.environ if env is None else env
        self.values = {n: str(env[n]) for n in self.needs if n in env and env[n] != ""}
        self.checked = True
        return self

    # -- use --------------------------------------------------------------- #
    def get(self, name: str, default: str | None = None) -> str | None:
        """The value, or ``default``. Never raises for an undeclared name."""
        return self.values.get(name, default)

    def __getitem__(self, name: str) -> str:
        value = self.values.get(name)
        if value is None:
            raise SpecError(f"secret {name!r} was not provided by the environment")
        return value

    def has(self, name: str) -> bool:
        return name in self.values

    def missing_required(self) -> list[SecretNeed]:
        """Declared-as-required needs the environment did not supply, in order."""
        return [n for n in self.needs.values() if n.required and n.name not in self.values]

    # -- never leak -------------------------------------------------------- #
    def redact(self, text: str) -> str:
        """Mask every resolved value that appears in ``text``.

        Applied to provider exception messages, which are the realistic way a
        credential escapes: `requests` happily puts a URL — token and all — into
        its error string.
        """
        if not text:
            return text
        out = str(text)
        # longest first, so a value that contains another is masked whole
        for value in sorted(self.values.values(), key=len, reverse=True):
            if value:
                out = out.replace(value, REDACTED)
        return out

    def redact_bytes(self, data: bytes) -> bytes:
        """Mask every resolved value appearing in ``data``, length-preserving.

        The bytes overload of :meth:`redact`, and it exists for one reason: a
        recorded terminal is a *published* terminal. A command that echoes an
        environment variable — or that gets its token printed back at it by a
        failing ``curl`` — would otherwise put the credential in the video and in
        the ``.cast`` next to it.

        Replacement is **in place and byte-for-byte the same length**, so the
        recording stays playable: a cast is a stream of timed cursor movements,
        and shortening it would shear every escape sequence that follows.
        """
        if not data:
            return data
        out = data
        for value in sorted(self.values.values(), key=len, reverse=True):
            if not value:
                continue
            raw = value.encode("utf-8")
            if raw in out:
                # a single-byte mask keeps the offset arithmetic intact; a
                # multi-byte replacement would shift everything after it
                out = out.replace(raw, b"*" * len(raw))
        return out

    def describe(self) -> list[str]:
        """Masked, printable lines — one per declared need, for ``doctor``."""
        lines = []
        for need in self.needs.values():
            if need.name in self.values:
                state = f"set ({len(self.values[need.name])} chars)"
            elif need.required:
                state = "NOT SET — required"
            else:
                state = "not set — optional"
            why = f"  {need.why}" if need.why else ""
            lines.append(f"{need.name:24s} {state}{why}")
        return lines
