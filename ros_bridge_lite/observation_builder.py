"""750-dim observation vector construction for RL policy inference.

Port of FSMStateImpl.cpp lines 186-295 (StateMLP::Run observation assembly).
"""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray

from .policy_config import PolicyConfig


def gait_phase(
    timer: float,
    gait_cycle: float,
    left_offset: float,
    right_offset: float,
    left_ratio: float,
    right_ratio: float,
) -> NDArray[np.float64]:
    """Compute 6-dim gait phase encoding."""
    lp = (timer / gait_cycle + left_offset) - math.floor(timer / gait_cycle + left_offset)
    rp = (timer / gait_cycle + right_offset) - math.floor(timer / gait_cycle + right_offset)
    return np.array(
        [
            math.sin(2.0 * math.pi * lp),
            math.sin(2.0 * math.pi * rp),
            math.cos(2.0 * math.pi * lp),
            math.cos(2.0 * math.pi * rp),
            left_ratio,
            right_ratio,
        ],
        dtype=np.float64,
    )


class ObservationBuilder:
    """Construct the 750-dim observation vector for policy1107."""

    def __init__(self, cfg: PolicyConfig) -> None:
        self.cfg = cfg
        self._buffer = np.zeros(750, dtype=np.float32)
        self._last_frame = np.zeros(75, dtype=np.float32)
        self._first_run = True

    def reset(self) -> None:
        self._buffer[:] = 0.0
        self._last_frame[:] = 0.0
        self._first_run = True

    def build(
        self,
        ang_vel: NDArray[np.float64],
        gravity_dir: NDArray[np.float64],
        command: NDArray[np.float64],
        joint_pos: NDArray[np.float64],
        joint_vel: NDArray[np.float64],
        action_last: NDArray[np.float64],
        gait_timer: float,
    ) -> NDArray[np.float32]:
        """Build the 750-dim observation history buffer."""
        cfg = self.cfg
        frame = np.zeros(75, dtype=np.float32)

        frame[0:3] = ang_vel.astype(np.float32)
        frame[3:6] = gravity_dir.astype(np.float32)
        frame[6] = float(command[0] * cfg.obs_scales_lin_vel)
        frame[7] = float(command[1] * cfg.obs_scales_lin_vel)
        frame[8] = float(command[2] * cfg.obs_scales_ang_vel)

        default_dof = np.array(cfg.default_dof_pos, dtype=np.float64)
        for i, idx in enumerate(cfg.mujoco_to_isaac):
            frame[9 + i] = float((joint_pos[idx] - default_dof[idx]) * cfg.obs_scales_dof_pos)
            frame[29 + i] = float(joint_vel[idx] * cfg.obs_scales_dof_vel)

        frame[49:69] = np.clip(action_last, -100.0, 100.0)[:20].astype(np.float32)
        frame[69:75] = gait_phase(
            gait_timer,
            cfg.gait_cycle,
            cfg.left_theta_offset,
            cfg.right_theta_offset,
            cfg.left_phase_ratio,
            cfg.right_phase_ratio,
        ).astype(np.float32)
        self._last_frame[:] = frame

        if self._first_run:
            self._buffer[:75] = frame
            self._first_run = False
        else:
            self._buffer[:675] = self._buffer[75:]
            self._buffer[675:750] = frame

        return self._buffer

    def last_frame(self) -> NDArray[np.float32]:
        return self._last_frame.copy()
