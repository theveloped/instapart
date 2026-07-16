"""Correctness checks, run in the parent process on a worker's artifacts.

Each check returns CheckResult(name, status, measured, expected, detail) with
status in {pass, warn, fail, skip}. Checks never raise: a broken artifact is a
failing check, not a harness crash.
"""

import math
import os
from collections import namedtuple

from . import golden as golden_mod
from . import metrics
from .manifest import REPO_ROOT

CheckResult = namedtuple("CheckResult", "name status measured expected detail")

# Mirrors production error 003 thresholds (auto.py)
RELATIVE_VOLUME_THRESHOLD = 0.025
ABSOLUTE_VOLUME_THRESHOLD = 5.0  # mm^3
THICKNESS_RANGE = (0.3, 30.0)


def _result(name, status, measured=None, expected=None, detail=None):
    return CheckResult(name, status, measured, expected, detail)


def run_checks(entry, result, golden_metrics=None):
    """Run all applicable checks for one manifest entry + worker result.

    Returns (checks, extra_metrics): a list of CheckResult and a dict of
    tracked numeric metrics (volume_rel_error, contour_area, ...).
    """
    checks = []
    extra = {}

    job = _load_job(result)
    dxf_data = _load_dxfs(result)

    checks.append(check_ran(result))
    if job is None:
        return checks, extra

    checks.append(check_message_codes(entry, result))

    sheet_shapes = _sheet_shapes(job)
    if sheet_shapes and dxf_data:
        checks.extend(check_volume_conservation(sheet_shapes, dxf_data, result, extra))
        checks.extend(check_flat_topology(sheet_shapes, dxf_data))
        checks.extend(check_dxf_valid(dxf_data))
        checks.extend(check_bends(entry, sheet_shapes))

    if entry.get("filename_thickness") is not None:
        checks.append(check_rolled_thickness(entry, result))

    if entry.get("attributes"):
        checks.extend(check_face_attributes(entry, job))
        checks.extend(check_pmi(entry, job))

    if entry.get("category") == "tube":
        checks.append(check_tube(result))

    checks.append(check_structure(entry, result))

    if golden_metrics:
        checks.extend(check_goldens(entry, result, job, dxf_data, golden_metrics))

    return [c for c in checks if c is not None], extra


# ---------------------------------------------------------------------------


def _load_job(result):
    path = (result.get("outputs") or {}).get("json")
    if not path or not os.path.isfile(path):
        return None
    try:
        return metrics.load_json(path)
    except Exception:
        return None


def _load_dxfs(result):
    data = {}
    for path in (result.get("outputs") or {}).get("dxf") or []:
        if os.path.isfile(path):
            try:
                data[path] = metrics.dxf_metrics(path)
            except Exception as exc:
                data[path] = {"error": str(exc)}
    return data


def _sheet_shapes(job):
    shapes = []

    def walk(node):
        if not isinstance(node, dict):
            return
        for shape in node.get("shapes") or []:
            if shape.get("type") == "SHEET" and shape.get("pattern"):
                shapes.append(shape)
        for comp in node.get("components") or []:
            walk(comp)

    walk(job.get("tree") or {})
    return shapes


def check_ran(result):
    if result.get("status") in ("ok", "pass", "warn"):
        return _result("ran", "pass")
    return _result("ran", "fail", detail=(result.get("error") or "")[-400:])


def check_message_codes(entry, result):
    observed = set(result.get("message_codes") or [])
    expected = entry.get("expected_message_codes")
    if expected is None:
        return _result("message_codes", "skip", measured=sorted(observed),
                       detail="no frozen expectation yet")
    if observed == set(expected):
        return _result("message_codes", "pass", measured=sorted(observed))
    return _result("message_codes", "fail", measured=sorted(observed), expected=sorted(expected))


def check_volume_conservation(sheet_shapes, dxf_data, result, extra):
    """Flagship: solid volume vs DXF flat_area x thickness (exact at k=0.5).

    Each shape's JSON records its own output files, giving the exact
    shape -> DXF mapping (heuristic pairing broke on assemblies with
    same-name export collisions).
    """
    checks = []
    dxf_by_name = {os.path.basename(path).lower(): data
                   for path, data in dxf_data.items()}
    for i, shape in enumerate(sheet_shapes):
        dxf = None
        dxf_name = None
        for file_ref in shape.get("files") or []:
            name = os.path.basename((file_ref.get("path") or "").replace("\\", "/"))
            if name.lower().endswith(".dxf"):
                dxf_name = name
                dxf = dxf_by_name.get(name.lower())
        if dxf is None or not dxf.get("flat_area"):
            checks.append(_result("volume_conservation", "fail",
                                  detail="sheet shape %d: DXF %s missing or empty"
                                  % (i, dxf_name)))
            continue
        volume = shape.get("volume")
        thickness = (shape.get("pattern") or {}).get("thickness")
        if not volume or not thickness:
            checks.append(_result("volume_conservation", "skip", detail="missing volume/thickness"))
            continue
        flat_volume = dxf["flat_area"] * thickness
        rel_error = abs(volume - flat_volume) / volume
        abs_error = abs(volume - flat_volume)
        extra["volume_rel_error"] = max(extra.get("volume_rel_error", 0.0), rel_error)
        if rel_error > RELATIVE_VOLUME_THRESHOLD:
            status = "fail"
        elif abs_error > ABSOLUTE_VOLUME_THRESHOLD:
            status = "warn"
        else:
            status = "pass"
        checks.append(_result("volume_conservation", status,
                              measured=round(rel_error, 6),
                              expected="<= %s" % RELATIVE_VOLUME_THRESHOLD,
                              detail=dxf_name))
    return checks


