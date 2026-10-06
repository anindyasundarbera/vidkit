"""Narration parsing and SRT caption generation.

Two things live here:

* :func:`parse_scene_script` reads a Markdown narration file whose scenes are
  headed ``## Scene N — title · mm:ss–mm:ss`` with the *spoken* lines in bold
  (``**...**``); bracketed ``[...]`` lines are stage directions and are ignored.
* :func:`build_srt` turns scene text + real scene durations into a readable SRT
  (at most 2 lines, at most 42 characters per line) and asserts that no spoken
  word was dropped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import SpecError

WIDTH = 42
CLAUSE_CAP = 72
_SCENE_RE = re.compile(r"^##\s*Scene\s+(\d+)\b.*?·\s*(\d+:\d+)\s*[–-]\s*(\d+:\d+)\s*$", re.M)


@dataclass
class SceneScript:
    n: int
    spoken: str


def _to_seconds(mmss: str) -> float:
    m, s = mmss.split(":")
    return int(m) * 60 + int(s)


def parse_scene_script(text: str) -> list[SceneScript]:
    """Extract each scene's spoken text from a narration Markdown file."""
    headers = list(_SCENE_RE.finditer(text))
    if not headers:
        raise SpecError("narration file has no '## Scene N — … · mm:ss–mm:ss' headers")
    out: list[SceneScript] = []
    for i, m in enumerate(headers):
        stop = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        body = text[m.end():stop].split("### ")[0]
        spoken_lines = [
            ln.strip().strip("*")
            for ln in body.splitlines()
            if ln.strip().startswith("**") and ln.strip().endswith("**")
        ]
        spoken = re.sub(r"\s+", " ", " ".join(spoken_lines)).strip()
        if spoken:
            out.append(SceneScript(n=int(m.group(1)), spoken=spoken))
    if not out:
        raise SpecError("no spoken (**bold**) lines found in narration file")
    return out


def scene_timeline(text: str) -> dict[int, tuple[float, float]]:
    """Scene n -> (start, end) as written in the narration file (for reference)."""
    return {
        int(m.group(1)): (_to_seconds(m.group(2)), _to_seconds(m.group(3)))
        for m in _SCENE_RE.finditer(text)
    }


# --------------------------------------------------------------------------- #
def _split_long(p: str, limit: int = CLAUSE_CAP) -> list[str]:
    if len(p) <= limit:
        return [p]
    pieces = re.split(r"(?<=[;:,—])\s+", p)
    out: list[str] = []
    cur = ""
    for s in pieces:
        if not cur:
            cur = s
        elif len(cur) + 1 + len(s) <= limit:
            cur += " " + s
        else:
            out.append(cur); cur = s
    if cur:
        out.append(cur)
    final: list[str] = []
    for x in out:
        if len(x) <= limit:
            final.append(x)
            continue
        words, cur = x.split(), ""
        for w in words:
            if not cur:
                cur = w
            elif len(cur) + 1 + len(w) <= limit:
                cur += " " + w
            else:
                final.append(cur); cur = w
        if cur:
            final.append(cur)
    return final


def _clauses(text: str) -> list[str]:
    parts = re.split(r"(?<=[.?!])\s+", text)
    out: list[str] = []
    for p in parts:
        out.extend(_split_long(p))
    merged: list[str] = []
    for p in out:
        if merged and len(merged[-1]) < 24 and len(merged[-1]) + 1 + len(p) <= CLAUSE_CAP:
            merged[-1] += " " + p
        else:
            merged.append(p)
    final: list[str] = []
    for m in merged:
        final.extend(_split_long(m) if len(m) > CLAUSE_CAP else [m])
    return final


def wrap_caption(s: str, width: int = WIDTH) -> list[str]:
    """Greedy word wrap to <= ``width`` chars; returns at most 2 lines."""
    words, lines, cur = s.split(), [], ""
    for w in words:
        if len(cur) + (1 if cur else 0) + len(w) <= width:
            cur = (cur + " " + w).strip()
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    return lines[:2] if len(lines) <= 2 else lines


def _ts(t: float) -> str:
    t = max(0.0, t)
    h, m, s = int(t // 3600), int((t % 3600) // 60), t % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def build_srt(scene_texts: dict[int, str], scene_spans: list[tuple[int, float, float]],
              *, strict: bool = True) -> str:
    """Build an SRT retimed to the *actual* scene spans.

    ``scene_spans`` is ``[(scene_n, start, end), ...]`` from measured audio.
    """
    cues: list[tuple[float, float, str]] = []
    for n, start, end in scene_spans:
        spoken = scene_texts.get(n, "")
        if not spoken:
            continue
        cl = _clauses(spoken)
        total = sum(len(c) for c in cl) or 1
        t = start
        for c in cl:
            d = (end - start) * (len(c) / total)
            cues.append((t, t + d, c)); t += d

    if strict:
        norm = lambda s: re.findall(r"[a-z0-9']+", re.sub(r"\s+", " ", s).lower())
        got = norm(" ".join(c[2] for c in cues))
        want = norm(" ".join(scene_texts.get(n, "") for n, _, _ in scene_spans))
        if got != want:
            raise SpecError("caption fidelity check failed: text was dropped or reordered")

    blocks: list[str] = []
    for i, (s, e, txt) in enumerate(cues, 1):
        lines = wrap_caption(txt)
        if strict and (len(lines) > 2 or any(len(l) > WIDTH for l in lines)):
            raise SpecError(f"caption cue {i} is not readable: {lines}")
        blocks.append(f"{i}\n{_ts(s)} --> {_ts(max(s, e - 0.04))}\n" + "\n".join(lines) + "\n")
    return "\n".join(blocks)


def word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9']+", text))
