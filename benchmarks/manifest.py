"""Corpus manifest: the committed contract describing every example file.

Entry fields:
  path                    repo-relative STEP file path (forward slashes)
  category                sheet_single | assembly | benchmark_1 | benchmark_2 |
                          rolled | tube | 3dhubs | xml
  smoke                   part of the fast pre-commit subset
  expected                pass | known_failure | unknown
  timeout_s               per-file worker timeout
  expected_parts / expected_sheets / expected_tubes
  expected_thickness / expected_bends / expected_bend_angles (sorted degrees)
  expected_message_codes  list of ints (ERRORS.md codes)
  filename_thickness      ground truth parsed from rolled-part filenames
  golden_json / golden_dxf  paths to committed reference outputs

`bootstrap` builds a skeleton from the examples/ tree; `freeze` fills the
expected_* fields from an observed run so a human can review the diff.
"""

import fnmatch
import json
import math
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = Path(__file__).resolve().parent / "manifest.yaml"

STEP_PATTERNS = ("*.stp", "*.step")

CATEGORY_BY_DIR = {
    "parts": "sheet_single",
    "assy": "assembly",
    "rolled": "rolled",
    "tube": "tube",
    "3dhubs": "3dhubs",
    "xml": "xml",
}

DEFAULT_TIMEOUTS = {
    "assembly": 900,
    "xml": 300,
}
DEFAULT_TIMEOUT = 120

# Fast pre-commit subset (see plan): a slice of every category plus the
# known-failure and non-ASCII cases.
SMOKE_PATHS = {
    "examples/parts/SmartPart_01.stp",
    "examples/parts/SmartPart_02.stp",
    "examples/parts/SmartPart_03.stp",
    "examples/rolled/1x_St_2mm_gerold_Ø200x400mm.STEP",  # corrected at bootstrap if name differs
    "examples/tube/SmartPart_01.stp",
    "examples/assy/EMO-72-07-200.stp",
    "examples/3dhubs/flat_with_curves_1.step",
    "examples/3dhubs/bent_failing_1.step",
    "examples/benchmark/test_1/BenchMark_01.stp",
}

THICKNESS_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*mm", re.IGNORECASE)


def _is_step(path):
    name = path.name.lower()
    return any(fnmatch.fnmatch(name, pat) for pat in STEP_PATTERNS)


def _relpath(path):
    return path.relative_to(REPO_ROOT).as_posix()


def _category_for(path):
    rel = path.relative_to(REPO_ROOT / "examples")
    top = rel.parts[0]
    if top == "benchmark":
        return "benchmark_1" if rel.parts[1] == "test_1" else "benchmark_2"
    return CATEGORY_BY_DIR.get(top, top)


def _find_goldens(path):
    """Committed outputs live in a sibling directory named like the input."""
    golden_dir = path.parent / path.stem
    result = {}
    if golden_dir.is_dir():
        jsons = sorted(golden_dir.glob("*.json"))
        dxfs = sorted(golden_dir.glob("*.dxf"))
        if jsons:
            result["golden_json"] = _relpath(jsons[0])
        if dxfs:
            result["golden_dxf"] = [_relpath(d) for d in dxfs]
    return result


def _filename_thickness(path):
    match = THICKNESS_RE.search(path.stem)
    if match:
        return float(match.group(1).replace(",", "."))
    return None


