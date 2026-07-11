"""
Harvest a press-brake kinematic graph from the unfolder's AdjacencyGraph.

This is the only planning module that touches OpenCASCADE.  It re-drives the
same public methods the flatten pipeline uses (``full/smooth/grouped``,
``get_sheet_base``, ``get_connected_subgraph``, ``unfold_graph``,
``extract_bend``) and reifies the fold tree that ``unfold_graph`` computes
implicitly (its BFS) before that information is discarded.

Everything happens once per part; the resulting ``KinematicGraph`` is pure
numpy and feeds the whole planning loop without further BREP work.
"""

import logging
import math

import networkx as nx
import numpy as np

from OCC.Core.BRep import BRep_Tool
from OCC.Core.BRepAdaptor import BRepAdaptor_Curve
from OCC.Core.GCPnts import GCPnts_QuasiUniformDeflection
from OCC.Core.TopAbs import TopAbs_WIRE
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopoDS import topods

from flatten import AdjacencyGraph, FaceTypes, wire_edges
from pressbrake.kinematics import finalize_graph
from pressbrake.model import Bend, KinematicGraph, Panel, polygon_area

logger = logging.getLogger("pressbrake.extract")

# Mapping from the Entity.angle sign convention of flatten.extract_bend
# (angle is negated for non-CONCAVE bend faces at flatten.py:1567-1569) to
# this package's convention (positive = child subtree rotates toward the +Z
# side of the flat pattern).  Pinned empirically by the folded-vs-BREP
# integration test in tests/pressbrake/test_extract.py.
ANGLE_SIGN = -1.0

CHAIN_TOLERANCE = 1e-3


class ExtractionError(Exception):
    pass


def extract_kinematic_graph(solid, k_factor=0.5, min_thickness=1e-3,
                            deflection=0.05, merge_bend_zones=True, source=""):
    """
    Full pipeline: build the AAG, unfold, and reify the kinematic graph.
    """
    aag = AdjacencyGraph(solid)
    aag.full()
    aag.smooth()
    aag.grouped()

    base_hash, _second_hash, thickness = aag.get_sheet_base(min_thickness=min_thickness)
    graph = aag.get_connected_subgraph(base_hash, ignore_complex=True)
    surface_handle, transformations, base_reversed = aag.unfold_graph(
        graph, thickness, base_hash=base_hash, align=True, k_factor=k_factor)

    return build_from_unfold(
        aag, graph, base_hash, surface_handle, transformations, base_reversed,
        thickness, k_factor=k_factor, deflection=deflection,
        merge_bend_zones=merge_bend_zones, source=source)


def build_from_unfold(aag, graph, base_hash, surface_handle, transformations,
                      base_reversed, thickness, k_factor=0.5, deflection=0.05,
                      merge_bend_zones=True, source=""):
    """
    Build a KinematicGraph from an already-unfolded AAG (so callers that ran
    the flatten pipeline themselves can reuse its results).
    """
    planar_hashes = {
        h for h in graph.nodes()
        if graph.nodes[h]["convexity"] == FaceTypes.PLANAR
    }
    if base_hash not in planar_hashes:
        raise ExtractionError("base face is not planar")

    # --- group coplanar flange faces connected by smooth planar-planar edges
    panel_graph = graph.subgraph(planar_hashes)
    panel_groups = [frozenset(c) for c in nx.connected_components(panel_graph)]
    group_of_face = {h: g for g in panel_groups for h in g}

    # --- group chained bend faces via the C2 graph (same logic as
    #     flatten.extract_bends)
    bend_components = []
    seen = set()
    for node_hash in graph.nodes():
        if node_hash in planar_hashes or node_hash in seen:
            continue
        if node_hash in aag.C2_faces:
            component = frozenset(
                h for h in nx.node_connected_component(aag.C2_faces, node_hash)
                if h in graph
            )
        else:
            component = frozenset([node_hash])
        seen |= component
        bend_components.append(component)

    # --- fold tree: BFS depth of every face, as unfold_graph traverses it
    depth = {base_hash: 0}
    for predecessor, successors in nx.bfs_successors(graph, source=base_hash):
        for successor in successors:
            depth[successor] = depth[predecessor] + 1

    # --- panels
    panels = []
    panel_index = {}
    base_group = group_of_face[base_hash]
    ordered_groups = sorted(
        panel_groups,
        key=lambda g: (g != base_group, min(depth.get(h, 1 << 30) for h in g)),
    )
    for group in ordered_groups:
        outline, holes = _group_polygon(
            aag, graph, group, surface_handle, transformations, thickness,
            k_factor, deflection)
        panel = Panel(
            id=len(panels), outline=outline, holes=holes,
            face_hashes=tuple(sorted(group)),
        )
        panels.append(panel)
        panel_index[group] = panel.id

    # --- bends
    bends = []
    bend_zones = []
    for component in bend_components:
        neighbor_groups = set()
        for face_hash in component:
            for neighbor in graph.neighbors(face_hash):
                if neighbor in group_of_face:
                    neighbor_groups.add(group_of_face[neighbor])
        if len(neighbor_groups) != 2:
            raise ExtractionError(
                "bend component connects {} panels (expected 2)".format(
                    len(neighbor_groups)))

        group_a, group_b = sorted(
            neighbor_groups, key=lambda g: min(depth.get(h, 1 << 30) for h in g))
        parent_id = panel_index[group_a]
        child_id = panel_index[group_b]

        entity, zone_polygons = _merged_bend_entity(
            aag, graph, component, surface_handle, transformations, thickness,
            k_factor, deflection)

        start = np.array(entity["start"])
        end = np.array(entity["end"])
        direction = end - start
        norm = np.linalg.norm(direction)
        if norm < CHAIN_TOLERANCE:
            raise ExtractionError("degenerate bend axis")

        bends.append(Bend(
            id=len(bends),
            axis_point=start,
            axis_dir=direction / norm,
            angle_target=ANGLE_SIGN * entity["angle"],
            inner_radius=entity["inner_radius"],
            k_factor=k_factor,
            length=entity["length"],
            parent_panel=parent_id,
            child_panel=child_id,
            face_hashes=tuple(sorted(component)),
        ))
        bend_zones.append((parent_id, child_id, start, direction / norm, zone_polygons))

    kinematic = KinematicGraph(
        panels=panels, bends=bends, base_panel=0, thickness=thickness,
        source=source,
    )

    if merge_bend_zones:
        _merge_bend_zones(kinematic, bend_zones)

    finalize_graph(kinematic)
    logger.info(
        "extracted kinematic graph: %d panels, %d bends, thickness %.2f",
        kinematic.panel_count, kinematic.bend_count, thickness)
    return kinematic


