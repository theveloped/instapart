"""CLI entry point: python -m benchmarks <command> [args]."""

import argparse
import sys

from . import manifest as manifest_mod
from . import golden as golden_mod


def cmd_bootstrap(args):
    data = manifest_mod.bootstrap()
    manifest_mod.save(data)
    print("Wrote %s with %d entries." % (manifest_mod.MANIFEST_PATH, len(data["files"])))
    smoke = [e["path"] for e in data["files"] if e["smoke"]]
    print("Smoke set (%d):" % len(smoke))
    for path in smoke:
        print("  " + path)
    return 0


def cmd_extract_goldens(args):
    manifest = manifest_mod.load()
    data = golden_mod.extract_golden_metrics(manifest)
    golden_mod.save_golden_metrics(data)
    print("Extracted metrics for %d golden DXF files -> %s"
          % (len(data), golden_mod.GOLDEN_METRICS_PATH))
    return 0


def cmd_validate(args):
    manifest = manifest_mod.load()
    unlisted = manifest_mod.validate(manifest)
    print("Manifest OK: %d entries." % len(manifest["files"]))
    if unlisted:
        print("WARNING: %d STEP files on disk are not in the manifest:" % len(unlisted))
        for path in unlisted:
            print("  " + path)
    conflicts = manifest_mod.check_thickness_consistency(manifest)
    for path, truth, frozen in conflicts:
        print("THICKNESS CONFLICT: %s filename says %.2f, frozen %.2f" % (path, truth, frozen))
    return 1 if conflicts else 0


def cmd_freeze(args):
    from .runner import find_run  # deferred: runner needs the ported pipeline
    manifest = manifest_mod.load()
    run_dir = find_run(args.run)
    results = manifest_mod.load_results(run_dir / "results.jsonl")
    updated = manifest_mod.freeze(manifest, results)
    manifest_mod.save(manifest)
    print("Froze expectations for %d entries from %s." % (updated, run_dir))
    print("Review the manifest diff (git diff benchmarks/manifest.yaml) before committing.")
    conflicts = manifest_mod.check_thickness_consistency(manifest)
    for path, truth, frozen in conflicts:
        print("THICKNESS CONFLICT: %s filename says %.2f, frozen %.2f" % (path, truth, frozen))
    return 0


def _not_yet(name):
    def cmd(args):
        print("'%s' requires the runner (built alongside the ported pipeline)." % name)
        return 2
    return cmd


def main(argv=None):
    parser = argparse.ArgumentParser(prog="benchmarks")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("bootstrap", help="scan examples/ and write a skeleton manifest")
    sub.add_parser("extract-goldens", help="extract metrics from golden DXF files")
    sub.add_parser("validate", help="check manifest against disk")

    p_freeze = sub.add_parser("freeze", help="fill manifest expectations from a run")
    p_freeze.add_argument("run", help="run directory name or 'latest'")

    for name, help_text in (
        ("run", "run the full corpus"),
        ("smoke", "run the smoke subset"),
        ("compare", "diff a run against the blessed baseline"),
        ("report", "regenerate report.md for a run"),
        ("recheck", "re-run invariants on a run's stored artifacts"),
        ("bless", "mark a run as the new baseline"),
        ("gallery", "render all flat patterns of a run to gallery.html"),
    ):
        sub.add_parser(name, help=help_text)

    args, extras = parser.parse_known_args(argv)
    # runner-backed subcommands parse their own options from the leftovers
    args.args = extras

    handlers = {
        "bootstrap": cmd_bootstrap,
        "extract-goldens": cmd_extract_goldens,
        "validate": cmd_validate,
        "freeze": cmd_freeze,
    }
    if args.command == "gallery":
        from .gallery import cmd_gallery
        handlers["gallery"] = cmd_gallery
    handler = handlers.get(args.command)
    if handler is None:
        # runner-backed commands are wired up in runner.py once it exists
        try:
            from . import runner
            handler = getattr(runner, "cmd_" + args.command.replace("-", "_"))
        except (ImportError, AttributeError):
            handler = _not_yet(args.command)
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
