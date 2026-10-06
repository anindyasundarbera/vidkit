"""Text-to-speech: one WAV per scene, so audio and video share one clock.

The default engine is `piper <https://github.com/rhasspy/piper>`_ (fast, local,
offline). Install with ``pip install piper-tts`` and fetch a voice with
``python -m piper.download_voices en_US-lessac-medium``.

If no engine is available, ``synthesize`` returns zero-duration spans and the
assembler produces a silent cut sized from the script wording — the pipeline
never hard-fails just because a voice is missing.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .context import Context
from .ffmpeg import Ffmpeg
from .narration import SceneScript


@dataclass
class SceneAudio:
    n: int
    path: Path | None
    seconds: float
    words: int


# Rough speech rate when no TTS engine is present (~150 wpm).
_FALLBACK_WPS = 2.5


def _piper_cmd(ctx: Context, text_path: Path, out: Path) -> list[str]:
    voice = ctx.spec.voice
    if not voice.model:
        raise ValueError("voice.model is not set")
    model = Path(voice.model)
    if not model.is_absolute():
        # resolve relative to the spec folder, then the repo root, then CWD
        for base in (ctx.root, ctx.root.parent, Path.cwd()):
            candidate = (base / voice.model)
            if candidate.exists():
                model = candidate
                break
    exe = voice.executable
    if exe:
        base = [exe]
    else:
        # prefer `python -m piper` from the running interpreter
        import sys
        base = [sys.executable, "-m", "piper"]
    cmd = base + ["-m", str(model), "-f", str(out),
                  "--length-scale", str(voice.length_scale)]
    if voice.sentence_silence is not None:
        cmd += ["--sentence-silence", str(voice.sentence_silence)]
    cmd += ["-i", str(text_path)]
    return cmd


def _engine_available(ctx: Context) -> bool:
    voice = ctx.spec.voice
    if voice.engine == "none":
        return False
    if voice.executable:
        return True
    try:
        import importlib.util
        return importlib.util.find_spec("piper") is not None
    except Exception:
        return False


def synthesize(ctx: Context, scripts: list[SceneScript]) -> list[SceneAudio]:
    """Synthesize each scene; measure the real durations with ffmpeg."""
    ctx.wavs.mkdir(parents=True, exist_ok=True)
    ff = Ffmpeg(ctx.shell)
    have_engine = _engine_available(ctx)
    if not have_engine:
        ctx.warn("no TTS engine available (voice.engine/piper) — producing a silent cut; "
                 "scene lengths are estimated from the script wording")

    results: list[SceneAudio] = []
    for sc in scripts:
        words = len(sc.spoken.split())
        text_path = ctx.wavs / f"scene-{sc.n:02d}.txt"
        text_path.write_text(sc.spoken, encoding="utf-8")
        wav = ctx.wavs / f"scene-{sc.n:02d}.wav"
        if have_engine:
            try:
                cmd = _piper_cmd(ctx, text_path, wav)
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode != 0 or not wav.exists():
                    raise RuntimeError((result.stderr or "no output")[-800:])
                seconds = ff.duration(wav)
            except Exception as exc:  # noqa: BLE001
                ctx.warn(f"TTS failed for scene {sc.n} ({exc}); estimating duration")
                seconds = words / _FALLBACK_WPS
                wav = None
        else:
            seconds = words / _FALLBACK_WPS
            wav = None
        results.append(SceneAudio(sc.n, wav, round(seconds, 3), words))
    total = sum(r.seconds for r in results)
    ctx.info(f"narration: {len(results)} scenes, {total:.2f}s ({total/60:.2f} min)")
    return results


def concat_audio(ctx: Context, parts: list[SceneAudio]) -> Path | None:
    """Concatenate the per-scene wavs into one narration track (None if silent)."""
    wavs = [p.path for p in parts if p.path is not None]
    if not wavs:
        return None
    listfile = ctx.wavs / "audio.txt"
    out = ctx.build / "narration.wav"
    listfile.write_text("".join(f"file '{w}'\n" for w in wavs), encoding="utf-8")
    ctx.ffmpeg.concat(wavs, out, listfile)
    return out
