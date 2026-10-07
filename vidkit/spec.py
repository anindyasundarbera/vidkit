"""The video *spec*: a small, declarative description of a video.

A spec is plain data (YAML or JSON). It names the scenes, what each scene shows
(a captured screen, a generated chart, or a static still), how narration is
sourced, and the guardrails the finished cut must satisfy. Nothing in a spec
executes code; the optional ``provider`` module supplies data and custom panels.
"""

from __future__ import annotations

import json
import math
import shlex
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
class Score:
    """A music bed under the narration (R-G3).

    The field names say what the mix *does*, not how it is implemented, because the
    whole point of the mix is that it is **derived from** narration's measured spans
    rather than competing with them for the role of master clock (I5). ``duck_db`` is
    the level the bed is taken down *to* while someone is speaking; between spans it
    returns to ``volume``.
    """
    src: str
    volume: float = 0.35                  # the bed's own gain, when nobody is speaking
    duck_db: float = -14.0                # how far under the voice it sits while speaking
    ramp: float = 0.25                    # seconds to fade in and out of a duck
    fade_in: float = 1.0
    fade_out: float = 1.5

    def to_dict(self) -> dict[str, Any]:
        return {"src": self.src, "volume_db": round(self.volume, 2),
                "duck_db": round(self.duck_db, 2), "ramp": self.ramp,
                "fade_in": self.fade_in, "fade_out": self.fade_out}


def _score_db(value: Any, where: str, field: str) -> float:
    """Read a gain as dB. A value above 0 is read as a *linear* multiplier.

    Both spellings are accepted because both are idiomatic — ``0.35`` "means" the same
    thing as ``-9.1`` to two different authors, and silently interpreting one as the
    other would be a 9 dB error. A number ≤ 0 is dB; a positive number is linear, and
    is converted here so that everything downstream works in dB.
    """
    n = float(value)
    if n <= 0:
        return n
    return 20.0 * math.log10(n)


@dataclass
class Narration:
    source: str | None = None             # markdown file with "## Scene N …" + **bold** spoken lines
    inline: dict[int, str] = field(default_factory=dict)  # scene n -> text


@dataclass
class Shot:
    """One visual beat. Exactly one of still/capture/chart/exec/card/solid is set.

    The last two are *declared artwork* rather than pictures of anything: a card
    is typography the engine draws from words the spec contains, and a solid is a
    flat field. Both exist so that a film can open on a title and rest between
    beats without an author having to ship a PNG for a rectangle. Neither invents
    a fact — the card states what the spec said, and ``verify`` classifies both as
    declared assets, exactly as it classifies a live capture as live.
    """
    kind: str                             # "still" | "capture" | "chart" | "exec" | "card" | "solid"
    ref: str                              # path, capture name, chart name, exec label, card text, or colour
    effect: str = "hold"                  # "hold" | "zoom" | "pan"
    fit: str = "cover"                    # "cover" (crop) | "contain" (letterbox)
    weight: float = 1.0                   # share of the scene's duration
    at: float | None = None               # exec shots: which second of the recording to freeze
    motion: "Motion | None" = None        # explicit camera move; overrides `effect`
    seconds: float | None = None          # explicit length; overrides duration-by-weight
    kicker: str = ""                      # card shots: the eyebrow line above the title
    backdrop: str | None = None           # card shots: a declared picture behind the words


# how a still's camera moves. ``hold`` is a static frame; ``zoom`` pushes in;
# ``pan`` slides across a picture that has been scaled up to leave room.
MOTIONS = frozenset({"hold", "zoom", "pan"})

# which way a pan travels, and which way a zoom's subject drifts. Named for the
# direction the *viewer's* eye moves, so `left` means the camera travels left and
# the subject appears to move right — the plain reading of "pan left".
DIRECTIONS = frozenset({
    "left", "right", "up", "down",
    "in", "out",
})


