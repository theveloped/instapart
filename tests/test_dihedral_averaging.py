"""Behavioral proof of dual-endpoint dihedral averaging in AdjacencyGraph.build_graphs.

On a part with tapered joints the dihedral varies along a shared edge, so single-point
and averaged sampling disagree. This asserts the production graph stores the averaged
value. Fails on the pre-port single-point code, passes after the port. Needs the
instapart3 env (OCC + pyclipper).
"""

import math
from pathlib import Path

import pytest

pytest.importorskip("OCC")
pytest.importorskip("pyclipper")

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = REPO_ROOT / "examples/parts/SmartPart_35.stp"
DIVERGENCE = 1.0 * math.pi / 180.0  # 1 degree: selects genuinely tapered edges


def _single_point_angle(other_face, face, edge):
    from flatten import calculating_normal_on_edge, edge_tangent
    normal_a = calculating_normal_on_edge(other_face, edge)
    normal_b = calculating_normal_on_edge(face, edge)
    return normal_b.AngleWithRef(normal_a, edge_tangent(edge))


def _averaged_angle(other_face, face, edge):
    from flatten import calculating_normals_on_edge, edge_tangents
    first_a, last_a = calculating_normals_on_edge(other_face, edge)
    first_b, last_b = calculating_normals_on_edge(face, edge)
    first_t, last_t = edge_tangents(edge)
    return (first_b.AngleWithRef(first_a, first_t)
            + last_b.AngleWithRef(last_a, last_t)) / 2.0


def test_build_graphs_stores_averaged_dihedral():
    from flatten import AdjacencyGraph, get_largest_solid
    from utils import import_step

    assert FIXTURE.exists(), "missing fixture %s" % FIXTURE
    graph = AdjacencyGraph(get_largest_solid(import_step(str(FIXTURE))))
    graph.full()

    diverging = 0
    stored_is_averaged = 0
    for u, v, data in graph.C0_faces.edges(data=True):
        continuity = data.get("continuity")
        if continuity is None or abs(continuity) >= 1:
            continue  # smooth edge: angle is 0 by construction
        other_face = graph.C0_faces.nodes[u]["shape"]
        face = graph.C0_faces.nodes[v]["shape"]
        edge = data["shape"]
        single = _single_point_angle(other_face, face, edge)
        averaged = _averaged_angle(other_face, face, edge)
        if abs(single - averaged) <= DIVERGENCE:
            continue
        diverging += 1
        stored = abs(data["angle"])
        # magnitude comparison is invariant to face-pair iteration order
        if abs(stored - abs(averaged)) < abs(stored - abs(single)):
            stored_is_averaged += 1

    assert diverging >= 5, (
        "fixture no longer exposes tapered joints (%d diverging edges); "
        "pick another part with a verified single-vs-averaged split" % diverging)
    assert stored_is_averaged == diverging, (
        "build_graphs stored the single-point dihedral on %d/%d tapered edges; "
        "averaging port not applied" % (diverging - stored_is_averaged, diverging))
