"""Recognizer tests for the CNC hole-family classifier (`recognize_cavities`).

OCC-dependent: needs the instapart3 conda env, so marked `smoke` (same marker
as the rest of the OCC-bound suite). Exercises the recognizer end-to-end on
three real NIST AP242 machined solids.

Characterization anchors, measured 2026-07-16 (instapart3 / OCC 7.9):
    nist_ctc_01: 11 features = 9 THROUGH_HOLE + 2 COUNTERSINK
    nist_ftc_06: 12 features = 10 COUNTERBORE + 2 COUNTERSINK
    nist_ftc_08: 20 features = 20 THROUGH_HOLE

The recall floors are lower bounds on the raw two-loop both-cap cylinder groups
per part (9 / 10 / 20). Coaxial merging only folds those cylinders into
COUNTERBORE / COUNTERSINK stacks, so THROUGH_HOLE + COUNTERBORE is a stable
lower bound and the exact split is implementation-dependent.
"""

import math
import os
from functools import lru_cache

import pytest

import utils
from flatten import AdjacencyGraph
from features import recognize_cavities
from models import Feature

pytestmark = pytest.mark.smoke

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "cnc")

FT = Feature.FeatureTypes
HOLE_TYPES = {FT.THROUGH_HOLE, FT.BLIND_HOLE, FT.COUNTERBORE, FT.COUNTERSINK, FT.POCKET}

FIXTURES = [
    "nist_ctc_01_asme1_ap242.stp",
    "nist_ftc_06_asme1_ap242.stp",
    "nist_ftc_08_asme1_ap242-1.stp",
]

# Recall floor on THROUGH_HOLE + COUNTERBORE per fixture (measured 9 / 10 / 20).
THROUGH_BORE_FLOOR = {
    "nist_ctc_01_asme1_ap242.stp": 8,
    "nist_ftc_06_asme1_ap242.stp": 9,
    "nist_ftc_08_asme1_ap242-1.stp": 18,
}


@lru_cache(maxsize=None)
def _features(filename):
    shape = utils.import_step(os.path.join(FIXTURE_DIR, filename))
    solid = list(utils.get_shape_solids(shape, sort=True))[0]
    aag = AdjacencyGraph(solid)
    aag.full()
    aag.smooth()
    aag.grouped()
    return recognize_cavities(aag)


def _count(feats, *types):
    wanted = set(types)
    return sum(1 for f in feats if f.type in wanted)


@pytest.mark.parametrize("filename", FIXTURES)
def test_feature_invariants(filename):
    feats = _features(filename)
    assert feats, "recognizer returned no features for %s" % filename

    for f in feats:
        assert f.type in HOLE_TYPES, "unexpected feature type %s" % f.type
        if f.type == FT.POCKET:
            continue

        assert f.diameter > 0, "%s diameter %r" % (f.type.name, f.diameter)
        assert len(f.axis) == 3, "%s axis %r" % (f.type.name, f.axis)
        norm = math.sqrt(sum(a * a for a in f.axis))
        assert abs(norm - 1.0) < 1e-6, "%s axis not unit: %s" % (f.type.name, f.axis)
        assert f.depth > 0, "%s depth %r" % (f.type.name, f.depth)

        if f.type == FT.COUNTERBORE:
            assert f.counterbore_diameter > f.diameter, (
                "counterbore %r <= bore %r" % (f.counterbore_diameter, f.diameter))

        if f.type == FT.COUNTERSINK:
            assert f.angle is not None and f.angle > 0, "countersink angle %r" % f.angle


@pytest.mark.parametrize("filename", FIXTURES)
def test_through_bore_recall_floor(filename):
    feats = _features(filename)
    through_bore = _count(feats, FT.THROUGH_HOLE, FT.COUNTERBORE)
    floor = THROUGH_BORE_FLOOR[filename]
    assert through_bore >= floor, "through/bore %d < floor %d" % (through_bore, floor)


@pytest.mark.parametrize("filename", FIXTURES)
def test_total_count_band(filename):
    feats = _features(filename)
    floor = THROUGH_BORE_FLOOR[filename]
    assert floor <= len(feats) <= floor * 3, (
        "total %d outside [%d, %d]" % (len(feats), floor, floor * 3))


def test_ctc_01_has_countersink():
    # Two 118-degree drill-point / countersink cones fold into their coaxial
    # cylinders (measured 2 COUNTERSINK).
    feats = _features("nist_ctc_01_asme1_ap242.stp")
    assert _count(feats, FT.COUNTERSINK) >= 1


def test_ftc_06_has_blind_or_counterbore():
    feats = _features("nist_ftc_06_asme1_ap242.stp")
    assert _count(feats, FT.BLIND_HOLE, FT.COUNTERBORE) >= 1


def test_ftc_08_no_countersink():
    # No cones present in this part.
    feats = _features("nist_ftc_08_asme1_ap242-1.stp")
    assert _count(feats, FT.COUNTERSINK) == 0
