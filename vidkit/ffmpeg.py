"""Thin, testable wrappers around external processes (ffmpeg, rsvg-convert).

Every external call goes through here so the rest of the toolkit is pure Python
and easy to unit-test with a fake runner.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Sequence

from .errors import ToolError

Runner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]


class MixResult:
    """What a mix actually did.

    A mix is a *claim* — "the bed was taken down where the voice was". Returning the
    output path alone would let the report repeat the claim instead of checking it,
    and a silent cut (no narration to duck under) would be reported as ducked. So the
    mix returns its own account of itself: how long the bed was held down for, and
    which of the two paths it took.
    """

    __slots__ = ("out", "seconds", "ducked", "spans")

    def __init__(self, out: Path, *, seconds: float, ducked: bool,
                 spans: int = 0) -> None:
        self.out = out
        #: how many seconds of the finished mix the bed was actually held down for
        self.seconds = seconds
        #: whether the ducking branch ran at all — False when there was no voice
        self.ducked = ducked
        #: how many speech windows were handed to the mix
        self.spans = spans

    def to_dict(self) -> dict[str, object]:
        return {"mixed": str(self.out), "duck_seconds": round(self.seconds, 3),
                "ducked": self.ducked, "spans": self.spans}

# letterbox bars for `fit: contain` — deliberately dark, so the bars are legible
# as bars rather than mistakable for page content
_PAD_COLOR = "0x101418"

# the transitions a spec may declare (R-D6), mapped to their xfade names. A
# transition changes *how* two filmed states follow one another; it can never
# stand in for a state change nobody filmed, which is why nothing that invents
# motion (a page-turn, a 3-D fly) is on this list.
TRANSITIONS = {"fade": "fade", "wipe": "wipeleft", "slide": "slideleft"}
_XFADE = TRANSITIONS


def _default_runner(cmd: Sequence[str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(list(cmd), capture_output=True, text=True)


class Shell:
    """Run commands, capturing output; raise ``ToolError`` on failure."""

    def __init__(self, runner: Runner | None = None, *, quiet: bool = True) -> None:
        self._run = runner or _default_runner
        self.quiet = quiet
        self.log: list[str] = []

    def which(self, binary: str) -> str | None:
        return shutil.which(binary)

    def has(self, binary: str) -> bool:
        return self.which(binary) is not None

    def run(self, cmd: Sequence[str], *, check: bool = True) -> str:
        """Run ``cmd``; return combined stderr (ffmpeg logs to stderr)."""
        self.log.append(" ".join(str(c) for c in cmd))
        result = self._run(cmd)
        if check and result.returncode != 0:
            tail = (result.stderr or result.stdout or "")[-2000:]
            raise ToolError(f"command failed ({result.returncode}): {' '.join(cmd)}\n{tail}")
        return result.stderr or ""

    def run_capture_stdout(self, cmd: Sequence[str], *, check: bool = True) -> str:
        result = self._run(cmd)
        if check and result.returncode != 0:
            raise ToolError(f"command failed: {' '.join(cmd)}\n{(result.stderr or '')[-2000:]}")
        return result.stdout


def _duck_expr(spans: Sequence[tuple[float, float]], duck_db: float,
               ramp: float, *, var: str = "t") -> str:
    """The *linear* gain ffmpeg should apply to the bed at time ``t``.

    ``volume``'s expression is a gain factor, not a dB value — writing an expression
    in dB here would silence the bed by a factor of 14 rather than 14 dB, so the
    conversion happens once, here, and the filter chain stays in one unit.

    Written as a *product* of per-span ramps rather than a search for "which span am I
    in", because spans may abut (measured narration is usually contiguous) and a shot
    may be declared longer than the speech inside it. Multiplying trapezoids that each
    reach 1 gives unity where they overlap, and any moment mid-ramp takes the deepest
    duck, which is the audible behaviour one wants.
    """
    d = 10.0 ** (duck_db / 20.0)
    if not spans or d >= 1.0:
        return "1"
    ramp = max(ramp, 1e-3)
    terms = []
    for s, e in spans:
        up = f"min(max(({var}-{s:.4f})/{ramp:.4f},0),1)"
        down = f"min(max(({e:.4f}-{var})/{ramp:.4f},0),1)"
        terms.append(f"min({up},{down})")
    hold = terms[0] if len(terms) == 1 else "min(1,(" + "+".join(terms) + "))"
    # the floor keeps a fully-ducked moment a finite (inaudible) number rather than 0,
    # so a long silent patch cannot hand ffmpeg a division to complain about
    return f"max(1-{1.0 - d:.6f}*({hold}),1e-6)"


def fit_filters(size: tuple[int, int]) -> str:
    """Filter chain that fits a still inside ``size`` *without distortion*.

    A bare ``scale=w:h`` stretches whatever aspect the source happens to have
    onto the frame — a full-page capture (tall) or a wide chart both come out
    wrong, and a stretched screenshot misrepresents the product it shows.

    The box is treated as one dimension: the source is scaled *up* until it
    covers the frame, then the overflow is cropped away from the centre. A
    portrait capture fills the frame with its middle band; a landscape one
    fills it with its middle columns. Nothing is ever squashed, and no letterbox
    bars appear.

    ``force_original_aspect_ratio=increase`` also guarantees the scaled source is
    at least as large as the box, so the crop can never hit empty space; it is
    kept anyway because it makes that fact local and readable.
    """
    w, h = size
    return (
        f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={w}:{h},setsar=1"
    )


#: the default room a pan travels in, as a share of the frame. A pan needs space to
#: move in both directions; 0.12 is ~115px on a 1920 frame — enough to read as
#: movement, little enough that no pixel is visibly doubled.
PAN_OVERSCAN = 0.12


def _move(motion: object | None) -> tuple[str, str, float, float, str] | None:
    """Normalise a duck-typed motion object to ``(kind, direction, amount, span, at)``.

    ``None`` in, ``None`` out — the caller then takes the pre-M9 path, which is what
    keeps every spec written before this field rendering byte-for-byte the same.
    """
    if motion is None:
        return None
    kind = str(getattr(motion, "kind", "hold"))
    return (
        kind,
        str(getattr(motion, "direction", "in")),
        float(getattr(motion, "amount", 0.10)),
        float(getattr(motion, "span", 1.0)),
        str(getattr(motion, "at", "start")),
    )


def _move_filters(size: tuple[int, int], seconds: float, fps: int,
                  move: tuple[str, str, float, float, str]) -> str:
    """The filterchain for a camera move, as a single ``-vf`` string.

    Both moves are ``zoompan`` over an *overscanned* source — fitted to
    ``1+amount`` times the frame — and they differ only in how ``z`` and ``x``/``y``
    are computed:

    * a **zoom** varies ``z`` from 1.0 to ``1+amount`` and keeps the subject centred,
      so the frame starts fractionally wide and pushes in to exactly the frame;
    * a **pan** holds ``z`` at ``1+amount`` and slides ``x``/``y`` across the slack
      that leaves. ``amount`` is both moves' "how much": for a zoom it is how far in
      it finishes, for a pan how much of the picture sits off-frame at either end.

    ``on`` is ffmpeg's output frame counter, so progress is expressed as a fraction
    of the travel rather than in pixels — which is what makes one chain correct at
    any resolution. ``span``/``at`` place the move in the clip: ``start`` moves over
    the first ``span`` then holds, ``end`` holds then moves over the last ``span``,
    ``full`` moves throughout. The held part is not a special case, just the same
    travel clipped.

    ``d=1`` makes ``zoompan`` emit one output frame per input frame; with the
    ``-loop 1`` input that means ``on`` advances and the expression is re-evaluated
    per frame, which is what animates anything at all.
    """
    w, h = size
    kind, direction, amount, span, at = move
    amount = max(amount, 0.0)
    total_frames = max(int(round(seconds * fps)), 1)
    move_frames = min(max(int(round(total_frames * span)), 1), total_frames)

    # `p` runs 0..1 across the move wherever the move sits in the clip
    if at == "end":
        progress = f"min(max((on-{total_frames - move_frames})/{move_frames},0),1)"
    elif at == "full":
        progress = f"min(on/{total_frames},1)"
    else:
        progress = f"min(on/{move_frames},1)"

    big = (int(round(w * (1.0 + amount))), int(round(h * (1.0 + amount))))
    if kind == "zoom":
        a, b = (1.0, 1.0 + amount) if direction != "out" else (1.0 + amount, 1.0)
        z = f"{a:.6f}+{b - a:.6f}*({progress})"
        # keep the centre fixed: this is a push-in, not a pan
        x, y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    else:  # pan — `z` is constant, so the slack is constant and the slide is linear
        z = f"{1.0 + amount:.6f}"
        # The parentheses around each slack term are load-bearing, not style: ffmpeg
        # folds `iw-iw/zoom*p` to a constant and the picture never moves. Verify any
        # change here by measuring a frame early and late, never by reading the string.
        slack_x, slack_y = "(iw-iw/zoom)", "(ih-ih/zoom)"
        if direction == "left":        # camera travels left; the subject drifts right
            x, y = f"{slack_x}*(1-({progress}))", "ih/2-(ih/zoom/2)"
        elif direction == "right":
            x, y = f"{slack_x}*({progress})", "ih/2-(ih/zoom/2)"
        elif direction == "up":        # camera rises; the subject drifts down
            x, y = "iw/2-(iw/zoom/2)", f"{slack_y}*(1-({progress}))"
        else:                          # down
            x, y = "iw/2-(iw/zoom/2)", f"{slack_y}*({progress})"

    return (
        f"{fit_filters(big)},"
        f"zoompan=z='{z}':d=1:x='{x}':y='{y}':s={w}x{h}:fps={fps},"
        "format=yuv420p"
    )


class Ffmpeg:
    """ffmpeg/ffprobe helpers. Duration is read without ffprobe (it is optional)."""

    _DUR = re.compile(r"Duration: (\d+):(\d+):([\d.]+)")
    _DIM = re.compile(r"Video: .*?, (\d+)x(\d+)[ ,]")

    def __init__(self, shell: Shell | None = None) -> None:
        self.shell = shell or Shell()

    @property
    def available(self) -> bool:
        return self.shell.has("ffmpeg")

    def duration(self, path: Path | str) -> float:
        """Duration in seconds. Uses ffprobe when present, else parses ffmpeg."""
        if self.shell.has("ffprobe"):
            out = self.shell.run_capture_stdout(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", str(path)], check=False,
            )
            try:
                return float(out.strip())
            except ValueError:
                pass
        out = self.shell.run(["ffmpeg", "-i", str(path)], check=False)
        m = self._DUR.search(out)
        if not m:
            return 0.0
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))

    def still_to_clip(
        self, image: Path, out: Path, seconds: float, *,
        size: tuple[int, int], fps: int, effect: str = "hold",
        zoom: float = 0.10, crf: int = 19, fit: str = "cover",
        motion: object | None = None,
    ) -> None:
        """Render a still PNG to a fixed-length clip.

        Three camera moves are available, and the difference between them is what
        the picture is *claiming*:

        * ``hold`` — a static frame. Nothing is implied.
        * ``zoom`` — a slow push-in, ending at ``1+zoom``. Says "look at this".
        * ``pan`` — a slide across a picture scaled up to leave room. Says "there is
          more here than fits", and is the only one of the three that can lie by
          showing a neighbouring part of a frame that was cropped out for a reason.

        ``motion`` is an object with ``kind``/``direction``/``amount``/``span``/``at``
        (the spec's :class:`~vidkit.spec.Motion`), duck-typed so this module stays
        free of the spec's types. When it is given, ``effect`` is not consulted —
        the caller has already refused a spec that declares both.

        The still is scaled to fill ``size`` without distortion (see
        :func:`fit_filters`), so a full-page capture is cropped, never squashed.
        ``fit='contain'`` letterboxes instead, which is the honest choice for a
        document page whose *whole* extent matters — nothing is hidden, and the
        bars state plainly that the page is not 16:9.
        """
        w, h = size
        vf: str
        move = _move(motion)
        if move is not None and move[0] != "hold":
            vf = _move_filters(size, seconds, fps, move)
        elif effect == "zoom":
            # zoompan needs a source larger than its output so it has room to
            # push in; that source is fitted the same way, so the push-in
            # respects the still's aspect just as a hold does.
            rate = zoom / max(seconds * fps, 1)
            big = (int(round(w * (1.0 + zoom))), int(round(h * (1.0 + zoom))))
            vf = (
                f"{fit_filters(big)},"
                f"zoompan=z='min(1.0+on*{rate:.6f},{1.0 + zoom:.3f})':d=1:"
                f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={fps},"
                "format=yuv420p"
            )
        elif fit == "contain":
            vf = (
                f"scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={_PAD_COLOR},setsar=1,"
                f"fps={fps},format=yuv420p"
            )
        else:
            vf = f"{fit_filters(size)},fps={fps},format=yuv420p"
        self.shell.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-loop", "1", "-framerate", str(fps), "-i", str(image),
            "-t", f"{seconds:.3f}", "-vf", vf,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
            "-pix_fmt", "yuv420p", str(out),
        ])

    def frames_to_clip(
        self, frames: Sequence[Path], out: Path, durations: Sequence[float], *,
        size: tuple[int, int], fps: int, crf: int = 19,
    ) -> None:
        """Mux real PNG frames into a clip, each held for its **own** duration.

        The frames are the *real* replayed screens — one per moment the recording
        actually reached — and ``durations[i]`` is how much recording time passed
        before frame ``i+1`` appeared. Holding each frame for that long is what
        keeps the temporal claim true: a command that took forty seconds looks
        like forty seconds. Compressing the pacing would show content that really
        happened at a speed it never happened at — a smaller lie than a fake
        terminal, but the same kind of lie, and this module exists to not tell it.

        Durations are floored at one frame so a burst of output still produces a
        visible frame rather than a skipped one.
        """
        if not frames:
            raise ToolError("frames_to_clip called with no frames")
        floor = 1.0 / max(fps, 1)
        listfile = out.with_suffix(".txt")
        lines = []
        for i, p in enumerate(frames):
            held = max(floor, durations[i] if i < len(durations) else floor)
            lines.append(f"file '{p.resolve()}'\nduration {held:.4f}\n")
        # the concat demuxer needs the last frame repeated, or ffmpeg drops it
        lines.append(f"file '{frames[-1].resolve()}'\n")
        listfile.write_text("".join(lines), encoding="utf-8")
        self.shell.run([
            "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
            "-i", str(listfile),
            "-vf", f"{fit_filters(size)},fps={fps},format=yuv420p",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
            "-pix_fmt", "yuv420p", str(out),
        ])

    def fit_clip(
        self, source: Path, out: Path, seconds: float, *,
        size: tuple[int, int], fps: int, fit: str = "cover", crf: int = 19,
    ) -> None:
        """Re-encode a *video* source into a clip of exactly ``seconds``.

        The sibling of :meth:`still_to_clip`, for a source that is already moving.
        It reuses the same :func:`fit_filters`, so a video and a still of
        identical geometry land in the frame identically and a viewer cannot tell
        which stage produced the picture.

        A source *shorter* than the slot is frozen on its last frame
        (``tpad stop_mode=clone``). A source *longer* is cut. Both are stated here
        rather than papered over: the recording is what it is, and the shot is the
        part of it the scene had room for.
        """
        w, h = size
        if fit == "contain":
            geom = (f"scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos,"
                    f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={_PAD_COLOR},setsar=1")
        else:
            geom = fit_filters(size)
        self.shell.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(source),
            "-vf", f"{geom},tpad=stop_mode=clone:stop_duration={seconds:.3f},"
                   f"fps={fps},format=yuv420p",
            "-t", f"{seconds:.3f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
            "-pix_fmt", "yuv420p", str(out),
        ])

    def clip_geometry(self, path: Path) -> tuple[int, int]:
        """The real pixel size of a clip's frames — ffmpeg reads the file, so
        this is a fact about the output, not about the filter that made it."""
        out = self.shell.run(["ffmpeg", "-i", str(path)], check=False)
        m = self._DIM.search(out)
        if not m:
            raise ToolError(f"cannot read frame size of {path}")
        return int(m.group(1)), int(m.group(2))

    def still_geometry(self, path: Path) -> tuple[int, int]:
        """The real pixel size of a still image."""
        out = self.shell.run(["ffmpeg", "-i", str(path)], check=False)
        m = self._DIM.search(out)
        if not m:
            raise ToolError(f"cannot read image size of {path}")
        return int(m.group(1)), int(m.group(2))

    def frame_rgb(self, path: Path, at: float, out: Path,
                  size: tuple[int, int] | None = None) -> bytes:
        """Decode one real frame of ``path`` to raw RGB24 and return the bytes.

        This exists so a truthfulness claim can be *measured*: a scaled image is
        a claim about geometry, and the only honest way to check one is to read
        the pixels the audience will see. ``out`` is a scratch file (ffmpeg needs
        a seekable destination for the raw muxer).
        """
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{at:.3f}",
               "-i", str(path), "-frames:v", "1"]
        if size is not None:
            cmd += ["-vf", f"scale={size[0]}:{size[1]}"]
        cmd += ["-f", "rawvideo", "-pix_fmt", "rgb24", str(out)]
        self.shell.run(cmd)
        return out.read_bytes()

    def overlay_clip(
        self, clip: Path, graphic: Path, out: Path, *,
        position: str = "bottom", opacity: float = 0.88,
        fade: float = 0.4, graphic_size: tuple[int, int] | None = None,
    ) -> None:
        """Composite ``graphic`` over every frame of ``clip`` (R-D4).

        The shot underneath is never replaced, never hidden for the whole take:
        the picture stays dominant and the graphic is drawn *into* it. That is
        the invariant, so it is enforced here rather than by convention.

        ``fade`` dissolves the graphic in and out. It is clamped to a third of
        the clip so the overlay can never end up invisible for its whole life —
        a declaration that produces nothing would be a lie with a plausible
        filter chain.
        """
        seconds = self.duration(clip)
        f = max(0.0, min(float(fade), seconds / 3.0))
        x = "(W-w)/2"
        y = "40" if position == "top" else "H-h-40"
        pre = []
        if graphic_size is not None:
            pre.append(f"scale={graphic_size[0]}:{graphic_size[1]}")
        pre.append(f"format=rgba,colorchannelmixer=aa={float(opacity):.3f}")
        if f > 0:
            pre.append(f"fade=in:st=0:d={f:.3f}:alpha=1,"
                       f"fade=out:st={max(seconds - f, 0.0):.3f}:d={f:.3f}:alpha=1")
        self.shell.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(clip), "-loop", "1", "-i", str(graphic),
            "-filter_complex",
            f"[1:v]{','.join(pre)}[ov];[0:v][ov]overlay={x}:{y}:"
            "eof_action=repeat:shortest=1:format=auto,format=yuv420p",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
            "-pix_fmt", "yuv420p", str(out),
        ])

    def concat(self, parts: Sequence[Path], out: Path, listfile: Path) -> None:
        listfile.write_text("".join(f"file '{p}'\n" for p in parts), encoding="utf-8")
        self.shell.run([
            "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
            "-i", str(listfile), "-c", "copy", str(out),
        ])

    def concat_with_transitions(
        self, parts: Sequence[Path], out: Path, *,
        transitions: dict[int, tuple[str, float]], crf: int = 19,
    ) -> None:
        """Join clips, dissolving across the declared junctions (R-D6).

        ``transitions[i]`` is ``(kind, seconds)`` for the junction *into* clip
        ``i``; every other junction is a hard cut. The chain is built so that the
        total length is unchanged: the incoming clip of a dissolve is rendered
        ``seconds`` longer before it gets here (see ``_build_clips``), and the
        overlap consumes exactly the extra. That matters because the narration
        audio is laid out end to end from measured scene durations — a video
        track that quietly lost half a second per dissolve would drift out of
        sync with it, and drift is a lie about timing.

        Both kinds are drawn from the two frames that already exist. A transition
        is a way of cutting, never a way of inventing a state that was not filmed.
        """
        if len(parts) < 2:
            raise ToolError("a transition needs at least two clips")
        cmd = ["ffmpeg", "-y", "-loglevel", "error"]
        for p in parts:
            cmd += ["-i", str(p)]
        chain: list[str] = []
        last = "0:v"
        length = self.duration(parts[0])
        for i in range(1, len(parts)):
            kind, seconds = transitions.get(i, ("cut", 0.0))
            label = f"v{i}"
            clip = self.duration(parts[i])
            if kind == "cut" or seconds <= 0:
                chain.append(f"[{last}][{i}:v]concat=n=2:v=1:a=0[{label}]")
                length += clip
            else:
                offset = max(length - seconds, 0.0)
                chain.append(
                    f"[{last}][{i}:v]xfade=transition={_XFADE[kind]}:"
                    f"duration={seconds:.3f}:offset={offset:.3f}[{label}]")
                length += clip - seconds
            last = label
        chain.append(f"[{last}]format=yuv420p[vout]")
        cmd += ["-filter_complex", ";".join(chain), "-map", "[vout]",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
                "-pix_fmt", "yuv420p", str(out)]
        self.shell.run(cmd)

    def mux_captioned(
        self, video: Path, audio: Path | None, srt: Path | None, out: Path, *,
        size: tuple[int, int], fps: int, ceiling: float | None = None,
        font: str = "Liberation Sans", font_size: int = 38, crf: int = 19,
    ) -> None:
        w, h = size
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video)]
        if audio is not None:
            cmd += ["-i", str(audio)]
        if srt is not None:
            style = (
                f"PlayResX={w},PlayResY={h},FontName={font},FontSize={font_size},"
                "PrimaryColour=&H00FFFFFF,OutlineColour=&HC0000000,BorderStyle=3,"
                "Outline=2,Shadow=0,MarginV=16,Alignment=2"
            )
            cmd += ["-vf", f"subtitles='{srt.resolve()}':force_style='{style}'"]
        if audio is not None:
            cmd += ["-map", "0:v:0", "-map", "1:a:0", "-shortest"]
            cmd += ["-c:a", "aac", "-b:a", "192k"]
        if ceiling is not None:
            cmd += ["-t", f"{ceiling:.0f}"]
        cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
                "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
        self.shell.run(cmd)

    def mix(
        self, narration: Path | None, score: Path, spans: Sequence[tuple[float, float]],
        out: Path, *, duration: float, volume_db: float, duck_db: float,
        ramp: float, fade_in: float, fade_out: float, sr: int = 48000,
        limit: float = 0.97,
    ) -> MixResult:
        """Lay a music bed under the narration (R-G3).

        ``spans`` are the **measured** (start, end) speech windows. The bed is taken
        down for exactly those windows and nowhere else, so the mix is derived from
        the same clock the pictures are (I5) — a change to the narration moves the
        ducking with it, with no second timing table to keep in sync.

        ``amix`` is deliberately not used. It has no level control on ffmpeg 4.3
        (``normalize=`` arrived in 4.4) and *divides* its sum by the input count, so a
        two-input mix of a quiet bed and a loud voice drops the voice ~3 dB and the
        result depends on the ffmpeg version — a portability bug (R-H6), not a mix.
        ``amerge`` + ``pan`` adds the channels explicitly, which is version-stable and
        does not change level behind the author's back.
        """
        nar = narration if narration is not None and Path(narration).exists() else None
        if nar is None:
            # A silent cut still gets its bed, but there is nothing to duck against.
            # The result says so: `ducked` is False and zero seconds were held down,
            # because a report that claimed otherwise would be describing a mix that
            # was never made. A silent cut is *declared* (I6), not denied.
            self._score_only(score, out, duration=duration, volume_db=volume_db,
                             fade_in=fade_in, fade_out=fade_out, sr=sr, limit=limit)
            return MixResult(out, seconds=0.0, ducked=False, spans=len(spans))

        # a window is only ducked for the part of it that survives inside the film;
        # a span that runs past the end cannot hold the bed down after it stopped
        held = sum(max(0.0, min(b, duration) - min(a, duration))
                   for a, b in spans if b > a)

        chain = [
            "[0:a]aformat=sample_fmts=fltp:channel_layouts=stereo,"
            "asetpts=N/SR/TB[nar]",
            # -stream_loop on the input means the bed lasts as long as the film however
            # short the file is; `atrim` turns that from a hope into a promise
            f"[1:a]aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"volume={volume_db:.2f}dB,"
            f"volume='{_duck_expr(spans, duck_db, ramp)}':eval=frame,"
            f"atrim=0:{duration:.3f},asetpts=N/SR/TB[bed]",
        ]
        bed = "bed"
        if fade_in > 0:
            chain.append(f"[{bed}]afade=t=in:st=0:d={fade_in:.3f}[bedf]")
            bed = "bedf"
        if fade_out > 0:
            start = max(duration - fade_out, 0.0)
            chain.append(f"[{bed}]afade=t=out:st={start:.3f}:d={fade_out:.3f}[bedo]")
            bed = "bedo"
        chain.append(
            f"[nar][{bed}]amerge=inputs=2,pan=stereo|c0=c0+c2|c1=c1+c3,"
            f"alimiter=limit={limit:.2f}[aout]")

        cmd = ["ffmpeg", "-y", "-loglevel", "error",
               "-i", str(nar), "-stream_loop", "-1", "-i", str(score),
               "-filter_complex", ";".join(chain), "-map", "[aout]",
               "-c:a", "pcm_s16le", "-ar", str(sr), str(out)]
        self.shell.run(cmd)
        return MixResult(out, seconds=held, ducked=True, spans=len(spans))

    def _score_only(self, score: Path, out: Path, *, duration: float, volume_db: float,
                    fade_in: float, fade_out: float, sr: int, limit: float) -> None:
        """A bed with no voice over it — the silent film's music."""
        chain = [f"volume={volume_db:.2f}dB,atrim=0:{duration:.3f},asetpts=N/SR/TB"]
        if fade_in > 0:
            chain.append(f"afade=t=in:st=0:d={fade_in:.3f}")
        if fade_out > 0:
            start = max(duration - fade_out, 0.0)
            chain.append(f"afade=t=out:st={start:.3f}:d={fade_out:.3f}")
        chain.append(f"alimiter=limit={limit:.2f}")
        self.shell.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-stream_loop", "-1", "-i", str(score),
            "-af", ",".join(chain), "-c:a", "pcm_s16le", "-ar", str(sr), str(out),
        ])

    def extract_frame(self, video: Path, at: float, out: Path) -> None:
        self.shell.run([
            "ffmpeg", "-y", "-loglevel", "error", "-ss", f"{at:.2f}",
            "-i", str(video), "-frames:v", "1", "-q:v", "2", str(out),
        ])

    def mean_volume(self, media: Path) -> float | None:
        """Mean volume in dB (None if it cannot be measured)."""
        out = self.shell.run(
            ["ffmpeg", "-i", str(media), "-af", "volumedetect", "-f", "null", "-"],
            check=False,
        )
        m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", out)
        return float(m.group(1)) if m else None


class Rsvg:
    """SVG -> PNG rendering."""

    def __init__(self, shell: Shell | None = None) -> None:
        self.shell = shell or Shell()

    @property
    def available(self) -> bool:
        return self.shell.has("rsvg-convert")

    def render(self, svg: Path, out: Path, size: tuple[int, int]) -> None:
        out.parent.mkdir(parents=True, exist_ok=True)
        self.shell.run(["rsvg-convert", "-w", str(size[0]), "-h", str(size[1]),
                        "-o", str(out), str(svg)])
