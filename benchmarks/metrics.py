"""Geometry metric extraction, independent of the production pipeline.

Two input worlds:
- Output JSON (JobSchema dumps): paths are lists of [x, y] or [x, y, bulge]
  vertices where the bulge applies to the segment from that vertex to the
  next. Closed paths repeat the first vertex at the end.
- DXF files (ezdxf): LWPOLYLINE (xyseb points), CIRCLE, LINE, TEXT on the
  CYCAD layers DESCRIPTION / BENDS / OUTLINE / ENGRAVING.

All areas returned by public helpers are positive; signed shoelace values
stay internal. Arc math (bulge) is exact for area and perimeter; bounding
boxes include arc extrema.
"""

import json
import math
import os

import ezdxf
from ezdxf.math import bulge_to_arc

# Layer conventions across exporter generations (all matched case-insensitively):
#   export_cycad:    OUTLINE / BENDS / ENGRAVING / DESCRIPTION
#   export_designer: GEOMETRY / BENDLINES / EXTRUSIONS / DESCRIPTION
#   legacy goldens:  cut / bend / description
OUTLINE_LAYERS = {"outline", "geometry", "cut"}
BEND_LAYERS = {"bends", "bendlines", "bend"}
ENGRAVING_LAYERS = {"engraving", "extrusions"}


def layer_role(layer_name):
    """Map a DXF layer name to its role: outline | bends | engraving | other."""
    name = layer_name.lower()
    if name in OUTLINE_LAYERS:
        return "outline"
    if name in BEND_LAYERS:
        return "bends"
    if name in ENGRAVING_LAYERS:
        return "engraving"
    return "other"


# ---------------------------------------------------------------------------
# Bulge / path math (JSON-style paths: [[x, y], [x, y, bulge], ...])
# ---------------------------------------------------------------------------

def _segments(path, closed=None):
    """Yield (p1, p2, bulge) for each segment of a JSON-style path.

    A path whose last vertex equals its first is treated as closed with the
    duplicate dropped. If `closed` is True an implicit wrap-around segment is
    added (used for DXF lwpolylines with the closed flag).
    """
    pts = [(p[0], p[1], p[2] if len(p) > 2 else 0.0) for p in path]
    if len(pts) < 2:
        return
    if closed is None:
        first, last = pts[0], pts[-1]
        if abs(first[0] - last[0]) < 1e-9 and abs(first[1] - last[1]) < 1e-9:
            closed = True
            pts = pts[:-1]
        else:
            closed = False
    n = len(pts)
    last_index = n if closed else n - 1
    for i in range(last_index):
        p1 = pts[i]
        p2 = pts[(i + 1) % n]
        yield (p1[0], p1[1]), (p2[0], p2[1]), p1[2]


def _bulge_geometry(p1, p2, bulge):
    """Return (theta, radius, arc_length, signed_segment_area) for a bulge arc.

    theta = included angle, signed like the bulge (positive = CCW).
    signed_segment_area is the circular-segment area between chord and arc,
    signed so it can be added directly to the signed shoelace area.
    """
    chord = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
    if chord < 1e-12 or abs(bulge) < 1e-12:
        return 0.0, 0.0, chord, 0.0
    theta = 4.0 * math.atan(bulge)
    radius = chord * (1.0 + bulge * bulge) / (4.0 * abs(bulge))
    arc_length = abs(radius * theta)
    segment_area = 0.5 * radius * radius * (theta - math.sin(theta))
    return theta, radius, arc_length, segment_area


def path_signed_area(path, closed=None):
    """Signed area of a JSON-style path (CCW positive), bulge-exact."""
    area = 0.0
    for p1, p2, bulge in _segments(path, closed):
        area += 0.5 * (p1[0] * p2[1] - p2[0] * p1[1])
        if bulge:
            _, _, _, seg = _bulge_geometry(p1, p2, bulge)
            area += seg
    return area


def path_perimeter(path, closed=None):
    """Length of a JSON-style path, bulge-exact."""
    total = 0.0
    for p1, p2, bulge in _segments(path, closed):
        if bulge:
            _, _, arc_len, _ = _bulge_geometry(p1, p2, bulge)
            total += arc_len
        else:
            total += math.hypot(p2[0] - p1[0], p2[1] - p1[1])
    return total


def path_bbox(path, closed=None):
    """(min_x, min_y, max_x, max_y) of a JSON-style path, arc extrema included."""
    xs, ys = [], []
    for p1, p2, bulge in _segments(path, closed):
        xs.extend((p1[0], p2[0]))
        ys.extend((p1[1], p2[1]))
        if bulge:
            center, start_angle, end_angle, radius = bulge_to_arc(p1, p2, bulge)
            for angle in (0.0, 0.5 * math.pi, math.pi, 1.5 * math.pi):
                if _angle_in_arc(angle, start_angle, end_angle):
                    xs.append(center[0] + radius * math.cos(angle))
                    ys.append(center[1] + radius * math.sin(angle))
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _angle_in_arc(angle, start, end):
    """True if `angle` lies on the CCW arc from start to end (ezdxf convention)."""
    tau = 2.0 * math.pi
    span = (end - start) % tau
    return (angle - start) % tau <= span


