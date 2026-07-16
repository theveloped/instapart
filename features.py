#!/usr/bin/env python
"""CNC machining-feature recognizer.

Ports geometry's `draw_features` concave-face + loop/cap topology classifier
into a general recognizer for milled solids, scoped to the holes family:
THROUGH_HOLE, BLIND_HOLE, COUNTERBORE, COUNTERSINK (from concave cylinder/cone
patches) plus a best-effort POCKET for freeform-concave groups.

Consumes an `AdjacencyGraph` with `.full()/.smooth()/.grouped()` already run.
"""

import math
from types import SimpleNamespace

import networkx as nx

from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
from OCC.Core.GeomAbs import GeomAbs_Cylinder, GeomAbs_Cone
from OCC.Core.gp import gp_Vec, gp_Dir

from utils import shape_hash
from flatten import FaceTypes, edge_end_vertices, face_edges, first_edge_point, face_normal
from models import Feature


# Two axes are coaxial when their directions agree within 1 degree.
AXIS_ANGLE_TOL = math.cos(math.radians(1.0))
# Max perpendicular distance (mm) between two infinite axis lines to be coaxial.
AXIS_DIST_TOL = 1e-2
TOLLERANCE = 1e-6


def _surface(face):
    """:return: (kind, radius, axis_loc, axis_dir, semi_angle) for a face.

    kind is 'CYL', 'CONE' or 'OTHER'. For OTHER the geometric fields are None.
    """
    adaptor = BRepAdaptor_Surface(face)
    surface_type = adaptor.GetType()

    if surface_type == GeomAbs_Cylinder:
        cyl = adaptor.Cylinder()
        axis = cyl.Axis()
        return ("CYL", cyl.Radius(), axis.Location(), axis.Direction(), None)

    elif surface_type == GeomAbs_Cone:
        cone = adaptor.Cone()
        axis = cone.Axis()
        return ("CONE", cone.RefRadius(), axis.Location(), axis.Direction(), cone.SemiAngle())

    else:
        return ("OTHER", None, None, None, None)


def _group_loops(aag, group):
    """Reconstruct the boundary loops of a smooth face group.

    Ported from geometry's `draw_features` (loop/cap section), adapted for
    instapart's `C0_faces` being a simple `nx.Graph` (one edge per face pair)
    while `C0_edges` stays a `nx.MultiGraph` carrying the per-edge dihedral
    `angle`.

    :return: (loop_count, caps, neighbors) where caps is a bool per loop
    (True when the loop's minimum dihedral angle <= 0) and neighbors is the set
    of face hashes bordering the group.
    """
    group_set = set(group)
    edge_component = set()
    neighbors = set()

    for node_a, node_b in nx.edge_boundary(aag.C0_faces, group_set):
        face_edge = aag.C0_faces[node_a][node_b]
        first_vertex, last_vertex = edge_end_vertices(face_edge["shape"])
        edge_component.add((shape_hash(first_vertex), shape_hash(last_vertex), face_edge["hash"]))
        neighbors.add(node_b if node_a in group_set else node_a)

    if not edge_component:
        return 0, [], neighbors

    sub_graph = aag.C0_edges.edge_subgraph(edge_component)

    caps = []
    for loop_nodes in nx.connected_components(sub_graph):
        loop_graph = sub_graph.subgraph(loop_nodes)
        angles = []
        for first_node, last_node in loop_graph.edges():
            for edge_key in sub_graph[first_node][last_node]:
                angles.append(sub_graph[first_node][last_node][edge_key]["angle"])

        caps.append((min(angles) <= 0.0) if angles else False)

    return len(caps), caps, neighbors


def _axial_span(aag, face_hashes, axis_loc, axis_dir):
    """:return: (min_t, max_t) of the group's vertices projected onto the axis."""
    dir_vec = gp_Vec(axis_dir)
    min_t = float("inf")
    max_t = float("-inf")

    for face_hash in face_hashes:
        face = aag.C0_faces.nodes[face_hash]["shape"]
        for edge, is_first, is_reversed in face_edges(face):
            point = first_edge_point(edge)
            t = gp_Vec(axis_loc, point).Dot(dir_vec)

            if t < min_t:
                min_t = t
            if t > max_t:
                max_t = t

    if min_t == float("inf"):
        return 0.0, 0.0

    return min_t, max_t


def _axial_extent(aag, face_hashes, axis_loc, axis_dir):
    """:return: extent (max-min) of the group projected onto the axis."""
    min_t, max_t = _axial_span(aag, face_hashes, axis_loc, axis_dir)
    return max_t - min_t


def _collect_records(aag):
    """Scan concave smooth patches into cylinder/cone records + pocket candidates."""
    records = []
    pocket_candidates = []

    for group in nx.connected_components(aag.C2_faces):
        representative = next(iter(group))
        if aag.C2_faces.nodes[representative]["convexity"] != FaceTypes.CONCAVE:
            continue

        kind, radius, axis_loc, axis_dir, semi_angle = "OTHER", None, None, None, None
        for face_hash in group:
            surface = _surface(aag.C0_faces.nodes[face_hash]["shape"])
            if surface[0] in ("CYL", "CONE"):
                kind, radius, axis_loc, axis_dir, semi_angle = surface
                break

        loop_count, caps, _neighbors = _group_loops(aag, group)
        record = SimpleNamespace(
            faces=set(group), kind=kind, radius=radius,
            axis_loc=axis_loc, axis_dir=axis_dir, semi_angle=semi_angle,
            loop_count=loop_count, caps=caps,
        )

        if kind == "OTHER":
            pocket_candidates.append(record)
            continue

        # Single-loop concave cylinders (threads, fillets, lead-ins) are the
        # noisy tail; drop them. Cones (countersink / drill-point entries) are
        # kept regardless of loop count so they can fold into a coaxial
        # cylinder stack and yield a COUNTERSINK.
        if kind == "CYL" and loop_count != 2:
            continue

        records.append(record)

    return records, pocket_candidates


