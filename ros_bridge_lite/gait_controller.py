from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(slots=True)
class GaitConfig:
    joint_names: tuple[str, ...]
    base_step_freq_hz: float = 1.2
    speed_to_freq_gain: float = 2.0
    max_step_freq_hz: float = 3.2
    step_scale: float = 0.5
    max_step_angle_rad: float = 0.38
    knee_coupling: float = 0.8
    ankle_coupling: float = 0.5
    turn_hip_gain: float = 0.15
    stand_knee_rad: float = 0.08


class GaitController:
    """
    Lightweight gait generator for bridge bring-up.

    This does not replace rl_control_new. It only converts velocity command
    (linear_x, angular_z) into joint targets so that the end-to-end
    "mobile joystick -> joint command -> Isaac articulation" chain can be
    verified quickly.
    """

    def __init__(self, cfg: GaitConfig) -> None:
        if len(cfg.joint_names) != 6:
            raise ValueError("gait joint_names must contain 6 entries")
        self.cfg = cfg
        self._phase = 0.0

    @property
    def joint_names(self) -> tuple[str, ...]:
        return self.cfg.joint_names

    def stand_pose(self) -> dict[str, float]:
        hip_l, knee_l, ankle_l, hip_r, knee_r, ankle_r = self.cfg.joint_names
        stand_knee = float(self.cfg.stand_knee_rad)
        return {
            hip_l: 0.0,
            knee_l: stand_knee,
            ankle_l: 0.0,
            hip_r: 0.0,
            knee_r: stand_knee,
            ankle_r: 0.0,
        }

    def update(self, linear_x: float, angular_z: float, dt: float) -> dict[str, float]:
        dt = max(1e-4, float(dt))
        speed = abs(float(linear_x))
        freq = self.cfg.base_step_freq_hz + speed * self.cfg.speed_to_freq_gain
        freq = max(0.0, min(self.cfg.max_step_freq_hz, freq))
        self._phase = (self._phase + (2.0 * math.pi * freq * dt)) % (2.0 * math.pi)

        left_phase = math.sin(self._phase)
        right_phase = math.sin(self._phase + math.pi)

        step = float(linear_x) * self.cfg.step_scale
        step = max(-self.cfg.max_step_angle_rad, min(self.cfg.max_step_angle_rad, step))

        turn_bias = float(angular_z) * self.cfg.turn_hip_gain
        turn_bias = max(-self.cfg.max_step_angle_rad * 0.5, min(self.cfg.max_step_angle_rad * 0.5, turn_bias))

        hip_left = step * left_phase - turn_bias
        hip_right = step * right_phase + turn_bias

        stand_knee = float(self.cfg.stand_knee_rad)
        knee_left = max(stand_knee, stand_knee + (-hip_left * self.cfg.knee_coupling))
        knee_right = max(stand_knee, stand_knee + (-hip_right * self.cfg.knee_coupling))

        ankle_left = -hip_left * self.cfg.ankle_coupling
        ankle_right = -hip_right * self.cfg.ankle_coupling

        hip_l, knee_l, ankle_l, hip_r, knee_r, ankle_r = self.cfg.joint_names
        return {
            hip_l: hip_left,
            knee_l: knee_left,
            ankle_l: ankle_left,
            hip_r: hip_right,
            knee_r: knee_right,
            ankle_r: ankle_right,
        }
