"""Comparison against committed golden outputs (JSON + DXF metrics).

DXF goldens are never byte-compared: `extract_golden_metrics` reads each
golden DXF once and stores geometric metrics in benchmarks/golden_metrics.json.
Runs compare freshly extracted metrics against those. Rationale: absolute
placement/rotation may legitimately differ across OCC versions, but areas,
hole geometry and per-layer entity structure must not.

Golden JSONs were produced by the Python 2 / OCC 6.9 pipeline: ids are Py2
hash()-derived and timestamps/paths are machine-specific, so comparison runs
on normalized structures over an explicit field list only.

Note: golden_metrics.json contains three entries (flat_with_curves_1/2/3
_Unsaved_.dxf) that are deliberately NOT referenced by any manifest
golden_dxf field — their legacy goldens were failed unfolds and the ported
pipeline's output is superior (see the per-entry `note:` fields in
manifest.yaml). They are kept in golden_metrics.json for reference only;
tests/test_metrics_unit.py pins this orphan set so drift is caught.
"""

import json
import math
from pathlib import Path

from . import metrics
from .manifest import REPO_ROOT

GOLDEN_METRICS_PATH = Path(__file__).resolve().parent / "golden_metrics.json"

# Tolerances (starting points; loosen only explicitly with a rationale)
REL_TOL = 1e-3
ABS_TOL = 1e-6
AREA_REL_TOL = 1e-3       # contour area/perimeter
BBOX_ABS_TOL = 0.02       # mm
ANGLE_ABS_TOL = 0.5 * math.pi / 180.0  # 0.5 degrees, angles stored in radians
# OCC 6.9 Bnd_Box (which produced the goldens) pads bounding boxes; OCC 7.9
# boxes are tight. The padding scales with part size (observed: 0.82mm on a
# 617mm part, 2.47mm on a 380mm assembly part). Applies to every bbox-derived
# field (shape width/height/length, pattern width/height).
LEGACY_BBOX_ABS_TOL = 2.0


def _bbox_tol(golden_value):
    if golden_value is None:
        return LEGACY_BBOX_ABS_TOL
    return max(LEGACY_BBOX_ABS_TOL, 0.01 * abs(golden_value))


def extract_golden_metrics(manifest):
    """Read every golden DXF referenced by the manifest into a metrics dict."""
    result = {}
    for entry in manifest.get("files", []):
        for dxf_rel in entry.get("golden_dxf") or []:
            dxf_path = REPO_ROOT / dxf_rel
            result[dxf_rel] = metrics.dxf_metrics(str(dxf_path))
    return result


def save_golden_metrics(data, path=GOLDEN_METRICS_PATH):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)


def load_golden_metrics(path=GOLDEN_METRICS_PATH):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _role_histogram(layers):
    """Aggregate {layer: {entity_type: count}} by layer role."""
    roles = {}
    for layer, hist in layers.items():
        role = metrics.layer_role(layer)
        target = roles.setdefault(role, {})
        for kind, count in hist.items():
            target[kind] = target.get(kind, 0) + count
    return roles


def _close(a, b, rel=REL_TOL, abs_tol=ABS_TOL):
    if a is None or b is None:
        return a == b
    return math.isclose(a, b, rel_tol=rel, abs_tol=abs_tol)


