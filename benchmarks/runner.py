"""Run scheduling: one subprocess per input file, timeouts, crash attribution."""

import argparse
import concurrent.futures
import datetime
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import HARNESS_VERSION
from . import golden as golden_mod
from . import invariants
from . import manifest as manifest_mod
from .manifest import REPO_ROOT

RUNS_DIR = Path(__file__).resolve().parent / "runs"
BASELINE_PATH = Path(__file__).resolve().parent / "baseline.json"
# Committed snapshot of the blessed run's results, so `compare` works on a
# fresh clone where the (gitignored) run directory does not exist.
BASELINE_DIR = Path(__file__).resolve().parent / "baseline"
HISTORY_PATH = Path(__file__).resolve().parent / "history.csv"

CRASH_CODES = {
    -1073741819: "access violation (0xC0000005)",
    -1073740791: "stack buffer overrun (0xC0000409)",
    -1073741571: "stack overflow (0xC00000FD)",
}


def _git(*args):
    try:
        out = subprocess.run(["git", "-C", str(REPO_ROOT)] + list(args),
                             capture_output=True, text=True, timeout=15)
        return out.stdout.strip()
    except Exception:
        return ""


def _slug(rel_path):
    return rel_path.replace("/", "__").replace("\\", "__").rsplit(".", 1)[0]


def run_one(entry, run_dir, jobs_env, timeout_scale=1.0, k_factor=0.5, features=False):
    """Run the worker for one manifest entry; returns the result record."""
    rel = entry["path"]
    slug = _slug(rel)
    artifacts = run_dir / "artifacts" / slug
    artifacts.mkdir(parents=True, exist_ok=True)
    result_path = artifacts / "result.json"
    progress_path = artifacts / "progress.json"
    log_path = run_dir / "logs" / (slug + ".log")
    log_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [sys.executable, "-W", "ignore", "-m", "benchmarks.worker",
           "--input", str(REPO_ROOT / rel),
           "--outdir", str(artifacts),
           "--result", str(result_path),
           "--progress", str(progress_path),
           "--k-factor", str(k_factor)]
    if features:
        cmd.append("--features")

    timeout = entry.get("timeout_s", 120) * timeout_scale
    record = {"path": rel, "category": entry.get("category"),
              "status": "fail", "exit_code": None, "crash_stage": None,
              "timings": {}, "log": str(log_path.relative_to(run_dir))}

    try:
        with open(log_path, "w", encoding="utf-8") as log_file:
            proc = subprocess.run(cmd, stdout=log_file, stderr=subprocess.STDOUT,
                                  cwd=str(REPO_ROOT), env=jobs_env, timeout=timeout)
        record["exit_code"] = proc.returncode
    except subprocess.TimeoutExpired:
        record["status"] = "timeout"
        record["crash_stage"] = _read_progress(progress_path)
        return record, None

    if proc.returncode != 0:
        record["status"] = "crash"
        record["crash_stage"] = _read_progress(progress_path)
        record["crash_kind"] = CRASH_CODES.get(proc.returncode, "exit %s" % proc.returncode)
        return record, None

    try:
        with open(result_path, "r", encoding="utf-8") as fh:
            worker_result = json.load(fh)
    except Exception as exc:
        record["status"] = "fail"
        record["error"] = "no result.json: %s" % exc
        return record, None

    record["timings"] = worker_result.get("timings") or {}
    for key in ("parts_found", "sheets", "tubes", "failed_shapes", "shape_ids", "message_codes", "metrics"):
        if key in worker_result:
            record[key] = worker_result[key]
    if worker_result.get("error"):
        record["error"] = worker_result["error"][-800:]
    return record, worker_result


def _read_progress(progress_path):
    try:
        with open(progress_path, "r", encoding="utf-8") as fh:
            return json.load(fh).get("stage")
    except Exception:
        return None


