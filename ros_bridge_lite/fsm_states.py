"""Finite State Machine for RL policy gait control.

Port of FSMStateImpl.cpp, FSMStateImpl.h, RobotFSM.cpp.
States: STOP → ZERO → MLP, driven by joystick/remote commands.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

import numpy as np
from numpy.typing import NDArray

from .imu_processor import IMUProcessor
from .motor_id_map import JOINT_NAMES
from .observation_builder import ObservationBuilder
from .policy_config import PolicyConfig


# --- Data structures ---


class FSMStateName(IntEnum):
    STOP = 0
    ZERO = 1
    MLP = 2


@dataclass
class XboxFlag:
    is_disable: bool = False
    fsm_state_command: str = ""
    x_speed_command: float = 0.0
    y_speed_command: float = 0.0
    yaw_speed_command: float = 0.0


@dataclass
class RobotData:
    """Equivalent of the C++ RobotData struct.

    q_a/q_dot_a: 20 joint positions/velocities (Mujoco order, after SP transform).
    imu_data: [yaw, pitch, roll, wx, wy, wz, ax, ay, az]
    q_d: 20 joint desired positions (output).
    """
    q_a: NDArray[np.float64] = field(default_factory=lambda: np.zeros(20, dtype=np.float64))
    q_dot_a: NDArray[np.float64] = field(default_factory=lambda: np.zeros(20, dtype=np.float64))
    tau_a: NDArray[np.float64] = field(default_factory=lambda: np.zeros(20, dtype=np.float64))
    q_d: NDArray[np.float64] = field(default_factory=lambda: np.zeros(20, dtype=np.float64))
    q_dot_d: NDArray[np.float64] = field(default_factory=lambda: np.zeros(20, dtype=np.float64))
    tau_d: NDArray[np.float64] = field(default_factory=lambda: np.zeros(20, dtype=np.float64))
    imu_data: NDArray[np.float64] = field(default_factory=lambda: np.zeros(9, dtype=np.float64))
    gait_a: float = 0.0
    pos_mode: bool = True


# --- Helpers ---


def fifth_poly(
    p0: NDArray, p0_dot: NDArray, p0_ddot: NDArray,
    p1: NDArray, p1_dot: NDArray, p1_ddot: NDArray,
    total_time: float, current_time: float,
) -> tuple[NDArray, NDArray, NDArray]:
    """5th order polynomial interpolation (port of BasicFunction.cpp FifthPoly)."""
    if current_time >= total_time:
        return p1.copy(), p1_dot.copy(), p1_ddot.copy()

    t = current_time
    T = total_time
    # Build coefficient matrix
    A = np.array([
        [1, 0, 0, 0, 0, 0],
        [0, 1, 0, 0, 0, 0],
        [0, 0, 0.5, 0, 0, 0],
        [-10/T**3, -6/T**2, -3/(2*T), 10/T**3, -4/T**2, 1/(2*T)],
        [15/T**4, 8/T**3, 3/(2*T**2), -15/T**4, 7/T**3, -1/(T**2)],
        [-6/T**5, -3/T**4, -1/(2*T**3), 6/T**5, -3/T**4, 1/(2*T**3)],
    ], dtype=np.float64)

    n = len(p0)
    pd = np.zeros(n, dtype=np.float64)
    pd_dot = np.zeros(n, dtype=np.float64)
    pd_ddot = np.zeros(n, dtype=np.float64)

    for i in range(n):
        x0 = np.array([p0[i], p0_dot[i], p0_ddot[i], p1[i], p1_dot[i], p1_ddot[i]], dtype=np.float64)
        a = A @ x0
        pd[i] = a[0] + a[1]*t + a[2]*t**2 + a[3]*t**3 + a[4]*t**4 + a[5]*t**5
        pd_dot[i] = a[1] + 2*a[2]*t + 3*a[3]*t**2 + 4*a[4]*t**3 + 5*a[5]*t**4
        pd_ddot[i] = 2*a[2] + 6*a[3]*t + 12*a[4]*t**2 + 20*a[5]*t**3

    return pd, pd_dot, pd_ddot


# --- FSM States ---


class FSMState(ABC):
    def __init__(self, robot_data: RobotData, cfg: PolicyConfig) -> None:
        self.robot_data = robot_data
        self.cfg = cfg
        self.joint_num = cfg.motor_num
        self.dt = cfg.control_dt
        self.timer = 0.0
        self._policy_elapsed = 0.0
        self._policy_tick_pending = True

    def _reset_timing(self) -> None:
        self.timer = 0.0
        self._policy_elapsed = 0.0
        self._policy_tick_pending = True

    def _is_policy_tick(self) -> bool:
        if self._policy_tick_pending:
            self._policy_tick_pending = False
            return True
        if self._policy_elapsed + 1e-9 >= self.cfg.policy_dt:
            self._policy_elapsed = max(0.0, self._policy_elapsed - self.cfg.policy_dt)
            return True
        return False

    def _advance_time(self) -> None:
        self.timer += self.dt
        self._policy_elapsed += self.dt

    @abstractmethod
    def on_enter(self) -> None: ...

    @abstractmethod
    def run(self, flag: XboxFlag) -> None: ...

    @abstractmethod
    def check_transition(self, flag: XboxFlag) -> FSMStateName: ...

    def on_exit(self) -> None: ...

    def debug_snapshot(self) -> dict[str, Any]:
        return {
            "state": self.__class__.__name__.removeprefix("State").upper(),
            "timer_s": float(self.timer),
            "dt_s": float(self.dt),
        }


class StateStop(FSMState):
    """STOP state: hold current position, keep model warm."""

    def __init__(self, robot_data: RobotData, cfg: PolicyConfig,
                 infer_request=None, input_tensor=None) -> None:
        super().__init__(robot_data, cfg)
        self._init_joint_pos = np.zeros(20, dtype=np.float64)
        self._hold_pose_override: NDArray[np.float64] | None = None
        self._preserve_hold_pose_once = False
        self._first_run = False
        self._infer_request = infer_request
        self._input_tensor = input_tensor

    def request_hold_pose(self, joint_pos: NDArray[np.float64]) -> None:
        self._hold_pose_override = joint_pos.copy()

    def on_enter(self) -> None:
        self._reset_timing()
        if self._hold_pose_override is not None:
            self._init_joint_pos = self._hold_pose_override.copy()
            self._hold_pose_override = None
            self._preserve_hold_pose_once = True
        else:
            self._init_joint_pos = self.robot_data.q_a.copy()
            self._preserve_hold_pose_once = False
        self._first_run = False
        print("[FSM] Enter STOP")

    def run(self, flag: XboxFlag) -> None:
        if not self._first_run:
            if not self._preserve_hold_pose_once:
                self._init_joint_pos = self.robot_data.q_a.copy()
            self._preserve_hold_pose_once = False
            self._first_run = True

        # Keep OpenVINO model warm
        if self._is_policy_tick() and self._infer_request is not None and self._input_tensor is not None:
            self._infer_request.infer({self._input_tensor: np.zeros(750, dtype=np.float32)})

        # Hold position
        self.robot_data.q_d[:] = self._init_joint_pos
        self.robot_data.q_dot_d[:] = 0.0
        self.robot_data.tau_d[:] = 0.0
        self.robot_data.pos_mode = True
        self._advance_time()

    def check_transition(self, flag: XboxFlag) -> FSMStateName:
        if flag.fsm_state_command == "gotoZero":
            print("[FSM] STOP → ZERO")
            return FSMStateName.ZERO
        return FSMStateName.STOP


class StateZero(FSMState):
    """ZERO state: interpolate to default standing pose over 2 seconds."""

    def __init__(self, robot_data: RobotData, cfg: PolicyConfig,
                 infer_request=None, input_tensor=None) -> None:
        super().__init__(robot_data, cfg)
        self._total_time = 2.0
        self._zero_finish = False
        self._first_run = False
        self._init_joint_pos = np.zeros(20, dtype=np.float64)
        self._zero_pos = cfg.default_dof_pos_np.copy()
        self._infer_request = infer_request
        self._input_tensor = input_tensor

    def on_enter(self) -> None:
        self._reset_timing()
        self._init_joint_pos = self.robot_data.q_a.copy()
        self._zero_finish = False
        self._first_run = False
        print("[FSM] Enter ZERO")

    def run(self, flag: XboxFlag) -> None:
        if not self._first_run:
            self._init_joint_pos = self.robot_data.q_a.copy()
            self._first_run = True

        # Keep model warm
        if self._is_policy_tick() and self._infer_request is not None and self._input_tensor is not None:
            self._infer_request.infer({self._input_tensor: np.zeros(750, dtype=np.float32)})

        zero = np.zeros(self.joint_num, dtype=np.float64)

        if self.timer < self._total_time:
            q, qd, _ = fifth_poly(
                self._init_joint_pos, zero, zero,
                self._zero_pos, zero, zero,
                self._total_time, self.timer,
            )
        else:
            self._zero_finish = True
            q = self._zero_pos.copy()
            qd = zero.copy()

        self.robot_data.q_d[:] = q
        self.robot_data.q_dot_d[:] = qd
        self.robot_data.tau_d[:] = 0.0
        self.robot_data.pos_mode = True
        self._advance_time()

    def check_transition(self, flag: XboxFlag) -> FSMStateName:
        if flag.fsm_state_command == "gotoMLP" and self._zero_finish:
            print("[FSM] ZERO → MLP")
            return FSMStateName.MLP
        if flag.fsm_state_command == "gotoStop":
            print("[FSM] ZERO → STOP")
            return FSMStateName.STOP
        return FSMStateName.ZERO


class StateMLP(FSMState):
    """MLP state: RL policy inference for walking.

    Core loop: command smoothing → IMU processing → observation construction
    → OpenVINO inference → output remapping → joint target scaling.
    """

    def __init__(self, robot_data: RobotData, cfg: PolicyConfig,
                 infer_request=None, input_tensor=None) -> None:
        super().__init__(robot_data, cfg)
        self._infer_request = infer_request
        self._input_tensor = input_tensor

        self._imu_processor = IMUProcessor(cfg.omega_cutoff_hz, cfg.omega_damping, cfg.control_dt)
        self._obs_builder = ObservationBuilder(cfg)

        self._command = np.zeros(3, dtype=np.float64)
        self._joystick_command = np.zeros(3, dtype=np.float64)
        self._command_scales = np.array([cfg.obs_scales_lin_vel, cfg.obs_scales_lin_vel, cfg.obs_scales_ang_vel])

        self._action_last = np.zeros(20, dtype=np.float64)
        self._output_data = np.zeros(20, dtype=np.float64)
        self._default_dof_pos = cfg.default_dof_pos_np.copy()
        self._entry_joint_pos = self._default_dof_pos.copy()
        self._obs_joint_names = tuple(JOINT_NAMES[idx] for idx in cfg.mujoco_to_isaac)
        self._last_obs_history = np.zeros(750, dtype=np.float32)
        self._last_obs_frame = np.zeros(75, dtype=np.float32)
        self._last_ang_vel = np.zeros(3, dtype=np.float64)
        self._last_gravity_dir = np.array([0.0, 0.0, -1.0], dtype=np.float64)
        self._last_imu_euler = np.zeros(3, dtype=np.float64)
        self._last_imu_omega = np.zeros(3, dtype=np.float64)
        self._last_joint_pos = np.zeros(20, dtype=np.float64)
        self._last_joint_vel = np.zeros(20, dtype=np.float64)
        self._last_raw_output_model_order = np.zeros(20, dtype=np.float64)
        self._last_raw_output_mujoco_order = np.zeros(20, dtype=np.float64)
        self._last_pre_entry_targets = self._default_dof_pos.copy()
        self._last_post_entry_targets = self._default_dof_pos.copy()
        self._last_entry_blend_alpha = 1.0
        self._last_infer_state_timer_s = 0.0
        self._last_obs_gait_timer_s = 0.0
        self._infer_count = 0

        self._timer_gait = 0.0
        self._first_run = True

    def on_enter(self) -> None:
        self._reset_timing()
        self._timer_gait = 0.0
        self._command[:] = 0.0
        self._joystick_command[:] = 0.0
        self._action_last[:] = 0.0
        self._output_data[:] = 0.0
        self._entry_joint_pos = self.robot_data.q_a.copy()
        self._obs_builder.reset()
        self._last_obs_history[:] = 0.0
        self._last_obs_frame[:] = 0.0
        self._last_ang_vel[:] = 0.0
        self._last_gravity_dir[:] = np.array([0.0, 0.0, -1.0], dtype=np.float64)
        self._last_imu_euler[:] = 0.0
        self._last_imu_omega[:] = 0.0
        self._last_joint_pos[:] = self.robot_data.q_a
        self._last_joint_vel[:] = self.robot_data.q_dot_a
        self._last_raw_output_model_order[:] = 0.0
        self._last_raw_output_mujoco_order[:] = 0.0
        self._last_pre_entry_targets[:] = self._default_dof_pos
        self._last_post_entry_targets[:] = self._default_dof_pos
        self._last_entry_blend_alpha = 1.0
        self._last_infer_state_timer_s = 0.0
        self._last_obs_gait_timer_s = 0.0
        self._infer_count = 0
        self._first_run = True
        print("[FSM] Enter MLP")

    def run(self, flag: XboxFlag) -> None:
        cfg = self.cfg
        step_scale = max(0.0, self.dt / max(1e-6, cfg.control_dt))
        x_slope = cfg.x_command_slope * step_scale
        x_release_slope = 0.0015 * step_scale
        yaw_slope = cfg.yaw_command_slope * step_scale

        # --- Command smoothing (slope limiter with deadzone) ---
        self._joystick_command[0] = flag.x_speed_command
        self._joystick_command[1] = flag.y_speed_command
        self._joystick_command[2] = flag.yaw_speed_command

        # X velocity: slope-limited
        x_cmd = self._joystick_command[0]
        if abs(x_cmd) > cfg.x_deadzone:
            diff = x_cmd - self._command[0]
            if abs(diff) > x_slope:
                self._command[0] += x_slope * math.copysign(1.0, diff)
            else:
                self._command[0] = x_cmd
        else:
            diff = x_cmd - self._command[0]
            if abs(diff) > x_release_slope:
                self._command[0] += x_release_slope * math.copysign(1.0, diff)
            else:
                self._command[0] = x_cmd

        # Y velocity: direct follow
        self._command[1] = self._joystick_command[1]

        # Yaw velocity: slope-limited with deadzone
        yaw_cmd = self._joystick_command[2]
        if abs(yaw_cmd - self._command[2]) > yaw_slope and abs(yaw_cmd) > cfg.yaw_deadzone:
            self._command[2] += yaw_slope * math.copysign(1.0, yaw_cmd - self._command[2])
        else:
            self._command[2] = yaw_cmd

        # Match the SDK cadence: IMU filtering runs every control step, while
        # history shifting + MLP inference only refresh on policy ticks.
        imu = self.robot_data.imu_data
        ang_vel, gravity_dir = self._imu_processor.process(
            imu[0], imu[1], imu[2],  # yaw, pitch, roll
            imu[3:6],                 # omega
        )
        self._last_imu_euler[:] = imu[0:3]
        self._last_imu_omega[:] = imu[3:6]
        self._last_ang_vel[:] = ang_vel
        self._last_gravity_dir[:] = gravity_dir

        if self._is_policy_tick():
            # Refresh observation/inference at the official 50 Hz policy cadence
            # while reusing the last action between refreshes.
            # Match the SDK cadence: the control state advances every 0.0025 s,
            # but in this HTTP bridge we only shift the 10x75 observation history
            # and refresh the MLP output every 0.02 s of accumulated control time.
            obs = self._obs_builder.build(
                ang_vel=ang_vel,
                gravity_dir=gravity_dir,
                command=self._command,
                joint_pos=self.robot_data.q_a,
                joint_vel=self.robot_data.q_dot_a,
                action_last=self._action_last,
                gait_timer=self._timer_gait,
            )
            self._last_obs_history[:] = obs
            if hasattr(self._obs_builder, "last_frame"):
                self._last_obs_frame[:] = self._obs_builder.last_frame()
            else:
                self._last_obs_frame[:] = np.array(obs[:75], dtype=np.float32)
            self._last_joint_pos[:] = self.robot_data.q_a
            self._last_joint_vel[:] = self.robot_data.q_dot_a
            self._last_obs_gait_timer_s = float(self._timer_gait)

            if self._infer_request is not None and self._input_tensor is not None:
                self._infer_request.infer({self._input_tensor: obs})
                output = self._infer_request.get_output_tensor().data.copy()
                self._output_data[:] = output[:20]
            else:
                # Fallback: zero output (model not loaded)
                self._output_data[:] = 0.0
            self._last_raw_output_model_order[:] = self._output_data
            self._last_infer_state_timer_s = float(self.timer)
            self._infer_count += 1

        # --- Output remapping (Isaac → Mujoco order) and scaling ---
        i2m = cfg.isaac_to_mujoco
        mlp_out_reordered = np.zeros(20, dtype=np.float64)
        for i in range(20):
            mlp_out_reordered[i] = self._output_data[i2m[i]]
        self._last_raw_output_mujoco_order[:] = mlp_out_reordered

        q_d_nominal = mlp_out_reordered * cfg.action_scales + self._default_dof_pos
        self._last_pre_entry_targets[:] = q_d_nominal
        q_d = q_d_nominal.copy()
        alpha = 1.0
        if cfg.simulation and cfg.mlp_entry_blend_s > 1e-6:
            alpha = min(1.0, (self.timer + self.dt) / cfg.mlp_entry_blend_s)
            q_d = (1.0 - alpha) * self._entry_joint_pos + alpha * q_d
        self._last_entry_blend_alpha = float(alpha)
        self._last_post_entry_targets[:] = q_d

        self.robot_data.q_d[:] = q_d
        self.robot_data.q_dot_d[:] = 0.0
        self.robot_data.tau_d[:] = 0.0
        self.robot_data.pos_mode = False

        # Update state for next iteration
        self._action_last[:] = self._output_data
        self._advance_time()
        self._timer_gait += self.dt
        self.robot_data.gait_a = 1.0  # gait active flag

    def _map_model_order(self, values: NDArray[np.float64] | NDArray[np.float32]) -> dict[str, float]:
        return {
            self._obs_joint_names[i]: float(values[i])
            for i in range(min(len(self._obs_joint_names), len(values)))
        }

    @staticmethod
    def _map_joint_order(values: NDArray[np.float64] | NDArray[np.float32]) -> dict[str, float]:
        return {
            JOINT_NAMES[i]: float(values[i])
            for i in range(min(len(JOINT_NAMES), len(values)))
        }

    def debug_snapshot(self) -> dict[str, Any]:
        frame = self._last_obs_frame
        return {
            "state": "MLP",
            "timer_s": float(self.timer),
            "dt_s": float(self.dt),
            "gait_timer_s": float(self._timer_gait),
            "last_obs_gait_timer_s": float(self._last_obs_gait_timer_s),
            "inference_count": int(self._infer_count),
            "last_infer_state_timer_s": float(self._last_infer_state_timer_s),
            "command": {
                "x": float(self._command[0]),
                "y": float(self._command[1]),
                "yaw": float(self._command[2]),
            },
            "joystick_command": {
                "x": float(self._joystick_command[0]),
                "y": float(self._joystick_command[1]),
                "yaw": float(self._joystick_command[2]),
            },
            "imu": {
                "feedback_euler_zyx": {
                    "yaw": float(self._last_imu_euler[0]),
                    "pitch": float(self._last_imu_euler[1]),
                    "roll": float(self._last_imu_euler[2]),
                },
                "feedback_omega": [float(v) for v in self._last_imu_omega.tolist()],
                "processed_ang_vel": [float(v) for v in self._last_ang_vel.tolist()],
                "gravity_dir": [float(v) for v in self._last_gravity_dir.tolist()],
            },
            "obs": {
                "joint_order": list(self._obs_joint_names),
                "frame": [float(v) for v in frame.tolist()],
                "command_terms": [float(v) for v in frame[6:9].tolist()],
                "joint_pos_terms": self._map_model_order(frame[9:29]),
                "joint_vel_terms": self._map_model_order(frame[29:49]),
                "action_last_terms": self._map_model_order(frame[49:69]),
                "gait_phase_terms": [float(v) for v in frame[69:75].tolist()],
            },
            "feedback_joint_pos": self._map_joint_order(self._last_joint_pos),
            "feedback_joint_vel": self._map_joint_order(self._last_joint_vel),
            "policy": {
                "raw_output_model_order": self._map_model_order(self._last_raw_output_model_order),
                "raw_output_mujoco_order": self._map_joint_order(self._last_raw_output_mujoco_order),
                "pre_entry_targets": self._map_joint_order(self._last_pre_entry_targets),
                "post_entry_targets": self._map_joint_order(self._last_post_entry_targets),
                "entry_blend_alpha": float(self._last_entry_blend_alpha),
            },
        }

    def check_transition(self, flag: XboxFlag) -> FSMStateName:
        # Joint limit check (matching C++ FSMStateImpl.cpp:326-330)
        q = self.robot_data.q_a
        if len(q) > 7 and (q[1] >= self.cfg.joint_pos_limit or q[7] >= self.cfg.joint_pos_limit):
            print(f"[FSM] Joint limit exceeded: l={q[1]:.3f} r={q[7]:.3f} -> STOP")
            return FSMStateName.STOP

        if flag.fsm_state_command == "gotoStop":
            print("[FSM] MLP -> STOP")
            return FSMStateName.STOP
        return FSMStateName.MLP


# --- Robot FSM ---


class RobotFSM:
    """Finite state machine managing STOP → ZERO → MLP transitions."""

    def __init__(self, cfg: PolicyConfig, robot_data: RobotData,
                 infer_request=None, input_tensor=None) -> None:
        self._robot_data = robot_data
        self._cfg = cfg

        self._states: dict[FSMStateName, FSMState] = {
            FSMStateName.STOP: StateStop(robot_data, cfg, infer_request, input_tensor),
            FSMStateName.ZERO: StateZero(robot_data, cfg, infer_request, input_tensor),
            FSMStateName.MLP: StateMLP(robot_data, cfg, infer_request, input_tensor),
        }

        self._current_name = FSMStateName.STOP
        self._current_state = self._states[FSMStateName.STOP]
        self._current_state.on_enter()
        self._disable_joints = False

    @property
    def current_state(self) -> FSMStateName:
        return self._current_name

    @property
    def disable_joints(self) -> bool:
        return self._disable_joints

    def set_step_dt(self, dt: float) -> None:
        step_dt = max(1e-4, float(dt))
        for state in self._states.values():
            state.dt = step_dt

    def run(self, flag: XboxFlag) -> None:
        # Emergency stop
        if flag.is_disable:
            self._disable_joints = True
            print("[FSM] Emergency stop triggered")
            return
        self._disable_joints = False

        # Safety check: NaN in feedback
        if np.any(np.isnan(self._robot_data.q_a)) or np.any(np.isnan(self._robot_data.q_dot_a)):
            print("[FSM] NaN in joint feedback, skipping")
            return

        # Safety check: command bounds
        if (abs(flag.x_speed_command) > 5.0 or abs(flag.y_speed_command) > 5.0
                or abs(flag.yaw_speed_command) > 5.0):
            print("[FSM] Command out of bounds, skipping")
            return

        # Run current state
        self._current_state.run(flag)

        # Check transition
        next_name = self._current_state.check_transition(flag)
        if next_name != self._current_name:
            if next_name == FSMStateName.STOP and self._current_name == FSMStateName.ZERO:
                stop_state = self._states[FSMStateName.STOP]
                if isinstance(stop_state, StateStop):
                    stop_state.request_hold_pose(self._cfg.default_dof_pos_np)
            self._current_state.on_exit()
            self._current_name = next_name
            self._current_state = self._states[next_name]
            self._current_state.on_enter()

    def debug_snapshot(self) -> dict[str, Any]:
        snapshot = self._current_state.debug_snapshot()
        snapshot.setdefault("state", self._current_name.name)
        return snapshot
