from __future__ import annotations

import math

from ros_bridge_lite.gait_controller import GaitConfig, GaitController


def _make_controller() -> GaitController:
    cfg = GaitConfig(
        joint_names=(
            "hip_pitch_l_joint",
            "knee_pitch_l_joint",
            "ankle_pitch_l_joint",
            "hip_pitch_r_joint",
            "knee_pitch_r_joint",
            "ankle_pitch_r_joint",
        )
    )
    return GaitController(cfg)


def test_stand_pose_covers_all_joint_names() -> None:
    ctrl = _make_controller()
    pose = ctrl.stand_pose()
    assert set(pose.keys()) == set(ctrl.joint_names)


def test_update_returns_finite_joint_targets() -> None:
    ctrl = _make_controller()
    targets = ctrl.update(linear_x=0.4, angular_z=0.2, dt=0.02)
    assert set(targets.keys()) == set(ctrl.joint_names)
    assert all(math.isfinite(v) for v in targets.values())


def test_forward_command_generates_leg_phase_difference() -> None:
    ctrl = _make_controller()
    targets = ctrl.update(linear_x=0.5, angular_z=0.0, dt=0.03)
    hip_left = targets["hip_pitch_l_joint"]
    hip_right = targets["hip_pitch_r_joint"]
    assert hip_left != hip_right
