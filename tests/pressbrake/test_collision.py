import math

import numpy as np
import pytest

from pressbrake import collision
from pressbrake.machine import load_dies, load_machine, load_punches
from pressbrake.model import BendAction

from tests.pressbrake import builders


@pytest.fixture(scope="module")
def catalogue():
    return load_machine(), load_punches(), load_dies()


def action_for(graph, bend_id, rotation=0):
    flip = graph.bends[bend_id].angle_target < 0
    return BendAction(bend_ids=(bend_id,), flip=flip, rotation=rotation)


def test_simple_l_bend_is_clear(catalogue):
    """
    A plain 90 deg bend with 88 deg tooling: the wings end up hugging the
    punch flanks - contact, not collision.
    """
    machine, punches, dies = catalogue
    graph = builders.l_bracket(width=100, leg=50, flange=30)
    report = collision.check_action(
        graph, np.zeros(1), action_for(graph, 0),
        punch=punches["P.88.R08"], die=dies["D.V16.88"], machine=machine)
    assert not report.collided, report.summary()


def test_lip_collides_with_straight_punch_but_not_gooseneck(catalogue):
    """
    Return lip already formed; bending the wall curls the lip over the
    blade: collision with the straight punch in both part rotations, clear
    with the gooseneck in the rotation that faces its relief window.
    """
    machine, punches, dies = catalogue
    graph = builders.offset_lip(base=60, wall=30, lip=20)
    state = np.array([0.0, math.pi / 2])  # lip formed, wall bend pending

    for rotation in (0, 1):
        report = collision.check_action(
            graph, state, action_for(graph, 0, rotation),
            punch=punches["P.88.R08"], die=dies["D.V16.88"])
        assert report.collided, "straight punch should collide (rotation {})".format(rotation)
        assert any(hit.obstacle == "punch" for hit in report.hits)
        # the lip enters the blade partway through the stroke, not at start
        assert report.first_phi > math.radians(20)

    gooseneck_reports = [
        collision.check_action(
            graph, state, action_for(graph, 0, rotation),
            punch=punches["P.88.GN"], die=dies["D.V16.88"])
        for rotation in (0, 1)
    ]
    clear = [not report.collided for report in gooseneck_reports]
    assert any(clear), "gooseneck should clear in one rotation"
    assert not all(clear), "gooseneck relief is one-sided"


def test_tall_wall_hits_punch_top(catalogue):
    """
    A very tall formed wall over a narrow base leans over the punch body as
    the second wall bends: punch collision even without the machine frame.
    """
    machine, punches, dies = catalogue
    graph = builders.u_channel(base=30, wall=200)
    state = np.array([math.pi / 2, 0.0])  # wall 1 formed, wall 2 pending

    report = collision.check_action(
        graph, state, action_for(graph, 1),
        punch=punches["P.88.R08"], die=dies["D.V16.88"])
    assert report.collided
    assert any(hit.obstacle == "punch" for hit in report.hits)


def test_formed_wall_hits_ram_only_with_machine(catalogue):
    """
    A 100 mm formed wall 80 mm from a 60 deg active bend rises past the
    punch (clear) but into the ram band: collision only when the machine
    frame is included.
    """
    from pressbrake.kinematics import finalize_graph
    from pressbrake.model import Bend, KinematicGraph, Panel

    machine, punches, dies = catalogue
    panels = [
        Panel(id=0, outline=builders.rectangle(0, 0, 100, 80)),
        Panel(id=1, outline=builders.rectangle(0, 80, 100, 180)),   # tall wall
        Panel(id=2, outline=builders.rectangle(0, -20, 100, 0)),    # active flange
    ]
    bends = [
        Bend(id=0, axis_point=np.array([0.0, 80.0]), axis_dir=np.array([1.0, 0.0]),
             angle_target=math.pi / 2, inner_radius=2.0, k_factor=0.5,
             length=100, parent_panel=0, child_panel=1),
        Bend(id=1, axis_point=np.array([0.0, 0.0]), axis_dir=np.array([1.0, 0.0]),
             angle_target=math.radians(60), inner_radius=2.0, k_factor=0.5,
             length=100, parent_panel=0, child_panel=2),
    ]
    graph = finalize_graph(KinematicGraph(
        panels=panels, bends=bends, base_panel=0, thickness=2.0))
    state = np.array([math.pi / 2, 0.0])

    without_machine = collision.check_action(
        graph, state, action_for(graph, 1),
        punch=punches["P.88.R08"], die=dies["D.V16.88"])
    assert not without_machine.collided, without_machine.summary()

    with_machine = collision.check_action(
        graph, state, action_for(graph, 1),
        punch=punches["P.88.R08"], die=dies["D.V16.88"], machine=machine)
    assert with_machine.collided
    assert any(hit.obstacle == "ram" for hit in with_machine.hits)


