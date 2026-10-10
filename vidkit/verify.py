"""Automated acceptance checks — the guardrails that keep a video honest.

The checks encode hard-won lessons: runtime inside a window, no forbidden
phrasing anywhere on screen or in narration, required disclosures present, audio
non-silent, captions readable, and (when a capture asserted a mode) the live-mode
guarantee actually held.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import exec as exec_mod
from .context import Context
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


#: The three honest sources a picture in a vidkit film can come from, and the shot
#: kinds that draw from each. This table is the honesty rule (I7) written down as
#: data rather than as a paragraph, so that a new shot kind cannot be added without
#: someone deciding which of the three it is. A kind in *neither* column is refused
#: outright — "rendered from nothing" is the category M9 was warned against
#: creating, and the only way to keep it from creeping in is to fail the build.
SHOT_SOURCES: dict[str, str] = {
    "capture": "live capture",     # a browser photographing a running product
    "exec": "live capture",        # a real program's real output, replayed from a cast
    "chart": "measured data",      # a panel drawn from a provider's own numbers
    "still": "declared asset",     # a file the author shipped
    "card": "declared asset",      # typography over the spec's own words
    "solid": "declared asset",     # one flat colour
}


def _artwork_facts(spec, assets) -> list[dict[str, Any]]:
    """Every shot in the film, with the source its picture actually came from."""
    stills = getattr(assets, "stills", None) or {}
    captures = getattr(assets, "capture_stills", None) or {}
    panels = getattr(assets, "panel_stills", None) or {}
    rows = []
    for sc in spec.scenes:
        for idx, shot in enumerate(sc.shots):
            if shot.kind == "capture":
                where = captures.get(shot.ref)
            elif shot.kind == "chart":
                where = panels.get(shot.ref)
            elif shot.kind in ("card", "solid"):
                where = None  # the engine drew it; there is no source file to name
            else:
                where = stills.get(shot.ref)
            row: dict[str, Any] = {
                "scene": sc.n, "index": idx, "kind": shot.kind,
                "ref": shot.ref, "source": SHOT_SOURCES.get(shot.kind, "UNKNOWN"),
                "file": str(where) if where else None,
                "seconds": None if shot.seconds is None else round(shot.seconds, 3),
            }
            if shot.motion is not None:
                row["motion"] = shot.motion.to_dict()
            elif shot.effect not in ("hold", "", None):
                # the M4 spelling, kept so a spec written before `motion:` existed
                # still reports the move it is actually making
                row["motion"] = {"kind": shot.effect, "direction": "in",
                                 "amount": 0.10, "span": 1.0, "at": "start"}
            rows.append(row)
    return rows


#: How much a picture has to change, as mean absolute RGB difference per channel
#: (0-255), before a declared camera move counts as having moved it. Calibrated on
#: the ``movie-demo`` fixture: a genuine pan or push-in over artwork measures 1.3-5.7,
#: and *anything* over a flat ``solid`` measures 0.00 however far the camera travels,
#: because a uniform field has nothing in it to shift. A tenth of a level is far
#: below the first and far above the second.
MOVE_MAE = 0.10


def _measure_move(ctx: Context, row: dict[str, Any]) -> float | None:
    """How much scene ``row['scene']``'s clip ``row['index']`` (shot) moves. ``None`` if
    the clip could not be read.

    A declared move is a claim about the picture, so this reads the picture: one real
    frame near the head of the clip and one near its tail, decoded to RGB and
    differenced. That is the only way to tell a push-in from a still — the filterchain
    is a string either way, and an expression ffmpeg folds to a constant renders a
    perfectly static frame with no error at all.

    Deliberately *not* a check that every declared move produced movement: a pan across
    a flat colour is an honest thing to ask for, and the frame it produces is the frame
    that was asked for. What must not happen is the report saying "5 shots move" when
    four do.
    """
    clip = ctx.clips / f"scene-{row['scene']:02d}-{row['index']}.mp4"
    if not clip.exists():
        return None
    try:
        seconds = ctx.ffmpeg.duration(clip)
        if seconds <= 0:
            return None
        scratch = ctx.build / "verify-motion.raw"
        head = ctx.ffmpeg.frame_rgb(clip, seconds * 0.08, scratch, size=(64, 36))
        tail = ctx.ffmpeg.frame_rgb(clip, seconds * 0.92, scratch, size=(64, 36))
    except Exception:  # noqa: BLE001 - a measurement that failed is not a measurement
        return None
    finally:
        (ctx.build / "verify-motion.raw").unlink(missing_ok=True)
    if not head or len(head) != len(tail):
        return None
    return round(sum(abs(a - b) for a, b in zip(head, tail)) / len(head), 3)


def _narration_facts(scene_audio: list) -> dict:
    """Where the spoken words sit in the cut — measured, or named as an estimate.

    ``narration_spans`` reads as *seek here and you will hear the words*, and a reviewer
    acts on it: the score is ducked under exactly those windows. So the name is only
    earned when each scene has a real recording to seek into. With no voice engine the
    audio stage divides a scene's word count by the fallback 2.5 words/second and moves
    on — there is no recording. Publishing those durations as spans claimed positions in
    a cut they do not describe: the silent ``movie-demo`` reported five spans totalling
    35.6s for a film 16.01s long. An unmeasured number is still worth reporting, but not
    under a name that asserts it was measured.
    """
    if not scene_audio:
        return {}
    # Imported here, not at module scope: `assembler` imports this module, so a
    # top-level import is circular. It must be bound inside whichever function reads
    # it — a sibling scope cannot see it, and a generator expression is a scope.
    from .assembler import _spans
    # str keys, matching what a JSON round-trip produces — otherwise this fact reads
    # one way in-process (`facts["narration_spans"][1]`) and another on disk (`...["1"]`).
    spans = {str(n): [round(a, 3), round(b, 3)]
             for n, a, b in _spans(scene_audio)}
    if all(a.path is not None and Path(a.path).exists() for a in scene_audio):
        return {"narration_spans": spans}
    return {"narration_estimate": spans}


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
    # A scored film is not a silent film. The voice may be absent by declaration, but
    # there is still an audio stream, and calling it a silent cut would read as "this
    # film has no sound" about one whose whole point is a music bed.
    scored = spec.score is not None
    if assets.audio_track or (ctx.build / "narration.wav").exists():
        rep.add("audio present", vol is not None and vol > -50,
                f"mean volume {vol} dB" if vol is not None else "no audio stream")
    elif scored:
        rep.add("audio present", vol is not None and vol > -50,
                f"mean volume {vol} dB (score only — no voice on this cut)"
                if vol is not None else "no audio stream")
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

    # --- movie mode (M9) -------------------------------------------------- #
    # Three fact classes and three checks, added together because a fact nobody
    # checks is decoration. The rule from M7's defects E and F holds: a check that
    # *passes* must be written down. An attestation that exists only as an absence
    # cannot be told apart from a check that never applied.
    artwork = _artwork_facts(spec, assets)
    if artwork:
        sources = sorted({row["source"] for row in artwork})
        unknown = [f"{r['kind']}:{r['ref']}" for r in artwork
                   if r["source"] == "UNKNOWN"]
        rep.facts["artwork"] = artwork
        rep.facts["artwork_sources"] = sources
        rep.add("every picture has an honest source", not unknown,
                f"unclassified: {unknown}" if unknown
                else f"{len(artwork)} shot(s) from {', '.join(sources)}")

    moved = [r for r in artwork if r.get("motion")]
    if moved:
        # A camera move is reported because it is a *claim about the picture*: a
        # push-in says "look here". So the claim is measured rather than restated —
        # the head and the tail of the clip are decoded and compared, and the row
        # carries the difference. Declaring a move and rendering a still picture are
        # both fine; what is not fine is the report being unable to tell them apart.
        # (It could not, before this: the check compared a list against a filter of
        # itself and so could never fail.)
        for row in moved:
            row["motion"]["mae"] = _measure_move(ctx, row)
        rep.facts["motion"] = [
            {"scene": r["scene"], "index": r["index"], "kind": r["kind"],
             **r["motion"]} for r in moved
        ]
        unmeasured = [f"scene {r['scene']} shot {r['index']}"
                      for r in moved if r["motion"]["mae"] is None]
        still_n = [r for r in moved
                   if r["motion"]["mae"] is not None and r["motion"]["mae"] < MOVE_MAE]
        rep.add("every camera move is accounted for", not unmeasured,
                f"could not measure {unmeasured}" if unmeasured
                else f"{len(moved) - len(still_n)} of {len(moved)} declared move(s) "
                     f"change the picture"
                     + (f"; {len(still_n)} over a field with nothing in it to reveal"
                        if still_n else ""))

    # Imported here rather than at module scope because `assembler` imports *this*
    # module. It is bound unconditionally — it used to be bound inside a branch and
    # read inside a *different* branch's generator expression, and a generator is a
    # separate scope, so the two never shared the name: any spec declaring a `score:`
    # and no narration raised UnboundLocalError before this line.
    rep.facts.update(_narration_facts(assets.scene_audio))

    rep.facts["timing_source"] = spec.timing_source
    if spec.timing_source == "spec":
        # Not a failure — a film cut to a declared length is a legitimate film. But
        # it is a *different claim*: narration is no longer the master clock (I5), so
        # the runtime proves the spec and not the recording, and a reader is entitled
        # to know which one they are looking at.
        declared = [f"scene {sc.n} = {sc.seconds:g}s" for sc in spec.scenes
                    if sc.seconds is not None]
        declared += [f"scene {sc.n} shot {i} = {sh.seconds:g}s"
                     for sc in spec.scenes for i, sh in enumerate(sc.shots)
                     if sh.seconds is not None]
        rep.add("shot timing is expressed, not measured", True,
                f"declared: {'; '.join(declared)} — the voice was cut to the "
                f"spec, so narration is not the master clock for these")

    if spec.score is not None:
        # A declared score is a promise, so the report says whether one was mixed —
        # and *what the mix did*, not what the spec asked for. `assets.mix` is set by
        # the mix itself rather than computed here: asking the spec whether music
        # *should* be present would be an assumption dressed as a fact, and the whole
        # point of the report is to state what happened.
        #
        # `duck_seconds` therefore comes from the mix's own result. It used to be
        # recomputed here from the narration spans, which made every scored film claim
        # it had ducked for the whole narration — including a *silent cut*, where the
        # mix takes the score-only branch and ducks for nobody. The spans were real;
        # the ducking was not.
        mixed_path = getattr(assets, "mix", None)
        result = getattr(assets, "mix_result", None)
        mixed_by_build = mixed_path is not None and Path(mixed_path).exists()
        facts = {
            "src": spec.score.src,
            "volume_db": round(spec.score.volume, 2),
            "duck_db": round(spec.score.duck_db, 2),
            "ramp": spec.score.ramp,
            "mixed": str(mixed_path) if mixed_by_build else None,
        }
        # A build hands over its own mix. A bare `vidkit verify` never mixed anything:
        # it re-reads a film somebody else built, so it looks for the mix beside it
        # rather than declaring a promise unmet.
        if result is None and (ctx.build / "mix.wav").exists():
            found = ctx.build / "mix.wav"
            facts["mixed"] = str(found)
            mixed_by_build = True
        if result is not None:
            facts["duck_seconds"] = round(result.seconds, 3)
            facts["ducked"] = result.ducked
        else:
            # Re-read, not re-mixed: the ducking length is not recoverable from the
            # wav, and inventing it from the narration spans is exactly the fabrication
            # being removed here. Say so instead.
            facts["duck_seconds"] = None
            facts["ducked"] = None
        rep.facts["score"] = facts

        if not mixed_by_build:
            detail = "declared but no mix was written"
        elif facts["ducked"] is True:
            detail = (f"mixed under {result.spans} narration span(s) covering "
                      f"{result.seconds:.1f}s of {dur:.1f}s")
        elif facts["ducked"] is False:
            # Honest by construction: the film is scored but nobody speaks on it, so
            # the bed plays alone. There was nothing to duck under, and the report says
            # so rather than claiming a ducking that never happened.
            detail = ("the score plays alone — this cut is silent, so there is nothing "
                      "to duck under")
        else:
            # A re-read found the mix on disk but did not make it, and the ducking
            # length is not recoverable from the wav. Saying "it ducked for 16s" here is
            # the same fabrication in a quieter voice.
            detail = (f"mix reads {Path(facts['mixed']).name} — rebuild to have the "
                      f"ducking measured again")
        rep.add("declared score is in the mix", mixed_by_build, detail)

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