def path_is_closed(path, tol=1e-6):
    if len(path) < 3:
        return False
    first, last = path[0], path[-1]
    return abs(first[0] - last[0]) <= tol and abs(first[1] - last[1]) <= tol


# ---------------------------------------------------------------------------
# JSON pattern metrics (JobSchema output)
# ---------------------------------------------------------------------------

def entity_area(entity):
    """Positive enclosed area of a pattern entity dict (CIRCLE / PATH / LINE)."""
    if entity is None:
        return 0.0
    if entity.get("type") == "CIRCLE" and entity.get("radius"):
        return math.pi * entity["radius"] ** 2
    path = entity.get("path") or []
    return abs(path_signed_area(path))


def entity_perimeter(entity):
    if entity is None:
        return 0.0
    if entity.get("type") == "CIRCLE" and entity.get("radius"):
        return 2.0 * math.pi * entity["radius"]
    return path_perimeter(entity.get("path") or [])


def entity_bbox(entity):
    if entity is None:
        return None
    if entity.get("type") == "CIRCLE" and entity.get("radius"):
        cx, cy = entity["centroid"][0], entity["centroid"][1]
        r = entity["radius"]
        return cx - r, cy - r, cx + r, cy + r
    return path_bbox(entity.get("path") or [])


def pattern_metrics(pattern):
    """Extract harness metrics from a JSON `pattern` dict.

    flat_area = contour area minus hole areas. Note: pattern["holes"] in the
    JSON contains real cutouts only in most cases, but engraved features can
    appear there too — the DXF OUTLINE layer is the authoritative source for
    the volume check; this JSON version is used for cross-validation.
    """
    contour = pattern.get("contour")
    holes = pattern.get("holes") or []
    contour_area = entity_area(contour)
    hole_areas = sorted((entity_area(h) for h in holes), reverse=True)
    bbox = entity_bbox(contour)
    return {
        "contour_area": contour_area,
        "contour_perimeter": entity_perimeter(contour),
        "contour_closed": path_is_closed(contour.get("path") or []) if contour else False,
        "hole_count": len(holes),
        "hole_areas": hole_areas,
        "flat_area": contour_area - sum(hole_areas),
        "bbox": bbox,
        "width": pattern.get("width"),
        "height": pattern.get("height"),
        "thickness": pattern.get("thickness"),
        "bend_quantity": pattern.get("bend_quantity"),
        "bend_groups": pattern.get("bend_groups"),
    }


# ---------------------------------------------------------------------------
# DXF metrics (ezdxf)
# ---------------------------------------------------------------------------

def _lwpolyline_path(entity):
    """LWPOLYLINE -> JSON-style path + closed flag."""
    points = [(p[0], p[1], p[4]) for p in entity.get_points("xyseb")]
    return points, bool(entity.closed)


def dxf_metrics(dxf_path):
    """Extract layer histograms and OUTLINE-layer geometry from a DXF file.

    Returns a dict with:
      layers: {layer: {entity_type: count}}
      contour_area / contour_perimeter / bbox (largest closed OUTLINE loop)
      hole_areas (descending), hole_signature (rigid-motion invariant),
      flat_area, bend_line_lengths (sorted), text_count
    """
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()

    layers = {}
    loops = []       # (area, perimeter, bbox, centroid) of closed OUTLINE loops
    bend_lengths = []
    text_count = 0

    for entity in msp:
        layer = entity.dxf.layer
        role = layer_role(layer)
        kind = entity.dxftype()
        layers.setdefault(layer, {}).setdefault(kind, 0)
        layers[layer][kind] += 1

        if kind == "TEXT":
            text_count += 1
            continue

        if role == "bends" and kind == "LINE":
            start, end = entity.dxf.start, entity.dxf.end
            bend_lengths.append(math.hypot(end[0] - start[0], end[1] - start[1]))
            continue

        if role == "outline":
            if kind == "LWPOLYLINE":
                path, closed = _lwpolyline_path(entity)
                if closed or path_is_closed([(p[0], p[1]) for p in path]):
                    area = abs(path_signed_area(path, closed=closed))
                    perimeter = path_perimeter(path, closed=closed)
                    bbox = path_bbox(path, closed=closed)
                    centroid = _path_centroid(path, closed=closed)
                    loops.append((area, perimeter, bbox, centroid))
            elif kind == "CIRCLE":
                c = entity.dxf.center
                r = entity.dxf.radius
                loops.append((
                    math.pi * r * r,
                    2.0 * math.pi * r,
                    (c[0] - r, c[1] - r, c[0] + r, c[1] + r),
                    (c[0], c[1]),
                ))

    loops.sort(key=lambda item: item[0], reverse=True)
    result = {
        "layers": layers,
        "bend_line_lengths": sorted(bend_lengths),
        "text_count": text_count,
        "contour_area": None,
        "contour_perimeter": None,
        "bbox": None,
        "hole_areas": [],
        "hole_signature": [],
        "flat_area": None,
    }
    if loops:
        contour_area, contour_perimeter, bbox, contour_centroid = loops[0]
        holes = loops[1:]
        result.update({
            "contour_area": contour_area,
            "contour_perimeter": contour_perimeter,
            "bbox": bbox,
            "hole_areas": [h[0] for h in holes],
            # rigid-motion invariant: (area, perimeter, distance to contour centroid)
            "hole_signature": sorted(
                (
                    round(h[0], 6),
                    round(h[1], 6),
                    round(math.hypot(h[3][0] - contour_centroid[0],
                                     h[3][1] - contour_centroid[1]), 6),
                )
                for h in holes
            ),
            "flat_area": contour_area - sum(h[0] for h in holes),
        })
    return result


