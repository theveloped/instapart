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

from flatten import AdjacencyGraph, FaceProperties, FaceTypes, face_surface_handle, wire_edges
from pressbrake.kinematics import finalize_graph
from pressbrake.model import Bend, KinematicGraph, Panel, polygon_area, polygon_centroid

logger = logging.getLogger("pressbrake.extract")

# Mapping from the Entity.angle sign convention of flatten.extract_bend
# (angle is negated for non-CONCAVE bend faces at flatten.py:1567-1569) to
# this package's convention (positive = child subtree rotates toward the +Z
# side of the flat pattern).  Pinned empirically by the folded-vs-BREP
# integration test in tests/pressbrake/test_extract.py: with -1.0 the folded
# part comes out as the mirror image of the source solid (matching pairwise
# distances, flipped chirality); +1.0 reproduces the source handedness.
ANGLE_SIGN = 1.0

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
        direction = direction / norm

        # Virtual-corner (mold line) hinge placement: extract_bend anchors
        # the axis on the CENTER line of the bend allowance zone, but the
        # line where the two mid-planes intersect sits at
        # (r + t/2)*tan(|angle|/2) from the bend tangent, not BA/2.  Rotating
        # rigid panels about the virtual corner reproduces the folded
        # mid-PLANES exactly (validated at sub-mm scale by the thickness
        # tests); the remaining error is a small in-plane conservatism near
        # the corner.
        shift = _virtual_corner_shift(
            entity["angle"], entity["inner_radius"], thickness, k_factor)
        child_centroid = polygon_centroid(panels[child_id].outline)
        toward_child = np.array([-direction[1], direction[0]])
        if float(toward_child @ (child_centroid - start)) < 0:
            toward_child = -toward_child
        start = start + shift * toward_child

        bends.append(Bend(
            id=len(bends),
            axis_point=start,
            axis_dir=direction,
            angle_target=ANGLE_SIGN * entity["angle"],
            inner_radius=entity["inner_radius"],
            k_factor=k_factor,
            length=entity["length"],
            parent_panel=parent_id,
            child_panel=child_id,
            zone_width=abs(entity["angle"]) * (
                entity["inner_radius"] + k_factor * thickness),
            face_hashes=tuple(sorted(component)),
        ))
        bend_zones.append((parent_id, child_id, start, direction, zone_polygons))

    kinematic = KinematicGraph(
        panels=panels, bends=bends, base_panel=0, thickness=thickness,
        z_offset=_material_z_offset(
            aag, base_hash, transformations, thickness),
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

    reference = _point2(sub_entities[0].path[0])
    start = np.zeros(2)
    end = np.zeros(2)
    for entity in sub_entities:
        point_a = _point2(entity.path[0])
        point_b = _point2(entity.path[1])
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


def _material_z_offset(aag, base_hash, transformations, thickness):
    """
    Mid-surface height above the pattern plane: the unfolder flattens one
    SKIN of the sheet (the base face), so the material occupies [0, t] on
    one side of z=0.  The side is determined EMPIRICALLY by classifying
    probe points against the solid (normal-sense/orientation-flag/transform
    conventions vary between parts and proved unreliable); the winning
    world-side direction is then mapped through the base alignment
    transforms as a point pair.  Validated at thickness scale by the signed
    parallel-plane test in tests/pressbrake/test_extract.py.
    """
    from OCC.Core.BRepClass3d import BRepClass3d_SolidClassifier
    from OCC.Core.BRepGProp import brepgprop
    from OCC.Core.GProp import GProp_GProps
    from OCC.Core.gp import gp_Pnt
    from OCC.Core.TopAbs import TopAbs_IN

    base_node = aag.C1_faces.nodes[base_hash]
    base_face = base_node["shape"]
    normal = FaceProperties(face_surface_handle(base_face)).normal()
    normal.Normalize()

    properties = GProp_GProps()
    brepgprop.SurfaceProperties(base_face, properties)
    centre = properties.CentreOfMass()

    directions = FaceProperties(face_surface_handle(base_face)).directions()
    probe_offsets = [(0.0, 0.0), (5.0, 0.0), (-5.0, 0.0), (0.0, 5.0),
                     (0.0, -5.0), (10.0, 10.0), (-10.0, -10.0)]

    classifier = BRepClass3d_SolidClassifier(aag.shape)
    depth = thickness / 4.0
    material_sign = None
    for du, dv in probe_offsets:
        anchor = np.array([centre.X(), centre.Y(), centre.Z()])
        anchor = anchor + du * np.array([directions[0].X(), directions[0].Y(),
                                         directions[0].Z()])
        anchor = anchor + dv * np.array([directions[1].X(), directions[1].Y(),
                                         directions[1].Z()])
        n = np.array([normal.X(), normal.Y(), normal.Z()])
        for sign in (1.0, -1.0):
            probe = anchor + sign * depth * n
            classifier.Perform(gp_Pnt(*probe), 1e-4)
            if classifier.State() == TopAbs_IN:
                material_sign = sign
                break
        if material_sign is not None:
            anchor_world = anchor
            break
    if material_sign is None:
        raise ExtractionError("could not determine the material side of the sheet")

    # map the material direction through the base alignment transforms as a
    # point pair (no normal-transform sense ambiguity)
    inside_world = anchor_world + material_sign * depth * np.array(
        [normal.X(), normal.Y(), normal.Z()])
    points = []
    for world in (anchor_world, inside_world):
        point = gp_Pnt(*world)
        for transformation in transformations.get(base_hash, []):
            point = point.Transformed(transformation)
        points.append(np.array([point.X(), point.Y(), point.Z()]))
    dz = points[1][2] - points[0][2]
    return (thickness / 2.0) if dz > 0 else (-thickness / 2.0)


def _virtual_corner_shift(angle, inner_radius, thickness, k_factor):
    """
    Distance from the bend-zone center line to the mid-plane intersection
    line (virtual sharp corner), along the in-plane normal toward the child:
    (r + t/2) * tan(|angle|/2) - BA/2, with BA = |angle| * (r + k*t).
    Capped for near-hem angles (flagged infeasible elsewhere anyway).
    """
    theta = min(abs(angle), math.radians(150.0))
    mid_radius = inner_radius + thickness / 2.0
    allowance = theta * (inner_radius + k_factor * thickness)
    shift = mid_radius * math.tan(theta / 2.0) - allowance / 2.0
    return max(shift, 0.0)


def _point2(point):
    """
    cycad.Path wraps appended coordinates in geometry.Point objects; pull
    plain floats out regardless of representation.
    """
    return np.array([float(point[0]), float(point[1])])


def _panel_side(kinematic, panel_id, axis_point, normal):
    centroid = kinematic.panels[panel_id].centroid()
    side = float(np.dot(normal, centroid - axis_point))
    return 1.0 if side >= 0 else -1.0
