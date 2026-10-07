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
from .ffmpeg import TRANSITIONS
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
    transition: str = "cut"               # "cut" | "fade" | "wipe" | "slide"
    transition_seconds: float = 0.5       # how long a dissolve lasts

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
    fit: str = "cover"                    # "cover" (crop) | "contain" (letterbox)
    weight: float = 1.0                   # share of the scene's duration


@dataclass
class Overlay:
    """A graphic composited over a scene's pictures (R-D4).

    Two kinds, and the difference is why the field exists at all:

    * ``banner`` — a strip drawn by the engine from the scene's own words. Costs
      no asset, cannot go stale, and is the right default for a lower-third.
    * ``image`` — a PNG or SVG the author supplies. Drawn as itself; a
      still that is not found is a load-time refusal, not a blank frame.

    An overlay never replaces the shot underneath. It says something *over* the
    product; it can never stand in for the product.
    """
    kind: str = "banner"                  # "banner" | "image"
    text: str = ""                       # banner subtitle (defaults to the scene title)
    kicker: str = ""                     # banner eyebrow text
    src: str | None = None               # image overlays: a path
    position: str = "bottom"             # "bottom" | "top"
    height: float = 0.16                 # banner share of the frame height
    opacity: float = 0.88
    fade: float = 0.4                    # seconds to fade in and out


OVERLAY_KINDS = {"banner", "image"}
OVERLAY_POSITIONS = {"top", "bottom"}


@dataclass
class Scene:
    n: int
    shots: list[Shot]
    title: str = ""
    overlay: Overlay | None = None


@dataclass
class Assert:
    selector: str
    contains: str | None = None
    equals: str | None = None
    exists: bool = False


@dataclass
class Action:
    kind: str                             # see ACTION_KINDS
    selector: str | None = None
    value: str | None = None
    seconds: float | None = None
    script: str | None = None
    timeout: float | None = None          # wait_for: how long to wait before refusing
    state: str | None = None              # wait_for: visible|attached|hidden|detached
    save_as: str | None = None            # download: artifact name inside _capture/artifacts
    assert_: Assert | None = None         # per-action check, run before the next action


# how a still is fitted to the frame (R-D5)
FITS = {"cover", "contain"}

ACTION_KINDS = frozenset({
    "select", "click", "fill", "press", "wait", "wait_for", "scroll", "eval",
    "download",
})

WAIT_STATES = frozenset({"visible", "attached", "hidden", "detached"})


@dataclass
class Artifact:
    """A file a capture produced — the *bytes*, not a filename on a slide."""
    name: str
    path: Path
    kind: str                             # "download" | "screenshot"
    bytes: int = 0


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
    storage_state: str | None = None      # R-C7: reuse a session instead of logging in
    deterministic: bool = True            # R-C8: freeze clock/locale/motion
    take: int = 1                         # R-C6: which take this capture is
    artifact: str | None = None           # R-C4: shoot the saved bytes instead of the URL
    allow_login: bool = False             # R-C7: a login form is only filmed on purpose


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
    require_live_data: bool = False                        # a degraded dataset must be declared, never accidental


@dataclass
class ProviderSpec:
    """How the spec names its provider, and what it promises about it (R-B4).

    Short form: ``provider: provider`` — the module name alone. Long form::

        provider:
          module: acme_metrics
          secrets: [ACME_TOKEN]
          write_back: false
    """
    module: str | None = None
    secrets: dict[str, bool] = field(default_factory=dict)   # name -> required
    write_back: bool = False

    def __bool__(self) -> bool:
        return bool(self.module)


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
    provider: ProviderSpec | None = None
    captures: list[Capture] = field(default_factory=list)
    charts: list[Chart] = field(default_factory=list)
    guard: Guard = field(default_factory=Guard)
    story: Story | None = None
    timeframe: Timeframe | None = None
    root: Path = field(default_factory=Path.cwd)
    degraded: dict[str, str] = field(default_factory=dict)   # dataset -> why it is not live

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

    @property
    def provider_name(self) -> str | None:
        """The provider module name, or ``None`` when the spec has no provider."""
        return self.provider.module if self.provider else None


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
    fit = str(raw.get("fit", "cover"))
    if fit not in FITS:
        raise SpecError(
            f"{where}: fit must be one of {', '.join(sorted(FITS))}, not {fit!r}"
        )
    return Shot(kind=kind, ref=str(raw[kind]),
                effect=str(raw.get("effect", "hold")),
                fit=fit,
                weight=float(raw.get("weight", 1.0)))