def check_flat_topology(sheet_shapes, dxf_data):
    checks = []
    for shape in sheet_shapes:
        pattern = shape["pattern"]
        contour = pattern.get("contour")
        if not contour or not contour.get("path"):
            checks.append(_result("flat_topology", "fail", detail="no contour"))
            continue
        problems = []
        warnings = []
        if contour.get("type") != "CIRCLE" and not metrics.path_is_closed(contour["path"]):
            problems.append("contour not closed")
        contour_bbox = metrics.entity_bbox(contour)
        contour_area = metrics.entity_area(contour)
        hole_area_total = 0.0
        for hole in pattern.get("holes") or []:
            hole_area_total += metrics.entity_area(hole)
            hb = metrics.entity_bbox(hole)
            if hb and contour_bbox:
                if (hb[0] < contour_bbox[0] - 0.01 or hb[1] < contour_bbox[1] - 0.01
                        or hb[2] > contour_bbox[2] + 0.01 or hb[3] > contour_bbox[3] + 0.01):
                    problems.append("hole outside contour bbox")
        if hole_area_total >= contour_area:
            problems.append("hole area exceeds contour area")
        thickness = pattern.get("thickness")
        if thickness is not None and not (THICKNESS_RANGE[0] <= thickness <= THICKNESS_RANGE[1]):
            # assemblies legitimately contain thick machined plates / thin
            # foils that the pipeline flattens as trivial plates: plausibility
            # warning, not a correctness failure
            warnings.append("thickness %.3f outside sheet range %s"
                            % (thickness, (THICKNESS_RANGE,)))
        status = "fail" if problems else ("warn" if warnings else "pass")
        checks.append(_result("flat_topology", status,
                              detail="; ".join(problems + warnings) or None))
    return checks


def check_dxf_valid(dxf_data):
    checks = []
    for path, data in dxf_data.items():
        name = os.path.basename(path)
        if "error" in data:
            checks.append(_result("dxf_valid", "fail", detail="%s: %s" % (name, data["error"])))
            continue
        problems = []
        try:
            n_err, _, msgs = metrics.audit_dxf(path)
            if n_err:
                problems.append("audit errors: %s" % msgs[:3])
        except Exception as exc:
            problems.append("audit crashed: %s" % exc)
        roles = {metrics.layer_role(layer) for layer in data.get("layers", {})}
        if "outline" not in roles:
            problems.append("no outline layer")
        checks.append(_result("dxf_valid", "fail" if problems else "pass",
                              detail="; ".join(problems) or None))
    return checks


def check_bends(entry, sheet_shapes):
    checks = []
    for shape in sheet_shapes:
        bends = shape.get("bends") or []
        pattern = shape.get("pattern") or {}
        problems = []
        if pattern.get("bend_quantity") is not None and pattern["bend_quantity"] != len(bends):
            problems.append("bend_quantity %s != len(bends) %s"
                            % (pattern["bend_quantity"], len(bends)))
        for bend in bends:
            angle = abs(bend.get("angle") or 0.0)
            # pi = hem (flattened bend), 2*pi = fully rolled cylinder
            if not (0.0 < angle <= 2.0 * math.pi + 1e-6):
                problems.append("bend angle %.4f out of range" % angle)
                break
            if (bend.get("radius") or 0) <= 0 or (bend.get("length") or 0) <= 0:
                problems.append("non-positive bend radius/length")
                break
        checks.append(_result("bend_sanity", "fail" if problems else "pass",
                              detail="; ".join(problems) or None))

    expected_bends = entry.get("expected_bends")
    if expected_bends is not None:
        total = sum(len(s.get("bends") or []) for s in sheet_shapes)
        status = "pass" if total == expected_bends else "fail"
        checks.append(_result("bend_count_frozen", status, measured=total, expected=expected_bends))

    expected_angles = entry.get("expected_bend_angles")
    if expected_angles is not None:
        observed = sorted(
            round(180.0 / math.pi * (b.get("angle") or 0.0), 2)
            for s in sheet_shapes for b in s.get("bends") or []
        )
        mirrored = sorted(-a for a in observed)
        ok = _angles_close(observed, expected_angles) or _angles_close(mirrored, expected_angles)
        checks.append(_result("bend_angles_frozen", "pass" if ok else "fail",
                              measured=observed, expected=expected_angles))
    return checks


def _angles_close(a, b, tol=0.5):
    return len(a) == len(b) and all(abs(x - y) <= tol for x, y in zip(a, b))


