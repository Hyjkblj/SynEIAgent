from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class PolicyConfig:
    # Model paths
    model_xml_path: str = ""
    model_bin_path: str = ""

    # Control timing
    dt: float = 0.02  # 50Hz bridge loop (C++ uses 0.0025 at 400Hz with freq_ratio=8)
    motor_num: int = 20
    action_num: int = 20
    action_scales: float = 0.25

    # Default DOF position (Mujoco order, 20 joints)
    default_dof_pos: list[float] = field(default_factory=lambda: [
        0.0, -0.5, 0.0, 1.0, -0.5, 0.0,   # left leg
        0.0, -0.5, 0.0, 1.0, -0.5, 0.0,   # right leg
        0.0,  0.1, 0.0, -0.3,               # left arm
        0.0, -0.1, 0.0, -0.3,               # right arm
    ])

    # Gait parameters (walk mode)
    gait_cycle: float = 0.85
    left_theta_offset: float = 0.38
    right_theta_offset: float = 0.88
    left_phase_ratio: float = 0.38
    right_phase_ratio: float = 0.38

    # Command smoothing
    x_command_slope: float = 0.002
    yaw_command_slope: float = 0.001
    x_deadzone: float = 0.1
    yaw_deadzone: float = 0.1

    # IMU low-pass filter
    omega_cutoff_hz: float = 30.0
    omega_damping: float = 0.707

    # Observation scales
    obs_scales_lin_vel: float = 1.0
    obs_scales_ang_vel: float = 1.0
    obs_scales_dof_pos: float = 1.0
    obs_scales_dof_vel: float = 1.0

    # PD gains (20 joints)
    joint_kp_p: list[float] = field(default_factory=lambda: [
        700.0, 700.0, 500.0, 700.0, 15.0, 15.0,   # left leg
        700.0, 700.0, 500.0, 700.0, 15.0, 15.0,   # right leg
        60.0, 20.0, 10.0, 10.0,                     # left arm
        60.0, 20.0, 10.0, 10.0,                     # right arm
    ])
    joint_kd_p: list[float] = field(default_factory=lambda: [
        20.0, 20.0, 15.0, 10.0, 1.25, 1.25,
        20.0, 20.0, 15.0, 10.0, 1.25, 1.25,
        3.0, 1.5, 1.0, 1.0,
        3.0, 1.5, 1.0, 1.0,
    ])

    # Zero position offset (all zeros for Lite)
    zero_pos_offset: list[float] = field(default_factory=lambda: [0.0] * 20)

    # Joint index mappings (Mujoco order ↔ Isaac Sim order)
    mujoco_to_isaac: list[int] = field(default_factory=lambda: [
        0,  6,  12, 16,  1,  7, 13, 17,  2,  8,
        14, 18,  3,  9, 15, 19,  4, 10,  5, 11,
    ])
    isaac_to_mujoco: list[int] = field(default_factory=lambda: [
        0, 4, 8, 12, 16, 18,  1, 5, 9, 13, 17, 19,  2, 6, 10, 14,  3, 7, 11, 15,
    ])

    # Simulation mode (skip funcSPTrans)
    simulation: bool = True

    # Safety limits
    imu_pitch_limit: float = 0.8
    imu_roll_limit: float = 0.8
    imu_gyro_limit: float = 5.0
    joint_pos_limit: float = 1.0  # hip pitch limit for MLP→STOP transition

    @classmethod
    def from_yaml(cls, path: str) -> PolicyConfig:
        cfg = cls()
        if not path:
            return cfg
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if "motor_num" in data:
            cfg.motor_num = int(data["motor_num"])
        if "actions_size" in data:
            cfg.action_num = int(data["actions_size"])
        if "dt" in data:
            # C++ dt is 0.0025 (400Hz), we use 0.02 (50Hz)
            # Only override if explicitly set to a different value
            pass
        if "zero_pos_offset" in data:
            cfg.zero_pos_offset = [float(x) for x in data["zero_pos_offset"][:20]]
        if "joint_kp_p" in data:
            cfg.joint_kp_p = [float(x) for x in data["joint_kp_p"][:20]]
        if "joint_kd_p" in data:
            cfg.joint_kd_p = [float(x) for x in data["joint_kd_p"][:20]]
        return cfg

    @property
    def default_dof_pos_np(self) -> Any:
        import numpy as np
        return np.array(self.default_dof_pos, dtype=np.float32)
