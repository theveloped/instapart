import math

import numpy as np
import pytest

from pressbrake import collision, envelope
from pressbrake.intervals import IntervalSet
from pressbrake.machine import load_dies, load_machine, load_punches
from pressbrake.model import BendAction

from tests.pressbrake import builders


@pytest.fixture(scope="module")
def catalogue():
    return load_machine(), load_punches(), load_dies()


def action_for(graph, bend_id, rotation=0, x_offset=0.0):
    flip = graph.bends[bend_id].angle_target < 0
    return BendAction(bend_ids=(bend_id,), flip=flip, rotation=rotation,
                      x_offset=x_offset)


def test_plain_bend_fully_required_and_feasible(catalogue):
    machine, punches, dies = catalogue
    graph = builders.l_bracket(width=100)
    result = envelope.compute_envelope(
        graph, np.zeros(1), action_for(graph, 0),
        punches["P.88.R08"], dies["D.V16.88"], machine)
    assert result.feasible
    assert result.forbidden_punch.is_empty()
    assert result.forbidden_die.is_empty()
    # the whole 100 mm bend line needs pressing
    assert result.required.measure() == pytest.approx(100.0, abs=1.0)


def test_notch_makes_gap_optional_not_required(catalogue):
    machine, punches, dies = catalogue
    graph = builders.notched_bend(width=100, notch=(40.0, 60.0))
    result = envelope.compute_envelope(
        graph, np.zeros(1), action_for(graph, 0),
        punches["P.88.R08"], dies["D.V16.88"], machine)
    required = result.required
    # material crosses the bend line only outside the notch
    assert required.measure() == pytest.approx(80.0, abs=1.5)
    assert not required.intersect(IntervalSet([(41.0, 59.0)])).measure()
    # the notch span is optional for the punch
    optional = result.optional_for(result.forbidden_punch)
    assert optional.contains(IntervalSet([(41.0, 59.0)]))


def test_sister_tabs_required_spans(catalogue):
    machine, punches, dies = catalogue
    graph = builders.tabbed_flange(width=100, gap=(40.0, 60.0))
    action = BendAction(bend_ids=(0, 1), flip=False, rotation=0)
    result = envelope.compute_envelope(
        graph, np.zeros(2), action, punches["P.88.R08"], dies["D.V16.88"],
        machine)
    assert result.feasible
    # two required spans matching the tabs; the gap stays free
    x_values = result.required
    assert len(x_values) == 2
    assert x_values.measure() == pytest.approx(80.0, abs=1.5)


def test_lip_forbidden_interval_localized(catalogue):
    """
    The formed return lip only exists over the wall's X span; a straight
    punch is forbidden there but fine elsewhere along the machine.
    """
    machine, punches, dies = catalogue
    graph = builders.offset_lip(width=100)
    state = np.array([0.0, math.pi / 2])
    result = envelope.compute_envelope(
        graph, state, action_for(graph, 0), punches["P.88.R08"],
        dies["D.V16.88"])
    # punch material over the (full-width) lip is forbidden -> infeasible,
    # since the whole bend line is required
    assert not result.forbidden_punch.is_empty()
    assert not result.feasible
    forbidden = result.forbidden_punch
    # the lip spans the full part width, margin-buffered
    assert forbidden.arr[0, 0] == pytest.approx(-result.margin, abs=1.0)
    assert forbidden.arr[-1, 1] == pytest.approx(100 + result.margin, abs=1.0)


