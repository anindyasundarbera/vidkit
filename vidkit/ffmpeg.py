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


class Ffmpeg:
    """ffmpeg/ffprobe helpers. Duration is read without ffprobe (it is optional)."""

    _DUR = re.compile(r"Duration: (\d+):(\d+):([\d.]+)")

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
        zoom: float = 0.10, crf: int = 19,
    ) -> None:
        """Render a still PNG to a fixed-length clip. ``hold`` keeps it static;
        ``zoom`` applies a slow Ken-Burns push-in (ends at ``1+zoom``)."""
        w, h = size
        if effect == "zoom":
            rate = zoom / max(seconds * fps, 1)
            vf = (
                f"scale={int(w * 1.25)}:{int(h * 1.25)},"
                f"zoompan=z='min(1.0+on*{rate:.6f},{1.0 + zoom:.3f})':d=1:"
                f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={fps},"
                "format=yuv420p"
            )
        else:
            vf = f"scale={w}:{h},setsar=1,fps={fps},format=yuv420p"
        self.shell.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-loop", "1", "-framerate", str(fps), "-i", str(image),
            "-t", f"{seconds:.3f}", "-vf", vf,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
            "-pix_fmt", "yuv420p", str(out),
        ])

    def concat(self, parts: Sequence[Path], out: Path, listfile: Path) -> None:
        listfile.write_text("".join(f"file '{p}'\n" for p in parts), encoding="utf-8")
        self.shell.run([
            "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
            "-i", str(listfile), "-c", "copy", str(out),
        ])

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