@dataclass
class Motion:
    """A camera move over one picture (R-G1).

    Declared rather than inferred because a move is a *claim about the picture*:
    a slow push-in says "this is the thing to look at", and a film that makes that
    claim over a fabricated frame has made the fabrication more convincing rather
    than less. Naming the move in the spec is what lets ``verify`` count it and a
    reviewer see it.
    """
    kind: str = "hold"                    # see MOTIONS
    direction: str = "in"                # see DIRECTIONS
    amount: float = 0.10                 # zoom: how far in (0.10 = 10%); pan: how far across
    span: float = 1.0                    # fraction of the clip the move occupies
    #: which part of the clip the move occupies: "start" (default) begins moving
    #: immediately, "end" settles into a held frame, "full" moves for the lot.
    at: str = "start"

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "direction": self.direction,
                "amount": round(self.amount, 4), "span": round(self.span, 4),
                "at": self.at, "label": self.label()}

    def label(self) -> str:
        """The move as one phrase, for a report that has to stay readable."""
        if self.kind == "hold":
            return "holds"
        return f"{self.kind} {self.direction} {self.amount * 100:.0f}% ({self.at})"


MOTION_AT = frozenset({"start", "end", "full"})


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
    #: explicit length for the whole scene. When set, narration is *not* the clock
    #: for this scene and the spec says so out loud — see ``Spec.timing_source``.
    seconds: float | None = None


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

# a colour the engine will hand to ffmpeg or an SVG fill. Names are limited to the
# ones both `ffmpeg -f lavfi color=` and SVG agree on, so one spelling works in
# both places rather than being quietly reinterpreted by whichever drew it.
_COLOUR_NAMES = frozenset({
    "black", "white", "red", "green", "blue", "yellow", "cyan", "magenta",
    "gray", "grey", "orange", "purple", "brown", "pink", "navy", "teal",
    "olive", "maroon", "silver", "lime", "aqua", "fuchsia",
})


def _is_colour(value: str) -> bool:
    """True for ``#RGB``/``#RRGGBB`` or a conservative set of CSS colour names."""
    s = value.strip().lower()
    if not s:
        return False
    if s.startswith("#"):
        body = s[1:]
        return len(body) in (3, 6) and all(c in "0123456789abcdef" for c in body)
    return s in _COLOUR_NAMES

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


#: Backends a spec may name. Each is a claim about how a command is confined,
#: so naming one the host cannot honour is a refusal at load time rather than a
#: quiet downgrade — see ``vidkit.exec.resolve_backend``.
EXEC_BACKENDS = {"local", "bubblewrap", "docker"}


@dataclass
class Exec:
    """One declared command, and the boundary it runs inside (R-E1).

    This is the *spec's* half of ``vidkit.exec.ExecRequest``: it says what to run
    and what it is allowed to touch, in the same declarative form as everything
    else. Nothing in it executes at load time.

    ``cmd`` may be a string — in which case the spec is declaring a shell script
    and that is spelled out — or a list, which is run as an argv with no shell at
    all.
    """
    label: str
    cmd: list[str]
    shell: list[str] = field(default_factory=list)
    cwd: str = "."
    env: dict[str, str] = field(default_factory=dict)
    timeout: float = 60.0
    backend: str = "bubblewrap"
    network: bool = False
    reads: list[str] = field(default_factory=list)
    expect_exit: list[int] = field(default_factory=lambda: [0])
    cols: int = 100
    rows: int = 30
    at: float | None = None               # which second of the recording a shot shows
    #: Which declared ``environment:`` this command runs inside. Required when
    #: ``backend: docker``, refused when it is not — an environment started for
    #: nothing is a container that would have to be torn down for nothing.
    environment: str = ""


@dataclass
class Environment:
    """One declared container environment, brought up and torn down once (R-E6).

    Written in the spec as::

        environment:
          name: db
          image: postgres:16-alpine
          env: {POSTGRES_PASSWORD: demo}
          ready: [pg_isready, -U, postgres]

    The lifecycle is the *engine's*, not the spec's: the spec says which image
    and what proves it is ready, and the engine guarantees it is removed on every
    exit path. A spec that had to remember to tear down its own container would
    eventually forget, and the leak would be on the author's machine.
    """
    name: str
    image: str
    command: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    ports: list[str] = field(default_factory=list)
    volumes: list[str] = field(default_factory=list)
    timeout: float = 120.0
    ready: list[str] = field(default_factory=list)
    ready_timeout: float = 60.0
    network: bool = False