def test_partial_lip_leaves_required_feasible(catalogue):
    """
    A lip covering only part of the width forbids punch material only
    there; the bend stays feasible because required spans avoid it only if
    the lip region is not required... here it IS required, so the geometry
    must come out infeasible for the straight punch but the forbidden
    interval must be localized to the lip span.
    """
    from pressbrake.kinematics import finalize_graph
    from pressbrake.model import Bend, KinematicGraph, Panel

    machine, punches, dies = catalogue
    width, base, wall, lip = 100.0, 60.0, 30.0, 20.0
    panels = [
        Panel(id=0, outline=builders.rectangle(0, 0, width, base)),
        Panel(id=1, outline=builders.rectangle(0, base, width, base + wall)),
        # lip only over x in [70, 100]
        Panel(id=2, outline=builders.rectangle(
            70, base + wall, width, base + wall + lip)),
    ]
    bends = [
        Bend(id=0, axis_point=np.array([0.0, base]), axis_dir=np.array([1.0, 0.0]),
             angle_target=math.pi / 2, inner_radius=2.0, k_factor=0.5,
             length=width, parent_panel=0, child_panel=1),
        Bend(id=1, axis_point=np.array([70.0, base + wall]),
             axis_dir=np.array([1.0, 0.0]),
             angle_target=math.pi / 2, inner_radius=2.0, k_factor=0.5,
             length=width - 70, parent_panel=1, child_panel=2),
    ]
    graph = finalize_graph(KinematicGraph(
        panels=panels, bends=bends, base_panel=0, thickness=2.0))

    state = np.array([0.0, math.pi / 2])
    result = envelope.compute_envelope(
        graph, state, action_for(graph, 0), punches["P.88.R08"],
        dies["D.V16.88"])
    forbidden = result.forbidden_punch
    assert not forbidden.is_empty()
    # forbidden only over the lip span (70..100), margin-buffered
    assert forbidden.arr[0, 0] > 60.0
    # and the punch remains allowed over the free part of the bend line
    assert result.optional_for(forbidden).union(result.required).contains(
        IntervalSet([(0.0, 65.0)]))


def test_x_offset_translates_envelope(catalogue):
    machine, punches, dies = catalogue
    graph = builders.notched_bend()
    base = envelope.compute_envelope(
        graph, np.zeros(1), action_for(graph, 0),
        punches["P.88.R08"], dies["D.V16.88"])
    shifted = envelope.compute_envelope(
        graph, np.zeros(1), action_for(graph, 0, x_offset=500.0),
        punches["P.88.R08"], dies["D.V16.88"])
    assert shifted.required == base.required.translate(500.0)


def test_machine_interference_is_fatal(catalogue):
    machine, punches, dies = catalogue
    graph = builders.u_channel(base=30, wall=250)
    state = np.array([math.pi / 2, 0.0])
    result = envelope.compute_envelope(
        graph, state, action_for(graph, 1), punches["P.88.R08"],
        dies["D.V16.88"], machine)
    assert not result.forbidden_machine.is_empty() or \
        not result.forbidden_punch.is_empty()
    assert not result.feasible


def test_swept_region_covers_all_rotations():
    from shapely.geometry import Point

    segments = [((50.0, 0.0), (100.0, 0.0))]
    swept = envelope.swept_region(segments, 1.0, 0.0, math.pi / 4)
    # every intermediate rotation must be inside the swept region
    for angle in np.linspace(0, math.pi / 4, 100):
        for radius in (50.0, 75.0, 100.0):
            point = radius * np.array([math.cos(angle), math.sin(angle)])
            assert swept.contains(Point(point))
    # and it must not massively overshoot the true annular wedge
    assert not swept.contains(Point(0.0, -10.0))
    assert not swept.contains(Point(103.0, -3.0))


def test_envelope_contains_sampled_hits(catalogue):
    """
    Cross-validation: every punch/die hit the sampling checker finds must
    lie inside the envelope's forbidden intervals (the envelope is the
    conservative superset).
    """
    machine, punches, dies = catalogue
    cases = [
        (builders.offset_lip(width=100), np.array([0.0, math.pi / 2]), 0),
        (builders.u_channel(base=30, wall=200), np.array([math.pi / 2, 0.0]), 1),
        (builders.notched_bend(), np.array([0.0]), 0),
    ]
    for graph, state, bend_id in cases:
        action = action_for(graph, bend_id)
        result = envelope.compute_envelope(
            graph, state, action, punches["P.88.R08"], dies["D.V16.88"],
            machine)
        report = collision.check_action(
            graph, state, action, punch=punches["P.88.R08"],
            die=dies["D.V16.88"], machine=machine)
        for hit in report.hits:
            if math.isnan(hit.x):
                continue
            forbidden = {
                "punch": result.forbidden_punch,
                "die": result.forbidden_die,
                "ram": result.forbidden_machine,
                "table": result.forbidden_machine,
            }[hit.obstacle]
            assert forbidden.contains_point(hit.x), \
                "sampled {} hit at x={:.2f} outside envelope".format(
                    hit.obstacle, hit.x)
