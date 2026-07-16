"""Tests for STEP attribute extraction (face colors, names, semantic PMI).

Requires the instapart3 env (OCC). Fixtures live in examples/colors/ and
examples/pmi/; tests that need a missing fixture are skipped.
"""

import json
import os

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COLOR_FIXTURE = os.path.join(REPO_ROOT, "examples", "colors", "colored_box.step")
PMI_FIXTURE = os.path.join(REPO_ROOT, "examples", "pmi", "pmi_box.step")
PLAIN_FIXTURE = os.path.join(REPO_ROOT, "examples", "parts", "SmartPart_01.stp")

RED = (1.0, 0.0, 0.0)
GREEN = (0.0, 1.0, 0.0)

needs_color_fixture = pytest.mark.skipif(
    not os.path.isfile(COLOR_FIXTURE), reason="color fixture missing")
needs_pmi_fixture = pytest.mark.skipif(
    not os.path.isfile(PMI_FIXTURE), reason="pmi fixture missing")
needs_plain_fixture = pytest.mark.skipif(
    not os.path.isfile(PLAIN_FIXTURE), reason="example part missing")


def build_tree(path, extract_attributes=True):
    from explode import TreeBuilder

    builder = TreeBuilder(path, extract_attributes=extract_attributes)
    tree = builder.compute(root=os.path.basename(path))
    builder.extract_attributes_tree(tree)
    return builder, tree


def reference_parts(tree):
    from utils import iterate_shape_parts

    return [p for p in iterate_shape_parts(tree) if p.index == p.reference]


@needs_color_fixture
def test_face_hash_bridge_matches_transformed_faces():
    """face_hash_by_id must key the faces of the *transformed* shape the
    pipeline works on, in TopExp.MapShapes order."""
    from OCC.Core.TopAbs import TopAbs_FACE
    from OCC.Core.TopExp import topexp
    from OCC.Core.TopTools import TopTools_IndexedMapOfShape
    from utils import shape_hash

    _, tree = build_tree(COLOR_FIXTURE)
    part = reference_parts(tree)[0]

    face_map = TopTools_IndexedMapOfShape()
    topexp.MapShapes(part.shapes[0], TopAbs_FACE, face_map)

    assert len(part.face_hash_by_id) == face_map.Size() == 6
    for face_id in range(1, face_map.Size() + 1):
        assert part.face_hash_by_id[face_id] == shape_hash(face_map.FindKey(face_id))


@needs_color_fixture
def test_colors_and_names_extracted():
    _, tree = build_tree(COLOR_FIXTURE)
    part = reference_parts(tree)[0]

    attributes = part.face_attributes
    assert set(attributes.keys()) == {1, 3}

    assert attributes[1].color == pytest.approx(RED)
    assert attributes[1].name == "LASER_FACE"
    assert attributes[3].color == pytest.approx(GREEN)
    assert attributes[3].name is None


@needs_plain_fixture
def test_plain_file_yields_no_face_attributes():
    """A typical export: a part-level display color, but no per-face colors
    and only placeholder ('NONE') face names — none of which should produce
    face attribute entries."""
    _, tree = build_tree(PLAIN_FIXTURE)
    for part in reference_parts(tree):
        assert part.color is None or len(part.color) == 3
        assert part.face_attributes == {}


@needs_color_fixture
def test_flag_off_extracts_nothing():
    builder, tree = build_tree(COLOR_FIXTURE, extract_attributes=False)
    assert builder.color_tool is None
    for part in reference_parts(tree):
        assert part.face_attributes is None
        assert part.face_hash_by_id is None


@needs_color_fixture
def test_auto_pipeline_exports_face_attributes(tmp_path):
    import auto
    from utils import StageTimer

    timings = StageTimer(progress_path=str(tmp_path / "progress.json"))
    auto.main(COLOR_FIXTURE, str(tmp_path), extract_attributes=True,
              export_names={}, timings=timings)

    assert "attributes" in timings.times

    with open(tmp_path / "colored_box.json", encoding="utf-8") as fh:
        job = json.load(fh)

    shapes = job["tree"]["shapes"]
    assert len(shapes) == 1
    faces = shapes[0]["faces"]
    assert [f["face_id"] for f in faces] == [1, 3]

    by_id = {f["face_id"]: f for f in faces}
    assert by_id[1]["color"] == pytest.approx(RED)
    assert by_id[1]["name"] == "LASER_FACE"
    assert by_id[3]["color"] == pytest.approx(GREEN)