@dataclass
class ExecPolicy:
    """What the spec as a whole permits, as opposed to what one command asks for.

    The two-layer shape is deliberate. A command says ``network: true`` and the
    policy says whether that is even on the table, so widening one command cannot
    quietly widen the build.
    """
    allow_network: bool = False
    max_timeout: float = 300.0


@dataclass
class Guard:
    min_seconds: float | None = None
    max_seconds: float | None = None
    banned: list[str] = field(default_factory=list)        # forbidden substrings in on-screen text + narration
    required: list[str] = field(default_factory=list)      # required substrings (any one? all — we require all)
    require_live_mode: bool = False
    require_audio: bool = True                             # a silent cut must be declared, never accidental
    require_live_data: bool = False                        # a degraded dataset must be declared, never accidental
    require_sandbox: bool = True                          # every exec step ran in a declared, isolated backend
    require_exec_success: bool = True                      # every exec step exited as it declared


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
    exec: list[Exec] = field(default_factory=list)
    exec_policy: ExecPolicy = field(default_factory=ExecPolicy)
    environments: list[Environment] = field(default_factory=list)
    guard: Guard = field(default_factory=Guard)
    score: Score | None = None
    story: Story | None = None
    timeframe: Timeframe | None = None
    root: Path = field(default_factory=Path.cwd)
    path: Path | None = None              # where this spec was loaded from
    degraded: dict[str, str] = field(default_factory=dict)   # dataset -> why it is not live

    # -- lookups ------------------------------------------------------------ #
    def capture(self, name: str) -> Capture | None:
        return next((c for c in self.captures if c.name == name), None)

    def chart(self, name: str) -> Chart | None:
        return next((c for c in self.charts if c.name == name), None)

    def exec_step(self, label: str) -> Exec | None:
        return next((e for e in self.exec if e.label == label), None)

    def exec_environment(self, label: str) -> str:
        """The environment a command label runs in, or ``""``. One rule, one place.

        Both the provenance writer and the verifier have to attribute a recorded
        command to the container it ran in, and if they disagreed the report would
        disagree with itself.
        """
        step = self.exec_step(label)
        return step.environment if step is not None else ""

    def environment(self, name: str) -> Environment | None:
        return next((e for e in self.environments if e.name == name), None)

    def scene(self, n: int) -> Scene | None:
        return next((s for s in self.scenes if s.n == n), None)

    @property
    def timing_source(self) -> str:
        """What sets this film's pace: ``"narration"`` or ``"spec"``.

        Before M9 there was one answer, and it was not worth a name. There are now
        two, and they are *not* interchangeable: ``narration`` means measured audio
        is the master clock (I5) and a scene's length is whatever the voice took;
        ``spec`` means an author wrote a length down and the voice was cut to fit
        it. A reader of ``verify.json`` is entitled to know which one they are
        looking at, because only the first one proves the runtime against the real
        recording.
        """
        if any(sc.seconds is not None for sc in self.scenes):
            return "spec"
        if any(sh.seconds is not None for sc in self.scenes for sh in sc.shots):
            return "spec"
        return "narration"

    def timed_scenes(self) -> list[int]:
        """Scene numbers whose length was declared rather than measured."""
        return [sc.n for sc in self.scenes if sc.seconds is not None]

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


