"""Single-file pipeline worker.

Runs the production pipeline (auto.main) on exactly one STEP file, writes a
machine-readable result.json and exits 0 even on pipeline errors — errors are
data. Only interpreter/native crashes produce a nonzero exit, in which case
progress.json tells the parent which stage died.

Invoked as:
    python -m benchmarks.worker --input <step> --outdir <dir> --result <json>
"""

import argparse
import json
import os
import sys
import time
import traceback

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def collect_outputs(outdir, input_name):
    json_path = os.path.join(outdir, input_name + ".json")
    dxfs = sorted(
        os.path.join(outdir, f) for f in os.listdir(outdir) if f.lower().endswith(".dxf")
    )
    stps = sorted(
        os.path.join(outdir, f) for f in os.listdir(outdir) if f.lower().endswith(".stp")
    )
    return (json_path if os.path.isfile(json_path) else None), dxfs, stps


def summarize_job(job):
    """Counts and metrics pulled from the output JSON."""
    from benchmarks import metrics

    parts = sheets = tubes = failed = 0
    thicknesses = []
    bend_count = 0
    bend_angles = []

    def walk(node):
        nonlocal parts, sheets, tubes, failed, bend_count
        if not isinstance(node, dict):
            return
        shapes = node.get("shapes") or []
        if shapes:
            parts += 1
        for shape in shapes:
            kind = shape.get("type")
            if kind == "SHEET":
                sheets += 1
                pattern = shape.get("pattern") or {}
                if pattern.get("thickness") is not None:
                    thicknesses.append(pattern["thickness"])
                for bend in shape.get("bends") or []:
                    bend_count += 1
                    if bend.get("angle") is not None:
                        bend_angles.append(round(180.0 / 3.141592653589793 * bend["angle"], 2))
            elif kind == "TUBE":
                tubes += 1
            else:
                failed += 1
        for comp in node.get("components") or []:
            walk(comp)

    walk(job.get("tree") or {})
    return {
        "parts_found": parts,
        "sheets": sheets,
        "tubes": tubes,
        "failed_shapes": failed,
        "message_codes": sorted(metrics.message_codes(job)),
        "metrics": {
            "thickness": thicknesses[0] if thicknesses else None,
            "bend_count": bend_count,
            "bend_angles": sorted(bend_angles),
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--progress", default=None)
    parser.add_argument("--k-factor", type=float, default=0.5)
    parser.add_argument("--features", action="store_true")
    args = parser.parse_args(argv)

    os.makedirs(args.outdir, exist_ok=True)
    progress_path = args.progress or os.path.join(args.outdir, "progress.json")

    result = {
        "input": args.input,
        "status": "fail",
        "error": None,
        "timings": {},
        "outputs": {},
    }

    wall_start = time.perf_counter()

    import logging
    logging.disable(logging.CRITICAL)  # OCC/pipeline noise goes to the log file

    from utils import StageTimer
    import auto

    timings = StageTimer(progress_path=progress_path)

    input_name = os.path.basename(args.input).rsplit(".", 1)[0]
    try:
        auto.main(
            args.input,
            args.outdir,
            repair=True,
            align=True,
            k_factor=args.k_factor,
            check_features=args.features,
            export_names={},
            timings=timings,
        )
        result["status"] = "ok"
    except Exception:
        result["error"] = traceback.format_exc()

    result["timings"] = dict(timings.times)
    result["timings"]["wall_total"] = time.perf_counter() - wall_start

    json_path, dxfs, stps = collect_outputs(args.outdir, input_name)
    result["outputs"] = {"json": json_path, "dxf": dxfs, "stp": stps}

    if json_path:
        try:
            with open(json_path, "r", encoding="utf-8") as fh:
                job = json.load(fh)
            result.update(summarize_job(job))
        except Exception:
            result["error"] = (result["error"] or "") + "\n" + traceback.format_exc()
            result["status"] = "fail"

    with open(args.result, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1)

    return 0


if __name__ == "__main__":
    sys.exit(main())