def _assert(raw: dict[str, Any], where: str) -> Assert:
    if "selector" not in raw:
        raise SpecError(f"{where}: an assertion needs a selector")
    return Assert(selector=str(raw["selector"]),
                  contains=None if raw.get("contains") is None else str(raw["contains"]),
                  equals=None if raw.get("equals") is None else str(raw["equals"]),
                  exists=bool(raw.get("exists", False)))


def _overlay(raw: Any, where: str) -> Overlay:
    if not isinstance(raw, dict):
        raise SpecError(f"{where}: overlay must be a mapping")
    kind = str(raw.get("kind", "banner"))
    if kind not in OVERLAY_KINDS:
        raise SpecError(f"{where}: overlay kind must be one of "
                        + ", ".join(sorted(OVERLAY_KINDS)) + f" (got {kind!r})")
    position = str(raw.get("position", "bottom"))
    if position not in OVERLAY_POSITIONS:
        raise SpecError(f"{where}: overlay position must be one of "
                        + ", ".join(sorted(OVERLAY_POSITIONS))
                        + f" (got {position!r})")
    src = raw.get("src")
    if kind == "image" and not src:
        raise SpecError(f"{where}: an image overlay needs a src")
    height = float(raw.get("height", 0.16))
    if not 0.04 <= height <= 0.5:
        raise SpecError(f"{where}: overlay height must be between 0.04 and 0.5 "
                        f"of the frame (got {height})")
    return Overlay(kind=kind, text=str(raw.get("text", "")),
                   kicker=str(raw.get("kicker", "")),
                   src=None if src is None else str(src),
                   position=position, height=height,
                   opacity=float(raw.get("opacity", 0.88)),
                   fade=float(raw.get("fade", 0.4)))


