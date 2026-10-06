"""Shared runtime context passed to providers and pipeline stages."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .ffmpeg import Ffmpeg, Rsvg, Shell
from .spec import Spec


@dataclass
class Context:
    spec: Spec
    root: Path                     # the video folder (spec location)
    out_dir: Path                  # where renders are written
    log: list[str] = field(default_factory=list)
    shell: Shell = field(default_factory=Shell)

    @property
    def project(self):
        return self.spec.project

    @property
    def build(self) -> Path:
        return self.out_dir / "_build"

    @property
    def captures(self) -> Path:
        return self.out_dir / "_capture"

    @property
    def stills(self) -> Path:
        return self.build / "stills"

    @property
    def panels_dir(self) -> Path:
        return self.build / "panels"

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
        for d in (self.out_dir, self.build, self.captures, self.stills,
                  self.panels_dir, self.clips, self.wavs, self.data_dir):
            d.mkdir(parents=True, exist_ok=True)

    def info(self, message: str) -> None:
        self.log.append(message)
        print(f"[vidkit] {message}")

    def warn(self, message: str) -> None:
        self.log.append(f"WARN {message}")
        print(f"[vidkit] WARN {message}")

    def get(self, key: str, default: Any = None) -> Any:
        return self.spec.__dict__.get(key, default)
