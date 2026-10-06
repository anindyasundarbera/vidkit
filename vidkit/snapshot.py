"""Dataset snapshots and the staleness contract (R-B3).

Every stage after ``data`` reads its numbers from disk. That is what lets a
build be resumed — re-render the panels for a new title, or the clips for a new
effect, without asking the provider for anything again. It is also exactly the
kind of convenience that can quietly lie: re-render from a snapshot taken for a
*different window and the video says "the last 90 days" over 30 days of data.

So the snapshot is not just files in a folder. Beside them vidkit writes
``data/_snapshot.json`` recording **what request produced them** — the provider,
a hash of the provider's source, and the resolved window — together with a hash
of each dataset. A stage that is about to reuse them compares its own request
against that record and refuses when they disagree.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import SpecError

#: The index file, inside the data directory. Leading underscore so it can never
#: collide with a dataset named after itself.
SNAPSHOT_FILE = "_snapshot.json"

#: What we are willing to say about staleness in an error message.
HINT = ("re-run the `data` stage (drop it from --only, or pass --refresh) to "
        "fetch it again")


def _digest(obj: Any) -> str:
    """A stable hash of a JSON-able value. Key order must not matter."""
    blob = json.dumps(obj, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def digest_text(text: str) -> str:
    """A short hash of a written dataset, so a reader can tell it changed."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def file_digest(path: Path | None) -> str | None:
    """A short hash of a file's bytes, or ``None`` when it is not there."""
    if path is None or not Path(path).exists():
        return None
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


@dataclass
class Snapshot:
    """The record of what the datasets on disk were computed from."""

    path: Path
    request: dict[str, Any]          # provider, provider_sha256, timeframe

    datasets: dict[str, str]         # name -> content hash
    degraded: dict[str, str]         # name -> why it is not live data

    @classmethod
    def read(cls, data_dir: Path) -> "Snapshot | None":
        path = Path(data_dir) / SNAPSHOT_FILE
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return cls(path=path,
                   request=dict(raw.get("request") or {}),
                   datasets=dict(raw.get("datasets") or {}),
                   degraded=dict(raw.get("degraded") or {}))

    def write(self) -> None:
        self.path.write_text(json.dumps({
            "version": 1,
            "request": self.request,
            "datasets": self.datasets,
            "degraded": self.degraded,
        }, indent=1, sort_keys=True), encoding="utf-8")


def request_key(*, provider: str | None, provider_path: Path | None,
                timeframe: Any) -> dict[str, Any]:
    """The question the datasets are an answer to.

    Deliberately narrow. The provider and the window are what change the
    *numbers*; changing a chart's title or a scene's effect does not, and should
    not force a refetch.
    """
    return {
        "provider": provider or "",
        "provider_sha256": file_digest(provider_path),
        "timeframe": timeframe.to_dict() if timeframe is not None else None,
    }


def fingerprint(request: dict[str, Any]) -> str:
    """The request condensed to one comparable value."""
    return _digest(request)


def describe_difference(recorded: dict[str, Any], wanted: dict[str, Any]) -> str:
    """A human sentence naming *what* changed, not just that something did."""
    bits = []
    for key in ("provider", "provider_sha256", "timeframe"):
        a, b = recorded.get(key), wanted.get(key)
        if a == b:
            continue
        if key == "provider_sha256":
            bits.append("the provider's source changed" if a else "no provider is recorded")
        elif key == "timeframe":
            bits.append(f"the window changed ({_tf(a)} -> {_tf(b)})")
        else:
            bits.append(f"the provider changed ({a or 'none'} -> {b or 'none'})")
    return "; ".join(bits) or "the recorded request differs"


def _tf(value: Any) -> str:
    if isinstance(value, dict):
        return f"{value.get('start')} to {value.get('end')} ({value.get('days')} days)"
    return "undeclared"


def load_datasets(data_dir: Path, needed: set[str] | None = None) -> dict[str, Any]:
    """Read the snapshotted datasets. ``needed`` limits what must be present."""
    data_dir = Path(data_dir)
    found: dict[str, Any] = {}
    for f in sorted(data_dir.glob("*.json")):
        if f.name == SNAPSHOT_FILE:
            continue
        try:
            found[f.stem] = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    if needed:
        absent = sorted(n for n in needed if n not in found)
        if absent:
            raise SpecError(
                "no snapshot for dataset(s): " + ", ".join(absent)
                + f" — {HINT}")
    return found


def verify_fresh(recorded: Snapshot | None, wanted: dict[str, Any], *,
                 data_dir: Path) -> None:
    """Refuse to re-render from datasets that answer a different question."""
    if recorded is None:
        raise SpecError(
            "no dataset snapshot in " + str(Path(data_dir))
            + f" — the `data` stage has not run here, so there is nothing to "
              f"re-render from; {HINT}")
    if recorded.request != wanted:
        raise SpecError(
            "dataset snapshot is stale: " + describe_difference(recorded.request, wanted)
            + f" — {HINT}")
