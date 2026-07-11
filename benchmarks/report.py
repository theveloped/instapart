"""Human-readable report.md generation for a run."""

from collections import defaultdict


def write_report(run_dir, run_meta, results):
    lines = []
    counts = run_meta.get("counts", {})

    lines.append("# Benchmark run %s" % run_dir.name)
    lines.append("")
    lines.append("- git: `%s`%s | python %s | pythonocc %s | jobs %s"
                 % (run_meta.get("sha"), " (dirty)" if run_meta.get("dirty") else "",
                    run_meta.get("python"), run_meta.get("pythonocc"), run_meta.get("jobs")))
    lines.append("- files: %d | total pipeline wall: %.1fs"
                 % (run_meta.get("n_files", 0), run_meta.get("total_wall", 0.0)))
    lines.append("")

    lines.append("## Summary by category")
    lines.append("")
    lines.append("| category | files | pass | warn | known fail | fail | crash | timeout | median wall (s) |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    by_category = defaultdict(list)
    for record in results:
        by_category[record.get("category") or "?"].append(record)
    for category in sorted(by_category):
        records = by_category[category]
        stat = defaultdict(int)
        walls = []
        for r in records:
            stat[r["status"]] += 1
            wall = (r.get("timings") or {}).get("wall_total")
            if wall:
                walls.append(wall)
        median = sorted(walls)[len(walls) // 2] if walls else 0.0
        lines.append("| %s | %d | %d | %d | %d | %d | %d | %d | %.2f |" % (
            category, len(records), stat["pass"], stat["warn"], stat["known_failure"],
            stat["fail"], stat["crash"], stat["timeout"], median))
    lines.append("")

    bad = [r for r in results if r["status"] in ("fail", "crash", "timeout")]
    if bad:
        lines.append("## Failures (%d)" % len(bad))
        lines.append("")
        for record in bad:
            lines.append("### %s — %s" % (record["path"], record["status"]))
            if record.get("crash_stage"):
                lines.append("- crashed in stage: `%s` (%s)"
                             % (record["crash_stage"], record.get("crash_kind", "")))
            if record.get("message_codes"):
                lines.append("- message codes: %s" % record["message_codes"])
            for check in record.get("checks") or []:
                if check["status"] == "fail":
                    lines.append("- check `%s` failed: %s %s"
                                 % (check["name"], check.get("measured") or "", check.get("detail") or ""))
            if record.get("error"):
                lines.append("- error tail: `%s`" % record["error"].strip().splitlines()[-1][:200])
            if record.get("log"):
                lines.append("- log: %s" % record["log"])
            lines.append("")

    warns = [r for r in results if r["status"] == "warn"]
    if warns:
        lines.append("## Warnings (%d)" % len(warns))
        lines.append("")
        for record in warns:
            failing = [c for c in record.get("checks") or [] if c["status"] == "warn"]
            lines.append("- %s: %s" % (record["path"],
                                       "; ".join(c["name"] for c in failing) or "warn"))
        lines.append("")

    timed = sorted(results, key=lambda r: -(r.get("timings") or {}).get("wall_total", 0.0))[:10]
    lines.append("## Slowest files")
    lines.append("")
    lines.append("| file | wall (s) | import | topology | classify | unfold | export |")
    lines.append("|---|---|---|---|---|---|---|")
    for record in timed:
        t = record.get("timings") or {}
        lines.append("| %s | %.2f | %.2f | %.2f | %.2f | %.2f | %.2f |" % (
            record["path"], t.get("wall_total", 0.0), t.get("import", 0.0),
            t.get("topology", 0.0), t.get("classify", 0.0),
            t.get("unfold", 0.0), t.get("export", 0.0)))
    lines.append("")

    with open(run_dir / "report.md", "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))
