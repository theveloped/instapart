"""Run-vs-run regression detection. Exit 1 on regression (CI-gateable)."""

import argparse
import json

from . import manifest as manifest_mod
from .runner import BASELINE_DIR, BASELINE_PATH, find_run

STATUS_ORDER = {"pass": 0, "warn": 1, "known_failure": 2, "fail": 3, "crash": 4, "timeout": 4}


def load_run(run_dir):
    results = manifest_mod.load_results(run_dir / "results.jsonl")
    return {r["path"]: r for r in results}


def main(argv):
    parser = argparse.ArgumentParser(prog="benchmarks compare")
    parser.add_argument("runs", nargs="*", help="[baseline] current (default: baseline.json vs latest)")
    parser.add_argument("--strict-timing", action="store_true")
    args = parser.parse_args(argv)

    if len(args.runs) >= 2:
        try:
            base_dir, cur_dir = find_run(args.runs[0]), find_run(args.runs[1])
        except FileNotFoundError as exc:
            print(exc)
            return 2
    else:
        try:
            with open(BASELINE_PATH, "r", encoding="utf-8") as fh:
                base_name = json.load(fh)["run"]
        except FileNotFoundError:
            print("No blessed baseline (run `python -m benchmarks bless <run>` first).")
            return 2
        try:
            base_dir = find_run(base_name)
        except FileNotFoundError:
            if (BASELINE_DIR / "results.jsonl").exists():
                print("Baseline run %s not present locally; using committed snapshot." % base_name)
                base_dir = BASELINE_DIR
            else:
                print("Baseline run %s is not present locally (benchmarks/runs/ is not committed)\n"
                      "and no committed snapshot exists under %s.\n"
                      "On a machine with the corpus results, run `python -m benchmarks bless <run>`\n"
                      "to write and commit the snapshot." % (base_name, BASELINE_DIR))
                return 2
        try:
            cur_dir = find_run(args.runs[0] if args.runs else "latest")
        except FileNotFoundError as exc:
            print(exc)
            return 2

    base, cur = load_run(base_dir), load_run(cur_dir)
    print("Comparing %s (baseline) -> %s" % (base_dir.name, cur_dir.name))

    regressions, improvements, timing_warnings = [], [], []

    for path, cur_record in sorted(cur.items()):
        base_record = base.get(path)
        if base_record is None:
            continue
        base_status, cur_status = base_record["status"], cur_record["status"]

        if STATUS_ORDER.get(cur_status, 9) > STATUS_ORDER.get(base_status, 9):
            regressions.append("%s: %s -> %s" % (path, base_status, cur_status))
        elif STATUS_ORDER.get(cur_status, 9) < STATUS_ORDER.get(base_status, 9):
            improvements.append("%s: %s -> %s" % (path, base_status, cur_status))

        base_codes = set(base_record.get("message_codes") or [])
        cur_codes = set(cur_record.get("message_codes") or [])
        if cur_codes - base_codes:
            regressions.append("%s: new message codes %s" % (path, sorted(cur_codes - base_codes)))

        # metric drift is a regression even while still passing
        bm = base_record.get("metrics") or {}
        cm = cur_record.get("metrics") or {}
        b_err, c_err = bm.get("volume_rel_error"), cm.get("volume_rel_error")
        if b_err is not None and c_err is not None and c_err - b_err > 0.005:
            regressions.append("%s: volume error %.4f -> %.4f" % (path, b_err, c_err))
        if bm.get("bend_count") is not None and cm.get("bend_count") is not None:
            if bm["bend_count"] != cm["bend_count"]:
                regressions.append("%s: bend count %s -> %s"
                                   % (path, bm["bend_count"], cm["bend_count"]))

        bt = (base_record.get("timings") or {}).get("wall_total")
        ct = (cur_record.get("timings") or {}).get("wall_total")
        if bt and ct and ct > bt * 1.2 and ct - bt > 0.5:
            timing_warnings.append("%s: %.2fs -> %.2fs (+%.0f%%)" % (path, bt, ct, (ct / bt - 1) * 100))

    print("\nRegressions (%d):" % len(regressions))
    for line in regressions:
        print("  " + line)
    print("\nImprovements (%d):" % len(improvements))
    for line in improvements:
        print("  " + line)
    if improvements:
        print("  (consider re-freezing the manifest and blessing a new baseline)")
    print("\nTiming warnings (%d):" % len(timing_warnings))
    for line in timing_warnings:
        print("  " + line)

    if regressions:
        return 1
    if timing_warnings and args.strict_timing:
        return 1
    return 0