def test_down_flange_hits_die():
    """
    A down-hanging formed flange close to the active bend line stands inside
    the die body.
    """
    from pressbrake.kinematics import finalize_graph
    from pressbrake.model import Bend, KinematicGraph, Panel

    panels = [
        Panel(id=0, outline=builders.rectangle(0, 0, 100, 20)),
        Panel(id=1, outline=builders.rectangle(0, 20, 100, 70)),   # down flange
        Panel(id=2, outline=builders.rectangle(0, -30, 100, 0)),   # active wall
    ]
    bends = [
        Bend(id=0, axis_point=np.array([0.0, 20.0]), axis_dir=np.array([1.0, 0.0]),
             angle_target=-math.pi / 2, inner_radius=2.0, k_factor=0.5,
             length=100, parent_panel=0, child_panel=1),
        Bend(id=1, axis_point=np.array([0.0, 0.0]), axis_dir=np.array([1.0, 0.0]),
             angle_target=math.pi / 2, inner_radius=2.0, k_factor=0.5,
             length=100, parent_panel=0, child_panel=2),
    ]
    graph = finalize_graph(KinematicGraph(
        panels=panels, bends=bends, base_panel=0, thickness=2.0))

    dies = load_dies()
    report = collision.check_action(
        graph, np.array([-math.pi / 2, 0.0]), action_for(graph, 1),
        die=dies["D.V16.88"])
    assert report.collided
    assert all(hit.obstacle == "die" for hit in report.hits)


def test_box_corner_self_collision():
    """
    Zero corner gap: the last wall's corners meet the formed neighbours
    within the margin -> self-collision; a 6 mm gap clears it.
    """
    tight = builders.box(corner_gap=0.0)
    state = np.array([math.pi / 2] * 3 + [0.0])
    action = action_for(tight, 3)
    hits = collision.check_self_collision(tight, state, action, margin=2.0)
    assert hits
    assert all(hit.obstacle.startswith("panel:") for hit in hits)

    roomy = builders.box(corner_gap=6.0)
    hits = collision.check_self_collision(roomy, state, action_for(roomy, 3),
                                          margin=2.0)
    assert not hits


def test_sister_tabs_clear(catalogue):
    machine, punches, dies = catalogue
    graph = builders.tabbed_flange()
    action = BendAction(bend_ids=(0, 1), flip=False, rotation=0)
    report = collision.check_action(
        graph, np.zeros(2), action,
        punch=punches["P.88.R08"], die=dies["D.V16.88"], machine=machine)
    assert not report.collided, report.summary()


def test_negative_bend_flip_clear(catalogue):
    machine, punches, dies = catalogue
    graph = builders.z_profile()
    # bend 0 is -90: the action must flip the part and then bend cleanly
    report = collision.check_action(
        graph, np.zeros(2), action_for(graph, 0),
        punch=punches["P.88.R08"], die=dies["D.V16.88"], machine=machine)
    assert not report.collided, report.summary()


def test_slice_panel_hole():
    """
    A slice through a hole must produce two separate material segments.
    """
    from pressbrake.kinematics import panel_points_3d
    from pressbrake.model import Panel

    panel = Panel(
        id=0,
        outline=builders.rectangle(0, 0, 100, 50),
        holes=[builders.rectangle(40, 10, 60, 40)[::-1]],
    )
    verts = panel_points_3d(panel)
    holes = [np.column_stack([h, np.zeros(len(h))]) for h in panel.holes]
    geometry = collision.slice_panel(verts, holes, np.eye(4), 2.0, x=50.0)
    assert geometry is not None
    assert geometry.geom_type == "MultiPolygon"
    assert len(geometry.geoms) == 2