def _path_centroid(path, closed=None):
    """Area centroid of a closed path, arcs tessellated at ~1 degree.

    Must not depend on the vertex density of the input polyline (different
    exporter generations discretize edges differently), so arcs are resampled
    and the polygon area centroid is computed over the tessellation.
    """
    points = []
    for p1, p2, bulge in _segments(path, closed):
        points.append(p1)
        if bulge:
            center, _, _, radius = bulge_to_arc(p1, p2, bulge)
            # sample from p1 towards p2 along the signed sweep (CCW positive);
            # bulge_to_arc normalizes angles to CCW so its order is unreliable
            sweep = 4.0 * math.atan(bulge)
            theta1 = math.atan2(p1[1] - center[1], p1[0] - center[0])
            steps = max(2, int(abs(math.degrees(sweep))))
            for i in range(1, steps):
                angle = theta1 + sweep * i / steps
                points.append((center[0] + radius * math.cos(angle),
                               center[1] + radius * math.sin(angle)))
    if len(points) < 3:
        if not points:
            return (0.0, 0.0)
        return (sum(p[0] for p in points) / len(points),
                sum(p[1] for p in points) / len(points))

    area2, cx, cy = 0.0, 0.0, 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i][0], points[i][1]
        x2, y2 = points[(i + 1) % n][0], points[(i + 1) % n][1]
        cross = x1 * y2 - x2 * y1
        area2 += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    if abs(area2) < 1e-12:
        return (sum(p[0] for p in points) / n, sum(p[1] for p in points) / n)
    return (cx / (3.0 * area2), cy / (3.0 * area2))


def audit_dxf(dxf_path):
    """Run ezdxf's auditor. Returns (n_errors, n_fixes, messages)."""
    doc = ezdxf.readfile(dxf_path)
    auditor = doc.audit()
    errors = [str(e) for e in auditor.errors]
    fixes = [str(e) for e in auditor.fixes]
    return len(errors), len(fixes), errors + fixes


# ---------------------------------------------------------------------------
# JSON normalization (golden comparison)
# ---------------------------------------------------------------------------

VOLATILE_KEYS = {"id", "timestamp"}


def normalize_job(job):
    """Normalize a JobSchema JSON dict for comparison.

    Drops volatile fields (ids are Py2 hash()-derived, timestamps change),
    reduces file paths to basenames, and sorts shapes deterministically.
    Returns a new structure; the input is not modified.
    """
    def walk(node):
        if isinstance(node, dict):
            out = {}
            for key, value in node.items():
                if key in VOLATILE_KEYS:
                    continue
                if key == "path" and isinstance(value, str):
                    out[key] = os.path.basename(value.replace("\\", "/"))
                    continue
                out[key] = walk(value)
            if "shapes" in out and isinstance(out["shapes"], list):
                out["shapes"] = sorted(
                    out["shapes"],
                    key=lambda s: (str(s.get("type")), s.get("volume") or 0.0),
                )
            return out
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node

    return walk(job)


def load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def message_codes(job):
    """All message codes in a job JSON: job level, tree nodes, shapes."""
    codes = set()

    def walk(node):
        if isinstance(node, dict):
            for message in node.get("messages") or []:
                if isinstance(message, dict) and "code" in message:
                    codes.add(int(message["code"]))
            for key in ("tree", "components", "shapes"):
                if key in node and node[key] is not None:
                    walk(node[key])
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(job)
    return codes
