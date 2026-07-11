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
    solids = get_shape_solids(shape, sort=True)
    return solids[0]


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
    Fold the extracted graph to the target angles: every folded panel plane
    must be parallel to a planar face of the original solid within a tight
    angular tolerance, and offset by no more than the sharp-hinge error.
    """
    solid = load_solid(path)
    graph = extract.extract_kinematic_graph(solid, source=path)

    # collect the original solid's planar face planes via the AAG traceability
    from flatten import AdjacencyGraph
    aag = AdjacencyGraph(solid)
    aag.full()
    aag.smooth()
    aag.grouped()

    theta = np.array([bend.angle_target for bend in graph.bends])
    transforms = graph.fold_transforms(theta)

    max_radius = max(bend.inner_radius for bend in graph.bends)
    offset_tolerance = 3.0 * (max_radius + graph.thickness) * (
        1 + max(_tree_depth(graph, p.id) for p in graph.panels))

    for panel in graph.panels:
        rotation = transforms[panel.id][:3, :3]
        folded_normal = rotation @ np.array([0.0, 0.0, 1.0])
        point3 = transforms[panel.id] @ np.append(
            np.append(panel.outline[0], graph.z_offset), 1.0)

        matched = False
        for face_hash in panel.face_hashes:
            node = aag.C0_faces.nodes.get(face_hash)
            if node is None or node["convexity"] != FaceTypes.PLANAR:
                continue
            surface = BRepAdaptor_Surface(node["shape"])
            if surface.GetType() != GeomAbs_Plane:
                continue
            plane = surface.Plane()
            axis = plane.Axis().Direction()
            normal = np.array([axis.X(), axis.Y(), axis.Z()])
            location = plane.Location()
            origin = np.array([location.X(), location.Y(), location.Z()])

            parallel = abs(float(np.dot(folded_normal, normal)))
            distance = abs(float(np.dot(point3[:3] - origin, normal)))
            if parallel > math.cos(math.radians(2.0)) and distance < offset_tolerance:
                matched = True
                break
        assert matched, "panel {} does not match any source plane".format(panel.id)


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
