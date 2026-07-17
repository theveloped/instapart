import math

import numpy as np
import pytest

from pressbrake import kinematics
from pressbrake.model import BendAction

from tests.pressbrake import builders


def folded_outline(graph, theta, panel_id):
    return graph.panel_vertices(np.asarray(theta, dtype=float))[panel_id]


def test_l_bracket_fold_90():
    graph = builders.l_bracket(width=100, leg=50, flange=30)
    vertices = folded_outline(graph, [math.pi / 2], 1)
    # flat (x, 50 + s, 0) -> folded (x, 50, s)
    expected = {(0.0, 50.0, 0.0), (100.0, 50.0, 0.0), (100.0, 50.0, 30.0), (0.0, 50.0, 30.0)}
    got = {tuple(np.round(v, 6)) for v in vertices}
    assert got == expected


def test_l_bracket_negative_fold_goes_down():
    graph = builders.l_bracket()
    graph.bends[0].angle_target = -math.pi / 2
    vertices = folded_outline(graph, [-math.pi / 2], 1)
    assert np.all(vertices[:, 2] <= 1e-9)
    assert np.min(vertices[:, 2]) == pytest.approx(-30.0)


def test_u_channel_both_walls_up():
    graph = builders.u_channel(width=100, base=80, wall=40)
    verts_a = folded_outline(graph, [math.pi / 2] * 2, 1)
    verts_b = folded_outline(graph, [math.pi / 2] * 2, 2)
    # wall A: flat (x, -s) -> (x, 0, s); wall B: flat (x, 80 + s) -> (x, 80, s)
    assert np.allclose(sorted(verts_a[:, 2]), [0, 0, 40, 40])
    assert np.allclose(verts_a[:, 1], 0.0, atol=1e-9)
    assert np.allclose(verts_b[:, 1], 80.0, atol=1e-9)
    assert np.max(verts_b[:, 2]) == pytest.approx(40.0)


def test_hat_profile_chained_transforms():
    graph = builders.hat_profile(width=100, top=40.0, wall=30.0, foot=20.0)
    theta = [b.angle_target for b in graph.bends]
    foot_a = folded_outline(graph, theta, 3)
    foot_b = folded_outline(graph, theta, 4)
    # both feet end horizontal at z = -wall, extending outward
    assert np.allclose(foot_a[:, 2], -30.0, atol=1e-9)
    assert np.allclose(foot_b[:, 2], -30.0, atol=1e-9)
    assert np.min(foot_a[:, 1]) == pytest.approx(-20.0)
    assert np.max(foot_b[:, 1]) == pytest.approx(60.0)


def test_partial_angles_intermediate_state():
    graph = builders.l_bracket(width=10, leg=10, flange=10)
    vertices = folded_outline(graph, [math.pi / 4], 1)
    tip = vertices[np.argmax(vertices[:, 2])]
    assert tip[2] == pytest.approx(10 * math.sin(math.pi / 4))
    assert tip[1] == pytest.approx(10 + 10 * math.cos(math.pi / 4))


def test_moving_masks():
    graph = builders.hat_profile()
    # bend 0 moves wall A (1) and foot A (3)
    assert graph.bends[0].moving_mask == (1 << 1) | (1 << 3)
    assert graph.bends[1].moving_mask == (1 << 2) | (1 << 4)
    assert graph.bends[2].moving_mask == 1 << 3
    assert graph.bends[3].moving_mask == 1 << 4


def test_axis_normalization_sign_convention():
    # u_channel bend 0's child lies at y < 0: axis_dir must have been flipped
    # so that z_hat x dir points toward the child.
    graph = builders.u_channel()
    bend = graph.bends[0]
    normal = kinematics.normal_2d(bend.axis_dir)
    child_centroid = graph.panels[bend.child_panel].centroid()
    assert np.dot(normal, child_centroid - bend.axis_point) > 0


def test_sister_groups_tabbed_flange():
    graph = builders.tabbed_flange()
    assert graph.bends[0].sister_group == graph.bends[1].sister_group
    graph2 = builders.u_channel()
    assert graph2.bends[0].sister_group != graph2.bends[1].sister_group


def test_relative_transforms_only_moves_subtree():
    graph = builders.u_channel()
    action = BendAction(bend_ids=(0,), flip=False, rotation=0)
    state = np.zeros(2)
    transforms = kinematics.relative_transforms(graph, state, action, math.pi / 4)
    assert np.allclose(transforms[0], np.eye(4))
    assert np.allclose(transforms[2], np.eye(4))
    assert not np.allclose(transforms[1], np.eye(4))