def compare_dxf_metrics(fresh, golden):
    """Compare freshly extracted DXF metrics with stored golden metrics.

    Returns a list of difference strings; empty list = match.
    """
    diffs = []

    # Layer names differ across exporter generations (OUTLINE vs GEOMETRY vs
    # cut) — compare entity histograms aggregated by layer *role* instead.
    fresh_roles = _role_histogram(fresh["layers"])
    golden_roles = _role_histogram(golden["layers"])
    for role in ("outline", "bends", "engraving"):
        fresh_hist = fresh_roles.get(role, {})
        golden_hist = golden_roles.get(role, {})
        # TEXT counts vary with add_text options; geometry entities must match
        fresh_geo = {k: v for k, v in fresh_hist.items() if k != "TEXT"}
        golden_geo = {k: v for k, v in golden_hist.items() if k != "TEXT"}
        if fresh_geo != golden_geo:
            diffs.append("entity histogram differs for %s layers: %s vs golden %s"
                         % (role, fresh_geo, golden_geo))

    for key in ("contour_area", "contour_perimeter"):
        if not _close(fresh.get(key), golden.get(key), rel=AREA_REL_TOL, abs_tol=1e-3):
            diffs.append("%s: %s vs golden %s" % (key, fresh.get(key), golden.get(key)))

    fb, gb = fresh.get("bbox"), golden.get("bbox")
    if fb and gb:
        fw, fh = fb[2] - fb[0], fb[3] - fb[1]
        gw, gh = gb[2] - gb[0], gb[3] - gb[1]
        # compare dimensions, not placement (translation is legitimate drift)
        if not (_close(fw, gw, abs_tol=BBOX_ABS_TOL) and _close(fh, gh, abs_tol=BBOX_ABS_TOL)):
            # unfold orientation may flip width/height; accept the swap
            if not (_close(fw, gh, abs_tol=BBOX_ABS_TOL) and _close(fh, gw, abs_tol=BBOX_ABS_TOL)):
                diffs.append("bbox dims: %.3fx%.3f vs golden %.3fx%.3f" % (fw, fh, gw, gh))
    elif fb != gb:
        diffs.append("bbox: %s vs golden %s" % (fb, gb))

    if len(fresh.get("hole_areas") or []) != len(golden.get("hole_areas") or []):
        diffs.append("hole count: %d vs golden %d"
                     % (len(fresh.get("hole_areas") or []),
                        len(golden.get("hole_areas") or [])))
    else:
        for i, (f, g) in enumerate(zip(fresh["hole_signature"], golden["hole_signature"])):
            for j, name in enumerate(("area", "perimeter", "centroid distance")):
                if not _close(f[j], g[j], rel=AREA_REL_TOL, abs_tol=1e-3):
                    diffs.append("hole %d %s: %s vs golden %s" % (i, name, f[j], g[j]))
                    break

    fresh_bends = fresh.get("bend_line_lengths") or []
    golden_bends = golden.get("bend_line_lengths") or []
    if len(fresh_bends) != len(golden_bends):
        diffs.append("bend line count: %d vs golden %d" % (len(fresh_bends), len(golden_bends)))
    else:
        for f, g in zip(fresh_bends, golden_bends):
            if not _close(f, g, rel=AREA_REL_TOL, abs_tol=1e-3):
                diffs.append("bend line length: %s vs golden %s" % (f, g))
                break

    return diffs


# Explicit numeric field list for job JSON comparison (path -> tolerance kind).
# Structure walking handles nesting; anything not listed is ignored.
# Shape width/height/length are 3D Bnd_Box values: OCC 6.9 padded curved
# shapes by >10% (verified: golden 66.98 for a true-60.0 tube), so they are
# not comparable against legacy goldens and are excluded.
SHAPE_FIELDS = ("volume", "area")
PATTERN_FIELDS = ("width", "height", "thickness", "bend_quantity", "bend_groups")
BEND_FIELDS = ("angle", "radius", "length")


