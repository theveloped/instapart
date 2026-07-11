"""Harness self-tests: pure geometry + committed golden files. No OCC needed."""

import json
import math
from pathlib import Path

import pytest

from benchmarks import golden as golden_mod
from benchmarks import manifest as manifest_mod
from benchmarks import metrics

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_JSON = REPO_ROOT / "examples/parts/SmartPart_01/SmartPart_01.json"
GOLDEN_DXF = REPO_ROOT / "examples/parts/SmartPart_01/301595.dxf"
GOLDEN_3DHUBS = REPO_ROOT / "examples/3dhubs/flat_with_curves_1/flat_with_curves_1.json"


# ---------------------------------------------------------------------------
# Bulge / path math on constructed shapes with known answers
# ---------------------------------------------------------------------------

class TestPathMath:
    def test_unit_square_area(self):
        square = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]
        assert metrics.path_signed_area(square) == pytest.approx(1.0)
        assert metrics.path_perimeter(square) == pytest.approx(4.0)

    def test_clockwise_square_is_negative(self):
        square = [[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]
        assert metrics.path_signed_area(square) == pytest.approx(-1.0)

    def test_full_circle_from_two_semicircle_bulges(self):
        # two semicircle segments (bulge=1) approximating a circle radius 1
        circle = [[-1, 0, 1.0], [1, 0, 1.0], [-1, 0]]
        assert metrics.path_signed_area(circle) == pytest.approx(math.pi, rel=1e-9)
        assert metrics.path_perimeter(circle) == pytest.approx(2 * math.pi, rel=1e-9)

    def test_quarter_arc_segment_area(self):
        # square with one corner replaced by a quarter-round (r=1, bulge=tan(22.5deg))
        bulge = math.tan(math.pi / 8)
        path = [[1, 0, bulge], [0, 1], [-1, 1], [-1, -1], [1, -1], [1, 0]]
        # area = 2x2 square minus corner square 1x1 plus quarter circle
        expected = 4.0 - 1.0 + math.pi / 4.0
        assert metrics.path_signed_area(path) == pytest.approx(expected, rel=1e-9)

    def test_bbox_includes_arc_extreme(self):
        # positive bulge = CCW: the arc from (-1,0) to (1,0) passes through (0,-1)
        path = [[-1, 0, 1.0], [1, 0]]
        bbox = metrics.path_bbox(path)
        assert bbox[1] == pytest.approx(-1.0, abs=1e-9)  # arc bottom at y=-1
        assert bbox[3] == pytest.approx(0.0, abs=1e-9)

    def test_closed_detection(self):
        assert metrics.path_is_closed([[0, 0], [1, 0], [1, 1], [0, 0]])
        assert not metrics.path_is_closed([[0, 0], [1, 0], [1, 1]])


# ---------------------------------------------------------------------------
# JSON pattern metrics against the committed golden JSON
# ---------------------------------------------------------------------------

class TestGoldenJson:
    @pytest.fixture(scope="class")
    def job(self):
        return metrics.load_json(str(GOLDEN_JSON))

    @pytest.fixture(scope="class")
    def pattern(self, job):
        return job["tree"]["shapes"][0]["pattern"]

    def test_contour_closed(self, pattern):
        assert metrics.path_is_closed(pattern["contour"]["path"])

    def test_pattern_bbox_matches_width_height(self, pattern):
        # Legacy pattern.width/height come from the unfolded surface, which
        # extends slightly (< ~1mm per side) beyond the trimmed contour, so
        # this is a sanity band, not an exact match (verified on the golden:
        # 616.27 contour vs 617.10 pattern width).
        m = metrics.pattern_metrics(pattern)
        bbox = m["bbox"]
        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]
        dims = sorted([width, height])
        expected = sorted([pattern["width"], pattern["height"]])
        for got, want in zip(dims, expected):
            assert got <= want + 0.01, "contour exceeds pattern dims"
            assert got == pytest.approx(want, rel=0.01, abs=2.0)

    def test_volume_conservation_on_golden(self, job):
        """The flagship invariant must hold on the legacy golden output."""
        shape = job["tree"]["shapes"][0]
        m = metrics.pattern_metrics(shape["pattern"])
        flat_volume = m["flat_area"] * m["thickness"]
        rel_error = abs(shape["volume"] - flat_volume) / shape["volume"]
        assert rel_error < 0.025, "volume error %.4f" % rel_error

    def test_message_codes_extraction(self, job):
        assert metrics.message_codes(job) == set()

    def test_3dhubs_golden_has_code_3(self):
        job = metrics.load_json(str(GOLDEN_3DHUBS))
        codes = metrics.message_codes(job)
        # flat_with_curves_1 was frozen with the volume-difference warning
        assert 3 in codes

    def test_normalize_drops_volatile(self, job):
        normalized = metrics.normalize_job(job)
        assert "timestamp" not in normalized
        assert "id" not in normalized["tree"]
        first_file = normalized["tree"]["shapes"][0]["files"][0]
        assert "\\" not in first_file["path"]

    def test_self_comparison_is_clean(self, job):
        assert golden_mod.compare_job_json(job, job) == []


