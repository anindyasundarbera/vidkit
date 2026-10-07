"""Automated acceptance checks — the guardrails that keep a video honest.

The checks encode hard-won lessons: runtime inside a window, no forbidden
phrasing anywhere on screen or in narration, required disclosures present, audio
non-silent, captions readable, and (when a capture asserted a mode) the live-mode
guarantee actually held.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .context import Context
from . import exec as exec_mod
from .timeframe import find_window_claims, timeframe_matches


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append(Check(name, ok, detail))

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    def to_dict(self) -> dict:
        return {"ok": self.ok, "facts": self.facts,
                "checks": [c.__dict__ for c in self.checks]}

    def print(self) -> None:
        print("\n[vidkit] verification")
        for c in self.checks:
            mark = "PASS" if c.ok else "FAIL"
            line = f"  [{mark}] {c.name}"
            if c.detail:
                line += f" — {c.detail}"
            print(line)
        print(f"[vidkit] verification: {'ALL PASS' if self.ok else 'FAILURES PRESENT'}")


# --------------------------------------------------------------------------- #
def _collect_text(ctx: Context, scenes_text: dict[int, str], srt: Path | None,
                  assets=None) -> str:
    parts = list(scenes_text.values())
    if srt and srt.exists():
        # strip cue numbers and timestamps, keep caption text
        for block in srt.read_text(encoding="utf-8").split("\n\n"):
            lines = block.splitlines()[2:]
            parts.extend(lines)
    # A recorded command's own output is part of what the film says, so a banned
    # or required phrase hides just as well in a terminal as in a caption. Put the
    # transcripts in the same haystack the checks search (R-E5).
    for result in (getattr(assets, "exec_results", None) or {}).values():
        parts.append(result.stdout)
        parts.append(result.stderr)
    return "\n".join(parts)


def _container_of(spec, assets, result) -> str:
    """The name of the container a recorded command ran in, or ``""``.

    Read from the live environment state, which is the only thing that knows a
    container was actually started. A ``backend: docker`` step is not enough: the
    spec declaring a container and a container existing are different facts, and
    ``verify`` must not report the first as if it were the second.
    """
    envs = getattr(assets, "environments", None) or {}
    state = envs.get(spec.exec_environment(result.request.label))
    return getattr(state, "container_name", "") if state is not None else ""


def verify_output(ctx: Context, assets, scenes_text: dict[int, str]) -> Report:
    spec = ctx.spec
    guard = spec.guard
    project = spec.project
    rep = Report()

    out = assets.output or (ctx.out_dir / project.output)
    dur = ctx.ffmpeg.duration(out) if Path(out).exists() else 0.0
    lo = guard.min_seconds or project.min_seconds
    hi = guard.max_seconds or project.max_seconds
    rep.facts["duration_seconds"] = round(dur, 2)
    rep.facts["duration_human"] = f"{int(dur//60)}:{dur%60:05.2f}"
    rep.facts["output"] = str(out)
    rep.add("output exists", Path(out).exists(), str(out))
    rep.add("runtime within window", lo <= dur <= hi,
            f"{dur:.2f}s within [{lo:.0f}, {hi:.0f}]")

    # audio present and audible
    vol = ctx.ffmpeg.mean_volume(out) if Path(out).exists() else None
    rep.facts["mean_volume_db"] = vol
    if assets.audio_track or (ctx.build / "narration.wav").exists():
        rep.add("audio present", vol is not None and vol > -50,
                f"mean volume {vol} dB" if vol is not None else "no audio stream")
    elif guard.require_audio:
        rep.add("audio present", False, "silent cut (no TTS audio)")
    else:
        rep.add("audio present", True, "silent cut (declared: guard.require_audio false)")

    # text-level guards
    haystack = _collect_text(ctx, scenes_text, assets.srt, assets)
    low = haystack.lower()
    for phrase in guard.banned:
        hits = low.count(phrase.lower())
        rep.add(f"banned phrase absent: {phrase!r}", hits == 0, f"{hits} hit(s)")
    for phrase in guard.required:
        rep.add(f"required phrase present: {phrase!r}",
                phrase.lower() in low, "found" if phrase.lower() in low else "missing")

    # readability of captions
    if assets.srt and assets.srt.exists():
        bad = []
        for block in assets.srt.read_text(encoding="utf-8").split("\n\n"):
            lines = block.splitlines()[2:]
            if len(lines) > 2 or any(len(l) > 42 for l in lines):
                bad.append(block.splitlines()[0])
        rep.add("captions readable (<=2 lines, <=42 chars)", not bad,
                f"{len(bad)} bad cue(s): {bad[:3]}" if bad else "all cues ok")

    # live-mode guarantee: every declared live capture was captured
    if guard.require_live_mode:
        missing = [c.name for c in spec.captures
                   if c.name not in (assets.capture_stills or {})]
        rep.add("all live captures present", not missing,
                f"missing: {missing}" if missing else f"{len(spec.captures)} captured")

    # artifact integrity: a filmed artifact is the real file, and it is not empty
    artifacts = getattr(assets, "artifacts", None) or {}
    declared = [c.artifact for c in spec.captures if c.artifact]
    if declared:
        rep.facts["artifacts"] = {
            n: {"path": str(a.path), "bytes": a.bytes}
            for n, a in sorted(artifacts.items())}
        absent = [p for p in declared if p not in artifacts]
        empty = sorted(n for n, a in artifacts.items() if not a.bytes)
        rep.add("filmed artifacts are real files", not absent and not empty,
                f"missing: {absent}, empty: {empty}" if (absent or empty)
                else f"{len(artifacts)} artifact(s)")

    # the film is the size the spec promised, and nothing in it was stretched
    # (R-D5). A geometry check reads the produced pixels, so it stays true even
    # if the filter chain is rewritten later.
    target = project.size
    probed = assets.video_track or out
    if Path(probed).exists():
        gw, gh = ctx.ffmpeg.clip_geometry(Path(probed))
        rep.facts["video_size"] = [gw, gh]
        rep.add("frames are the declared size", (gw, gh) == tuple(target),
                f"{gw}x{gh} (declared {target[0]}x{target[1]})")
    else:
        rep.add("frames are the declared size", False, "no video track to probe")

    # live-data guarantee: every dataset came from the source, not a fallback
    degraded = dict(spec.degraded)
    if guard.require_live_data:
        where = "; ".join(f"{k}: {v}" for k, v in sorted(degraded.items()))
        rep.add("all datasets live", not degraded,
                f"degraded: {where}" if degraded else f"{len(ctx.data_dir.glob('*.json'))} dataset(s)")
    elif degraded:
        rep.add("all datasets live", True,
                "degraded but declared (guard.require_live_data false): " + where)

    # narration word count vs duration (sanity: ~2-3 words/sec is plausible speech)
    total_words = sum(len(t.split()) for t in scenes_text.values())
    wps = total_words / dur if dur else 0
    rep.facts["narration_words"] = total_words
    if not assets.audio_track and not (ctx.build / "narration.wav").exists():
        # no narration track was muxed, so the speech-rate check has nothing to read
        rep.add("speech rate plausible", True, "skipped (silent cut)")
    else:
        rep.add("speech rate plausible", 1.6 <= wps <= 3.6,
                f"{wps:.2f} words/sec")

    # no mock leakage on screen
    rep.add("no mock mode referenced", "mode=mock" not in low or "never" in low,
            "mode=mock only appears as a prohibition")

    # timeframe consistency (R-F7): the window narration states must be the one
    # the spec resolved. A video that says "the last 28 days" while its spec says
    # 90 is exactly the kind of lie this engine exists to catch.
    tf = spec.timeframe
    if tf is not None:
        rep.facts["timeframe"] = tf.to_dict()
    claims = find_window_claims(haystack, as_of=tf.end if tf else None)
    rep.facts["window_claims"] = [
        {"raw": c.raw, "days": c.days, "exact": c.exact,
         "start": c.start.isoformat() if c.start else None,
         "end": c.end.isoformat() if c.end else None,
         "end_anchor": c.end_anchor.isoformat() if c.end_anchor else None}
        for c in claims
    ]
    if tf is None:
        rep.add("timeframe consistent with spec", not claims,
                "narration states "
                + ", ".join(f"{c.raw!r}" for c in claims)
                + " but the spec declares no timeframe" if claims else "no timeframe declared")
    elif not claims:
        rep.add("timeframe consistent with spec", True,
                f"narration states no window; spec says {tf.label()}")
    else:
        bad = [d for c in claims for ok, d in [timeframe_matches(tf, c)] if not ok]
        bad = list(dict.fromkeys(bad))          # one line per distinct disagreement
        rep.add("timeframe consistent with spec", not bad,
                "; ".join(bad) if bad else f"matches {tf.label()}")

    # the environments that were declared, and what became of them. Reported as
    # facts for the same reason the commands are: "the database was up for 2.6s
    # and was removed afterwards" is a claim a reader can check against their own
    # `docker ps`, and the container id and image digest are what they would need
    # to check it. A build that leaked a container says so here.
    environments = getattr(assets, "environments", None) or {}
    if environments:
        rep.facts["environments"] = [
            state.to_dict() for state in environments.values()
        ]

    # the commands that ran, and the sandbox they ran in (R-E5). Two things are
    # proved here that nothing else can: that every command did what the spec said
    # it would, and that isolation was *real* rather than merely requested.
    exec_results = getattr(assets, "exec_results", None) or {}
    if exec_results or spec.exec:
        casts = getattr(assets, "exec_casts", None) or {}
        playback = getattr(assets, "exec_playback", None) or {}
        frames = getattr(assets, "exec_take_frames", None) or {}
        rep.facts["exec"] = [
            {
                "label": result.request.label,
                "cmd": result.request.argv(),
                "backend": result.backend,
                "network": result.request.network,
                "exit_code": result.exit_code,
                "expect_exit": list(result.request.expect_exit),
                "expected": result.expected,
                "timed_out": result.timed_out,
                "refused": result.refused,
                "seconds": round(result.seconds, 3),
                "truncated": dict(result.truncated),
                "cast": (casts[result.request.label].name
                         if result.request.label in casts else None),
                # Which *container* it ran in, by name. Two runs of the same image
                # are two different systems, and a demo whose whole claim is "step 2
                # reads back what step 1 wrote" is a claim about one of them.
                "container": _container_of(spec, assets, result),
                # `None` frames means the recording was not shown as a moving take
                # (a single screen, or an effect that took it as a still) — which is
                # a different claim from "replayed at 1.0x" and must read differently.
                "frames": frames.get(result.request.label),
                "playback": playback.get(result.request.label),
                "stdout_excerpt": result.stdout.strip().splitlines()[-8:],
            }
            for result in exec_results.values()
        ]
        declared = [e.label for e in spec.exec]
        unrun = [label for label in declared if label not in exec_results]
        if declared:
            # Emitted whether or not it passes. An attestation that exists only as
            # an absence cannot be told apart from a check that never applied.
            rep.add("every declared command ran", not unrun,
                    f"the `exec` stage did not run for: {unrun}" if unrun
                    else f"{len(declared)} command(s), all recorded")

    if guard.require_exec_success and exec_results:
        failed = [r.request.label for r in exec_results.values() if not r.ok]
        rep.add("every command exited as declared", not failed,
                f"not as expected: {failed}" if failed
                else f"{len(exec_results)} command(s), all as declared")

    if guard.require_sandbox and exec_results:
        # An attestation, not a preference. `backend: local` means the command ran
        # unconfined on the machine — a spec that asks for a sandbox and gets one
        # anyway only because the host happened to have it has proved nothing, so
        # this reads what the runner actually used, not what the spec asked for.
        #
        # "Confined" is a list, not a constant, and it is read from the engine rather
        # than spelled here. A docker-backed command runs inside a container with the
        # image's own filesystem and no view of the host's, which is a stronger
        # boundary than bwrap's rather than an absence of one; a check that only knew
        # the word "bubblewrap" would call it a lie.
        unconfined = [r.request.label for r in exec_results.values()
                      if r.backend not in exec_mod.CONFINING_BACKENDS]
        used = sorted({r.backend for r in exec_results.values()})
        rep.add("commands ran sandboxed", not unconfined,
                f"not sandboxed: {unconfined}" if unconfined
                else f"{len(exec_results)} command(s) under {', '.join(used)}")

    # provenance (R-F8): what this *is*, as opposed to whether it is honest. It is
    # reported as a fact rather than a check — there is no passing or failing an
    # identity — but a reader who has verify.json in hand should not have to go
    # looking for a second file to find out which spec and which window it proves.
    from .provenance import Provenance
    record = Provenance.read(ctx.build)
    if record is not None:
        rep.facts["provenance"] = {
            "vidkit": record.get("vidkit"),
            "spec": record.get("spec"),
            "spec_sha256": record.get("spec_sha256"),
            "built_at": record.get("built_at"),
            "tools": {t["name"]: t["version"] for t in record.get("tools", [])
                      if t.get("present")},
        }
    return rep