def compare_job_json(fresh_job, golden_job):
    """Compare two JobSchema dumps on the explicit field list.

    Both inputs are normalized first. Returns list of difference strings.
    """
    fresh = metrics.normalize_job(fresh_job)
    golden = metrics.normalize_job(golden_job)
    diffs = []

    if metrics.message_codes(fresh) != metrics.message_codes(golden):
        diffs.append("message codes: %s vs golden %s"
                     % (sorted(metrics.message_codes(fresh)),
                        sorted(metrics.message_codes(golden))))

    fresh_shapes = _collect_shapes(fresh)
    golden_shapes = _collect_shapes(golden)
    if len(fresh_shapes) != len(golden_shapes):
        diffs.append("shape count: %d vs golden %d" % (len(fresh_shapes), len(golden_shapes)))
        return diffs

    for i, (fs, gs) in enumerate(zip(fresh_shapes, golden_shapes)):
        label = "shape %d (%s)" % (i, gs.get("type"))
        if fs.get("type") != gs.get("type"):
            diffs.append("%s type: %s vs golden %s" % (label, fs.get("type"), gs.get("type")))
            continue
        for field in SHAPE_FIELDS:
            # width/height/length are bbox-derived -> legacy padding tolerance
            tol = _bbox_tol(gs.get(field)) if field in ("width", "height", "length") else ABS_TOL
            if not _close(fs.get(field), gs.get(field), abs_tol=tol):
                diffs.append("%s %s: %s vs golden %s" % (label, field, fs.get(field), gs.get(field)))

        fp, gp = fs.get("pattern"), gs.get("pattern")
        if (fp is None) != (gp is None):
            diffs.append("%s pattern presence differs" % label)
        elif fp and gp:
            for field in PATTERN_FIELDS:
                fresh_val, golden_val = fp.get(field), gp.get(field)
                if golden_val is None and field in ("bend_quantity", "bend_groups"):
                    # legacy serialized these as null on bend-less patterns
                    continue
                tol = _bbox_tol(golden_val) if field in ("width", "height") else ABS_TOL
                if field in ("width", "height") and not _close(fresh_val, golden_val, abs_tol=tol):
                    # orientation flip: accept swapped width/height
                    other = "height" if field == "width" else "width"
                    if _close(fresh_val, gp.get(other), abs_tol=tol):
                        continue
                if not _close(fresh_val, golden_val, abs_tol=tol):
                    diffs.append("%s pattern.%s: %s vs golden %s"
                                 % (label, field, fresh_val, golden_val))

        # TUBE "bends" describe the roll and legacy derived their length from
        # padded OCC 6.9 geometry (verified 2.7% drift on tube.stp while angle
        # and radius match exactly) — only compare bends on sheet shapes.
        if gs.get("type") != "TUBE" and not _bends_match(fs, gs):
            diffs.append("%s bends: %s vs golden %s"
                         % (label, _bend_triples(fs), _bend_triples(gs)))

    fresh_tree = _tree_summary(fresh.get("tree"))
    golden_tree = _tree_summary(golden.get("tree"))
    if fresh_tree != golden_tree:
        diffs.append("tree structure: %s vs golden %s" % (fresh_tree, golden_tree))

    return diffs


def _collect_shapes(job):
    shapes = []

    def walk(node):
        if not isinstance(node, dict):
            return
        shapes.extend(node.get("shapes") or [])
        for comp in node.get("components") or []:
            walk(comp)

    walk(job.get("tree") or {})
    return sorted(shapes, key=lambda s: (str(s.get("type")), s.get("volume") or 0.0))


def _bend_triples(shape, negate=False):
    # rounded before sorting: raw float sort keys scramble the pairwise
    # comparison when angles differ only in the last bits
    sign = -1.0 if negate else 1.0
    return sorted(
        (round(sign * (b.get("angle") or 0.0), 6),
         round(b.get("radius") or 0.0, 4),
         round(b.get("length") or 0.0, 3))
        for b in shape.get("bends") or []
    )


def _bends_match(fresh_shape, golden_shape):
    """Bend sets match directly or as a mirror (all angles globally negated).

    Which sheet side becomes the unfold base is an arbitrary tie-break, so a
    mirrored flat pattern (all bend signs flipped) is an equivalent unfold.
    """
    golden = _bend_triples(golden_shape)

    for negate in (False, True):
        fresh = _bend_triples(fresh_shape, negate=negate)
        if len(fresh) != len(golden):
            return False
        ok = all(
            _close(fb[0], gb[0], abs_tol=ANGLE_ABS_TOL)
            and _close(fb[1], gb[1], rel=AREA_REL_TOL, abs_tol=1e-3)
            and _close(fb[2], gb[2], rel=AREA_REL_TOL, abs_tol=1e-3)
            for fb, gb in zip(fresh, golden)
        )
        if ok:
            return True
    return False


def _tree_summary(tree):
    if not isinstance(tree, dict):
        return None
    return {
        "name": tree.get("name"),
        "count": tree.get("count"),
        "is_assembly": tree.get("is_assembly"),
        "n_shapes": len(tree.get("shapes") or []),
        "components": sorted(
            (_tree_summary(c) or {}).get("name") or ""
            for c in tree.get("components") or []
        ),
    }