# --- geometry harvesting ----------------------------------------------------


def _group_polygon(aag, graph, group, surface_handle, transformations,
                   thickness, k_factor, deflection):
    """
    Flattened outline + holes of a panel group.  Each face's wires are
    discretized from the transformed (unfolded) edges; coplanar face groups
    with more than one face are unioned with shapely.
    """
    outlines = []
    for face_hash in group:
        node = graph.nodes[face_hash]
        loops = _face_loops(
            aag, node, face_hash, surface_handle, transformations, thickness,
            k_factor, deflection)
        outlines.append(loops)

    if len(outlines) == 1:
        return _orient_loops(outlines[0])

    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    polygons = []
    for loops in outlines:
        outer, holes = _orient_loops(loops)
        polygons.append(Polygon(outer, holes))
    merged = unary_union(polygons)
    merged = merged.buffer(0)
    if merged.geom_type == "MultiPolygon":
        logger.warning("coplanar panel group did not merge cleanly; keeping largest piece")
        merged = max(merged.geoms, key=lambda g: g.area)
    outline = np.asarray(merged.exterior.coords[:-1], dtype=float)
    holes = [np.asarray(ring.coords[:-1], dtype=float) for ring in merged.interiors]
    return _orient_loops([outline] + holes)


def _face_loops(aag, node, face_hash, surface_handle, transformations,
                thickness, k_factor, deflection):
    """
    All closed loops (outer + holes, unclassified) of one face after
    unfolding, as (N,2) arrays.
    """
    face = node["shape"]
    scale = aag.node_scale(node, thickness, k_factor=k_factor)
    face_transforms = transformations[face_hash]

    loops = []
    wire_explorer = TopExp_Explorer(face, TopAbs_WIRE)
    while wire_explorer.More():
        wire = topods.Wire(wire_explorer.Current())
        polylines = []
        for edge, _is_first, _is_reversed in wire_edges(wire, ignore_orientation=True):
            flat_edge = aag.transformed_edge(
                edge, face, surface_handle, scale=scale,
                transformations=face_transforms)
            points = _discretize_edge(flat_edge, deflection)
            if len(points) >= 2:
                polylines.append(points)
        loop = _chain_polylines(polylines)
        if loop is not None and len(loop) >= 3:
            loops.append(loop)
        wire_explorer.Next()

    if not loops:
        raise ExtractionError("face produced no closed loops")
    return loops


def _discretize_edge(edge, deflection):
    adaptor = BRepAdaptor_Curve(edge)
    discretizer = GCPnts_QuasiUniformDeflection(adaptor, deflection)
    if not discretizer.IsDone():
        first = adaptor.Value(adaptor.FirstParameter())
        last = adaptor.Value(adaptor.LastParameter())
        return np.array([[first.X(), first.Y()], [last.X(), last.Y()]])
    points = np.array([
        [adaptor.Value(discretizer.Parameter(i + 1)).X(),
         adaptor.Value(discretizer.Parameter(i + 1)).Y()]
        for i in range(discretizer.NbPoints())
    ])
    return points