def check_rolled_thickness(entry, result):
    truth = entry["filename_thickness"]
    measured = (result.get("metrics") or {}).get("thickness")
    if measured is None:
        return _result("rolled_thickness", "fail", expected=truth, detail="no thickness extracted")
    status = "pass" if abs(measured - truth) <= 0.1 else "fail"
    return _result("rolled_thickness", status, measured=measured, expected=truth)


def _all_shapes(job):
    shapes = []

    def walk(node):
        if not isinstance(node, dict):
            return
        shapes.extend(node.get("shapes") or [])
        for comp in node.get("components") or []:
            walk(comp)

    walk(job.get("tree") or {})
    return shapes


def check_face_attributes(entry, job):
    """Attribute-enabled entries: shapes[].faces must be present (a list) and
    optionally match the frozen count of faces carrying a color."""
    checks = []
    shapes = _all_shapes(job)

    missing = [s for s in shapes if not isinstance(s.get("faces"), list)]
    checks.append(_result("face_attributes_present", "fail" if missing else "pass",
                          measured=len(shapes) - len(missing), expected=len(shapes)))

    expected = entry.get("expected_colored_faces")
    if expected is not None:
        colored = sum(1 for s in shapes for f in s.get("faces") or [] if f.get("color"))
        checks.append(_result("colored_faces_frozen", "pass" if colored == expected else "fail",
                              measured=colored, expected=expected))

    return checks


def check_pmi(entry, job):
    """Attribute-enabled entries: optional frozen counts of semantic PMI
    entities across all shapes."""
    checks = []
    shapes = _all_shapes(job)

    counts = {"dimensions": 0, "tolerances": 0, "datums": 0}
    for shape in shapes:
        pmi = shape.get("pmi") or {}
        for key in counts:
            counts[key] += len(pmi.get(key) or [])

    for key, manifest_key in (("dimensions", "expected_pmi_dimensions"),
                              ("tolerances", "expected_pmi_tolerances"),
                              ("datums", "expected_pmi_datums")):
        expected = entry.get(manifest_key)
        if expected is not None:
            checks.append(_result("pmi_%s_frozen" % key,
                                  "pass" if counts[key] == expected else "fail",
                                  measured=counts[key], expected=expected))

    return checks


def check_tube(result):
    if (result.get("tubes") or 0) < 1:
        return _result("tube_detected", "fail",
                       detail="no TUBE shape (sheets=%s failed=%s)"
                       % (result.get("sheets"), result.get("failed_shapes")))
    if not (result.get("outputs") or {}).get("stp"):
        return _result("tube_detected", "fail", detail="no STP re-export written")
    return _result("tube_detected", "pass")


def check_structure(entry, result):
    problems = []
    for key, field in (("expected_parts", "parts_found"),
                       ("expected_sheets", "sheets"),
                       ("expected_tubes", "tubes")):
        expected = entry.get(key)
        if expected is not None and result.get(field) != expected:
            problems.append("%s: %s != %s" % (field, result.get(field), expected))
    if not problems:
        frozen = any(entry.get(k) is not None
                     for k in ("expected_parts", "expected_sheets", "expected_tubes"))
        return _result("structure", "pass" if frozen else "skip",
                       detail=None if frozen else "no frozen expectation yet")
    return _result("structure", "fail", detail="; ".join(problems))


def check_goldens(entry, result, job, dxf_data, golden_metrics):
    checks = []
    golden_json_rel = entry.get("golden_json")
    if golden_json_rel:
        try:
            golden_job = metrics.load_json(str(REPO_ROOT / golden_json_rel))
            diffs = golden_mod.compare_job_json(job, golden_job)
            checks.append(_result("golden_json", "pass" if not diffs else "fail",
                                  detail="; ".join(diffs[:5]) or None))
        except Exception as exc:
            checks.append(_result("golden_json", "fail", detail=str(exc)))

    golden_dxf_rels = entry.get("golden_dxf") or []
    fresh = [d for d in dxf_data.values() if "error" not in d and d.get("contour_area")]
    if golden_dxf_rels and fresh:
        stored = [golden_metrics.get(rel) for rel in golden_dxf_rels]
        stored = [s for s in stored if s]
        # match fresh to golden by descending contour area
        fresh.sort(key=lambda d: -(d["contour_area"] or 0))
        stored.sort(key=lambda d: -(d["contour_area"] or 0))
        if len(fresh) != len(stored):
            checks.append(_result("golden_dxf", "fail",
                                  measured=len(fresh), expected=len(stored),
                                  detail="DXF count differs"))
        else:
            all_diffs = []
            for f, s in zip(fresh, stored):
                all_diffs.extend(golden_mod.compare_dxf_metrics(f, s))
            checks.append(_result("golden_dxf", "pass" if not all_diffs else "fail",
                                  detail="; ".join(all_diffs[:5]) or None))
    return checks


def overall_status(result, checks):
    """pass | warn | fail from worker status + check results."""
    if result.get("status") not in ("ok", "pass", "warn"):
        return "fail"
    statuses = {c.status for c in checks}
    if "fail" in statuses:
        return "fail"
    if "warn" in statuses:
        return "warn"
    return "pass"
