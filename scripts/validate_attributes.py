#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Validate STEP attribute extraction (colors, names, semantic PMI) against
real files and report per-file results.

For every input file the script runs the TreeBuilder with attribute
extraction enabled and prints:
- parts and their part-level colors / colored-face / named-face counts
- semantic PMI entities with values, datum names and resolved face/edge ids
- internal consistency checks (ids in range, pmi_refs cross-reference)
- ground-truth entity counts grepped from the raw STEP text for comparison
  (presentation/semantic counts differ; zero-vs-nonzero is the signal)

Run from the repo root inside the instapart3 environment:
    python scripts/validate_attributes.py examples/color/*.stp
    python scripts/validate_attributes.py -v examples/nist/*_ap242.stp
"""

import argparse
import logging
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

STEP_ENTITY_PATTERNS = {
    "styled_faces": re.compile(r"(?:OVER_RIDING_)?STYLED_ITEM\s*\(", re.IGNORECASE),
    "dimensions": re.compile(r"DIMENSIONAL_(?:CHARACTERISTIC_REPRESENTATION|LOCATION|SIZE)\s*\(", re.IGNORECASE),
    "geom_tolerances": re.compile(r"\w*_TOLERANCE\s*\(|GEOMETRIC_TOLERANCE", re.IGNORECASE),
    "datums": re.compile(r"\bDATUM\s*\(", re.IGNORECASE),
}


def is_lfs_pointer(path):
    with open(path, "rb") as fh:
        return fh.read(40).startswith(b"version https://git-lfs")


def step_ground_truth(path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    return {name: len(pattern.findall(text)) for name, pattern in STEP_ENTITY_PATTERNS.items()}


def validate_file(path, verbose=False):
    from explode import TreeBuilder
    from utils import iterate_shape_parts, suppress_stdout_stderr

    report = {"path": path, "errors": [], "warnings": []}

    with suppress_stdout_stderr():
        builder = TreeBuilder(path, extract_attributes=True)
        tree = builder.compute(root=os.path.basename(path))
    builder.extract_attributes_tree(tree)

    if tree is None:
        report["errors"].append("tree failed to compute")
        return report

    report["pmi_degraded"] = builder.pmi_degraded

    parts = [p for p in iterate_shape_parts(tree) if p.index == p.reference]
    report["parts"] = len(parts)

    part_colors = colored = named = 0
    pmi_ids = set()
    counts = {"dimensions": 0, "tolerances": 0, "datums": 0}
    unresolved = 0
    lines = []

    for part in parts:
        face_count = len(part.face_hash_by_id or {})
        attributes = part.face_attributes or {}

        if part.color:
            part_colors += 1
        part_colored = [a for a in attributes.values() if a.color]
        part_named = [a for a in attributes.values() if a.name]
        colored += len(part_colored)
        named += len(part_named)

        for face_id in attributes:
            if not (1 <= face_id <= face_count):
                report["errors"].append(
                    "%s: face_id %s out of range 1..%s" % (part.name, face_id, face_count))

        if verbose and (part.color or attributes):
            lines.append("  part %-30s color=%s colored_faces=%s named=%s" % (
                part.name[:30],
                tuple(round(c, 2) for c in part.color) if part.color else None,
                [a.face_id for a in part_colored],
                [(a.face_id, a.name) for a in part_named]))

        if part.pmi:
            for kind in ("dimensions", "tolerances", "datums"):
                for entity in getattr(part.pmi, kind):
                    counts[kind] += 1
                    pmi_ids.add(entity.id)
                    refs = list(entity.face_ids) + list(entity.edge_ids)
                    refs += list(getattr(entity, "secondary_face_ids", []))
                    if not refs:
                        unresolved += 1
                    for face_id in entity.face_ids + getattr(entity, "secondary_face_ids", []):
                        if not (1 <= face_id <= face_count):
                            report["errors"].append(
                                "%s: PMI %s face_id %s out of range" % (part.name, entity.id, face_id))
                    if verbose:
                        detail = "value=%s" % getattr(entity, "value", None)
                        if kind == "tolerances":
                            detail += " datums=%s" % entity.datum_names
                        if kind == "datums":
                            detail = "name=%s" % entity.name
                        lines.append("  %s #%s %s %s faces=%s%s edges=%s" % (
                            kind[:-1], entity.id, getattr(entity, "type", ""), detail,
                            entity.face_ids,
                            "+%s" % entity.secondary_face_ids if getattr(entity, "secondary_face_ids", None) else "",
                            entity.edge_ids))

        # pmi_refs must point at existing PMI entities
        for attribute in attributes.values():
            for ref in attribute.pmi_refs:
                if ref not in pmi_ids:
                    report["warnings"].append(
                        "%s: face %s pmi_ref %s not in extracted PMI (may belong to another part)" % (
                            part.name, attribute.face_id, ref))

    report["part_colors"] = part_colors
    report["colored_faces"] = colored
    report["named_faces"] = named
    report["pmi"] = counts
    report["pmi_unresolved"] = unresolved
    report["detail"] = lines
    report["ground_truth"] = step_ground_truth(path)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.disable(logging.CRITICAL)
    failures = 0

    for path in args.inputs:
        if is_lfs_pointer(path):
            print("%-45s SKIP (git-lfs pointer, run: git lfs pull)" % os.path.basename(path))
            continue
        try:
            report = validate_file(path, verbose=args.verbose)
        except Exception as exc:
            print("%-45s CRASH %s" % (os.path.basename(path), exc))
            failures += 1
            continue

        truth = report["ground_truth"]
        status = "FAIL" if report["errors"] else "ok"
        if report["errors"]:
            failures += 1
        print("%-45s %-4s parts=%-3s colors: part=%s face=%s (styled~%s) names=%s  "
              "pmi: dim=%s/%s tol=%s/%s datum=%s/%s unresolved=%s%s" % (
                  os.path.basename(path), status, report["parts"],
                  report["part_colors"], report["colored_faces"], truth["styled_faces"],
                  report["named_faces"],
                  report["pmi"]["dimensions"], truth["dimensions"],
                  report["pmi"]["tolerances"], truth["geom_tolerances"],
                  report["pmi"]["datums"], truth["datums"],
                  report["pmi_unresolved"],
                  "  DEGRADED" if report.get("pmi_degraded") else ""))
        for line in report["detail"]:
            print(line)
        for error in report["errors"]:
            print("    ERROR: %s" % error)
        for warning in report["warnings"]:
            print("    warn: %s" % warning)

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