def _chain_polylines(polylines, tolerance=CHAIN_TOLERANCE):
    """
    Chain unordered, arbitrarily oriented polylines into one closed loop.
    """
    if not polylines:
        return None
    remaining = [np.asarray(p) for p in polylines]
    chain = list(remaining.pop(0))
    while remaining:
        tail = chain[-1]
        best = None
        for index, polyline in enumerate(remaining):
            if np.linalg.norm(polyline[0] - tail) < tolerance:
                best = (index, polyline[1:])
                break
            if np.linalg.norm(polyline[-1] - tail) < tolerance:
                best = (index, polyline[::-1][1:])
                break
        if best is None:
            logger.debug("open loop while chaining wire edges")
            return None
        index, points = best
        remaining.pop(index)
        chain.extend(points)
    # drop the closing duplicate
    if np.linalg.norm(np.asarray(chain[0]) - np.asarray(chain[-1])) < tolerance:
        chain = chain[:-1]
    return np.asarray(chain, dtype=float)


def _orient_loops(loops):
    """
    Split loops into (outer CCW, holes CW) by absolute area.
    """
    areas = [abs(polygon_area(loop)) for loop in loops]
    outer_index = int(np.argmax(areas))
    outer = loops[outer_index]
    if polygon_area(outer) < 0:
        outer = outer[::-1]
    holes = []
    for index, loop in enumerate(loops):
        if index == outer_index:
            continue
        if polygon_area(loop) > 0:
            loop = loop[::-1]
        holes.append(loop)
    return np.asarray(outer, dtype=float), holes


def _merged_bend_entity(aag, graph, component, surface_handle, transformations,
                        thickness, k_factor, deflection):
    """
    Bend axis/angle/radius for a (possibly multi-face) bend component,
    mirroring flatten.extract_bends' C2 merge, plus the flattened bend-zone
    outlines for the panel merge step.
    """
    sub_entities = []
    zone_polygons = []
    for face_hash in component:
        node = graph.nodes[face_hash]
        entity = aag.extract_bend(
            node, face_hash, surface_handle, thickness,
            transformations=transformations, k_factor=k_factor)
        sub_entities.append(entity)
        try:
            loops = _face_loops(
                aag, node, face_hash, surface_handle, transformations,
                thickness, k_factor, deflection)
            zone_polygons.append(_orient_loops(loops)[0])
        except ExtractionError:
            pass

    total_angle = sum(entity.angle for entity in sub_entities)
    if abs(total_angle) < 1e-9:
        raise ExtractionError("bend component has zero total angle")

    reference = np.array(sub_entities[0].path[0], dtype=float)
    start = np.zeros(2)
    end = np.zeros(2)
    for entity in sub_entities:
        point_a = np.array(entity.path[0], dtype=float)
        point_b = np.array(entity.path[1], dtype=float)
        if np.linalg.norm(reference - point_a) > np.linalg.norm(reference - point_b):
            point_a, point_b = point_b, point_a
        weight = entity.angle / total_angle
        start += weight * point_a
        end += weight * point_b

    length = max(entity.length for entity in sub_entities)
    return {
        "start": start,
        "end": end,
        "angle": total_angle,
        "inner_radius": sub_entities[-1].inner_radius,
        "length": length,
    }, zone_polygons


def _merge_bend_zones(kinematic, bend_zones):
    """
    Split each flattened bend-zone region at the bend axis and union each
    half into the adjacent panel outline, so panels tile the full flat
    pattern with no material gap at hinges.
    """
    from shapely.geometry import LineString, Polygon
    from shapely.ops import split as shapely_split, unary_union

    additions = {}
    for parent_id, child_id, axis_point, axis_dir, zone_polygons in bend_zones:
        for zone in zone_polygons:
            polygon = Polygon(zone)
            if not polygon.is_valid:
                polygon = polygon.buffer(0)
            if polygon.is_empty:
                continue
            bounds_diameter = math.hypot(
                polygon.bounds[2] - polygon.bounds[0],
                polygon.bounds[3] - polygon.bounds[1]) + 1.0
            line = LineString([
                axis_point - bounds_diameter * axis_dir,
                axis_point + bounds_diameter * axis_dir,
            ])
            try:
                pieces = list(shapely_split(polygon, line).geoms)
            except Exception:
                pieces = [polygon]
            normal = np.array([-axis_dir[1], axis_dir[0]])
            for piece in pieces:
                centroid = np.array([piece.centroid.x, piece.centroid.y])
                side = float(np.dot(normal, centroid - axis_point))
                child_side = _panel_side(kinematic, child_id, axis_point, normal)
                target = child_id if side * child_side > 0 else parent_id
                additions.setdefault(target, []).append(piece)

    for panel_id, pieces in additions.items():
        panel = kinematic.panels[panel_id]
        merged = unary_union(
            [Polygon(panel.outline, [h for h in panel.holes])] + pieces)
        merged = merged.buffer(0)
        if merged.geom_type == "MultiPolygon":
            merged = max(merged.geoms, key=lambda g: g.area)
        panel.outline = np.asarray(merged.exterior.coords[:-1], dtype=float)
        panel.holes = [
            np.asarray(ring.coords[:-1], dtype=float) for ring in merged.interiors
        ]


def _panel_side(kinematic, panel_id, axis_point, normal):
    centroid = kinematic.panels[panel_id].centroid()
    side = float(np.dot(normal, centroid - axis_point))
    return 1.0 if side >= 0 else -1.0