def _motion(raw: Any, where: str, effect: str) -> "Motion | None":
    """Parse a shot's camera move. ``None`` means "nothing was asked for".

    ``effect:`` is the M4 spelling and stays valid — a ``zoom`` effect *is* a push
    in, and every spec written before this field existed must keep rendering the
    same frames. When both are given, ``motion:`` wins and the effect's own move is
    suppressed, because two camera moves over one picture is one move too many.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        # `motion: pan` and `motion: {kind: pan}` are the same request
        raw = {"kind": str(raw)}
    kind = str(raw.get("kind", "hold"))
    if kind not in MOTIONS:
        raise SpecError(
            f"{where}: motion must be one of {', '.join(sorted(MOTIONS))}, not {kind!r}")
    direction = str(raw.get("direction", "in"))
    if direction not in DIRECTIONS:
        raise SpecError(
            f"{where}: motion direction must be one of "
            f"{', '.join(sorted(DIRECTIONS))}, not {direction!r}")
    if kind == "pan" and direction in ("in", "out"):
        raise SpecError(
            f"{where}: a pan moves across the frame — direction must be "
            "left, right, up or down (got 'in'/'out')")
    at = str(raw.get("at", "start"))
    if at not in MOTION_AT:
        raise SpecError(
            f"{where}: motion.at must be one of {', '.join(sorted(MOTION_AT))}, not {at!r}")
    motion = Motion(kind=kind, direction=direction,
                    amount=float(raw.get("amount", 0.10)),
                    span=float(raw.get("span", 1.0)), at=at)
    if not 0.0 < motion.span <= 1.0:
        raise SpecError(f"{where}: motion.span is the fraction of the clip to move in, "
                        f"so it must be within (0, 1]; got {motion.span}")
    if motion.kind == "pan" and motion.amount <= 0:
        raise SpecError(
            f"{where}: a pan needs a positive amount — it is how far across the "
            f"picture the camera travels; got {motion.amount}")
    if effect not in ("hold", "", None) and motion.kind != "hold":
        raise SpecError(
            f"{where}: `effect: {effect}` and `motion:` both describe a camera move; "
            "keep one. Drop `effect` and write the move as `motion:`")
    return motion


#: Every shot kind, named once. ``verify`` keeps a parallel table of which of the
#: three honest sources each one draws from, and a test pins the two together — a
#: new kind may not be added without deciding where its picture comes from.
SHOT_KINDS = ("still", "capture", "chart", "exec", "card", "solid")


def _shots(raw: dict[str, Any], where: str) -> Shot:
    present = [k for k in SHOT_KINDS if k in raw]
    if len(present) != 1:
        raise SpecError(
            f"{where}: a shot needs exactly one of {'/'.join(SHOT_KINDS)}")
    kind = present[0]
    fit = str(raw.get("fit", "cover"))
    if fit not in FITS:
        raise SpecError(
            f"{where}: fit must be one of {', '.join(sorted(FITS))}, not {fit!r}"
        )
    effect = str(raw.get("effect", "hold"))
    seconds = None if raw.get("seconds") is None else float(raw["seconds"])
    if seconds is not None and seconds <= 0:
        raise SpecError(f"{where}: `seconds: {seconds}` — a shot's length must be "
                        "positive; remove the field to divide the scene by weight")
    kicker = str(raw.get("kicker", "")).strip()
    backdrop = None if raw.get("backdrop") is None else str(raw["backdrop"]).strip()
    if kind not in ("card", "solid"):
        # A field the engine would ignore is worse than one it refuses: `backdrop:`
        # on a `still:` reads as "put this picture behind the words" and silently
        # does nothing, so the author ships a card they did not get. Caught here
        # rather than at render, where it would already have cost a build.
        for field, value in (("kicker", kicker), ("backdrop", backdrop)):
            if value:
                raise SpecError(
                    f"{where}: `{field}:` describes a *card*, but this is a "
                    f"`{kind}` shot — write the words as `card: ...` (a card may "
                    "sit over a declared picture via `backdrop:`)")
    return Shot(kind=kind, ref=str(raw[kind]),
                effect=effect,
                fit=fit,
                weight=float(raw.get("weight", 1.0)),
                at=None if raw.get("at") is None else float(raw["at"]),
                motion=_motion(raw.get("motion"), where, effect),
                seconds=seconds,
                kicker=kicker,
                backdrop=backdrop)


def _exec_step(raw: dict[str, Any], where: str) -> Exec:
    """Parse one declared command.

    The string/list distinction is the interesting part. A string command is
    wrapped as ``["/bin/sh", "-c", <string>]`` and the shell is therefore
    *declared*; a list is run as-is, with no interpreter. Both are honest — the
    difference is that one of them says so in the spec.
    """
    if "label" not in raw:
        raise SpecError(f"{where}: an exec step needs a `label` (shots reference it)")
    if "cmd" not in raw:
        raise SpecError(f"{where}: an exec step needs a `cmd`")
    raw_cmd = raw["cmd"]
    if isinstance(raw_cmd, str):
        if not raw_cmd.strip():
            raise SpecError(f"{where}: `cmd` is empty")
        cmd, shell = [raw_cmd], ["/bin/sh", "-c"]
    elif isinstance(raw_cmd, (list, tuple)):
        cmd = [str(x) for x in raw_cmd]
        if not cmd:
            raise SpecError(f"{where}: `cmd` is an empty list")
        shell = []
    else:
        raise SpecError(
            f"{where}: `cmd` must be a string (run through a declared /bin/sh) or "
            f"a list (run as an argv, no shell), not {type(raw_cmd).__name__}")
    if raw.get("shell"):
        raise SpecError(
            f"{where}: `shell:` is not a spec field — write `cmd:` as a string to "
            "declare a shell script, or as a list to run an argv directly")
    backend = str(raw.get("backend", "bubblewrap"))
    if backend not in EXEC_BACKENDS:
        raise SpecError(
            f"{where}: unknown backend {backend!r}; known: "
            + ", ".join(sorted(EXEC_BACKENDS)))
    environment = str(raw.get("environment", "") or "")
    if backend == "docker" and not environment:
        raise SpecError(
            f"{where}: `backend: docker` needs an `environment:` naming which "
            "declared environment the command runs inside — a container started "
            "for one command would have to be torn down for one command, and "
            "the demo would show a different system each time")
    if backend != "docker" and environment:
        raise SpecError(
            f"{where}: `environment: {environment}` is declared but the backend "
            f"is {backend!r}; only `backend: docker` runs inside an environment")
    env = raw.get("env") or {}
    if not isinstance(env, dict):
        raise SpecError(f"{where}: `env` must be a mapping of NAME: value")
    expect = raw.get("expect_exit", [0])
    if isinstance(expect, int):
        expect = [expect]
    reads = raw.get("reads") or []
    if isinstance(reads, str):
        reads = [reads]
    return Exec(
        label=str(raw["label"]),
        cmd=cmd,
        shell=shell,
        cwd=str(raw.get("cwd", ".")),
        env={str(k): str(v) for k, v in env.items()},
        timeout=float(raw.get("timeout", 60.0)),
        backend=backend,
        network=bool(raw.get("network", False)),
        reads=[str(x) for x in reads],
        expect_exit=[int(x) for x in expect],
        cols=int(raw.get("cols", 100)),
        rows=int(raw.get("rows", 30)),
        at=None if raw.get("at") is None else float(raw["at"]),
        environment=environment,
    )


def _environment(raw: dict[str, Any], where: str) -> Environment:
    """Parse one declared container environment.

    Strict about the fields it does not know, because this is the part of the spec
    that can affect the *host*: a silently ignored ``privileged: true`` would be
    an author believing they had asked for something the engine never granted.
    """
    known = {"name", "image", "command", "env", "ports", "volumes", "timeout",
             "ready", "ready_timeout", "network"}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise SpecError(
            f"{where}: unknown field(s) {', '.join(unknown)}; known: "
            + ", ".join(sorted(known)))
    if not raw.get("name"):
        raise SpecError(f"{where}: an environment needs a `name` (exec steps reference it)")
    if not raw.get("image"):
        raise SpecError(
            f"{where}: an environment needs an `image` — this is the whole point "
            "of the backend: the image is what says *which* Postgres the video "
            "was filmed against")
    env = raw.get("env") or {}
    if not isinstance(env, dict):
        raise SpecError(f"{where}: `env` must be a mapping of NAME: value")
    ports, volumes = raw.get("ports") or [], raw.get("volumes") or []
    if isinstance(ports, (str, int)):
        ports = [ports]
    if isinstance(volumes, str):
        volumes = [volumes]
    ready = raw.get("ready") or []
    if isinstance(ready, str):
        ready = shlex.split(ready)
    command = raw.get("command") or []
    if isinstance(command, str):
        command = shlex.split(command)
    for volume in volumes:
        # The bind syntax `-v /host:/container` is what the runtime takes; a
        # single path would mount an anonymous volume and quietly give the
        # container nothing, which reads as the command failing rather than the
        # spec being thin.
        if ":" not in str(volume):
            raise SpecError(
                f"{where}: volume {volume!r} must be HOST:CONTAINER (or "
                "HOST:CONTAINER:ro) — a bare path mounts an empty volume")
    return Environment(
        name=str(raw["name"]),
        image=str(raw["image"]),
        command=[str(x) for x in command],
        env={str(k): str(v) for k, v in env.items()},
        ports=[str(p) for p in ports],
        volumes=[str(v) for v in volumes],
        timeout=float(raw.get("timeout", 120.0)),
        ready=[str(x) for x in ready],
        ready_timeout=float(raw.get("ready_timeout", 60.0)),
        network=bool(raw.get("network", False)),
    )


def _exec_policy(raw: dict[str, Any], where: str) -> ExecPolicy:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise SpecError(f"{where}: `exec` must be a mapping of steps or policy")
    return ExecPolicy(
        allow_network=bool(raw.get("allow_network", False)),
        max_timeout=float(raw.get("max_timeout", 300.0)),
    )


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

    # `exec:` is either a mapping of steps or a policy block. A mapping under
    # `steps:` is a list of steps; anything else that is a list is one too. That
    # covers the two shapes an author will write without needing a third.
    raw_exec = raw.get("exec")
    exec_steps: list[Exec] = []
    exec_policy = ExecPolicy()
    if raw_exec:
        if not isinstance(raw_exec, dict):
            raise SpecError("`exec` must be a mapping: `steps:` plus optional policy")
        exec_policy = _exec_policy({k: v for k, v in raw_exec.items()
                                    if k in ("allow_network", "max_timeout")},
                                   "exec")
        for i, step in enumerate(raw_exec.get("steps") or []):
            if not isinstance(step, dict):
                raise SpecError("exec.steps: each step must be a mapping")
            exec_steps.append(_exec_step(step, f"exec step {i + 1}"))
        seen_labels: set[str] = set()
        for step in exec_steps:
            if step.label in seen_labels:
                raise SpecError(
                    f"exec step {step.label!r}: a second step with the same label — "
                    "shots reference a step by label, so two would be ambiguous")
            seen_labels.add(step.label)

    # `environment:` is a list of container environments. Each is brought up
    # before the exec stage and torn down after it, unconditionally (R-E6).
    raw_envs = raw.get("environment") or []
    if isinstance(raw_envs, dict):
        raw_envs = [raw_envs]
    if not isinstance(raw_envs, list):
        raise SpecError("`environment:` must be a list of environments")
    environments: list[Environment] = []
    for i, item in enumerate(raw_envs):
        if not isinstance(item, dict):
            raise SpecError(f"environment {i + 1}: must be a mapping")
        environments.append(_environment(item, f"environment {i + 1}"))
    seen_envs: set[str] = set()
    for env in environments:
        if env.name in seen_envs:
            raise SpecError(
                f"environment {env.name!r}: declared twice — exec steps reference "
                "an environment by name, so two would be ambiguous")
        seen_envs.add(env.name)

    scenes: list[Scene] = []
    for s in raw.get("scenes") or []:
        shots = [_shots(sh, f"scene {s.get('n')}") for sh in (s.get("shots") or [])]
        if not shots:
            raise SpecError(f"scene {s.get('n')} has no shots")
        ov = s.get("overlay")
        scene_seconds = None if s.get("seconds") is None else float(s["seconds"])
        if scene_seconds is not None and scene_seconds <= 0:
            raise SpecError(
                f"scene {s.get('n')}: `seconds: {scene_seconds}` — a scene's length "
                "must be positive; remove the field to derive it from narration")
        scenes.append(Scene(n=int(s["n"]), shots=shots,
                            title=str(s.get("title", "")),
                            overlay=_overlay(ov, f"scene {s.get('n')}")
                            if ov is not None else None,
                            seconds=scene_seconds))
    if not scenes:
        raise SpecError("spec defines no scenes")
    scenes.sort(key=lambda x: x.n)

    g = raw.get("guard") or {}
    guard = Guard(min_seconds=g.get("min_seconds"), max_seconds=g.get("max_seconds"),
                  banned=[str(x) for x in (g.get("banned") or [])],
                  required=[str(x) for x in (g.get("required") or [])],
                  require_live_mode=bool(g.get("require_live_mode", False)),
                  require_audio=bool(g.get("require_audio", True)),
                  require_live_data=bool(g.get("require_live_data", False)),
                  require_sandbox=bool(g.get("require_sandbox", True)),
                  require_exec_success=bool(g.get("require_exec_success", True)))

    provider = _provider_spec(raw.get("provider"))

    score = _score_spec(raw.get("score"))

    root = path.parent.resolve()
    spec = Spec(project=project, scenes=scenes, voice=voice, narration=narration,
                provider=provider, captures=captures, charts=charts,
                exec=exec_steps, exec_policy=exec_policy,
                environments=environments,
                guard=guard, score=score, root=root)

    spec.story = load_story(root, default_as_of=as_of)
    spec.timeframe = _resolve_timeframe(raw, spec, timeframe, as_of)
    # remembered so a job manifest can name the spec it actually ran, and a
    # caller never has to re-derive it from the output paths
    spec.path = path.resolve()

    _validate(spec)
    return spec


def _score_spec(raw: Any) -> Score | None:
    """Read ``score:`` — a music bed under the narration.

    Returns ``None`` for an absent *or* empty block: a `score:` key with nothing in it
    describes no score, and a silent film stays silent. A declared `src` is not checked
    for existence here — it is resolved against the spec root, and refusing at load time
    would make an offline edit of the spec impossible without the audio present.
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        raw = {"src": raw}
    if not isinstance(raw, dict):
        raise SpecError("score: must be a file path or a mapping")
    if not raw:
        return None
    unknown = sorted(set(raw) - {"src", "volume", "duck_db", "ramp",
                                 "fade_in", "fade_out"})
    if unknown:
        raise SpecError("score: unknown key(s): " + ", ".join(unknown)
                        + " — expected src, volume, duck_db, ramp, fade_in, fade_out")
    src = str(raw.get("src") or "").strip()
    if not src:
        raise SpecError("score: needs a `src:` — the audio file to play under the voice")
    volume = _score_db(raw.get("volume", 0.35), "score", "volume")
    duck_db = float(raw.get("duck_db", -14.0))
    if volume > 0.0:
        raise SpecError("score: `volume:` is a gain of at most 1 "
                        f"(got {raw.get('volume')!r}) — a bed that is louder than the "
                        "voice it sits under is not a bed")
    if duck_db > 0.0:
        raise SpecError("score: `duck_db:` must be at or below 0 dB "
                        f"(got {duck_db:+.1f}) — ducking raises nobody")
    ramp = float(raw.get("ramp", 0.25))
    if ramp < 0.0:
        raise SpecError("score: `ramp:` cannot be negative")
    return Score(src=src, volume=volume, duck_db=duck_db, ramp=ramp,
                 fade_in=float(raw.get("fade_in", 1.0)),
                 fade_out=float(raw.get("fade_out", 1.5)))


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
    exec_labels = {e.label for e in spec.exec}
    known_provider = spec.provider is not None
    for sc in spec.scenes:
        for sh in sc.shots:
            if sh.kind == "still":
                target = (spec.root / sh.ref)
                if not target.exists() and not (spec.root / ".." / sh.ref).exists():
                    # tolerate provider-supplied stills only if a provider exists
                    if not known_provider:
                        raise SpecError(f"scene {sc.n}: still not found: {sh.ref}")
            elif sh.kind in ("card", "solid"):
                # Neither is a file, so neither may be excused by a provider. If a
                # card slipped into the `still` branch above, a spec with a provider
                # could name artwork that does not exist and render a blank frame —
                # an absence wearing the costume of a declared asset.
                if sh.kind == "card" and not sh.ref.strip():
                    raise SpecError(
                        f"scene {sc.n}: a `card` shot needs its words — `card: ...` "
                        "is drawn by the engine, so the text is the whole asset")
                if sh.kind == "card" and sh.backdrop:
                    # A backdrop is a *declared picture*, so it must exist — and,
                    # like the card itself, a provider may not supply it. If it could,
                    # a spec could name artwork that is not there and render a title
                    # over nothing: an absence dressed as a declared asset.
                    bd = spec.root / sh.backdrop
                    if not bd.exists() and not (spec.root / ".." / sh.backdrop).exists():
                        raise SpecError(
                            f"scene {sc.n}: card backdrop not found: {sh.backdrop} "
                            "(a card's `backdrop:` is a declared picture beside the "
                            "spec, not a provider asset)")
                if sh.kind == "solid" and not _is_colour(sh.ref):
                    raise SpecError(
                        f"scene {sc.n}: `solid: {sh.ref}` is not a colour — use "
                        "#RRGGBB, #RGB, or a name like 'black' (alpha via "
                        "`fit`/overlays, not in the colour)")
            elif sh.kind == "capture" and sh.ref not in cap_names and not known_provider:
                raise SpecError(f"scene {sc.n}: capture {sh.ref!r} is not defined")
            elif sh.kind == "chart" and sh.ref not in chart_names and not known_provider:
                raise SpecError(f"scene {sc.n}: chart {sh.ref!r} is not defined")
            elif sh.kind == "exec" and sh.ref not in exec_labels:
                if not exec_labels:
                    raise SpecError(
                        f"scene {sc.n}: shows an exec shot but the spec declares no "
                        "`exec:` steps — add an `exec:` block naming the commands")
                raise SpecError(
                    f"scene {sc.n}: exec step {sh.ref!r} is not declared — a shot "
                    "must show a command the spec wrote down (declared: "
                    + ", ".join(sorted(exec_labels)) + ")")
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
    _validate_exec(spec)


