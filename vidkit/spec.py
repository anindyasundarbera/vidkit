"""The video *spec*: a small, declarative description of a video.

A spec is plain data (YAML or JSON). It names the scenes, what each scene shows
(a captured screen, a generated chart, or a static still), how narration is
sourced, and the guardrails the finished cut must satisfy. Nothing in a spec
executes code; the optional ``provider`` module supplies data and custom panels.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any

from .errors import SpecError
from .timeframe import Timeframe, find_window_claims, parse_timeframe

try:  # optional
    import yaml as _yaml
except Exception:  # pragma: no cover
    _yaml = None


# --------------------------------------------------------------------------- #
@dataclass
class Project:
    title: str
    slug: str
    output: str
    fps: int = 30
    size: tuple[int, int] = (1920, 1080)
    min_seconds: float = 180.0
    max_seconds: float = 300.0

    @property
    def width(self) -> int:
        return self.size[0]

    @property
    def height(self) -> int:
        return self.size[1]


@dataclass
class Voice:
    engine: str = "piper"                 # "piper" | "none"
    model: str | None = None              # path to a piper .onnx
    length_scale: float = 1.0
    executable: str | None = None         # override the python/piper entry point
    sentence_silence: float | None = None


@dataclass
class Narration:
    source: str | None = None             # markdown file with "## Scene N …" + **bold** spoken lines
    inline: dict[int, str] = field(default_factory=dict)  # scene n -> text


@dataclass
class Shot:
    """One visual beat. Exactly one of still/capture/chart is set."""
    kind: str                             # "still" | "capture" | "chart"
    ref: str                              # path, capture name, or chart name
    effect: str = "hold"                  # "hold" | "zoom"
    weight: float = 1.0                   # share of the scene's duration


@dataclass
class Scene:
    n: int
    shots: list[Shot]
    title: str = ""


@dataclass
class Assert:
    selector: str
    contains: str | None = None
    equals: str | None = None
    exists: bool = False


@dataclass
class Action:
    kind: str                             # select|click|fill|press|wait|scroll|eval
    selector: str | None = None
    value: str | None = None
    seconds: float | None = None
    script: str | None = None


@dataclass
class Capture:
    name: str
    url: str
    actions: list[Action] = field(default_factory=list)
    assert_: Assert | None = None
    viewport: tuple[int, int] | None = None
    device_scale: float = 2.0
    wait_until: str = "networkidle"
    wait_after: float = 0.0
    full_page: bool = False


@dataclass
class Chart:
    name: str
    kind: str
    dataset: str
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class Guard:
    min_seconds: float | None = None
    max_seconds: float | None = None
    banned: list[str] = field(default_factory=list)        # forbidden substrings in on-screen text + narration
    required: list[str] = field(default_factory=list)      # required substrings (any one? all — we require all)
    require_live_mode: bool = False
    require_audio: bool = True                             # a silent cut must be declared, never accidental


STORY_MANIFEST = "story.yaml"


@dataclass
class Story:
    """The identity of a story: the folder it lives in, plus what it declares.

    A story is a *folder* (``video.yaml`` + ``narration.md`` + ``provider.py``).
    It may additionally declare itself with a ``story.yaml`` manifest; when that
    is present it is validated strictly, and when it is absent the identity is
    synthesised from the folder so there is only ever one code path (D1).
    """

    root: Path
    slug: str
    title: str = ""
    timeframe: Timeframe | None = None
    manifest: Path | None = None          # set only when story.yaml was read
    owner: str = ""
    description: str = ""

    @property
    def declared(self) -> bool:
        """True when a manifest file backed this identity."""
        return self.manifest is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "title": self.title or self.slug,
            "root": str(self.root),
            "declared": self.declared,
            "manifest": str(self.manifest) if self.manifest else None,
            "owner": self.owner,
            "description": self.description,
            "timeframe": self.timeframe.to_dict() if self.timeframe else None,
        }


@dataclass
class Spec:
    project: Project
    scenes: list[Scene]
    voice: Voice = field(default_factory=Voice)
    narration: Narration = field(default_factory=Narration)
    provider: str | None = None
    captures: list[Capture] = field(default_factory=list)
    charts: list[Chart] = field(default_factory=list)
    guard: Guard = field(default_factory=Guard)
    story: Story | None = None
    timeframe: Timeframe | None = None
    root: Path = field(default_factory=Path.cwd)

    # -- lookups ------------------------------------------------------------ #
    def capture(self, name: str) -> Capture | None:
        return next((c for c in self.captures if c.name == name), None)

    def chart(self, name: str) -> Chart | None:
        return next((c for c in self.charts if c.name == name), None)

    def scene(self, n: int) -> Scene | None:
        return next((s for s in self.scenes if s.n == n), None)

    @property
    def size(self) -> tuple[int, int]:
        return self.project.size


# --------------------------------------------------------------------------- #
def _load_raw(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        if _yaml is None:
            raise SpecError(
                f"{path.name} is YAML but PyYAML is not installed "
                "(pip install pyyaml, or use a .json spec)"
            )
        return _yaml.safe_load(text)
    return json.loads(text)


def _slugify(text: str) -> str:
    out = [c if c.isalnum() else "-" for c in text.strip().lower()]
    slug = "".join(out).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "story"


def load_story(root: Path | str, *, default_as_of: Any = None) -> Story:
    """Read (or synthesise) the identity of the story in ``root``.

    ``story.yaml`` when present is validated strictly — a typo in a manifest
    must fail loudly, not be silently ignored. When it is absent the identity is
    derived from the folder name, so a bare folder is still a first-class story
    that an agent can be handed (D1, R-A1).
    """
    root = Path(root).resolve()
    manifest = root / STORY_MANIFEST
    if not manifest.exists():
        return Story(root=root, slug=_slugify(root.name), title=root.name)

    raw = _load_raw(manifest)
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise SpecError(f"{STORY_MANIFEST} must be a mapping")

    known = {"title", "slug", "timeframe", "owner", "description"}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise SpecError(
            f"{STORY_MANIFEST}: unknown key(s) {', '.join(unknown)} — "
            f"allowed: {', '.join(sorted(known))}"
        )
    title = str(raw.get("title", "") or root.name)
    slug = _slugify(str(raw.get("slug", "") or root.name))
    timeframe = parse_timeframe(raw.get("timeframe"), where=f"{STORY_MANIFEST}.timeframe",
                                source="story", default_as_of=default_as_of)
    return Story(root=root, slug=slug, title=title, timeframe=timeframe,
                 manifest=manifest, owner=str(raw.get("owner", "")),
                 description=str(raw.get("description", "")))


def _shots(raw: dict[str, Any], where: str) -> Shot:
    present = [k for k in ("still", "capture", "chart") if k in raw]
    if len(present) != 1:
        raise SpecError(f"{where}: a shot needs exactly one of still/capture/chart")
    kind = present[0]
    return Shot(kind=kind, ref=str(raw[kind]),
                effect=str(raw.get("effect", "hold")),
                weight=float(raw.get("weight", 1.0)))


def _action(raw: dict[str, Any], where: str) -> Action:
    if "type" in raw:
        kind, body = str(raw["type"]), raw
    elif len(raw) == 1:
        kind, body = next(iter(raw.items()))[0], raw
        body = {**raw, **(raw[kind] if isinstance(raw[kind], dict) else {})} if isinstance(raw.get(kind), dict) else raw
    else:
        raise SpecError(f"{where}: action must be {{type: ...}} or a single key")
    sel = body.get("selector")
    val = body.get("value")
    secs = body.get("seconds")
    script = body.get("script")
    if kind == "select":
        return Action("select", selector=sel, value=str(val))
    if kind in {"click", "fill", "press"}:
        return Action(kind, selector=sel, value=None if val is None else str(val))
    if kind == "wait":
        return Action("wait", seconds=float(secs if secs is not None else val or 1.0))
    if kind == "scroll":
        return Action("scroll", selector=sel, value=None if val is None else str(val))
    if kind == "eval":
        return Action("eval", script=str(script or val))
    raise SpecError(f"{where}: unknown action type {kind!r}")


def load_spec(path: Path | str, *,
              timeframe: Timeframe | None = None,
              as_of: date | None = None) -> Spec:
    """Read a spec, resolve its story and its timeframe, and validate.

    ``timeframe`` (already resolved) is an explicit caller override — the CLI's
    ``--timeframe``/``--days`` flags and the MCP job contract both arrive here,
    and override whatever the spec declared. ``as_of`` is the fallback end date
    for a relative window that did not write one down.
    """
    path = Path(path)
    if not path.exists():
        raise SpecError(f"spec not found: {path}")
    raw = _load_raw(path)
    if not isinstance(raw, dict):
        raise SpecError("spec root must be a mapping")

    pj = raw.get("project") or {}
    for key in ("title", "slug", "output"):
        if key not in pj:
            raise SpecError(f"project.{key} is required")
    size = pj.get("size", [1920, 1080])
    project = Project(
        title=str(pj["title"]), slug=str(pj["slug"]), output=str(pj["output"]),
        fps=int(pj.get("fps", 30)), size=(int(size[0]), int(size[1])),
        min_seconds=float(pj.get("min_seconds", 180)),
        max_seconds=float(pj.get("max_seconds", 300)),
    )
    if project.min_seconds >= project.max_seconds:
        raise SpecError("project.min_seconds must be < max_seconds")

    v = raw.get("voice") or {}
    voice = Voice(engine=str(v.get("engine", "piper")), model=v.get("model"),
                  length_scale=float(v.get("length_scale", 1.0)),
                  executable=v.get("executable"),
                  sentence_silence=v.get("sentence_silence"))

    n = raw.get("narration") or {}
    narration = Narration(source=n.get("source"),
                          inline={int(k): str(v2) for k, v2 in (n.get("inline") or {}).items()})

    captures: list[Capture] = []
    for c in raw.get("captures") or []:
        ap = c.get("assert") or {}
        assert_ = None
        if ap:
            assert_ = Assert(selector=str(ap["selector"]),
                             contains=ap.get("contains"), equals=ap.get("equals"),
                             exists=bool(ap.get("exists", False)))
        captures.append(Capture(
            name=str(c["name"]), url=str(c["url"]),
            actions=[_action(a, f"capture {c['name']}") for a in (c.get("actions") or [])],
            assert_=assert_,
            viewport=tuple(c["viewport"]) if c.get("viewport") else None,
            device_scale=float(c.get("device_scale", 2.0)),
            wait_until=str(c.get("wait_until", "networkidle")),
            wait_after=float(c.get("wait_after", 0.0)),
            full_page=bool(c.get("full_page", False)),
        ))

    charts = [Chart(name=str(c["name"]), kind=str(c["kind"]),
                    dataset=str(c.get("dataset", c["name"])),
                    options=dict(c.get("options") or {}))
              for c in (raw.get("charts") or [])]

    scenes: list[Scene] = []
    for s in raw.get("scenes") or []:
        shots = [_shots(sh, f"scene {s.get('n')}") for sh in (s.get("shots") or [])]
        if not shots:
            raise SpecError(f"scene {s.get('n')} has no shots")
        scenes.append(Scene(n=int(s["n"]), shots=shots, title=str(s.get("title", ""))))
    if not scenes:
        raise SpecError("spec defines no scenes")
    scenes.sort(key=lambda x: x.n)

    g = raw.get("guard") or {}
    guard = Guard(min_seconds=g.get("min_seconds"), max_seconds=g.get("max_seconds"),
                  banned=[str(x) for x in (g.get("banned") or [])],
                  required=[str(x) for x in (g.get("required") or [])],
                  require_live_mode=bool(g.get("require_live_mode", False)),
                  require_audio=bool(g.get("require_audio", True)))

    root = path.parent.resolve()
    spec = Spec(project=project, scenes=scenes, voice=voice, narration=narration,
                provider=raw.get("provider"), captures=captures, charts=charts,
                guard=guard, root=root)

    spec.story = load_story(root, default_as_of=as_of)
    spec.timeframe = _resolve_timeframe(raw, spec, timeframe, as_of)

    _validate(spec)
    return spec


def _resolve_timeframe(raw: dict[str, Any], spec: Spec, override: Timeframe | None,
                       as_of: date | None) -> Timeframe | None:
    """One resolved window, and where it came from. Precedence: override > spec > story."""
    declared = parse_timeframe(raw.get("timeframe"), where="timeframe",
                               source="spec", default_as_of=as_of)
    if override is not None:
        return replace(override, source="override")
    if declared is not None:
        return declared
    return spec.story.timeframe


def _validate(spec: Spec) -> None:
    """Cross-reference checks that catch typos before any expensive rendering."""
    cap_names = {c.name for c in spec.captures}
    chart_names = {c.name for c in spec.charts}
    known_provider = spec.provider is not None
    for sc in spec.scenes:
        for sh in sc.shots:
            if sh.kind == "still":
                target = (spec.root / sh.ref)
                if not target.exists() and not (spec.root / ".." / sh.ref).exists():
                    # tolerate provider-supplied stills only if a provider exists
                    if not known_provider:
                        raise SpecError(f"scene {sc.n}: still not found: {sh.ref}")
            elif sh.kind == "capture" and sh.ref not in cap_names and not known_provider:
                raise SpecError(f"scene {sc.n}: capture {sh.ref!r} is not defined")
            elif sh.kind == "chart" and sh.ref not in chart_names and not known_provider:
                raise SpecError(f"scene {sc.n}: chart {sh.ref!r} is not defined")
    if spec.narration.source is None and not spec.narration.inline:
        raise SpecError("spec needs narration.source or narration.inline")

    _validate_timeframe(spec)


def _validate_timeframe(spec: Spec) -> None:
    """Refuse a narration whose window the resolved timeframe cannot guarantee.

    The verify check (R-F7) compares the window narration *states* against the
    resolved window, so narration that pins an endpoint is only checkable when
    the spec pinned that same endpoint. Two cases are caught here, before any
    expensive rendering, rather than at verify time:

    * a **floating** window — ``{days: 28}`` with no ``as_of`` — resolves against
      today, so narration may only mention the day count, never a date;
    * a window narration states that the spec does not declare at all.
    """
    if spec.narration.source is None:
        return
    text = _narration_text(spec)
    if text is None:
        return
    claims = find_window_claims(text, as_of=spec.timeframe.end if spec.timeframe else None)
    if not claims:
        return
    if spec.timeframe is None:
        first = claims[0]
        raise SpecError(
            f"narration states a {first.label()} window (`{first.raw}`) but the "
            "spec declares no timeframe — add `timeframe: {days: N, as_of: YYYY-MM-DD}` "
            "or `timeframe: {start: ..., end: ...}`, or drop the dates from the narration"
        )
    if spec.timeframe.floating:
        dated = [c for c in claims if c.exact or c.end_anchor]
        if dated:
            raise SpecError(
                f"narration states the window `{dated[0].raw}` but the spec's "
                "timeframe is relative and pins no `as_of`, so it would mean a "
                "different window tomorrow — add `as_of: YYYY-MM-DD` to the spec "
                "timeframe, or use `timeframe: {start: ..., end: ...}`"
            )


def _narration_text(spec: Spec) -> str | None:
    """The narration prose, or ``None`` when it cannot be read yet."""
    if spec.narration.source:
        path = spec.root / spec.narration.source
        if not path.exists():
            raise SpecError(f"narration file not found: {spec.narration.source}")
        return path.read_text(encoding="utf-8")
    if spec.narration.inline:
        return "\n".join(spec.narration.inline[k] for k in sorted(spec.narration.inline))
    return None
