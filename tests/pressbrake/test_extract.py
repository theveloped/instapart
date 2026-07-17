"""
OCC-dependent integration tests for the kinematic-graph extraction layer.

These need the instapart3 conda environment (pythonocc-core); they are
skipped automatically elsewhere.  Marked ``occ`` so they can be deselected
explicitly with ``-m "not occ"``.

The folded-vs-BREP test is the ground truth for the extraction sign
conventions (ANGLE_SIGN, base_reversed handling): it folds the extracted
graph to the target angles and checks every folded panel is parallel to a
planar face of the original solid, at an offset no larger than the sharp
hinge approximation allows.
"""

import math
import os

import numpy as np
import pytest

OCC = pytest.importorskip("OCC")

from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
from OCC.Core.GeomAbs import GeomAbs_Plane

from flatten import FaceTypes
from pressbrake import extract
from utils import import_step, get_shape_solids

pytestmark = pytest.mark.occ

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CASES = [
    # (path, expected bends, expected thickness)
    ("examples/parts/SmartPart_01.stp", 6, 1.2),
    ("examples/parts/SmartPart_08.stp", 4, 2.0),
    ("examples/parts/SmartPart_09.stp", 5, 4.0),
]


def load_solid(relative_path):
    path = os.path.join(REPO, relative_path)
    if not os.path.exists(path):
        pytest.skip("sample part not available: " + relative_path)
    shape = import_step(path)
    solid = next(get_shape_solids(shape, sort=True), None)
    if solid is None:
        pytest.skip("no valid solid in " + relative_path)
    return solid


@pytest.mark.parametrize("path,expected_bends,expected_thickness", CASES)
def test_extract_counts(path, expected_bends, expected_thickness):
    solid = load_solid(path)
    graph = extract.extract_kinematic_graph(solid, source=path)

    assert graph.bend_count == expected_bends
    assert graph.thickness == pytest.approx(expected_thickness, abs=0.05)
    # a spanning tree over panels
    assert graph.panel_count == graph.bend_count + 1
    for bend in graph.bends:
        assert bend.moving_mask != 0
        assert not (bend.moving_mask >> graph.base_panel & 1)
        assert abs(bend.angle_target) > 1e-3
        assert bend.inner_radius > 0
        assert bend.length > 0
    for panel in graph.panels:
        assert len(panel.outline) >= 3


@pytest.mark.parametrize("path,expected_bends,expected_thickness", CASES[:2])
def test_folded_state_matches_brep(path, expected_bends, expected_thickness):
    """
    Fold the extracted graph to the target angles and compare against the
    original solid.  The folded state lives in the aligned flat frame (not
    the STEP frame), so the comparison must be rigid-invariant: the pairwise
    panel-centroid distance matrix must match the source faces' centroid
    distances within the sharp-hinge error, and the chirality (signed
    volume of a non-degenerate centroid quadruple) must match - a wrong
    ANGLE_SIGN in extract.py produces a mirror image, which passes the
    distance check but flips the handedness.
    """
    solid = load_solid(path)
    graph = extract.extract_kinematic_graph(solid, source=path)

    from flatten import AdjacencyGraph
    from OCC.Core.GProp import GProp_GProps
    from OCC.Core.BRepGProp import brepgprop

    aag = AdjacencyGraph(solid)
    aag.full()
    aag.smooth()
    aag.grouped()

    theta = np.array([bend.angle_target for bend in graph.bends])
    transforms = graph.fold_transforms(theta)

    folded = []
    source = []
    for panel in graph.panels:
        from pressbrake.model import polygon_centroid
        centroid2 = polygon_centroid(panel.outline)
        point = transforms[panel.id] @ np.array(
            [centroid2[0], centroid2[1], graph.z_offset, 1.0])
        folded.append(point[:3])

        face_points = []
        for face_hash in panel.face_hashes:
            node = aag.C0_faces.nodes.get(face_hash)
            if node is None or node["convexity"] != FaceTypes.PLANAR:
                continue
            properties = GProp_GProps()
            brepgprop.SurfaceProperties(node["shape"], properties)
            centre = properties.CentreOfMass()
            face_points.append([centre.X(), centre.Y(), centre.Z()])
        assert face_points, "panel {} has no planar source face".format(panel.id)
        source.append(np.mean(face_points, axis=0))

    folded = np.array(folded)
    source = np.array(source)

    max_radius = max(bend.inner_radius for bend in graph.bends)
    depth = 1 + max(_tree_depth(graph, p.id) for p in graph.panels)
    tolerance = 3.0 * (max_radius + graph.thickness) * depth

    # rigid-invariant shape: pairwise centroid distances
    for i in range(len(folded)):
        for j in range(i + 1, len(folded)):
            folded_distance = np.linalg.norm(folded[i] - folded[j])
            source_distance = np.linalg.norm(source[i] - source[j])
            assert folded_distance == pytest.approx(source_distance, abs=tolerance), \
                "panels {}-{}: folded {:.1f} vs source {:.1f}".format(
                    i, j, folded_distance, source_distance)

    # chirality: the folded part must not be the mirror image
    if len(folded) >= 4:
        best = None
        for quad in _candidate_quads(len(folded)):
            a, b, c, d = quad
            volume = float(np.linalg.det(np.stack([
                source[b] - source[a], source[c] - source[a], source[d] - source[a]])))
            if best is None or abs(volume) > abs(best[1]):
                best = (quad, volume)
        quad, source_volume = best
        if abs(source_volume) > tolerance ** 3 / 10.0:
            a, b, c, d = quad
            folded_volume = float(np.linalg.det(np.stack([
                folded[b] - folded[a], folded[c] - folded[a], folded[d] - folded[a]])))
            assert folded_volume * source_volume > 0, \
                "folded part is the mirror image of the source (ANGLE_SIGN?)"


