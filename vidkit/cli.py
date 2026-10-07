"""Command-line interface.

    vidkit doctor [SPEC]     check the environment and every dependency
    vidkit plan   SPEC       show the scene plan and estimated runtime
    vidkit build  SPEC [--only a,b] [--out DIR]
    vidkit tts    SPEC       (re)synthesize narration only
    vidkit capture SPEC      (re)capture screen recordings only
    vidkit verify SPEC       re-run the acceptance checks on the last render
    vidkit provenance SPEC   show what made the last build, and when
    vidkit init   DIR        scaffold a runnable story (spec + narration + provider)
    vidkit run    ACTION     run a job and print its artifact manifest
    vidkit docs   [NAME]     print the docs router, or a named document
    vidkit auth   URL        sign in once by hand; captures reuse the session

``--timeframe``/``--days``/``--as-of`` override the window declared by the spec or its
``story.yaml``, for every command that loads a spec. ``--days`` is a shorthand for
``--timeframe "Nd"`` ending at ``--as-of`` (today, if omitted).

``--json`` turns any command into a machine-readable call: one JSON manifest on stdout,
the same document ``vidkit run`` returns. ``--progress`` streams the run's own log to
stderr, so stdout stays parseable.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .assembler import Assets, make_context, run
from .errors import VidkitError
from .job import ACTION_HELP, ACTIONS, run_job
from .timeframe import Timeframe, parse_timeframe


_JSON_HELP = ("print one JSON manifest on stdout instead of prose (the same document "
              "`vidkit run` returns)")
_PROGRESS_HELP = "let the run's own log through to stderr as it happens (needs --json)"


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
    p.add_argument("--timeframe", default=None, metavar="WINDOW",
                   help='override the window: "28d", "6m", "2026-09-08..2026-10-06", '
                        '"{days: 28, as_of: 2026-10-06}"')
    p.add_argument("--days", type=int, default=None, metavar="N",
                   help='shorthand for --timeframe "Nd"')
    p.add_argument("--as-of", default=None, metavar="DATE",
                   help="the day a relative window ends (default: today)")


def _doctor(spec_path: Path | None, timeframe: Timeframe | None = None) -> int:
    from .reports import doctor_report, format_doctor

    report = doctor_report(spec_path, timeframe=timeframe)
    print(format_doctor(report))
    return 0 if report["ok"] else 1


def _plan(spec_path: Path, timeframe: Timeframe | None = None) -> int:
    from .reports import format_plan, plan_report

    print(format_plan(plan_report(spec_path, timeframe=timeframe)))
    return 0


def _provenance(spec_path: Path, out: Path | None,
                timeframe: Timeframe | None = None) -> int:
    """The ``provenance`` verb: read the last build's record, print it, never write one.

    It goes through the same job the other verbs use, so the text here and the
    ``--json`` manifest cannot disagree about which build this is.
    """
    from .reports import format_provenance

    manifest = run_job("provenance", story=str(spec_path), out=str(out) if out else None,
                       timeframe=timeframe)
    record = manifest.get("provenance")
    if not manifest.get("ok") or record is None:
        failure = manifest.get("failure") or {}
        print(f"vidkit: error: {failure.get('message') or 'no readable provenance'}"
              + (f"\nhint: {failure['hint']}" if failure.get("hint") else ""),
              file=sys.stderr)
        return 1
    print(format_provenance(record))
    return 0


def _init(target: Path, *, title: str | None, slug: str | None,
          timeframe: Timeframe | None) -> int:
    """Scaffold a runnable story directory; never overwrite what is already there."""
    from .scaffold import scaffold_story

    written = scaffold_story(target, title=title, slug=slug, timeframe=timeframe)
    print(f"scaffolded {target}")
    for path in written:
        print(f"  + {path.relative_to(target)}")
    print("\nnext:")
    print(f"  vidkit plan  {target / 'video.yaml'}")
    print(f"  vidkit build {target / 'video.yaml'}")
    return 0


def default_state_path(spec: Path | None = None) -> Path:
    """Where a recorded session lives when nobody says otherwise."""
    return (spec.parent if spec else Path.cwd()) / ".auth" / "state.json"


def _auth(url: str, *, save: str | None, wait: float, spec: Path | None) -> int:
    """Record a browser session once, so no capture ever films a login form.

    A headed browser is opened *for the human*, not for the video: they sign in
    however the product requires — SSO, MFA, a magic link — and the resulting
    cookies are written to a storage state the captures reuse. vidkit never sees
    the password, and the recording never contains one.
    """
    from .capture import _find_chrome, _playwright_available

    if not _playwright_available():
        raise VidkitError(
            "recording a session needs Playwright — install it with "
            "`pip install playwright && playwright install chromium`")

    dest = Path(save) if save else default_state_path(spec)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest = dest.resolve()

    from playwright.sync_api import sync_playwright

    print(f"opening {url}")
    print("sign in in the window that opens; vidkit writes nothing until you finish.")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, executable_path=_find_chrome(),
                                    args=["--no-sandbox"])
        context = browser.new_context()
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        print(f"waiting up to {wait:g}s for the page to settle at a different URL, "
              "or for you to close the window …")
        try:
            page.wait_for_timeout(int(wait * 1000))
        except Exception:  # noqa: BLE001 - a closed window ends the wait
            pass
        context.storage_state(path=str(dest))
        browser.close()

    if not dest.exists():
        raise VidkitError(f"no session was written to {dest}")
    _warn_if_secret(dest)
    print(f"wrote {dest}")
    print(f"  capture it without filming a login:  storage_state: {_relative_hint(dest, spec)}")
    return 0


def _warn_if_secret(path: Path) -> None:
    """A storage state is a credential; say so out loud, every single time."""
    print("NOTE: this file holds live session cookies — treat it as a password.")
    print("      Keep it out of git (`vidkit init` already ignores .auth/).")


def _relative_hint(dest: Path, spec: Path | None) -> str:
    base = spec.parent if spec else Path.cwd()
    try:
        return str(dest.relative_to(base))
    except ValueError:
        return str(dest)


def _assets_to_json(assets: Assets) -> dict:
    return {
        "output": str(assets.output) if assets.output else None,
        "srt": str(assets.srt) if assets.srt else None,
        "clips": sorted(str(p) for p in assets.stills.values() if str(p).endswith(".mp4")),
        "report": assets.report.to_dict() if assets.report else None,
    }


# --------------------------------------------------------------------------- #
# --json  (R-G2): every command answers with the same manifest
# --------------------------------------------------------------------------- #
#: Which job answers which command, so ``--json`` and ``vidkit run`` agree by
#: construction rather than by two lists kept in step by hand.
_COMMAND_ACTION = {
    "doctor": "doctor", "plan": "plan", "build": "build", "tts": "tts",
    "capture": "capture", "verify": "verify", "provenance": "provenance",
    "init": "init",
}


def _action_for(args) -> str | None:
    """Which job a command line is. ``run`` names its action; the rest map by name."""
    if args.cmd == "run":
        return args.action
    return _COMMAND_ACTION.get(args.cmd)


def _job_kwargs(args, action: str) -> dict:
    """One command line, one job call — whichever verb was typed.

    Every job takes the same arguments, so this is one dict rather than a branch per
    verb; only ``init`` differs, because it *writes* a story instead of reading one
    and so wants a title and a slug that mean nothing to the others.
    """
    spec, dest = getattr(args, "spec", None), getattr(args, "dir", None)
    only = getattr(args, "only", None)
    kw: dict = {
        "story": getattr(args, "story", None) or spec or dest,
        "out": getattr(args, "out", None),
        "only": [x.strip() for x in only.split(",") if x.strip()] if only else None,
        "from_stage": getattr(args, "from_stage", None),
        "refresh": bool(getattr(args, "refresh", False)),
        "timeframe": _override(args),
    }
    if action == "init":
        kw["title"] = getattr(args, "title", None)
        kw["slug"] = getattr(args, "slug", None)
    return kw


def _run(action: str, args, *, echo: bool = False) -> int:
    """The ``run`` verb: a job manifest, printed, with an exit code to match.

    The manifest is the output, so the run's own log must not land on stdout; when
    the caller wants to watch it happen, it goes to stderr line by line. ``echo``
    is therefore about *where* the log goes, never *whether* it is captured.
    """
    manifest = run_job(action, on_progress=_stderr_progress if echo else None,
                       **_job_kwargs(args, action))
    print(json.dumps(manifest, indent=1))
    return _exit_code(manifest)


def _stderr_progress(line: str) -> None:
    print(line, file=sys.stderr, flush=True)


def _json_main(args) -> int:
    """``--json``: the manifest ``vidkit run`` prints, for any command that is a job.

    ``docs`` prints documentation and ``auth`` opens a browser for a human, so
    neither is a job; they answer in their own shape rather than pretending.
    """
    if args.cmd == "docs":
        from .mcp_server import tool_docs, tool_docs_index
        print(json.dumps(tool_docs_index() if args.index else {"doc": tool_docs(args.name)},
                         indent=1))
        return 0
    action = _action_for(args)
    if action is None:
        print(json.dumps({"ok": False, "failure": {
            "kind": "usage",
            "message": f"{args.cmd or 'vidkit'} is not a job and has no JSON form",
            "hint": f"one of: {', '.join(ACTIONS)}",
        }}, indent=1))
        return 1
    # stdout carries the manifest and nothing else, so a pipe stays parseable;
    # with --progress the log goes to stderr, without it the manifest keeps it
    return _run(action, args, echo=bool(getattr(args, "progress", False)))


def _exit_code(manifest: dict) -> int:
    """0 = done; 1 = refused; 2 = it ran but the result did not verify."""
    if manifest.get("ok"):
        return 0
    return 2 if (manifest.get("failure") or {}).get("kind") == "verification" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vidkit", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"vidkit {__version__}")
    parser.add_argument("--json", action="store_true", help=_JSON_HELP)
    parser.add_argument("--progress", action="store_true", help=_PROGRESS_HELP)
    # The same two flags are also accepted *after* the verb, which is where a user
    # reaching for them will type them. `SUPPRESS` keeps the after-the-verb copy from
    # resetting what the global one already set.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                        help=_JSON_HELP)
    common.add_argument("--progress", action="store_true", default=argparse.SUPPRESS,
                        help=_PROGRESS_HELP)
    sub = parser.add_subparsers(dest="cmd")

    p_run = sub.add_parser(
        "run", parents=[common], help="run a job and print its artifact manifest",
        description="One entry point for every job: it takes a story, a window and an "
                    "output directory, and answers with a manifest — always the same "
                    "shape, so a caller can branch on `ok` instead of on which command "
                    "it happened to invoke.")
    p_run.add_argument("action", choices=list(ACTIONS),
                       help="; ".join(f"{a}: {h}" for a, h in ACTION_HELP.items()))
    p_run.add_argument("--story", default=None,
                       help="the story folder (or its video.yaml)")
    p_run.add_argument("--out", default=None, help="output directory (default: story folder)")
    _add_timeframe_args(p_run)
    p_run.add_argument("--title", default=None, help="init: project title")
    p_run.add_argument("--slug", default=None, help="init: project slug")
    p_run.add_argument("--only", default=None,
                       help="comma-separated stages, for the rendering actions")
    p_run.add_argument("--from", dest="from_stage", default=None, metavar="STAGE",
                       help="run this stage and everything after it")
    p_run.add_argument("--refresh", action="store_true",
                       help="fetch provider data again instead of reusing a snapshot")

    p_doc = sub.add_parser("doctor", parents=[common], help="check environment + spec")
    p_doc.add_argument("spec", nargs="?")
    _add_timeframe_args(p_doc)

    p_plan = sub.add_parser("plan", parents=[common], help="show the scene plan")
    p_plan.add_argument("spec")
    _add_timeframe_args(p_plan)

    for name, help_ in (("build", "run the full pipeline"),
                        ("tts", "synthesize narration only"),
                        ("capture", "capture screen recordings only"),
                        ("verify", "re-run acceptance checks"),
                        ("provenance", "show what made the last build, and when")):
        p = sub.add_parser(name, parents=[common], help=help_)
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

    p_init = sub.add_parser("init", parents=[common], help="scaffold a new story directory")
    p_init.add_argument("dir", help="directory to create the story in")
    p_init.add_argument("--title", default=None, help="project title (default: from the dir name)")
    p_init.add_argument("--slug", default=None, help="project slug (default: from the dir name)")
    _add_timeframe_args(p_init)

    p_auth = sub.add_parser(
        "auth", parents=[common],
        help="record a browser session once, so captures never film a login")
    p_auth.add_argument("url", help="the page to sign in at")
    p_auth.add_argument("--save", default=None, metavar="PATH",
                        help="where to write the storage state "
                             "(default: <spec folder>/.auth/state.json)")
    p_auth.add_argument("--wait", type=float, default=180.0, metavar="SECONDS",
                        help="how long to wait for the sign-in to finish (default: 180)")
    p_auth.add_argument("--spec", default=None,
                        help="a spec, to put the default state file beside it")

    p_docs = sub.add_parser("docs", parents=[common], help="print the docs router or a named document")
    p_docs.add_argument("name", nargs="?", help="doc name (bare stem or module/name)")
    p_docs.add_argument("--index", action="store_true",
                        help="print the machine-readable module route table (JSON)")

    args = parser.parse_args(argv)

    if getattr(args, "json", False):
        return _json_main(args)
    if getattr(args, "progress", False):
        # the flag belongs to --json; without it, say so rather than silently ignore it
        print("vidkit: error: --progress needs --json (otherwise the log already "
              "reaches your terminal)", file=sys.stderr)
        return 1

    try:
        if args.cmd == "run":
            # without --json, stdout *is* the terminal, so a person watching gets
            # the run's log as it happens and the manifest underneath it
            return _run(args.action, args, echo=True)
        if args.cmd == "doctor":
            tf = _override(args) if args.spec else None
            return _doctor(Path(args.spec).resolve() if args.spec else None, tf)
        if args.cmd == "plan":
            return _plan(Path(args.spec).resolve(), _override(args))
        if args.cmd == "init":
            return _init(Path(args.dir).resolve(), title=args.title, slug=args.slug,
                         timeframe=_override(args))
        if args.cmd == "auth":
            return _auth(args.url, save=args.save, wait=args.wait,
                         spec=Path(args.spec).resolve() if args.spec else None)
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
        if args.cmd == "provenance":
            return _provenance(Path(args.spec).resolve(),
                               Path(args.out) if args.out else None,
                               _override(args))
    except VidkitError as exc:
        print(f"vidkit: error: {exc}", file=sys.stderr)
        return 1

    parser.print_help()
    return 0
