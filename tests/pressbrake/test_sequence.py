import json

import pytest

from pressbrake import envelope as envelope_mod
from pressbrake import sequence
from pressbrake.machine import load_dies, load_machine, load_punches
from pressbrake.sequence import SearchConfig

from tests.pressbrake import builders


@pytest.fixture(scope="module")
def catalogue():
    return load_machine(), load_punches(), load_dies()


def group_order(plan):
    return [step.sister_group for step in plan.steps]


def test_hat_auto_discovers_feet_first(catalogue):
    """
    The search must discover on its own that feet (groups of bends 2, 3)
    have to be formed before their walls (bends 0, 1) - previously this
    ordering was hand-supplied.
    """
    machine, punches, dies = catalogue
    graph = builders.hat_profile()
    result = sequence.search_sequences(
        graph, machine, punches, dies, SearchConfig(max_solutions=8))
    assert result.feasible

    groups = graph.sister_groups()
    group_of = {bend: key for key, bends in groups.items() for bend in bends}
    for plan in result.plans:
        order = group_order(plan)
        assert order.index(group_of[2]) < order.index(group_of[0])
        assert order.index(group_of[3]) < order.index(group_of[1])
    # walls-first prefixes were explored and rejected
    assert result.stats["dead_states"] > 0


def test_offset_lip_orders_lip_first_and_picks_relief_punch(catalogue):
    machine, punches, dies = catalogue
    graph = builders.offset_lip()
    result = sequence.search_sequences(graph, machine, punches, dies)
    assert result.feasible
    best = result.plans[0]
    order = [step.bend_ids for step in best.steps]
    assert order == [(1,), (0,)]
    # the wall step's setup must use a lip-clearing punch
    wall_setup = next(s for s in best.setups if best.steps[s.step_indices[0]].bend_ids == (0,)
                      or len(s.step_indices) > 1)
    assert wall_setup.punch_id in ("P.88.GN", "P.30.R08")


def test_offset_lip_straight_only_unsolvable(catalogue):
    machine, punches, dies = catalogue
    graph = builders.offset_lip()
    result = sequence.search_sequences(
        graph, machine, {"P.88.R08": punches["P.88.R08"]}, dies)
    assert not result.feasible
    assert result.exhaustive


def test_box_any_order(catalogue):
    machine, punches, dies = catalogue
    graph = builders.box(corner_gap=6.0)
    result = sequence.search_sequences(
        graph, machine, punches, dies, SearchConfig(max_solutions=4))
    assert result.feasible
    for plan in result.plans:
        assert len(plan.steps) == 4
        assert {step.sister_group for step in plan.steps} == set(
            graph.sister_groups().keys())


def test_u_channel_single_setup(catalogue):
    machine, punches, dies = catalogue
    graph = builders.u_channel()
    # 2 groups x 2 rotations each = at most 8 sequences; a cap above that
    # lets the search prove exhaustiveness
    result = sequence.search_sequences(
        graph, machine, punches, dies, SearchConfig(max_solutions=20))
    assert result.feasible
    assert result.exhaustive
    best = result.plans[0]
    assert best.objective[0] == 0          # no setup changes
    assert len(best.setups) == 1
    assert best.setups[0].punch_placement.section_count >= 1


def test_partial_lip_notched_single_setup_two_stations(catalogue):
    """
    Straight punch only: the search exploits rotation freedom (position
    invariance) - the wall bend runs mirrored so the formed lip's curl zone
    lands away from the lip-bend station.  One setup, two punch runs (two
    stations along the installed tooling), the lip curl zone kept free of
    punch material.
    """
    from pressbrake.intervals import IntervalSet

    machine, punches, dies = catalogue

    graph = builders.partial_lip_notched()
    straight = sequence.search_sequences(
        graph, machine, {"P.88.R08": punches["P.88.R08"]}, dies)
    assert straight.feasible
    best = straight.plans[0]
    assert best.objective[0] == 0          # no setup changes
    assert len(best.setups) == 1
    setup = best.setups[0]
    # lip bend and wall bend use opposite rotations (mirrored stations)
    rotations = {step.bend_ids: step.action.rotation for step in best.steps}
    assert rotations[(0,)] != rotations[(1,)]
    # two punch stations, and the lip curl zone stays free of punch material
    assert len(setup.punch_placement.runs) == 2
    installed = setup.punch_placement.installed()
    assert installed.intersect(IntervalSet([(-30.0, 0.0)])).is_empty()

    graph = builders.partial_lip_notched()
    full = sequence.search_sequences(graph, machine, punches, dies)
    assert full.feasible
    assert full.plans[0].objective[0] == 0
    assert len(full.plans[0].setups) == 1


def test_setup_dp_splits_blocks_when_sharing_impossible(catalogue, monkeypatch):
    """
    Force solve_setup to reject multi-step blocks: the DP must fall back to
    one setup per step and the objective must count the changes.
    """
    from pressbrake import tooling

    machine, punches, dies = catalogue
    original = tooling.solve_setup

    def single_step_only(envelopes, punch, die, machine=None, step_indices=None):
        setup = original(envelopes, punch, die, machine, step_indices)
        if len(envelopes) > 1:
            setup.feasible = False
            setup.reason = "forced single-step blocks"
        return setup

    monkeypatch.setattr(sequence.tooling, "solve_setup", single_step_only)
    graph = builders.u_channel()
    result = sequence.search_sequences(
        graph, machine, punches, dies, SearchConfig(max_solutions=20))
    assert result.feasible
    best = result.plans[0]
    assert len(best.setups) == 2
    assert best.objective[0] == 1


def test_hem_rejected(catalogue):
    import math
    machine, punches, dies = catalogue
    graph = builders.l_bracket(angle=math.radians(170))
    result = sequence.search_sequences(graph, machine, punches, dies)
    assert not result.feasible
    assert "hem" in result.stats.get("reason", "")


def test_envelope_cache_no_recompute(catalogue, monkeypatch):
    machine, punches, dies = catalogue
    graph = builders.u_channel()

    calls = []
    original = envelope_mod.compute_envelope

    def counting(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(sequence.envelope, "compute_envelope", counting)
    sequence.search_sequences(graph, machine, punches, dies,
                              SearchConfig(max_solutions=20))
    # every (mask, group, rotation, punch, die) evaluated at most once:
    # the cache key space bounds the calls
    keys = set()
    for args in calls:
        _graph, theta, action, punch, die = args[0], args[1], args[2], args[3], args[4]
        keys.add((tuple(theta.round(6)), tuple(action.bend_ids),
                  action.rotation, punch.id, die.id))
    assert len(calls) == len(keys)


def test_search_report_serialization(catalogue):
    from pressbrake import serialize

    machine, punches, dies = catalogue
    graph = builders.u_channel()
    result = sequence.search_sequences(
        graph, machine, punches, dies, SearchConfig(max_solutions=20))
    payload = serialize.dump_search_report(result, graph, machine_name=machine.name)
    data = json.loads(json.dumps(payload))
    assert data["feasible"] is True
    assert data["exhaustive"] is True
    assert data["plans"]
    best = data["plans"][0]
    assert best["objective"][0] == 0
    assert best["setups"][0]["punch"]["runs"]
    assert len(best["steps"]) == 2
