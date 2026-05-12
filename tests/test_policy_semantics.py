from __future__ import annotations

import numpy as np
import pytest

from ros_bridge_lite.imu_processor import (
    IMUProcessor,
    LowPassFilter,
    euler_xyz_to_matrix,
    euler_zyx_to_matrix,
    matrix_to_euler_xyz,
    rot_x,
    rot_y,
)
from ros_bridge_lite.observation_builder import ObservationBuilder
from ros_bridge_lite.policy_config import PolicyConfig
from ros_bridge_lite.sp_transform import SimulationSPTransform
from TGrobot4s.isaac_sim.ros2_control_bridge import (
    STARTUP_STAND_ORIENTATION_WXYZ,
    quat_wxyz_to_euler,
    relative_quat_wxyz,
)


def test_policy_joint_reorder_matches_sdk_and_is_invertible() -> None:
    cfg = PolicyConfig()

    assert cfg.mujoco_to_isaac == [
        0, 6, 12, 16, 1, 7, 13, 17, 2, 8,
        14, 18, 3, 9, 15, 19, 4, 10, 5, 11,
    ]
    assert cfg.isaac_to_mujoco == [
        0, 4, 8, 12, 16, 18, 1, 5, 9, 13,
        17, 19, 2, 6, 10, 14, 3, 7, 11, 15,
    ]

    for isaac_idx, mujoco_idx in enumerate(cfg.mujoco_to_isaac):
        assert cfg.isaac_to_mujoco[mujoco_idx] == isaac_idx


def test_observation_builder_reorders_canonical_joint_state_into_policy_order() -> None:
    cfg = PolicyConfig()
    builder = ObservationBuilder(cfg)

    joint_pos = np.arange(20, dtype=np.float64) * 0.1
    joint_vel = np.arange(20, dtype=np.float64) * 0.01
    action_last = np.linspace(-1.0, 1.0, 20, dtype=np.float64)

    obs = builder.build(
        ang_vel=np.array([0.1, 0.2, 0.3], dtype=np.float64),
        gravity_dir=np.array([0.0, 0.0, -1.0], dtype=np.float64),
        command=np.array([0.4, 0.0, -0.2], dtype=np.float64),
        joint_pos=joint_pos,
        joint_vel=joint_vel,
        action_last=action_last,
        gait_timer=0.0,
    )

    frame = obs[:75]
    expected_pos = np.array(
        [
            (joint_pos[idx] - cfg.default_dof_pos[idx]) * cfg.obs_scales_dof_pos
            for idx in cfg.mujoco_to_isaac
        ],
        dtype=np.float32,
    )
    expected_vel = np.array(
        [joint_vel[idx] * cfg.obs_scales_dof_vel for idx in cfg.mujoco_to_isaac],
        dtype=np.float32,
    )

    assert np.allclose(frame[9:29], expected_pos)
    assert np.allclose(frame[29:49], expected_vel)
    assert np.allclose(frame[49:69], np.clip(action_last, -100.0, 100.0).astype(np.float32))
    assert np.allclose(obs[75:], 0.0)


def test_observation_builder_matches_sdk_warmup_shift_semantics() -> None:
    cfg = PolicyConfig()
    builder = ObservationBuilder(cfg)

    builder.build(
        ang_vel=np.array([0.1, 0.2, 0.3], dtype=np.float64),
        gravity_dir=np.array([0.0, 0.0, -1.0], dtype=np.float64),
        command=np.array([0.0, 0.0, 0.0], dtype=np.float64),
        joint_pos=np.zeros(20, dtype=np.float64),
        joint_vel=np.zeros(20, dtype=np.float64),
        action_last=np.zeros(20, dtype=np.float64),
        gait_timer=0.0,
    )
    obs2 = builder.build(
        ang_vel=np.array([1.1, 1.2, 1.3], dtype=np.float64),
        gravity_dir=np.array([0.1, 0.2, -0.9], dtype=np.float64),
        command=np.array([0.4, 0.0, -0.2], dtype=np.float64),
        joint_pos=np.zeros(20, dtype=np.float64),
        joint_vel=np.zeros(20, dtype=np.float64),
        action_last=np.ones(20, dtype=np.float64),
        gait_timer=0.2,
    )

    assert np.allclose(obs2[:675], 0.0)
    assert np.allclose(obs2[-75:-72], np.array([1.1, 1.2, 1.3], dtype=np.float32))


def test_policy_imu_processor_matches_sdk_formula() -> None:
    pitch = 0.21
    roll = -0.17
    omega = np.array([0.31, -0.42, 0.53], dtype=np.float64)
    processor = IMUProcessor()

    ang_vel, gravity_dir = processor.process(0.8, pitch, roll, omega)

    ypr = np.array([0.0, pitch, roll], dtype=np.float64)
    ned_r_ypr = euler_zyx_to_matrix(ypr[0], ypr[1], ypr[2])
    rpy = np.array(matrix_to_euler_xyz(ned_r_ypr), dtype=np.float64)
    r_xyz_omega = np.eye(3, dtype=np.float64)
    r_xyz_omega[1, :] = rot_x(rpy[0])[1, :]
    r_xyz_omega[2, :] = (rot_x(rpy[0]) @ rot_y(rpy[1]))[2, :]
    q_dot = r_xyz_omega.T @ ned_r_ypr @ omega
    rb_w = euler_xyz_to_matrix(rpy[0], rpy[1], rpy[2])
    expected_ang_vel = LowPassFilter(30.0, 0.707, 0.02, n=3).filter(rb_w.T @ r_xyz_omega @ q_dot)
    expected_gravity = -rb_w.T[:, 2]

    assert ang_vel.tolist() == pytest.approx(expected_ang_vel.tolist(), abs=1e-9)
    assert gravity_dir.tolist() == pytest.approx(expected_gravity.tolist(), abs=1e-9)


def test_simulation_sp_transform_is_intentional_identity_for_lite_ankles() -> None:
    transform = SimulationSPTransform()
    q = np.array([0.2, -0.1, -0.3, 0.4], dtype=np.float64)
    qd = np.array([1.0, -2.0, 3.0, -4.0], dtype=np.float64)
    tor = np.array([5.0, -6.0, 7.0, -8.0], dtype=np.float64)

    assert all(np.allclose(part, expected) for part, expected in zip(transform.forward(q, qd, tor), (q, qd, tor)))
    assert all(np.allclose(part, expected) for part, expected in zip(transform.inverse(q, qd, tor), (q, qd, tor)))


def test_policy_imu_neutralizes_nominal_startup_orientation() -> None:
    processor = IMUProcessor()
    neutral = STARTUP_STAND_ORIENTATION_WXYZ.tolist()
    corrected = relative_quat_wxyz(neutral, neutral)
    yaw, pitch, roll = quat_wxyz_to_euler(corrected.tolist())
    _, gravity_dir = processor.process(yaw, pitch, roll, np.zeros(3, dtype=np.float64))

    assert gravity_dir.tolist() == pytest.approx([0.0, 0.0, -1.0], abs=1e-6)