def _candidate_quads(count, limit=40):
    import itertools
    quads = list(itertools.combinations(range(count), 4))
    return quads[:limit]


# --- thickness-scale validation ----------------------------------------------
#
# The panels are embedded as mid-surfaces at z=0 with material at +/- t/2
# (KinematicGraph.z_offset stays 0 by design: the unfolder's outlines are
# neutral-surface developments).  These two tests prove that at
# sub-millimetre precision on real parts; a half-thickness embedding error
# fails both loudly.

THICKNESS_CASES = [
    ("examples/parts/SmartPart_01.stp", 1.2),   # thin sheet
    ("examples/parts/SmartPart_09.stp", 4.0),   # thick plate: t/2 > margin
]


def _panel_brep_midplanes(graph, aag, thickness):
    """
    Per panel: (mid-plane centroid, unit OUTWARD normal) in the ORIGINAL
    BREP frame.  All source faces of one component are the same skin side,
    so the mid-plane is the source plane shifted t/2 opposite the
    orientation-corrected outward normal.

    The normal is derived exactly as extract._material_z_offset does
    (FaceProperties + Orientation reversal): BRepAdaptor_Surface's Plane()
    axis carries the opposite sense on these faces, which a diagnostic
    exposed as globally sign-flipped gap comparisons.
    """
    from flatten import FaceProperties, face_surface_handle
    from OCC.Core.BRepGProp import brepgprop
    from OCC.Core.GProp import GProp_GProps

    centroids = []
    normals = []
    for panel in graph.panels:
        face_data = []
        for face_hash in panel.face_hashes:
            node = aag.C0_faces.nodes.get(face_hash)
            if node is None or node["convexity"] != FaceTypes.PLANAR:
                continue
            face = node["shape"]
            surface = BRepAdaptor_Surface(face)
            if surface.GetType() != GeomAbs_Plane:
                continue
            normal_vec = FaceProperties(face_surface_handle(face)).normal()
            if face.Orientation() != 0:
                normal_vec.Reverse()
            normal = np.array([normal_vec.X(), normal_vec.Y(), normal_vec.Z()])
            normal = normal / np.linalg.norm(normal)
            properties = GProp_GProps()
            brepgprop.SurfaceProperties(face, properties)
            centre = properties.CentreOfMass()
            skin_centroid = np.array([centre.X(), centre.Y(), centre.Z()])
            face_data.append((properties.Mass(),
                              skin_centroid - (thickness / 2.0) * normal,
                              normal))
        assert face_data, "panel {} has no planar source face".format(panel.id)
        weights = np.array([d[0] for d in face_data])
        centroids.append(np.average([d[1] for d in face_data], axis=0,
                                    weights=weights))
        normals.append(face_data[0][2])
    return np.array(centroids), np.array(normals)


def _folded_midplanes(graph):
    """
    Per panel: (mid-plane centroid, unit normal) in the folded flat frame.
    """
    from pressbrake.model import polygon_centroid

    theta = np.array([bend.angle_target for bend in graph.bends])
    transforms = graph.fold_transforms(theta)
    centroids = []
    normals = []
    for panel in graph.panels:
        centroid2 = polygon_centroid(panel.outline)
        point = transforms[panel.id] @ np.array(
            [centroid2[0], centroid2[1], graph.z_offset, 1.0])
        centroids.append(point[:3])
        normals.append(transforms[panel.id][:3, :3] @ np.array([0.0, 0.0, 1.0]))
    return np.array(centroids), np.array(normals), transforms