def _validate_exec(spec: Spec) -> None:
    """Refuse commands that could only fail once the camera was rolling (R-E1).

    Every reason a declared command cannot run as written is available at load
    time: the working directory is on disk or it is not, the backend is installed
    or it is not, the policy permits the network or it does not. Checking here
    means ``vidkit plan`` already tells the truth about what a build will do.
    """
    from .exec import check_policy

    # An environment that no step runs inside is a container the engine would
    # start, film nothing of, and tear down again. Refusing it at load time turns
    # a wasted minute of the operator's life into a sentence.
    used = {e.environment for e in spec.exec if e.environment}
    problems = [
        f"environment {env.name!r}: declared but no exec step declares "
        f"`environment: {env.name}` — the container would start and be torn down "
        "without appearing in the video"
        for env in spec.environments if env.name not in used
    ]
    for step in spec.exec:
        if step.environment and spec.environment(step.environment) is None:
            problems.append(
                f"exec step {step.label!r}: declares `environment: "
                f"{step.environment}` but no such environment is defined")

    if not spec.exec:
        if problems:
            raise SpecError("; ".join(problems))
        return
    problems += check_policy(
        [e for e in spec.exec], root=spec.root,
        allow_network=spec.exec_policy.allow_network)
    problems += [
        f"exec step {e.label!r}: timeout {e.timeout:g}s exceeds the spec's "
        f"exec.max_timeout of {spec.exec_policy.max_timeout:g}s — raise the policy "
        "deliberately, or lower the command's timeout"
        for e in spec.exec if e.timeout > spec.exec_policy.max_timeout
    ]
    if problems:
        raise SpecError("; ".join(problems))


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
