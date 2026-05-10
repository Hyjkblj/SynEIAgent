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
    """Compute 6-dim gait phase encoding.

    Returns [sin(left), sin(right), cos(left), cos(right), left_ratio, right_ratio].
    """
    lp = (timer / gait_cycle + left_offset) - math.floor(timer / gait_cycle + left_offset)
    rp = (timer / gait_cycle + right_offset) - math.floor(timer / gait_cycle + right_offset)
    return np.array([
        math.sin(2.0 * math.pi * lp),
        math.sin(2.0 * math.pi * rp),
        math.cos(2.0 * math.pi * lp),
        math.cos(2.0 * math.pi * rp),
        left_ratio,
        right_ratio,
    ], dtype=np.float64)


class ObservationBuilder:
    """Constructs the 750-dim observation vector for policy1107.

    10 frames × 75 dims/frame. Each frame:
      [ang_vel(3), gravity(3), command(3), q_dev(20), qd(20), action(20), gait(6)]
    """

    def __init__(self, cfg: PolicyConfig) -> None:
        self.cfg = cfg
        self._buffer = np.zeros(750, dtype=np.float32)
        self._first_run = True

    def reset(self) -> None:
        self._buffer[:] = 0.0
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
        """Build 750-dim observation and shift buffer.

        Args:
            ang_vel: (3,) filtered angular velocity in world frame
            gravity_dir: (3,) gravity direction in body frame
            command: (3,) [x_vel, y_vel, yaw_vel] scaled
            joint_pos: (20,) current joint positions (Mujoco order)
            joint_vel: (20,) current joint velocities (Mujoco order)
            action_last: (20,) previous action output
            gait_timer: gait phase timer

        Returns:
            750-dim float32 observation buffer
        """
        cfg = self.cfg

        # Assemble 75-dim frame
        frame = np.zeros(75, dtype=np.float32)

        # [0-2] angular velocity
        frame[0] = ang_vel[0]
        frame[1] = ang_vel[1]
        frame[2] = ang_vel[2]

        # [3-5] gravity direction
        frame[3] = gravity_dir[0]
        frame[4] = gravity_dir[1]
        frame[5] = gravity_dir[2]

        # [6-8] velocity command (scaled)
        frame[6] = command[0] * cfg.obs_scales_lin_vel
        frame[7] = command[1] * cfg.obs_scales_lin_vel
        frame[8] = command[2] * cfg.obs_scales_ang_vel

        # [9-28] joint position deviation (reordered to Isaac Sim indices)
        default_dof = np.array(cfg.default_dof_pos, dtype=np.float64)
        m2i = cfg.mujoco_to_isaac
        for i in range(20):
            idx = m2i[i]
            frame[9 + i] = (joint_pos[idx] - default_dof[idx]) * cfg.obs_scales_dof_pos

        # [29-48] joint velocities (reordered)
        for i in range(20):
            idx = m2i[i]
            frame[29 + i] = joint_vel[idx] * cfg.obs_scales_dof_vel

        # [49-68] previous action (clipped)
        clipped = np.clip(action_last, -100.0, 100.0)
        frame[49:69] = clipped[:20].astype(np.float32)

        # [69-74] gait phase
        gp = gait_phase(
            gait_timer,
            cfg.gait_cycle,
            cfg.left_theta_offset,
            cfg.right_theta_offset,
            cfg.left_phase_ratio,
            cfg.right_phase_ratio,
        )
        frame[69:75] = gp.astype(np.float32)

        # Shift buffer: drop oldest 75, append new frame
        if self._first_run:
            self._first_run = False
        else:
            self._buffer[:675] = self._buffer[75:]
        self._buffer[675:750] = frame

        return self._buffer
