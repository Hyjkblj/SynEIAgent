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
    dt: float = 0.02  # Effective policy refresh interval (0.0025 s * freq_ratio)
    control_dt: float = 0.0025  # Official FSM/control step at 400Hz
    freq_ratio: int = 8
    max_control_substeps: int = 32
    motor_num: int = 20
    action_num: int = 20
    action_scales: float = 0.25
    mlp_entry_blend_s: float = 0.0

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
    clamp_joint_targets: bool = False
    clamp_joint_target_names: list[str] = field(default_factory=list)
    clamp_joint_target_upper_only_names: list[str] = field(default_factory=list)
    clamp_joint_target_upper_only_margin_rad: float = 0.0
    clamp_joint_target_upper_only_delay_s: float = 0.0
    slew_joint_target_names: list[str] = field(default_factory=list)
    slew_joint_target_rate_rad_s: float = 0.0
    joint_pos_lower: list[float] = field(default_factory=lambda: [
        -0.79, -2.79, -1.04, 0.0, -1.22, -0.4363,
        -0.79, -2.79, -1.04, 0.0, -1.22, -0.4363,
        -2.96, -0.2618, -2.96, -2.61,
        -2.96, -3.4, -2.96, -2.61,
    ])
    joint_pos_upper: list[float] = field(default_factory=lambda: [
        0.79, 2.09, 1.04, 2.39, 0.5236, 0.4363,
        0.79, 2.09, 1.04, 2.39, 0.5236, 0.4363,
        2.96, 3.4, 2.96, 0.261,
        2.96, 0.2618, 2.96, 0.261,
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
    sp_lib_path: str = ""
    enable_sim_sp_transform: bool = False

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
        if "freq_ratio" in data:
            cfg.freq_ratio = max(1, int(data["freq_ratio"]))
        if "max_control_substeps" in data:
            cfg.max_control_substeps = max(1, int(data["max_control_substeps"]))
        if "control_dt" in data:
            cfg.control_dt = max(1e-4, float(data["control_dt"]))
        elif "dt" in data:
            cfg.control_dt = max(1e-4, float(data["dt"]))
        cfg.dt = cfg.control_dt * max(1, cfg.freq_ratio)
        if "zero_pos_offset" in data:
            cfg.zero_pos_offset = [float(x) for x in data["zero_pos_offset"][:20]]
        if "joint_kp_p" in data:
            cfg.joint_kp_p = [float(x) for x in data["joint_kp_p"][:20]]
        if "joint_kd_p" in data:
            cfg.joint_kd_p = [float(x) for x in data["joint_kd_p"][:20]]
        if "clamp_joint_targets" in data:
            cfg.clamp_joint_targets = bool(data["clamp_joint_targets"])
        if "clamp_joint_target_names" in data:
            raw_names = data["clamp_joint_target_names"]
            if isinstance(raw_names, str):
                raw_names = [part.strip() for part in raw_names.split(",")]
            if isinstance(raw_names, list):
                cfg.clamp_joint_target_names = [
                    str(name).strip() for name in raw_names if str(name).strip()
                ]
        if "clamp_joint_target_upper_only_names" in data:
            raw_names = data["clamp_joint_target_upper_only_names"]
            if isinstance(raw_names, str):
                raw_names = [part.strip() for part in raw_names.split(",")]
            if isinstance(raw_names, list):
                cfg.clamp_joint_target_upper_only_names = [
                    str(name).strip() for name in raw_names if str(name).strip()
                ]
        if "clamp_joint_target_upper_only_margin_rad" in data:
            cfg.clamp_joint_target_upper_only_margin_rad = max(
                0.0, float(data["clamp_joint_target_upper_only_margin_rad"])
            )
        if "clamp_joint_target_upper_only_delay_s" in data:
            cfg.clamp_joint_target_upper_only_delay_s = max(
                0.0, float(data["clamp_joint_target_upper_only_delay_s"])
            )
        if "slew_joint_target_names" in data:
            raw_names = data["slew_joint_target_names"]
            if isinstance(raw_names, str):
                raw_names = [part.strip() for part in raw_names.split(",")]
            if isinstance(raw_names, list):
                cfg.slew_joint_target_names = [
                    str(name).strip() for name in raw_names if str(name).strip()
                ]
        if "slew_joint_target_rate_rad_s" in data:
            cfg.slew_joint_target_rate_rad_s = max(
                0.0, float(data["slew_joint_target_rate_rad_s"])
            )
        if "mlp_entry_blend_s" in data:
            cfg.mlp_entry_blend_s = max(0.0, float(data["mlp_entry_blend_s"]))
        return cfg

    @property
    def default_dof_pos_np(self) -> Any:
        import numpy as np
        return np.array(self.default_dof_pos, dtype=np.float32)

    @property
    def policy_dt(self) -> float:
        return self.control_dt * max(1, self.freq_ratio)

    @property
    def joint_pos_lower_np(self) -> Any:
        import numpy as np
        return np.array(self.joint_pos_lower, dtype=np.float32)

    @property
    def joint_pos_upper_np(self) -> Any:
        import numpy as np
        return np.array(self.joint_pos_upper, dtype=np.float32)