def _action(raw: dict[str, Any], where: str) -> Action:
    if "type" in raw:
        kind, body = str(raw["type"]), raw
    elif len(raw) == 1:
        kind = next(iter(raw))
        inner = raw[kind]
        body = {**raw, **inner} if isinstance(inner, dict) else raw
    else:
        raise SpecError(f"{where}: action must be {{type: ...}} or a single key")
    sel = body.get("selector")
    val = body.get("value")
    secs = body.get("seconds")
    script = body.get("script")
    timeout = body.get("timeout")
    check = (_assert(body["assert"], f"{where}: action {kind!r}")
             if body.get("assert") else None)
    if kind == "select":
        return Action("select", selector=sel, value=str(val), assert_=check)
    if kind in {"click", "fill", "press"}:
        return Action(kind, selector=sel,
                      value=None if val is None else str(val), assert_=check)
    if kind == "wait":
        return Action("wait", seconds=float(secs if secs is not None else val or 1.0),
                      assert_=check)
    if kind == "wait_for":
        state = str(body.get("state", "visible"))
        if state not in WAIT_STATES:
            raise SpecError(
                f"{where}: wait_for state must be one of "
                + ", ".join(sorted(WAIT_STATES)) + f" (got {state!r})")
        if not sel:
            raise SpecError(f"{where}: wait_for needs a selector")
        return Action("wait_for", selector=str(sel), state=state,
                      timeout=float(timeout if timeout is not None else 30.0),
                      assert_=check)
    if kind == "scroll":
        return Action("scroll", selector=sel,
                      value=None if val is None else str(val), assert_=check)
    if kind == "eval":
        return Action("eval", script=str(script or val), assert_=check)
    if kind == "download":
        if not sel:
            raise SpecError(f"{where}: download needs a selector to click")
        return Action("download", selector=str(sel),
                      value=None if val is None else str(val),
                      save_as=None if body.get("save_as") is None else str(body["save_as"]),
                      timeout=float(timeout if timeout is not None else 30.0),
                      assert_=check)
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
    transition = str(pj.get("transition", "cut")).lower()
    if transition not in TRANSITIONS and transition != "cut":
        raise SpecError(
            "project.transition must be one of cut, "
            + ", ".join(sorted(TRANSITIONS)) + f" (got {transition!r})")
    transition_seconds = float(pj.get("transition_seconds", 0.5))
    if transition != "cut" and not 0.05 <= transition_seconds <= 2.0:
        raise SpecError(
            "project.transition_seconds must be between 0.05 and 2.0 — a "
            f"transition is a beat between two states, not a shot of its own "
            f"(got {transition_seconds})")
    project = Project(
        title=str(pj["title"]), slug=str(pj["slug"]), output=str(pj["output"]),
        fps=int(pj.get("fps", 30)), size=(int(size[0]), int(size[1])),
        min_seconds=float(pj.get("min_seconds", 180)),
        max_seconds=float(pj.get("max_seconds", 300)),
        transition=transition, transition_seconds=transition_seconds,
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
        where = f"capture {c.get('name')!r}"
        ap = c.get("assert") or {}
        captures.append(Capture(
            name=str(c["name"]),
            url=str(c.get("url", "")),
            actions=[_action(a, where) for a in (c.get("actions") or [])],
            assert_=_assert(ap, where) if ap else None,
            viewport=tuple(c["viewport"]) if c.get("viewport") else None,
            device_scale=float(c.get("device_scale", 2.0)),
            wait_until=str(c.get("wait_until", "networkidle")),
            wait_after=float(c.get("wait_after", 0.0)),
            full_page=bool(c.get("full_page", False)),
            storage_state=None if c.get("storage_state") is None else str(c["storage_state"]),
            deterministic=bool(c.get("deterministic", True)),
            take=int(c.get("take", 1)),
            artifact=None if c.get("artifact") is None else str(c["artifact"]),
            allow_login=bool(c.get("allow_login", False)),
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
        ov = s.get("overlay")
        scenes.append(Scene(n=int(s["n"]), shots=shots,
                            title=str(s.get("title", "")),
                            overlay=_overlay(ov, f"scene {s.get('n')}")
                            if ov is not None else None))
    if not scenes:
        raise SpecError("spec defines no scenes")
    scenes.sort(key=lambda x: x.n)

    g = raw.get("guard") or {}
    guard = Guard(min_seconds=g.get("min_seconds"), max_seconds=g.get("max_seconds"),
                  banned=[str(x) for x in (g.get("banned") or [])],
                  required=[str(x) for x in (g.get("required") or [])],
                  require_live_mode=bool(g.get("require_live_mode", False)),
                  require_audio=bool(g.get("require_audio", True)),
                  require_live_data=bool(g.get("require_live_data", False)))

    provider = _provider_spec(raw.get("provider"))

    root = path.parent.resolve()
    spec = Spec(project=project, scenes=scenes, voice=voice, narration=narration,
                provider=provider, captures=captures, charts=charts,
                guard=guard, root=root)

    spec.story = load_story(root, default_as_of=as_of)
    spec.timeframe = _resolve_timeframe(raw, spec, timeframe, as_of)

    _validate(spec)
    return spec


def _provider_spec(raw: Any) -> ProviderSpec | None:
    """Accept both spellings of ``provider:``.

    ``provider: acme`` is the short form and means the same as
    ``provider: {module: acme}``. The long form is what lets a spec *declare*
    what the provider needs, so a missing credential is a `doctor` failure
    rather than a stack trace halfway through a render.
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        name = raw.strip()
        return ProviderSpec(module=name) if name else None
    if not isinstance(raw, dict):
        raise SpecError("provider: must be a module name or a mapping")
    unknown = sorted(set(raw) - {"module", "secrets", "write_back"})
    if unknown:
        raise SpecError("provider: unknown key(s): " + ", ".join(unknown)
                        + " — expected module, secrets, write_back")
    module = raw.get("module") or raw.get("name")
    secrets: dict[str, bool] = {}
    sec = raw.get("secrets")
    if isinstance(sec, dict):
        secrets = {str(k): bool(v) for k, v in sec.items()}
    else:
        for item in (sec or []):
            secrets[str(item)] = True
    if not module:
        # a block with nothing but `secrets` describes no provider at all
        if secrets or raw.get("write_back"):
            raise SpecError("provider: a `secrets` or `write_back` entry needs a `module`")
        return None
    return ProviderSpec(module=str(module).strip(),
                         secrets=secrets,
                         write_back=bool(raw.get("write_back", False)))


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
    if spec.provider is not None and spec.provider.write_back:
        raise SpecError(
            "the spec declares `provider.write_back: true`, but vidkit is read-only "
            "by contract — a provider may read from its source system and report on "
            "it, and nothing else")
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
        ov = sc.overlay
        if ov is not None and ov.kind == "image" and ov.src:
            if not (spec.root / ov.src).exists() and not (spec.root / ".." / ov.src).exists():
                raise SpecError(
                    f"scene {sc.n}: overlay image not found: {ov.src} — an overlay "
                    "is drawn from a file that exists, never invented")
    if spec.narration.source is None and not spec.narration.inline:
        raise SpecError("spec needs narration.source or narration.inline")

    _validate_captures(spec)
    _validate_timeframe(spec)


def _validate_captures(spec: Spec) -> None:
    """Refuse captures that could only fail after a browser had been opened.

    A capture that *cannot* succeed is a spec error, and the operator should learn
    that from loading the file, not from a stack trace forty seconds into a run.
    """
    # A download may be filmed by a *later* capture: the capture that has a page
    # open produces the bytes, and a separate artifact capture films them. So the
    # set of filmable names is collected across the whole spec, not per capture.
    downloads = {a.save_as for c in spec.captures for a in c.actions
                 if a.kind == "download" and a.save_as}
    seen: dict[str, int] = {}
    for cap in spec.captures:
        where = f"capture {cap.name!r}"
        if cap.name in seen:
            raise SpecError(
                f"{where}: a second capture with the same name — the screenshot "
                "path would be overwritten by whichever ran last")
        seen[cap.name] = 1
        if cap.take < 1:
            raise SpecError(f"{where}: take must be >= 1 (got {cap.take})")
        if cap.artifact and cap.url:
            raise SpecError(
                f"{where}: `artifact:` and `url:` are mutually exclusive — an "
                "artifact capture films a file this same capture downloaded, so "
                "it has nothing to navigate to. Drop `url:`.")
        if cap.artifact and cap.artifact not in downloads:
            raise SpecError(
                f"{where}: artifact {cap.artifact!r} is not the `save_as` of any "
                "`download` action in this spec, so no capture could ever produce it "
                f"(this spec downloads: {_downloads_phrase(downloads)})")
        if not cap.url and not cap.artifact:
            raise SpecError(f"{where}: needs a `url:` or an `artifact:`")
        if cap.storage_state and not (spec.root / cap.storage_state).exists():
            raise SpecError(
                f"{where}: storage_state {cap.storage_state!r} not found — capture "
                "it once with `vidkit auth` and commit nothing (see the capture guide)")
        for a in cap.actions:
            if a.kind == "download" and a.save_as:
                if "/" in a.save_as or "\\" in a.save_as or a.save_as in {".", ".."}:
                    raise SpecError(
                        f"{where}: save_as {a.save_as!r} must be a plain filename — "
                        "artifacts are written under _capture/artifacts/")
        if _looks_like_login(cap) and not cap.allow_login and not cap.storage_state:
            raise SpecError(
                f"{where}: this capture types into a password field but declares no "
                "`storage_state:`, so it would film a login form — and a login form "
                "is only part of the story when you say it is. Reuse a session "
                "(record one with `vidkit auth`), or set `allow_login: true` to "
                "declare that signing in *is* this scene.")


def _downloads_phrase(names: set[str]) -> str:
    if not names:
        return "nothing"
    return ", ".join(sorted(n for n in names if n))


def _looks_like_login(cap: Capture) -> bool:
    """A capture that types into something password-shaped."""
    for a in cap.actions:
        if a.kind != "fill":
            continue
        sel = (a.selector or "").lower()
        if "password" in sel or "passwd" in sel or 'type="password"' in sel:
            return True
    return False


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
