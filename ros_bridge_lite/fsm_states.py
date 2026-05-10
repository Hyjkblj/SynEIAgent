"""Finite State Machine for RL policy gait control.

Port of FSMStateImpl.cpp, FSMStateImpl.h, RobotFSM.cpp.
States: STOP → ZERO → MLP, driven by joystick/remote commands.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import IntEnum

import numpy as np
from numpy.typing import NDArray

from .imu_processor import IMUProcessor
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
        self.dt = cfg.dt
        self.timer = 0.0

    @abstractmethod
    def on_enter(self) -> None: ...

    @abstractmethod
    def run(self, flag: XboxFlag) -> None: ...

    @abstractmethod
    def check_transition(self, flag: XboxFlag) -> FSMStateName: ...

    def on_exit(self) -> None: ...


class StateStop(FSMState):
    """STOP state: hold current position, keep model warm."""

    def __init__(self, robot_data: RobotData, cfg: PolicyConfig,
                 infer_request=None, input_tensor=None) -> None:
        super().__init__(robot_data, cfg)
        self._init_joint_pos = np.zeros(20, dtype=np.float64)
        self._first_run = False
        self._infer_request = infer_request
        self._input_tensor = input_tensor

    def on_enter(self) -> None:
        self.timer = 0.0
        self._init_joint_pos = self.robot_data.q_a.copy()
        self._first_run = False
        print("[FSM] Enter STOP")

    def run(self, flag: XboxFlag) -> None:
        if not self._first_run:
            self._init_joint_pos = self.robot_data.q_a.copy()
            self._first_run = True

        # Keep OpenVINO model warm
        if self._infer_request is not None and self._input_tensor is not None:
            self._infer_request.infer({self._input_tensor: np.zeros(750, dtype=np.float32)})

        # Hold position
        self.robot_data.q_d[:] = self._init_joint_pos
        self.robot_data.q_dot_d[:] = 0.0
        self.robot_data.tau_d[:] = 0.0
        self.robot_data.pos_mode = True
        self.timer += self.dt

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
        self.timer = 0.0
        self._init_joint_pos = self.robot_data.q_a.copy()
        self._zero_finish = False
        self._first_run = False
        print("[FSM] Enter ZERO")

    def run(self, flag: XboxFlag) -> None:
        if not self._first_run:
            self._init_joint_pos = self.robot_data.q_a.copy()
            self._first_run = True

        # Keep model warm
        if self._infer_request is not None and self._input_tensor is not None:
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
        self.timer += self.dt

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

        self._imu_processor = IMUProcessor(cfg.omega_cutoff_hz, cfg.omega_damping, cfg.dt)
        self._obs_builder = ObservationBuilder(cfg)

        self._command = np.zeros(3, dtype=np.float64)
        self._joystick_command = np.zeros(3, dtype=np.float64)
        self._command_scales = np.array([cfg.obs_scales_lin_vel, cfg.obs_scales_lin_vel, cfg.obs_scales_ang_vel])

        self._action_last = np.zeros(20, dtype=np.float64)
        self._output_data = np.zeros(20, dtype=np.float64)
        self._default_dof_pos = cfg.default_dof_pos_np.copy()

        self._timer_gait = 0.0
        self._first_run = True

    def on_enter(self) -> None:
        self.timer = 0.0
        self._timer_gait = 0.0
        self._command[:] = 0.0
        self._joystick_command[:] = 0.0
        self._action_last[:] = 0.0
        self._output_data[:] = 0.0
        self._obs_builder.reset()
        self._first_run = True
        print("[FSM] Enter MLP")

    def run(self, flag: XboxFlag) -> None:
        cfg = self.cfg

        # --- Command smoothing (slope limiter with deadzone) ---
        self._joystick_command[0] = flag.x_speed_command
        self._joystick_command[1] = flag.y_speed_command
        self._joystick_command[2] = flag.yaw_speed_command

        # X velocity: slope-limited
        x_cmd = self._joystick_command[0]
        if abs(x_cmd) > cfg.x_deadzone:
            diff = x_cmd - self._command[0]
            if abs(diff) > cfg.x_command_slope:
                self._command[0] += cfg.x_command_slope * math.copysign(1.0, diff)
            else:
                self._command[0] = x_cmd
        else:
            diff = x_cmd - self._command[0]
            if abs(diff) > 0.0015:
                self._command[0] += 0.0015 * math.copysign(1.0, diff)
            else:
                self._command[0] = x_cmd

        # Y velocity: direct follow
        self._command[1] = self._joystick_command[1]

        # Yaw velocity: slope-limited with deadzone
        yaw_cmd = self._joystick_command[2]
        if abs(yaw_cmd - self._command[2]) > cfg.yaw_command_slope and abs(yaw_cmd) > cfg.yaw_deadzone:
            self._command[2] += cfg.yaw_command_slope * math.copysign(1.0, yaw_cmd - self._command[2])
        else:
            self._command[2] = yaw_cmd

        # --- IMU processing ---
        imu = self.robot_data.imu_data
        ang_vel, gravity_dir = self._imu_processor.process(
            imu[0], imu[1], imu[2],  # yaw, pitch, roll
            imu[3:6],                 # omega
        )

        # --- Observation construction ---
        obs = self._obs_builder.build(
            ang_vel=ang_vel,
            gravity_dir=gravity_dir,
            command=self._command,
            joint_pos=self.robot_data.q_a,
            joint_vel=self.robot_data.q_dot_a,
            action_last=self._action_last,
            gait_timer=self._timer_gait,
        )

        # --- OpenVINO inference ---
        if self._infer_request is not None and self._input_tensor is not None:
            self._infer_request.infer({self._input_tensor: obs})
            output = self._infer_request.get_output_tensor().data.copy()
            self._output_data[:] = output[:20]
        else:
            # Fallback: zero output (model not loaded)
            self._output_data[:] = 0.0

        # --- Output remapping (Isaac → Mujoco order) and scaling ---
        i2m = cfg.isaac_to_mujoco
        mlp_out_reordered = np.zeros(20, dtype=np.float64)
        for i in range(20):
            mlp_out_reordered[i] = self._output_data[i2m[i]]

        q_d = mlp_out_reordered * cfg.action_scales + self._default_dof_pos

        self.robot_data.q_d[:] = q_d
        self.robot_data.q_dot_d[:] = 0.0
        self.robot_data.tau_d[:] = 0.0
        self.robot_data.pos_mode = False

        # Update state for next iteration
        self._action_last[:] = self._output_data
        self.timer += self.dt
        self._timer_gait += self.dt
        self.robot_data.gait_a = 1.0  # gait active flag

    def check_transition(self, flag: XboxFlag) -> FSMStateName:
        # Joint limit check (matching C++ FSMStateImpl.cpp:326-330)
        q = self.robot_data.q_a
        if len(q) > 13 and (q[7] >= self.cfg.joint_pos_limit or q[13] >= self.cfg.joint_pos_limit):
            print(f"[FSM] Joint limit exceeded: l={q[7]:.3f} r={q[13]:.3f} → STOP")
            return FSMStateName.STOP

        if flag.fsm_state_command == "gotoStop":
            print("[FSM] MLP → STOP")
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
            self._current_state.on_exit()
            self._current_name = next_name
            self._current_state = self._states[next_name]
            self._current_state.on_enter()