# ---------------------------------------------------------------------------
# DXF metrics against the committed golden DXF
# ---------------------------------------------------------------------------

class TestGoldenDxf:
    @pytest.fixture(scope="class")
    def dxf(self):
        return metrics.dxf_metrics(str(GOLDEN_DXF))

    def test_outline_and_bend_layers_present(self, dxf):
        # golden uses the legacy lowercase convention (cut/bend); match by role
        roles = {metrics.layer_role(name) for name in dxf["layers"]}
        assert "outline" in roles
        assert "bends" in roles

    def test_bend_lines_match_golden_json(self, dxf):
        job = metrics.load_json(str(GOLDEN_JSON))
        expected_bends = job["tree"]["shapes"][0]["pattern"]["bend_quantity"]
        assert len(dxf["bend_line_lengths"]) == expected_bends

    def test_dxf_area_matches_json_area(self, dxf):
        """DXF-derived flat geometry agrees with the JSON pattern (cross-artifact)."""
        job = metrics.load_json(str(GOLDEN_JSON))
        pattern = job["tree"]["shapes"][0]["pattern"]
        m = metrics.pattern_metrics(pattern)
        assert dxf["contour_area"] == pytest.approx(m["contour_area"], rel=1e-3)
        assert len(dxf["hole_areas"]) == m["hole_count"]
        assert dxf["flat_area"] == pytest.approx(m["flat_area"], rel=1e-3)

    def test_self_comparison_is_clean(self, dxf):
        assert golden_mod.compare_dxf_metrics(dxf, dxf) == []

    def test_comparison_detects_change(self, dxf):
        mutated = json.loads(json.dumps(dxf))
        mutated["contour_area"] *= 1.01
        diffs = golden_mod.compare_dxf_metrics(mutated, dxf)
        assert any("contour_area" in d for d in diffs)


# ---------------------------------------------------------------------------
# Manifest bootstrap on the real examples tree
# ---------------------------------------------------------------------------

class TestManifest:
    @pytest.fixture(scope="class")
    def data(self):
        return manifest_mod.bootstrap()

    def test_full_corpus_found(self, data):
        assert len(data["files"]) >= 120

    def test_categories_assigned(self, data):
        categories = {e["category"] for e in data["files"]}
        assert {"sheet_single", "assembly", "rolled", "tube",
                "3dhubs", "benchmark_1", "benchmark_2", "xml"} <= categories

    def test_goldens_linked(self, data):
        by_path = {e["path"]: e for e in data["files"]}
        smartpart = by_path["examples/parts/SmartPart_01.stp"]
        assert smartpart.get("golden_json", "").endswith("SmartPart_01.json")
        assert smartpart.get("golden_dxf")

    def test_rolled_thickness_parsed(self, data):
        rolled = [e for e in data["files"] if e["category"] == "rolled"]
        assert rolled
        parsed = [e for e in rolled if e.get("filename_thickness")]
        assert len(parsed) == len(rolled), "thickness parsing failed for some rolled parts"

    def test_every_category_has_smoke_member(self, data):
        smoke_categories = {e["category"] for e in data["files"] if e["smoke"]}
        all_categories = {e["category"] for e in data["files"]}
        assert smoke_categories == all_categories

    def test_roundtrip(self, data, tmp_path):
        path = tmp_path / "manifest.yaml"
        manifest_mod.save(data, path)
        loaded = manifest_mod.load(path)
        assert loaded["files"] == data["files"]


