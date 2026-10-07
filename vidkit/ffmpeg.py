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
    ) -> None:
        """Render a still PNG to a fixed-length clip. ``hold`` keeps it static;
        ``zoom`` applies a slow Ken-Burns push-in (ends at ``1+zoom``).

        The still is scaled to fill ``size`` without distortion (see
        :func:`fit_filters`), so a full-page capture is cropped, never squashed.
        ``fit='contain'`` letterboxes instead, which is the honest choice for a
        document page whose *whole* extent matters — nothing is hidden, and the
        bars state plainly that the page is not 16:9.
        """
        w, h = size
        if effect == "zoom":
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