def bootstrap():
    """Scan examples/ and build a skeleton manifest (expected_* all null)."""
    examples = REPO_ROOT / "examples"
    files = sorted(
        (p for p in examples.rglob("*") if p.is_file() and _is_step(p)),
        key=lambda p: _relpath(p).lower(),
    )
    smoke_lower = {s.lower() for s in SMOKE_PATHS}
    entries = []
    for path in files:
        rel = _relpath(path)
        category = _category_for(path)
        entry = {
            "path": rel,
            "category": category,
            "smoke": rel.lower() in smoke_lower,
            "expected": "unknown",
            "timeout_s": DEFAULT_TIMEOUTS.get(category, DEFAULT_TIMEOUT),
            "expected_parts": None,
            "expected_sheets": None,
            "expected_tubes": None,
            "expected_thickness": None,
            "expected_bends": None,
            "expected_bend_angles": None,
            "expected_message_codes": None,
        }
        if category == "rolled":
            thickness = _filename_thickness(path)
            if thickness is not None:
                entry["filename_thickness"] = thickness
        entry.update(_find_goldens(path))
        entries.append(entry)
    # Fallback: if a hardcoded smoke path didn't match (renamed file), promote
    # the first file of any category that has no smoke member yet.
    smoke_categories = {e["category"] for e in entries if e["smoke"]}
    for entry in entries:
        if entry["category"] not in smoke_categories:
            entry["smoke"] = True
            smoke_categories.add(entry["category"])
    return {
        "defaults": {"k_factor": 0.5, "timeout_s": DEFAULT_TIMEOUT},
        "files": entries,
    }


def load(path=MANIFEST_PATH):
    with open(path, "r", encoding="utf-8") as fh:
        manifest = yaml.safe_load(fh)
    validate(manifest)
    return manifest


def save(manifest, path=MANIFEST_PATH):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        yaml.safe_dump(manifest, fh, sort_keys=False, allow_unicode=True,
                       default_flow_style=None, width=100)


def validate(manifest):
    """Error on manifest paths missing from disk; warn on unmanifested files."""
    problems = []
    listed = set()
    for entry in manifest.get("files", []):
        listed.add(entry["path"].lower())
        if not (REPO_ROOT / entry["path"]).is_file():
            problems.append("missing on disk: %s" % entry["path"])
    if problems:
        raise FileNotFoundError("Manifest/disk mismatch:\n  " + "\n  ".join(problems))
    examples = REPO_ROOT / "examples"
    unlisted = [
        _relpath(p)
        for p in examples.rglob("*")
        if p.is_file() and _is_step(p) and _relpath(p).lower() not in listed
    ]
    return unlisted  # caller decides whether to warn


def freeze(manifest, results):
    """Fill expected_* fields from a run's results (list of per-file dicts).

    Only touches entries whose result status is pass/warn (observed behavior
    becomes the contract) or fail/crash/timeout (frozen as known_failure).
    Returns the number of updated entries; caller saves + human reviews diff.
    """
    by_path = {r["path"].lower(): r for r in results}
    updated = 0
    for entry in manifest.get("files", []):
        result = by_path.get(entry["path"].lower())
        if result is None:
            continue
        status = result.get("status")
        if status in ("pass", "warn"):
            entry["expected"] = "pass"
            metrics = result.get("metrics") or {}
            entry["expected_parts"] = result.get("parts_found")
            entry["expected_sheets"] = result.get("sheets")
            entry["expected_tubes"] = result.get("tubes")
            if metrics.get("thickness") is not None:
                entry["expected_thickness"] = round(metrics["thickness"], 3)
            if metrics.get("bend_count") is not None:
                entry["expected_bends"] = metrics["bend_count"]
            if metrics.get("bend_angles") is not None:
                entry["expected_bend_angles"] = [
                    round(a, 2) for a in sorted(metrics["bend_angles"])
                ]
            entry["expected_message_codes"] = sorted(result.get("message_codes") or [])
        elif status in ("fail", "crash", "timeout"):
            entry["expected"] = "known_failure"
            entry["expected_message_codes"] = sorted(result.get("message_codes") or [])
        updated += 1
    return updated


def load_results(results_path):
    results = []
    with open(results_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                results.append(json.loads(line))
    return results


def check_thickness_consistency(manifest):
    """Flag entries whose frozen thickness disagrees with filename ground truth."""
    conflicts = []
    for entry in manifest.get("files", []):
        truth = entry.get("filename_thickness")
        frozen = entry.get("expected_thickness")
        if truth is not None and frozen is not None:
            if not math.isclose(truth, frozen, abs_tol=0.1):
                conflicts.append((entry["path"], truth, frozen))
    return conflicts
