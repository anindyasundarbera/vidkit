"""Shared runtime context passed to providers and pipeline stages."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import SpecError
from .ffmpeg import Ffmpeg, Rsvg, Shell
from .secrets import Secrets
from .spec import Spec


@dataclass
class Context:
    spec: Spec
    root: Path                     # the video folder (spec location)
    out_dir: Path                  # where renders are written
    log: list[str] = field(default_factory=list)
    shell: Shell = field(default_factory=Shell)
    secrets: Secrets = field(default_factory=Secrets)
    #: Takes the caller has promoted, as ``{"<capture>/<take>"}``. A studio sitting
    #: chooses the moment to film; a later build must honour that choice instead of
    #: re-shooting the page and overwriting it, which would put a moment the client
    #: never picked into the film while the record still named the one it did.
    selections: set[str] = field(default_factory=set)
    _provider_module: Any = None   # set only while provider.datasets() is running

    def selected_take(self, capture: str) -> int | None:
        """Which take of ``capture`` was chosen, or ``None`` if none was.

        The highest wins: a caller may promote take 2 and later prefer take 3
        after seeing the render, and the second choice is the one it means.
        """
        best: int | None = None
        prefix = f"{capture}/"
        for marker in self.selections:
            if not marker.startswith(prefix):
                continue
            try:
                n = int(marker[len(prefix):])
            except ValueError:
                continue
            best = n if best is None else max(best, n)
        return best

    def secret(self, name: str, default: str | None = None) -> str | None:
        """Read a declared secret.

        The only supported way for a provider to reach a credential, so that
        every value the engine knows about can be redacted from anything it
        prints.
        """
        return self.secrets.get(name, default)

    def require_secret(self, name: str) -> str:
        """Read a secret, or raise naming the variable that is missing."""
        if not self.secrets.has(name):
            raise SpecError(
                f"provider needs the environment variable {name}, which is not set"
                " — export it, or declare it optional in the spec's `provider:` block")
        return self.secrets[name]

    # -- declared degradation (R-B5) --------------------------------------- #
    def degrade(self, name: str, why: str) -> None:
        """Declare that the dataset ``name`` is real but reduced.

        Called by a provider that could not reach its source and fell back to
        its own deterministic default. The build keeps going — a missing model
        must never hang a render — but the fact is recorded, and
        ``guard.require_live_data`` turns it into a verify failure.
        """
        self.degraded[str(name)] = str(why)
        self.warn(f"dataset {name!r} is degraded: {why}")

    @property
    def degraded(self) -> dict[str, str]:
        return self.spec.degraded

    @property
    def project(self):
        return self.spec.project

    @property
    def story(self):
        return self.spec.story

    @property
    def stories_dir(self) -> Path:
        """The folder holding the sibling stories of this one (usually the repo)."""
        return self.root.parent

    @property
    def repo_stories(self) -> list[Path]:
        """Sibling story folders — one per ``video.y*ml`` under the parent folder.

        What makes this a *studio* rather than a one-off script: a provider can
        scope itself to "all the stories in this repo", not just itself.
        """
        try:
            return sorted({p.parent for p in self.stories_dir.glob("*/video.y*ml")})
        except OSError:
            return []

    @property
    def timeframe(self):
        """The one resolved window this build is about (``None`` if undeclared).

        Providers hand ``ctx.timeframe.as_prompt()`` to their data source instead
        of hard-coding ``?days=28`` — see `docs/authoring/stories-and-timeframes.md`.
        """
        return self.spec.timeframe

    @property
    def build(self) -> Path:
        return self.out_dir / "_build"

    @property
    def captures(self) -> Path:
        return self.out_dir / "_capture"

    @property
    def capture_artifacts(self) -> Path:
        """Where a capture's real downloaded bytes are kept (R-C3)."""
        return self.captures / "artifacts"

    @property
    def stills(self) -> Path:
        return self.build / "stills"

    @property
    def panels_dir(self) -> Path:
        return self.build / "panels"

    @property
    def execs(self) -> Path:
        """Recorded command streams — one asciinema v2 ``.cast`` per exec step."""
        return self.build / "exec"

    @property
    def clips(self) -> Path:
        return self.build / "clips"

    @property
    def wavs(self) -> Path:
        return self.build / "wavs"

    @property
    def data_dir(self) -> Path:
        return self.build / "data"

    @property
    def ffmpeg(self) -> Ffmpeg:
        return Ffmpeg(self.shell)

    @property
    def rsvg(self) -> Rsvg:
        return Rsvg(self.shell)

    def ensure_dirs(self) -> None:
        for d in (self.out_dir, self.build, self.captures, self.capture_artifacts,
                  self.stills, self.panels_dir, self.clips, self.wavs, self.data_dir,
                  self.execs):
            d.mkdir(parents=True, exist_ok=True)

    def facts(self) -> dict[str, Any]:
        """The identity of this build — what it is about, and when.

        Providers merge this into their datasets so a video's own data can quote
        the window it covers without re-deriving it.
        """
        out: dict[str, Any] = {
            "title": self.spec.project.title,
            "slug": self.spec.project.slug,
            "story": self.spec.story.slug if self.spec.story else self.spec.project.slug,
        }
        if self.spec.timeframe is not None:
            out["timeframe"] = self.spec.timeframe.to_dict()
        if self.spec.degraded:
            out["degraded"] = dict(self.spec.degraded)
        return out

    def info(self, message: str) -> None:
        self.log.append(message)
        print(f"[vidkit] {message}")

    def warn(self, message: str) -> None:
        self.log.append(f"WARN {message}")
        print(f"[vidkit] WARN {message}")

    def get(self, key: str, default: Any = None) -> Any:
        return self.spec.__dict__.get(key, default)