@needs_color_fixture
def test_auto_pipeline_flag_off_is_neutral(tmp_path):
    import auto
    from utils import StageTimer

    timings = StageTimer(progress_path=str(tmp_path / "progress.json"))
    auto.main(COLOR_FIXTURE, str(tmp_path), export_names={}, timings=timings)

    assert "attributes" not in timings.times

    with open(tmp_path / "colored_box.json", encoding="utf-8") as fh:
        job = json.load(fh)

    shape = job["tree"]["shapes"][0]
    assert shape["faces"] is None
    assert shape.get("pmi") is None
    assert job["tree"]["color"] is None


@needs_pmi_fixture
def test_pmi_dimension_extracted():
    """The AP242 fixture carries one semantic linear-distance dimension
    (20.0 +0.1/-0.05) between face 1 and face 2."""
    _, tree = build_tree(PMI_FIXTURE)
    part = reference_parts(tree)[0]

    assert part.pmi is not None
    assert len(part.pmi.dimensions) == 1
    assert not part.pmi.tolerances and not part.pmi.datums

    dimension = part.pmi.dimensions[0]
    assert dimension.type == "Location_LinearDistance"
    assert dimension.value == pytest.approx(20.0)
    assert dimension.upper_tolerance == pytest.approx(0.1)
    # OCCT returns the lower tolerance as a magnitude after the STEP roundtrip
    assert abs(dimension.lower_tolerance) == pytest.approx(0.05)
    assert dimension.face_ids == [1]
    assert dimension.secondary_face_ids == [2]
    assert dimension.part_index == part.reference

    # both annotated faces are tagged with the dimension's PMI id
    assert part.face_attributes[1].pmi_refs == [dimension.id]
    assert part.face_attributes[2].pmi_refs == [dimension.id]


@needs_pmi_fixture
def test_pmi_exported_to_json(tmp_path):
    import auto

    auto.main(PMI_FIXTURE, str(tmp_path), extract_attributes=True, export_names={})

    with open(tmp_path / "pmi_box.json", encoding="utf-8") as fh:
        job = json.load(fh)

    shape = job["tree"]["shapes"][0]
    assert shape["pmi"]["dimensions"], "dimension missing from JSON"
    dimension = shape["pmi"]["dimensions"][0]
    assert dimension["value"] == pytest.approx(20.0)
    assert dimension["face_ids"] == [1]
    assert dimension["secondary_face_ids"] == [2]

    face_ids_with_pmi = [f["face_id"] for f in shape["faces"] if f["pmi_refs"]]
    assert face_ids_with_pmi == [1, 2]

    # cross reference: pmi_refs point at the exported dimension id
    assert shape["faces"][0]["pmi_refs"] == [dimension["id"]]


@needs_pmi_fixture
def test_gdt_transfer_crash_degrades_gracefully(monkeypatch, tmp_path):
    """The known OCCT GD&T-transfer crash must fall back to a PMI-less read:
    geometry and colors intact, pmi_degraded flagged, message 010 in JSON."""
    import auto
    from OCC.Core.STEPCAFControl import STEPCAFControl_Reader

    original = STEPCAFControl_Reader.Transfer
    calls = {"count": 0}

    def flaky_transfer(self, *args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("gp_Dir::CrossCross() - result vector has zero norm")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(STEPCAFControl_Reader, "Transfer", flaky_transfer)

    auto.main(PMI_FIXTURE, str(tmp_path), extract_attributes=True, export_names={})

    assert calls["count"] == 2, "expected a retry without GD&T"

    with open(tmp_path / "pmi_box.json", encoding="utf-8") as fh:
        job = json.load(fh)

    assert any(m["code"] == 10 for m in job["messages"])
    shape = job["tree"]["shapes"][0]
    assert shape["pmi"] is None
    # geometry survived the fallback
    assert shape["volume"] == pytest.approx(20.0 * 30.0 * 40.0, rel=1e-3)


@needs_color_fixture
def test_aag_nodes_carry_attributes():
    from flatten import AdjacencyGraph
    from utils import get_shape_solids, part_compound_shape

    _, tree = build_tree(COLOR_FIXTURE)
    part = reference_parts(tree)[0]

    solid = next(iter(get_shape_solids(part_compound_shape(part), sort=True)))
    aag = AdjacencyGraph(solid)
    aag.full()

    attributes_by_hash = {
        part.face_hash_by_id[face_id]: attrs
        for face_id, attrs in part.face_attributes.items()
    }
    matched = aag.set_face_attributes(attributes_by_hash)

    assert sorted(a.face_id for a in matched) == [1, 3]
    tagged = [h for h, data in aag.C0_faces.nodes(data=True) if data.get("attributes")]
    assert len(tagged) == 2
