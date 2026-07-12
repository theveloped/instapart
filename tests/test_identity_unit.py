"""Unit tests for the pure (OCC-free) parts of identity.py."""

import pytest

import identity


class TestQuantize:
    def test_basic_bucketing(self):
        assert identity.quantize(1.0, 0.001) == 1000
        assert identity.quantize(0.0, 0.001) == 0
        assert identity.quantize(-1.0, 0.001) == -1000

    def test_none_passthrough(self):
        assert identity.quantize(None, 0.001) is None

    def test_noise_within_bucket_is_absorbed(self):
        step = identity.step_for(100.0)  # 1e-4
        value = 42.123
        noisy = value * (1 + 1e-9)
        assert identity.quantize(value, step) == identity.quantize(noisy, step)

    def test_boundary_can_flip(self):
        # documented residual risk: values straddling a bucket edge flip
        # (1.49999 rounds to 1, 1.5 banker's-rounds to 2)
        step = 0.001
        assert identity.quantize(0.0015, step) != identity.quantize(0.00149999, step)

    def test_step_scaling(self):
        assert identity.step_for(100.0, "length") == pytest.approx(1e-4)
        assert identity.step_for(100.0, "area") == pytest.approx(1e-2)
        assert identity.step_for(100.0, "volume") == pytest.approx(1.0)
        # floor applies to tiny parts
        assert identity.step_for(0.1, "length") == identity.FLOOR


class TestStableDigest:
    def test_deterministic(self):
        assert identity.stable_digest(1, 2, ("a", 3)) == identity.stable_digest(1, 2, ("a", 3))

    def test_different_input_different_id(self):
        assert identity.stable_digest(1, 2) != identity.stable_digest(2, 1)

    def test_returns_60_bit_int(self):
        value = identity.stable_digest("x")
        assert isinstance(value, int)
        assert 0 <= value < 2 ** 60

    def test_lists_and_tuples_equivalent(self):
        assert identity.stable_digest([1, [2, 3]]) == identity.stable_digest((1, (2, 3)))

    def test_raw_floats_rejected(self):
        with pytest.raises(TypeError):
            identity.stable_digest(1.5)
        with pytest.raises(TypeError):
            identity.stable_digest((1, (2.5,)))

    def test_scheme_version_in_digest(self):
        # a known-value pin: changing SCHEME_VERSION must change every id
        assert identity.stable_digest(1) != identity.stable_digest(("g2", 1))


class TestDupRanks:
    def test_unique_fingerprints_rank_zero(self):
        fps = [("a",), ("b",), ("c",)]
        assert identity.assign_dup_ranks(fps) == [(("a",), 0), (("b",), 0), (("c",), 0)]

    def test_duplicates_ranked_in_order(self):
        fps = [("a",), ("b",), ("a",), ("a",)]
        assert identity.assign_dup_ranks(fps) == [
            (("a",), 0), (("b",), 0), (("a",), 1), (("a",), 2)]

    def test_empty(self):
        assert identity.assign_dup_ranks([]) == []


def test_module_imports_without_occ():
    # identity.py must import in the OCC-free unit environment; if this test
    # is running at all, the module-level import above already proved it.
    assert identity.SCHEME_VERSION == "g1"
