"""Command-line interface.

    vidkit doctor [SPEC]     check the environment and every dependency
    vidkit plan   SPEC       show the scene plan and estimated runtime
    vidkit build  SPEC [--only a,b] [--out DIR]
    vidkit tts    SPEC       (re)synthesize narration only
    vidkit capture SPEC      (re)capture screen recordings only
    vidkit verify SPEC       re-run the acceptance checks on the last render
    vidkit init   DIR        scaffold a runnable story (spec + narration + provider)
    vidkit docs   [NAME]     print the docs router, or a named document

``--timeframe``/``--days``/``--as-of`` override the window declared by the spec or its
``story.yaml``, for every command that loads a spec. ``--days`` is a shorthand for
``--timeframe "Nd"`` ending at ``--as-of`` (today, if omitted).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .assembler import Assets, make_context, run
from .errors import VidkitError
from .narration import parse_scene_script, word_count
from .panels import kinds as panel_kinds
from .secrets import Secrets
from .spec import load_spec
from .scaffold import scaffold_story
from .timeframe import Timeframe, parse_timeframe


# --------------------------------------------------------------------------- #
def _override(args) -> Timeframe | None:
    """Build a timeframe override from ``--timeframe`` / ``--days`` / ``--as-of``."""
    raw = getattr(args, "timeframe", None)
    days = getattr(args, "days", None)
    as_of = getattr(args, "as_of", None)
    if days is not None:
        if raw:
            raise VidkitError("use either --timeframe or --days, not both")
        raw = f"{days}d"
    if raw is None:
        if as_of is not None:
            raise VidkitError("--as-of only makes sense with --timeframe or --days")
        return None
    return parse_timeframe(raw, where="--timeframe", source="override", default_as_of=as_of)


def _add_timeframe_args(p) -> None:
    p.add_argument("--timeframe", default=None, metavar="SPEC",
                   help='override the window: "28d", "6m", "2026-09-08..2026-10-06", '
                        '"{days: 28, as_of: 2026-10-06}"')
    p.add_argument("--days", type=int, default=None, metavar="N",
                   help='shorthand for --timeframe "Nd"')
    p.add_argument("--as-of", default=None, metavar="DATE",
                   help="the day a relative window ends (default: today)")


def _doctor(spec_path: Path | None, timeframe: Timeframe | None = None) -> int:
    from .capture import _find_chrome, _playwright_available
    from .ffmpeg import Ffmpeg, Rsvg, Shell

    sh = Shell()
    print(f"vidkit {__version__}  (python {sys.version.split()[0]})")
    ok = True

    checks = [
        ("ffmpeg", sh.has("ffmpeg"), "required — renders and muxes video"),
        ("ffprobe", sh.has("ffprobe"), "optional — durations read from ffmpeg if absent"),
        ("rsvg-convert", sh.has("rsvg-convert"), "required — SVG assets to PNG"),
    ]
    for name, present, note in checks:
        req = "required" in note
        status = "yes" if present else ("NO " if req else "no ")
        print(f"  [{status}] {name:16s} {note}")
        if req and not present:
            ok = False

    have_pw = _playwright_available()
    chrome = _find_chrome()
    print(f"  [{'yes' if have_pw else 'no '}] {'playwright':16s} "
          f"{'optional — screen capture'}")
    print(f"  [{'yes' if chrome else 'no '}] {'chrome/chromium':16s} "
          f"{chrome or 'optional — needed for capture'}")

    import importlib.util
    have_piper = importlib.util.find_spec("piper") is not None
    print(f"  [{'yes' if have_piper else 'no '}] {'piper (TTS)':16s} "
          f"{'optional — narration audio'}")

    if spec_path:
        try:
            spec = load_spec(spec_path, timeframe=timeframe)
        except VidkitError as exc:
            print(f"  [NO ] spec              {exc}")
            return 1
        print(f"  [yes] spec              {spec_path}")
        print(f"        project         {spec.project.title} ({spec.project.slug})")
        print(f"        size/fps        {spec.project.width}x{spec.project.height} @ {spec.project.fps}")
        print(f"        scenes          {len(spec.scenes)}")
        print(f"        captures        {len(spec.captures)}")
        print(f"        charts          {len(spec.charts)}")
        print(f"        provider        {spec.provider_name or '(none)'}")
        if spec.story:
            note = "" if spec.story.declared else "  (folder convention)"
            print(f"        story           {spec.story.slug}{note}")
        else:
            print("        story           (not resolved)")
        tf = spec.timeframe
        print(f"        timeframe       {tf.label_with_source if tf else '(not declared)'}")
        print(f"        panel kinds     {', '.join(panel_kinds())}")
        ok = _doctor_secrets(spec) and ok
    return 0 if ok else 1


def _doctor_secrets(spec) -> bool:
    """Print what the provider will ask for, masked, and fail on a missing must.

    Nothing here ever contains a value: ``Secrets.describe`` renders a length,
    which is enough to tell a wrong token from an absent one (R-B4).
    """
    if spec.provider is None:
        return True
    from .provider import collect_secrets, load_provider

    declared = dict(spec.provider.secrets)
    try:
        module, _ = load_provider(spec.provider.module, spec.root)
        declared.update(collect_secrets(module))
    except VidkitError as exc:
        print(f"  [NO ] provider          {exc}")
        return False

    needs = Secrets()
    needs.declare(declared, why=f"declared by provider {spec.provider.module!r}")
    needs.resolve()
    print(f"        secrets         provider {spec.provider.module!r}")
    if not needs.needs:
        print("          (none declared)")
    for line in needs.describe():
        print(f"          {line}")
    missing = needs.missing_required()
    if missing:
        print(f"  [NO ] secrets           not set: {', '.join(missing)}")
        return False
    return True


def _plan(spec_path: Path, timeframe: Timeframe | None = None) -> int:
    spec = load_spec(spec_path, timeframe=timeframe)
    print(f"{spec.project.title}  [{spec.project.slug}]")
    print(f"  output: {spec.project.output}  {spec.project.width}x{spec.project.height} "
          f"@{spec.project.fps}")
    print(f"  runtime window: {spec.project.min_seconds:.0f}-{spec.project.max_seconds:.0f}s")
    if spec.story:
        note = "" if spec.story.declared else "  (folder convention)"
        print(f"  story: {spec.story.slug}{note}")
    else:
        print("  story: (not resolved)")
    print(f"  timeframe: {spec.timeframe.label_with_source if spec.timeframe else '(not declared)'}")
    total_words = 0
    source = None
    if spec.narration.source:
        p = (spec_path.parent / spec.narration.source)
        if p.exists():
            source = {s.n: s.spoken for s in parse_scene_script(p.read_text())}
    print("  scenes:")
    for sc in spec.scenes:
        text = spec.narration.inline.get(sc.n) or (source or {}).get(sc.n, "")
        w = word_count(text) if text else 0
        total_words += w
        shots = ", ".join(f"{s.kind}:{s.ref}({s.effect})" for s in sc.shots)
        est = (w / 2.78) if w else 0  # ~1.08 x 2.5 wps, matching the example
        print(f"    {sc.n:2d}. {sc.title or '(untitled)':38s} {est:5.1f}s  {shots}")
    est_total = total_words / 2.78 if total_words else 0
    print(f"  narration words: {total_words}  |  est. runtime ~{est_total/60:.2f} min")
    if est_total and not (spec.project.min_seconds <= est_total <= spec.project.max_seconds):
        print("  WARNING: estimated runtime outside the project window")
    print(f"  banned phrases: {len(spec.guard.banned)}")
    for b in spec.guard.banned:
        print(f"    - {b}")
    print(f"  required phrases: {len(spec.guard.required)}")
    for r in spec.guard.required:
        print(f"    - {r}")
    return 0


def _init(target: Path, *, title: str | None, slug: str | None,
          timeframe: Timeframe | None) -> int:
    """Scaffold a runnable story directory; never overwrite what is already there."""
    written = scaffold_story(target, title=title, slug=slug, timeframe=timeframe)
    print(f"scaffolded {target}")
    for path in written:
        print(f"  + {path.relative_to(target)}")
    print("\nnext:")
    print(f"  vidkit plan  {target / 'video.yaml'}")
    print(f"  vidkit build {target / 'video.yaml'}")
    return 0


def _assets_to_json(assets: Assets) -> dict:
    return {
        "output": str(assets.output) if assets.output else None,
        "srt": str(assets.srt) if assets.srt else None,
        "clips": sorted(str(p) for p in assets.stills.values() if str(p).endswith(".mp4")),
        "report": assets.report.to_dict() if assets.report else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vidkit", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"vidkit {__version__}")
    sub = parser.add_subparsers(dest="cmd")

    p_doc = sub.add_parser("doctor", help="check environment + spec")
    p_doc.add_argument("spec", nargs="?")
    _add_timeframe_args(p_doc)

    p_plan = sub.add_parser("plan", help="show the scene plan")
    p_plan.add_argument("spec")
    _add_timeframe_args(p_plan)

    for name, help_ in (("build", "run the full pipeline"),
                        ("tts", "synthesize narration only"),
                        ("capture", "capture screen recordings only"),
                        ("verify", "re-run acceptance checks")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("spec")
        p.add_argument("--out", default=None, help="output directory (default: spec folder)")
        _add_timeframe_args(p)
        if name == "build":
            p.add_argument("--only", default=None,
                           help="comma-separated stages: "
                                "data,panels,stills,capture,narration,clips,concat,render,verify")
            p.add_argument("--from", dest="from_stage", default=None, metavar="STAGE",
                           help="run this stage and everything after it")
            p.add_argument("--refresh", action="store_true",
                           help="fetch provider data again instead of reusing a "
                                "snapshot (adds the data stage back into --only/--from)")

    p_init = sub.add_parser("init", help="scaffold a new story directory")
    p_init.add_argument("dir", help="directory to create the story in")
    p_init.add_argument("--title", default=None, help="project title (default: from the dir name)")
    p_init.add_argument("--slug", default=None, help="project slug (default: from the dir name)")
    _add_timeframe_args(p_init)

    p_docs = sub.add_parser("docs", help="print the docs router or a named document")
    p_docs.add_argument("name", nargs="?", help="doc name (bare stem or module/name)")
    p_docs.add_argument("--index", action="store_true",
                        help="print the machine-readable module route table (JSON)")

    args = parser.parse_args(argv)

    try:
        if args.cmd == "doctor":
            tf = _override(args) if args.spec else None
            return _doctor(Path(args.spec).resolve() if args.spec else None, tf)
        if args.cmd == "plan":
            return _plan(Path(args.spec).resolve(), _override(args))
        if args.cmd == "init":
            return _init(Path(args.dir).resolve(), title=args.title, slug=args.slug,
                         timeframe=_override(args))
        if args.cmd == "docs":
            from .mcp_server import tool_docs, tool_docs_index
            if args.index:
                print(json.dumps(tool_docs_index(), indent=1))
            else:
                print(tool_docs(args.name))
            return 0
        if args.cmd == "build":
            only = [s.strip() for s in args.only.split(",")] if args.only else None
            if args.only and args.from_stage:
                raise VidkitError("--only and --from select stages two different ways; "
                                  "use one of them")
            assets = run(Path(args.spec).resolve(), only=only,
                         from_stage=args.from_stage,
                         out_dir=Path(args.out) if args.out else None,
                         timeframe=_override(args), refresh=args.refresh)
            print(json.dumps(_assets_to_json(assets), indent=1))
            return 0 if (assets.report is None or assets.report.ok) else 2
        if args.cmd == "tts":
            assets = run(Path(args.spec).resolve(), only=["narration"],
                         out_dir=Path(args.out) if args.out else None,
                         timeframe=_override(args))
            return 0
        if args.cmd == "capture":
            assets = run(Path(args.spec).resolve(), only=["capture"],
                         out_dir=Path(args.out) if args.out else None,
                         timeframe=_override(args))
            return 0
        if args.cmd == "verify":
            ctx = make_context(Path(args.spec).resolve(),
                               Path(args.out) if args.out else None,
                               timeframe=_override(args))
            assets = Assets()
            assets.output = ctx.out_dir / ctx.spec.project.output
            wav = ctx.build / "narration.wav"
            assets.audio_track = wav if wav.exists() else None
            assets.srt = ctx.out_dir / "narration.srt"
            from .assembler import _scripts_for
            from .verify import verify_output
            scripts = _scripts_for(ctx.spec, ctx)
            assets.report = verify_output(ctx, assets, {s.n: s.spoken for s in scripts})
            assets.report.print()
            return 0 if assets.report.ok else 2
    except VidkitError as exc:
        print(f"vidkit: error: {exc}", file=sys.stderr)
        return 1

    parser.print_help()
    return 0
