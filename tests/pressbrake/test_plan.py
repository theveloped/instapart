import json
import math

import numpy as np
import pytest

from pressbrake import plan, serialize
from pressbrake.machine import load_dies, load_machine, load_punches

from tests.pressbrake import builders


@pytest.fixture(scope="module")
def catalogue():
    return load_machine(), load_punches(), load_dies()


def test_hat_profile_plan_feasible_feet_first(catalogue):
    """
    Feet before walls works; walls before feet curls the formed hat body
    over the punch and must come out infeasible - sequencing matters.
    """
    machine, punches, dies = catalogue
    graph = builders.hat_profile()
    report = plan.plan_graph(graph, machine, punches, dies,
                             sequence=[2, 3, 0, 1])
    assert report.feasible
    # 4 sister groups x 2 rotations
    assert len(report.actions) == 8
    for action in report.actions:
        if action.feasible:
            assert action.best.punch_id
            assert action.best.die_id
            assert action.best.required.measure() > 90.0

    graph = builders.hat_profile()
    walls_first = plan.plan_graph(graph, machine, punches, dies,
                                  sequence=[0, 1, 2, 3])
    assert not walls_first.feasible


def test_springback_applied(catalogue):
    machine, punches, dies = catalogue
    graph = builders.l_bracket()
    plan.plan_graph(graph, machine, punches, dies, springback_deg=3.0)
    assert graph.bends[0].angle_overbend == pytest.approx(
        math.pi / 2 + math.radians(3.0))
    assert graph.bends[0].angle_relaxed == pytest.approx(math.pi / 2)


def test_sister_group_single_action(catalogue):
    machine, punches, dies = catalogue
    graph = builders.tabbed_flange()
    report = plan.plan_graph(graph, machine, punches, dies)
    # one sister group -> 2 actions (rotations), both covering both bends
    assert len(report.actions) == 2
    assert all(sorted(action.bend_ids) == [0, 1] for action in report.actions)
    assert report.feasible


def test_hem_flagged_infeasible(catalogue):
    machine, punches, dies = catalogue
    graph = builders.l_bracket(angle=math.radians(170))
    report = plan.plan_graph(graph, machine, punches, dies)
    assert not report.feasible
    assert any("hem" in (action.collision_summary or "")
               for action in report.actions)


def test_offset_lip_needs_gooseneck(catalogue):
    """
    End-to-end selection: the return-lip part is infeasible with only the
    straight punch but planable when the gooseneck is in the catalogue.
    """
    machine, punches, dies = catalogue
    straight_only = {"P.88.R08": punches["P.88.R08"]}

    graph = builders.offset_lip()
    # lip (bend 1) must be formed first: sequence lip -> wall
    report = plan.plan_graph(
        graph, machine, straight_only, dies, sequence=[1, 0])
    wall_actions = [a for a in report.actions if a.bend_ids == [0]]
    assert not any(action.feasible for action in wall_actions)

    graph = builders.offset_lip()
    report = plan.plan_graph(graph, machine, punches, dies, sequence=[1, 0])
    wall_actions = [a for a in report.actions if a.bend_ids == [0]]
    feasible = [a for a in wall_actions if a.feasible]
    assert feasible
    # only tools with lip clearance qualify: the gooseneck relief or the
    # narrow acute blade - never the straight 88 punch
    assert all(action.best.punch_id in ("P.88.GN", "P.30.R08")
               for action in feasible)


def test_report_serialization_round_trip(catalogue):
    machine, punches, dies = catalogue
    graph = builders.notched_bend()
    report = plan.plan_graph(graph, machine, punches, dies)
    payload = serialize.dump_report(report)
    # must be plain-JSON serializable
    text = json.dumps(payload)
    data = json.loads(text)
    assert data["feasible"] is True
    assert data["graph"]["thickness"] == pytest.approx(2.0)
    assert len(data["graph"]["bends"]) == 1
    assert data["actions"]
    best = data["actions"][0]["best"]
    assert best["feasible"] is True
    # required spans exclude the notch
    spans = best["required"]
    assert len(spans) == 2


def test_self_collision_blocks_action(catalogue):
    machine, punches, dies = catalogue
    graph = builders.box(corner_gap=0.0)
    report = plan.plan_graph(graph, machine, punches, dies)
    assert any("self-collision" in (action.collision_summary or "")
               for action in report.actions)


def test_plot_outputs(tmp_path, catalogue):
    machine, punches, dies = catalogue
    graph = builders.hat_profile()
    report = plan.plan_graph(graph, machine, punches, dies)
    plan._write_plots(report, str(tmp_path), "hat")
    assert (tmp_path / "hat.fold.png").exists()
    assert (tmp_path / "hat.intervals.png").exists()
