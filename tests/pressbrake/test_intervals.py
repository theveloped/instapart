import numpy as np
import pytest

from pressbrake.intervals import IntervalSet


def test_normalization_merges_touching_and_overlapping():
    intervals = IntervalSet([(5, 7), (0, 2), (2, 3), (6, 9)])
    assert intervals.to_pairs() == [(0, 3), (5, 9)]


def test_empty_and_inverted_inputs_dropped():
    assert IntervalSet([(3, 3), (5, 4)]).is_empty()
    assert IntervalSet().is_empty()
    assert IntervalSet.empty().measure() == 0.0


def test_measure():
    assert IntervalSet([(0, 2), (5, 9)]).measure() == pytest.approx(6.0)


def test_union():
    a = IntervalSet([(0, 2), (6, 8)])
    b = IntervalSet([(1, 3), (4, 5)])
    assert a.union(b).to_pairs() == [(0, 3), (4, 5), (6, 8)]
    assert a.union(IntervalSet()) == a


def test_intersect():
    a = IntervalSet([(0, 4), (6, 10)])
    b = IntervalSet([(2, 7), (9, 12)])
    assert a.intersect(b).to_pairs() == [(2, 4), (6, 7), (9, 10)]
    assert a.intersect(IntervalSet()).is_empty()


def test_complement():
    a = IntervalSet([(2, 4), (6, 8)])
    assert a.complement(0, 10).to_pairs() == [(0, 2), (4, 6), (8, 10)]
    assert IntervalSet().complement(0, 5).to_pairs() == [(0, 5)]
    assert a.complement(3, 7).to_pairs() == [(4, 6)]


def test_difference():
    a = IntervalSet([(0, 10)])
    b = IntervalSet([(2, 3), (5, 7)])
    assert a.difference(b).to_pairs() == [(0, 2), (3, 5), (7, 10)]
    assert b.difference(a).is_empty()


def test_buffer_and_translate():
    a = IntervalSet([(2, 3), (5, 6)])
    assert a.buffer(1.0).to_pairs() == [(1, 4), (4, 7)] or a.buffer(1.0).to_pairs() == [(1, 7)]
    assert a.buffer(1.0).measure() == pytest.approx(6.0)
    assert a.translate(10).to_pairs() == [(12, 13), (15, 16)]
    assert a.buffer(-0.6).is_empty()


def test_contains():
    a = IntervalSet([(0, 5), (7, 9)])
    assert a.contains(IntervalSet([(1, 2), (8, 9)]))
    assert not a.contains(IntervalSet([(4, 6)]))
    assert a.contains(IntervalSet())
    assert a.contains_point(4.5)
    assert not a.contains_point(6.0)


def test_round_trip_properties():
    rng = np.random.default_rng(42)
    for _ in range(50):
        a = IntervalSet(rng.uniform(0, 100, (6, 2)))
        b = IntervalSet(rng.uniform(0, 100, (6, 2)))
        union = a.union(b)
        inter = a.intersect(b)
        # inclusion-exclusion on measures
        assert union.measure() == pytest.approx(a.measure() + b.measure() - inter.measure())
        # a \ b and a ∩ b partition a
        assert a.difference(b).measure() + inter.measure() == pytest.approx(a.measure())
        # complement round trip within a hull
        hull_low, hull_high = -1.0, 101.0
        assert a.complement(hull_low, hull_high).complement(hull_low, hull_high) == a