def _coaxial(aag, stack, record):
    """:return: True when record shares stack's axis and axially overlaps it."""
    if abs(stack.axis_dir.Dot(record.axis_dir)) < AXIS_ANGLE_TOL:
        return False

    distance = gp_Vec(stack.axis_loc, record.axis_loc).Crossed(gp_Vec(stack.axis_dir)).Magnitude()
    if distance > AXIS_DIST_TOL:
        return False

    stack_min, stack_max = _axial_span(aag, stack.faces, stack.axis_loc, stack.axis_dir)
    record_min, record_max = _axial_span(aag, record.faces, stack.axis_loc, stack.axis_dir)
    if record_min > stack_max + AXIS_DIST_TOL or stack_min > record_max + AXIS_DIST_TOL:
        return False

    return True


def _merge_coaxial(aag, records):
    """Union coaxial cylinder/cone records into stacks."""
    stacks = []

    for record in records:
        placed = False
        for stack in stacks:
            if _coaxial(aag, stack, record):
                stack.faces |= record.faces
                stack.members.append(record)
                placed = True
                break

        if not placed:
            stacks.append(SimpleNamespace(
                faces=set(record.faces), members=[record],
                axis_loc=record.axis_loc, axis_dir=record.axis_dir,
            ))

    return stacks


def _classify_stack(aag, stack):
    """:return: a dimensioned hole Feature for the stack, or None if unclassified."""
    cyls = [m for m in stack.members if m.kind == "CYL"]
    cones = [m for m in stack.members if m.kind == "CONE"]
    radii = sorted({round(m.radius, 4) for m in cyls})

    feature_type = None
    if cones and cyls:
        feature_type = Feature.FeatureTypes.COUNTERSINK

    elif len(radii) >= 2:
        feature_type = Feature.FeatureTypes.COUNTERBORE

    elif len(cyls) == 1:
        cap_count = sum(1 for cap in cyls[0].caps if cap)
        if cap_count >= 2:
            feature_type = Feature.FeatureTypes.THROUGH_HOLE
        elif cap_count == 1:
            feature_type = Feature.FeatureTypes.BLIND_HOLE

    if feature_type is None:
        return None

    feature = Feature(feature_type=feature_type, component=list(stack.faces))
    feature.diameter = 2 * min(m.radius for m in cyls)
    feature.axis = [stack.axis_dir.X(), stack.axis_dir.Y(), stack.axis_dir.Z()]
    feature.depth = _axial_extent(aag, stack.faces, stack.axis_loc, stack.axis_dir)

    if feature_type == Feature.FeatureTypes.COUNTERBORE:
        feature.counterbore_diameter = 2 * max(m.radius for m in cyls)

    if feature_type == Feature.FeatureTypes.COUNTERSINK:
        feature.angle = cones[0].semi_angle

    return feature


def _mean_normal(aag, face_hashes):
    """:return: unit gp_Dir of the group's mean face normal, or None if degenerate."""
    accumulator = gp_Vec(0.0, 0.0, 0.0)
    for face_hash in face_hashes:
        try:
            accumulator.Add(face_normal(aag.C0_faces.nodes[face_hash]["shape"]))
        except Exception:
            continue

    if accumulator.Magnitude() >= TOLLERANCE:
        return gp_Dir(accumulator)

    # Normals cancelled out; fall back to any single defined face normal.
    for face_hash in face_hashes:
        try:
            return gp_Dir(face_normal(aag.C0_faces.nodes[face_hash]["shape"]))
        except Exception:
            continue

    return None


def _first_point(aag, face_hashes):
    """:return: an arbitrary vertex point of the group, or None."""
    for face_hash in face_hashes:
        face = aag.C0_faces.nodes[face_hash]["shape"]
        for edge, is_first, is_reversed in face_edges(face):
            return first_edge_point(edge)
    return None


def _pocket_features(aag, pocket_candidates):
    """Best-effort POCKET emission for closed freeform-concave groups."""
    features = []

    for record in pocket_candidates:
        if record.loop_count < 1 or not record.caps or any(record.caps):
            continue

        axis_dir = _mean_normal(aag, record.faces)
        axis_loc = _first_point(aag, record.faces)
        if axis_dir is None or axis_loc is None:
            continue

        feature = Feature(feature_type=Feature.FeatureTypes.POCKET, component=list(record.faces))
        feature.depth = _axial_extent(aag, record.faces, axis_loc, axis_dir)
        features.append(feature)

    return features


def recognize_cavities(aag):
    """:return: list of machining-feature Features (holes family + best-effort pockets)."""
    records, pocket_candidates = _collect_records(aag)
    stacks = _merge_coaxial(aag, records)

    features = []
    for stack in stacks:
        feature = _classify_stack(aag, stack)
        if feature is not None:
            features.append(feature)

    features.extend(_pocket_features(aag, pocket_candidates))

    return features