# ---------------------------------------------------------------------------
# Frozen bend-angle comparison (per-shape mirror tolerance)
# ---------------------------------------------------------------------------

class TestBendAngleCheck:
    @staticmethod
    def _shape(angles_deg):
        return {"pattern": {}, "bends": [
            {"angle": math.radians(a), "radius": 1.0, "length": 10.0} for a in angles_deg]}

    @staticmethod
    def _angle_check(entry, shapes):
        from benchmarks import invariants
        checks = invariants.check_bends(entry, shapes)
        return next(c for c in checks if c.name == "bend_angles_frozen")

    def test_single_shape_mirror_passes(self):
        entry = {"expected_bend_angles": [-90.0, -90.0]}
        assert self._angle_check(entry, [self._shape([90.0, 90.0])]).status == "pass"

    def test_per_shape_mirror_passes(self):
        # one shape of a multi-part file unfolds from the other side
        # (observed for examples/assy/EMO-72-07-200.stp on Linux)
        entry = {"expected_bend_angles": sorted([-90.0] * 6 + [45.0] * 2 + [90.0] * 4)}
        shapes = [
            self._shape([-90.0, -90.0, 45.0, 45.0]),
            self._shape([90.0, 90.0, 90.0, 90.0]),   # frozen as -90 x4
            self._shape([90.0, 90.0, 90.0, 90.0]),
        ]
        assert self._angle_check(entry, shapes).status == "pass"

    def test_wrong_angles_still_fail(self):
        entry = {"expected_bend_angles": [-90.0, -90.0]}
        assert self._angle_check(entry, [self._shape([45.0, 90.0])]).status == "fail"

    def test_large_assembly_one_shape_flipped(self):
        # one flipped 4-bend shape in a >12-shape assembly (observed for
        # examples/assy/3D-Uebersicht-7014-S2.STEP on Linux); grouping by
        # identical angle multiset keeps the search exact and tiny
        shapes = ([self._shape([90.0, 90.0])] * 20
                  + [self._shape([-90.0, -90.0])] * 8
                  + [self._shape([-95.0, 95.0])]           # flip-invariant
                  + [self._shape([90.0] * 4)])             # frozen as -90 x4
        expected = sorted([90.0] * 40 + [-90.0] * 16 + [-95.0, 95.0] + [-90.0] * 4)
        entry = {"expected_bend_angles": expected}
        assert self._angle_check(entry, shapes).status == "pass"

    def test_large_assembly_wrong_angles_still_fail(self):
        shapes = [self._shape([90.0, 90.0])] * 20 + [self._shape([45.0, 45.0])]
        expected = sorted([90.0] * 40 + [30.0, 30.0])
        entry = {"expected_bend_angles": expected}
        assert self._angle_check(entry, shapes).status == "fail"


# ---------------------------------------------------------------------------
# Golden bookkeeping: golden_metrics.json vs manifest references
# ---------------------------------------------------------------------------

class TestGoldenBookkeeping:
    def test_orphaned_golden_metrics_are_exactly_the_known_set(self):
        """flat_with_curves_1/2/3 goldens are deliberately unlinked (legacy
        goldens were failed unfolds; see manifest notes). Any other mismatch
        between golden_metrics.json and the manifest is unintended drift."""
        golden_metrics = golden_mod.load_golden_metrics()
        manifest = manifest_mod.load()
        referenced = {dxf for e in manifest["files"] for dxf in e.get("golden_dxf") or []}
        orphans = set(golden_metrics) - referenced
        assert orphans == {
            "examples/3dhubs/flat_with_curves_1/_Unsaved_.dxf",
            "examples/3dhubs/flat_with_curves_2/_Unsaved_.dxf",
            "examples/3dhubs/flat_with_curves_3/_Unsaved_.dxf",
        }
        assert referenced <= set(golden_metrics), (
            "manifest references golden DXFs missing from golden_metrics.json: %s"
            % sorted(referenced - set(golden_metrics)))