def execute(entries, jobs=1, timeout_scale=1.0, keep_artifacts=False, label=""):
    """Run all entries, apply invariants, write the run directory."""
    sha = _git("rev-parse", "--short", "HEAD") or "nosha"
    dirty = "-dirty" if _git("status", "--porcelain") else ""
    stamp = datetime.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    run_dir = RUNS_DIR / ("%s_%s%s%s" % (stamp, sha, dirty, label))
    run_dir.mkdir(parents=True, exist_ok=True)

    try:
        golden_metrics = golden_mod.load_golden_metrics()
    except FileNotFoundError:
        golden_metrics = {}

    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    # The pipeline has hash-order-dependent behavior (unfold side selection,
    # occasionally classification); random per-process str hashing makes runs
    # flip results on a handful of corpus files. Pin the seed so runs are
    # reproducible on a given platform.
    env["PYTHONHASHSEED"] = "0"

    results = []

    def process(entry):
        record, worker_result = run_one(entry, run_dir, env, timeout_scale=timeout_scale)
        if worker_result is not None:
            checks, extra = invariants.run_checks(entry, worker_result, golden_metrics)
            record["checks"] = [c._asdict() for c in checks]
            record.setdefault("metrics", {}).update(extra)
            record["status"] = invariants.overall_status(worker_result, checks)
        expected = entry.get("expected")
        if expected == "known_failure" and record["status"] in ("fail", "crash", "timeout"):
            record["status"] = "known_failure"
        return record

    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {pool.submit(process, e): e for e in entries}
        done = 0
        for future in concurrent.futures.as_completed(futures):
            entry = futures[future]
            try:
                record = future.result()
            except Exception as exc:
                record = {"path": entry["path"], "category": entry.get("category"),
                          "status": "fail", "error": "harness error: %s" % exc}
            results.append(record)
            done += 1
            print("[%3d/%3d] %-12s %s" % (done, len(futures), record["status"], record["path"]),
                  flush=True)

    results.sort(key=lambda r: r["path"].lower())
    with open(run_dir / "results.jsonl", "w", encoding="utf-8") as fh:
        for record in results:
            fh.write(json.dumps(record) + "\n")

    import OCC
    run_meta = {
        "sha": sha, "dirty": bool(dirty), "timestamp": stamp,
        "python": sys.version.split()[0], "pythonocc": OCC.VERSION,
        "harness": HARNESS_VERSION, "jobs": jobs, "n_files": len(results),
        "counts": _status_counts(results),
        "total_wall": sum((r.get("timings") or {}).get("wall_total", 0.0) for r in results),
    }
    with open(run_dir / "run.json", "w", encoding="utf-8") as fh:
        json.dump(run_meta, fh, indent=2)

    if not keep_artifacts:
        for record in results:
            if record["status"] == "pass":
                shutil.rmtree(run_dir / "artifacts" / _slug(record["path"]), ignore_errors=True)

    from . import report as report_mod
    report_mod.write_report(run_dir, run_meta, results)
    _append_history(run_meta)

    print("\nRun: %s" % run_dir.name)
    for status, count in sorted(run_meta["counts"].items()):
        print("  %-14s %d" % (status, count))
    print("Report: %s" % (run_dir / "report.md"))
    return run_dir, run_meta, results


def _status_counts(results):
    counts = {}
    for record in results:
        counts[record["status"]] = counts.get(record["status"], 0) + 1
    return counts


def _append_history(run_meta):
    new = not HISTORY_PATH.exists()
    with open(HISTORY_PATH, "a", encoding="utf-8", newline="\n") as fh:
        if new:
            fh.write("timestamp,sha,dirty,n_files,pass,warn,fail,crash,timeout,known_failure,total_wall_s,jobs\n")
        counts = run_meta["counts"]
        fh.write("%s,%s,%s,%d,%d,%d,%d,%d,%d,%d,%.1f,%d\n" % (
            run_meta["timestamp"], run_meta["sha"], run_meta["dirty"], run_meta["n_files"],
            counts.get("pass", 0), counts.get("warn", 0), counts.get("fail", 0),
            counts.get("crash", 0), counts.get("timeout", 0), counts.get("known_failure", 0),
            run_meta["total_wall"], run_meta["jobs"]))


def find_run(name):
    if name in (None, "latest"):
        runs = sorted(RUNS_DIR.iterdir()) if RUNS_DIR.exists() else []
        runs = [r for r in runs if (r / "results.jsonl").exists()]
        if not runs:
            raise FileNotFoundError("no runs found in %s" % RUNS_DIR)
        return runs[-1]
    path = RUNS_DIR / name
    if not (path / "results.jsonl").exists():
        raise FileNotFoundError("run %s has no results.jsonl" % name)
    return path


# ---------------------------------------------------------------------------
# CLI command handlers (dispatched from benchmarks.__main__)
# ---------------------------------------------------------------------------