def test_machine_transforms_both_wings_lift():
    graph = builders.l_bracket(width=100, leg=50, flange=30)
    action = BendAction(bend_ids=(0,), flip=False, rotation=0)
    state = np.zeros(1)
    poses = kinematics.machine_transforms(graph, state, action, [0.0, math.pi / 2])

    # phi = 0: everything flat on the die plane (z=0), hinge on the X axis
    for panel in graph.panels:
        flat = kinematics.transform_points(
            poses[0, panel.id], kinematics.panel_points_3d(panel))
        assert np.allclose(flat[:, 2], 0.0, atol=1e-9)

    # phi = 90 deg: both wings lifted, all z >= 0, relative angle is 90 deg
    lifted = [
        kinematics.transform_points(poses[1, p.id], kinematics.panel_points_3d(p))
        for p in graph.panels
    ]
    for verts in lifted:
        assert np.min(verts[:, 2]) >= -1e-9
    tips = [verts[np.argmax(np.abs(verts[:, 1]))] for verts in lifted]
    # wing tips rise to |y_flat_extent| * sin(45 deg)
    assert tips[0][2] == pytest.approx(50 * math.sin(math.pi / 4))
    assert tips[1][2] == pytest.approx(30 * math.sin(math.pi / 4))
    # opposite Y sides
    assert tips[0][1] * tips[1][1] < 0


def test_machine_transforms_negative_bend_flip():
    graph = builders.l_bracket()
    graph.bends[0].angle_target = -math.pi / 2
    actions = kinematics.enumerate_actions(graph, [0])
    assert all(action.flip for action in actions)
    poses = kinematics.machine_transforms(
        graph, np.zeros(1), actions[0], [math.pi / 2])
    # even a negative bend forms upward in the machine frame
    for panel in graph.panels:
        verts = kinematics.transform_points(
            poses[0, panel.id], kinematics.panel_points_3d(panel))
        assert np.min(verts[:, 2]) >= -1e-9


def test_machine_transforms_relative_angle_matches_fold():
    graph = builders.l_bracket()
    action = BendAction(bend_ids=(0,), flip=False, rotation=0)
    phi = math.radians(60)
    poses = kinematics.machine_transforms(graph, np.zeros(1), action, [phi])
    normals = []
    for panel in graph.panels:
        normals.append(poses[0, panel.id][:3, :3] @ np.array([0.0, 0.0, 1.0]))
    angle = math.acos(np.clip(np.dot(normals[0], normals[1]), -1, 1))
    assert angle == pytest.approx(phi)


def test_x_offset_translates_along_machine_x():
    graph = builders.l_bracket()
    action_a = BendAction(bend_ids=(0,), flip=False, rotation=0, x_offset=0.0)
    action_b = BendAction(bend_ids=(0,), flip=False, rotation=0, x_offset=25.0)
    pose_a = kinematics.machine_transforms(graph, np.zeros(1), action_a, [0.3])
    pose_b = kinematics.machine_transforms(graph, np.zeros(1), action_b, [0.3])
    verts_a = kinematics.transform_points(
        pose_a[0, 1], kinematics.panel_points_3d(graph.panels[1]))
    verts_b = kinematics.transform_points(
        pose_b[0, 1], kinematics.panel_points_3d(graph.panels[1]))
    assert np.allclose(verts_b - verts_a, [25.0, 0.0, 0.0])


def test_sister_bend_shared_stroke():
    graph = builders.tabbed_flange()
    action = BendAction(bend_ids=(0, 1), flip=False, rotation=0)
    poses = kinematics.machine_transforms(graph, np.zeros(2), action, [math.pi / 2])
    for tab in (1, 2):
        verts = kinematics.transform_points(
            poses[0, tab], kinematics.panel_points_3d(graph.panels[tab]))
        assert np.max(verts[:, 2]) == pytest.approx(30 * math.sin(math.pi / 4))


def test_fold_state_helpers():
    graph = builders.u_channel()
    state = graph.flat_state()
    assert state.done_mask == 0
    next_state = state.with_bend_done(graph, 1)
    assert next_state.done_mask == 0b10
    assert next_state.theta[1] == pytest.approx(graph.bends[1].angle_relaxed)
    folded = graph.folded_state()
    assert folded.done_mask == 0b11