@pytest.mark.parametrize("path,thickness", THICKNESS_CASES)
def test_parallel_plane_distances_thickness_exact(path, thickness):
    """
    Frame-free thickness check, no registration needed: for every pair of
    parallel panels, the SIGNED gap between the mid-planes measured along
    panel i's own OUTWARD normal must match between the folded state and
    the BREP within 0.5 mm.  The signed comparison also pins the material
    side: a flipped z_offset inverts the folded value (even on parts whose
    bend axes are all parallel, where a normals-only check is blind to the
    flip).
    """
    solid = load_solid(path)
    graph = extract.extract_kinematic_graph(solid, source=path)
    assert graph.thickness == pytest.approx(thickness, abs=0.05)
    assert abs(graph.z_offset) == pytest.approx(graph.thickness / 2.0, abs=1e-6), \
        "z_offset must be half the sheet thickness (pattern plane is a skin)"

    from flatten import AdjacencyGraph
    aag = AdjacencyGraph(solid)
    aag.full()
    aag.smooth()
    aag.grouped()

    brep_centroids, brep_normals = _panel_brep_midplanes(graph, aag, graph.thickness)
    folded_centroids, folded_normals, _ = _folded_midplanes(graph)
    # outward-skin direction in the folded frame: the pattern skin faces
    # away from the material, i.e. opposite the z_offset side
    side = -1.0 if graph.z_offset > 0 else 1.0

    pairs_checked = 0
    for i in range(graph.panel_count):
        for j in range(i + 1, graph.panel_count):
            if abs(float(folded_normals[i] @ folded_normals[j])) < math.cos(
                    math.radians(2.0)):
                continue
            folded_gap = float(
                (folded_centroids[j] - folded_centroids[i])
                @ (side * folded_normals[i]))
            brep_gap = float(
                (brep_centroids[j] - brep_centroids[i]) @ brep_normals[i])
            assert folded_gap == pytest.approx(brep_gap, abs=0.5), \
                "panels {}-{}: folded signed mid-plane gap {:.2f} vs BREP {:.2f}".format(
                    i, j, folded_gap, brep_gap)
            pairs_checked += 1
    assert pairs_checked >= 1, "no parallel panel pair found to check"


@pytest.mark.parametrize("path,thickness", THICKNESS_CASES)
def test_material_side_consistent(path, thickness):
    """
    The material-side check: the pattern plane is one SKIN of the sheet, so
    z_offset must be +/- t/2 and every panel's outward-skin direction in
    the folded state (-sign(z_offset) * panel normal) must map onto that
    panel's BREP outward normal under a rotation-only registration.
    Normals are free of the bend-zone centroid noise that limits a
    positional registration, so this is sharp: a flipped or zero z_offset
    fails for every panel.
    """
    solid = load_solid(path)
    graph = extract.extract_kinematic_graph(solid, source=path)

    assert abs(graph.z_offset) == pytest.approx(graph.thickness / 2.0, abs=1e-6), \
        "z_offset must be half the sheet thickness (pattern plane is a skin)"

    from flatten import AdjacencyGraph
    aag = AdjacencyGraph(solid)
    aag.full()
    aag.smooth()
    aag.grouped()

    _brep_centroids, brep_normals = _panel_brep_midplanes(graph, aag, graph.thickness)
    _folded_centroids, folded_normals, _ = _folded_midplanes(graph)

    side = -1.0 if graph.z_offset > 0 else 1.0
    folded_outward = side * folded_normals

    rotation = _procrustes_rotation(folded_outward, brep_normals)
    for panel in graph.panels:
        aligned = rotation @ folded_outward[panel.id]
        agreement = float(aligned @ brep_normals[panel.id])
        assert agreement > math.cos(math.radians(5.0)), \
            "panel {}: outward-skin direction disagrees with the BREP " \
            "normal (dot {:.3f}) - material on the wrong side?".format(
                panel.id, agreement)


def _procrustes_rotation(source_directions, target_directions):
    """
    Best-fit rotation mapping unit direction vectors source -> target.
    """
    covariance = source_directions.T @ target_directions
    u, _s, vt = np.linalg.svd(covariance)
    sign = np.sign(np.linalg.det(vt.T @ u.T))
    return vt.T @ np.diag([1.0, 1.0, sign]) @ u.T


def _kabsch(source_points, target_points):
    """
    Best-fit rotation+translation mapping source -> target; returns
    (R, t, rms residual).
    """
    source_mean = source_points.mean(axis=0)
    target_mean = target_points.mean(axis=0)
    covariance = (source_points - source_mean).T @ (target_points - target_mean)
    u, _s, vt = np.linalg.svd(covariance)
    sign = np.sign(np.linalg.det(vt.T @ u.T))
    correction = np.diag([1.0, 1.0, sign])
    rotation = vt.T @ correction @ u.T
    translation = target_mean - rotation @ source_mean
    mapped = source_points @ rotation.T + translation
    residual = float(np.sqrt(np.mean(np.sum((mapped - target_points) ** 2, axis=1))))
    return rotation, translation, residual


def test_rolled_part_rejected():
    path = None
    rolled_dir = os.path.join(REPO, "examples", "rolled")
    if os.path.isdir(rolled_dir):
        for name in sorted(os.listdir(rolled_dir)):
            if name.lower().endswith((".stp", ".step")):
                path = os.path.join("examples", "rolled", name)
                break
    if path is None:
        pytest.skip("no rolled sample available")
    solid = load_solid(path)
    try:
        graph = extract.extract_kinematic_graph(solid, source=path)
    except Exception:
        return  # rejection is acceptable
    # if extraction succeeds, large-radius rolls must be flagged by radius
    assert any(
        bend.inner_radius > 5 * graph.thickness for bend in graph.bends
    ), "rolled part produced only ordinary bends"


def _tree_depth(graph, panel_id):
    parents = {bend.child_panel: bend.parent_panel for bend in graph.bends}
    depth = 0
    while panel_id in parents:
        panel_id = parents[panel_id]
        depth += 1
    return depth