def _run_args(argv):
    parser = argparse.ArgumentParser(prog="benchmarks run")
    parser.add_argument("--category", action="append", default=None)
    parser.add_argument("--path", default=None, help="substring filter")
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--timeout-scale", type=float, default=1.0)
    parser.add_argument("--keep-artifacts", action="store_true")
    parser.add_argument("--label", default="")
    return parser.parse_args(argv)


def _select(manifest, opts, smoke_only=False):
    entries = manifest["files"]
    if smoke_only:
        entries = [e for e in entries if e.get("smoke")]
    if opts.category:
        entries = [e for e in entries if e.get("category") in opts.category]
    if opts.path:
        entries = [e for e in entries if opts.path.lower() in e["path"].lower()]
    if opts.limit:
        entries = entries[:opts.limit]
    return entries


def cmd_run(args):
    opts = _run_args(args.args)
    manifest = manifest_mod.load()
    entries = _select(manifest, opts)
    print("Running %d files with %d parallel workers" % (len(entries), opts.jobs))
    _, meta, results = execute(entries, jobs=opts.jobs, timeout_scale=opts.timeout_scale,
                               keep_artifacts=opts.keep_artifacts,
                               label=("_" + opts.label) if opts.label else "")
    bad = meta["counts"].get("fail", 0) + meta["counts"].get("crash", 0) + meta["counts"].get("timeout", 0)
    return 1 if bad else 0


def cmd_smoke(args):
    opts = _run_args(args.args)
    manifest = manifest_mod.load()
    entries = _select(manifest, opts, smoke_only=True)
    print("Smoke: %d files" % len(entries))
    _, meta, results = execute(entries, jobs=opts.jobs, timeout_scale=opts.timeout_scale,
                               keep_artifacts=opts.keep_artifacts, label="_smoke")
    bad = meta["counts"].get("fail", 0) + meta["counts"].get("crash", 0) + meta["counts"].get("timeout", 0)
    return 1 if bad else 0


def cmd_bless(args):
    run_dir = find_run(args.args[0] if args.args else "latest")
    with open(BASELINE_PATH, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"run": run_dir.name}, fh, indent=2)
    BASELINE_DIR.mkdir(exist_ok=True)
    shutil.copy2(run_dir / "results.jsonl", BASELINE_DIR / "results.jsonl")
    if (run_dir / "run.json").exists():
        shutil.copy2(run_dir / "run.json", BASELINE_DIR / "run.json")
    print("Blessed baseline: %s" % run_dir.name)
    print("Snapshot copied to %s (commit it so `compare` works on fresh clones)" % BASELINE_DIR)
    return 0


def cmd_compare(args):
    from . import compare as compare_mod
    return compare_mod.main(args.args)


def cmd_report(args):
    from . import report as report_mod
    run_dir = find_run(args.args[0] if args.args else "latest")
    with open(run_dir / "run.json", "r", encoding="utf-8") as fh:
        run_meta = json.load(fh)
    results = manifest_mod.load_results(run_dir / "results.jsonl")
    report_mod.write_report(run_dir, run_meta, results)
    print("Wrote %s" % (run_dir / "report.md"))
    return 0


def cmd_recheck(args):
    """Re-run invariants on a stored run's artifacts (only non-deleted ones)."""
    run_dir = find_run(args.args[0] if args.args else "latest")
    manifest = manifest_mod.load()
    by_path = {e["path"]: e for e in manifest["files"]}
    try:
        golden_metrics = golden_mod.load_golden_metrics()
    except FileNotFoundError:
        golden_metrics = {}
    results = manifest_mod.load_results(run_dir / "results.jsonl")
    updated = 0
    for record in results:
        entry = by_path.get(record["path"])
        result_path = run_dir / "artifacts" / _slug(record["path"]) / "result.json"
        if not entry or not result_path.exists():
            continue
        with open(result_path, "r", encoding="utf-8") as fh:
            worker_result = json.load(fh)
        checks, extra = invariants.run_checks(entry, worker_result, golden_metrics)
        record["checks"] = [c._asdict() for c in checks]
        record.setdefault("metrics", {}).update(extra)
        record["status"] = invariants.overall_status(worker_result, checks)
        updated += 1
    with open(run_dir / "results.jsonl", "w", encoding="utf-8") as fh:
        for record in results:
            fh.write(json.dumps(record) + "\n")
    print("Rechecked %d results in %s" % (updated, run_dir.name))
    return 0
