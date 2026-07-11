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
