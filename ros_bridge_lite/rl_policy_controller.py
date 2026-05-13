"""RL Policy Controller — top-level integration of OpenVINO inference with ROS2.

Subscribes to robot feedback (/leg/status, /arm/status, /imu/status),
runs RL policy via FSM, and publishes joint targets (/leg/cmd_ctrl, /arm/cmd_ctrl).
"""

from __future__ import annotations

import threading
import time
from typing import Any

import numpy as np
from numpy.typing import NDArray

from .fsm_states import FSMStateName, RobotData, RobotFSM, StateStop, XboxFlag
from .motor_id_map import CAN_ID_TO_INDEX, INDEX_TO_CAN_ID, JOINT_NAMES, NAME_TO_INDEX
from .policy_config import PolicyConfig
from .sp_transform import SPTransformBase, create_sp_transform


class RLPolicyController:
    """RL policy controller with OpenVINO inference and ROS2 I/O."""

    def __init__(self, cfg: PolicyConfig, node: Any) -> None:
        self.cfg = cfg
        self._node = node
        self._lock = threading.Lock()

        # --- Robot data ---
        self._robot_data = RobotData()
        self._feedback_pos = np.zeros(20, dtype=np.float64)
        self._feedback_vel = np.zeros(20, dtype=np.float64)
        self._feedback_tor = np.zeros(20, dtype=np.float64)
        self._feedback_imu = np.zeros(9, dtype=np.float64)

        # --- Command state ---
        self._target_x_vel = 0.0
        self._target_y_vel = 0.0
        self._target_yaw_vel = 0.0
        self._transition_request_until = 0.0
        self._pending_gait_transition = False

        # --- OpenVINO model ---
        self._infer_request = None
        self._input_tensor = None
        if cfg.model_xml_path:
            self._load_model()

        # --- Serial-parallel transform ---
        self._sp_transform: SPTransformBase = create_sp_transform(
            cfg.simulation,
            cfg.sp_lib_path,
            allow_simulation_transform=bool(cfg.enable_sim_sp_transform),
        )
        self._joint_pos_lower = np.array(cfg.joint_pos_lower, dtype=np.float64)
        self._joint_pos_upper = np.array(cfg.joint_pos_upper, dtype=np.float64)
        self._selective_clamp_indices = self._resolve_joint_indices(
            cfg.clamp_joint_target_names
        )
        self._selective_upper_only_clamp_indices = self._resolve_joint_indices(
            cfg.clamp_joint_target_upper_only_names
        )
        self._selective_upper_only_clamp_margin_rad = max(
            0.0, float(cfg.clamp_joint_target_upper_only_margin_rad)
        )
        self._selective_upper_only_clamp_delay_s = max(
            0.0, float(cfg.clamp_joint_target_upper_only_delay_s)
        )
        self._slew_limit_indices = self._resolve_joint_indices(
            cfg.slew_joint_target_names
        )
        self._slew_limit_rate_rad_s = max(0.0, float(cfg.slew_joint_target_rate_rad_s))
        self._last_output_targets = np.array(cfg.default_dof_pos, dtype=np.float64)

        # --- FSM ---
        self._robot_fsm = RobotFSM(cfg, self._robot_data, self._infer_request, self._input_tensor)
        self._prime_stop_hold_pose()

        # --- ROS2 publishers (skipped when node is None, i.e. HTTP mode) ---
        self._cmd_motor_ctrl_type = None
        self._leg_pub = None
        self._arm_pub = None
        if node is not None:
            self._try_create_publishers()

        # --- ROS2 subscribers (skipped when node is None, i.e. HTTP mode) ---
        self._sub_leg = None
        self._sub_arm = None
        self._sub_imu = None
        if node is not None:
            self._create_subscribers()

        print(f"[RLPolicyController] Initialized (simulation={cfg.simulation}, "
              f"model={'loaded' if self._infer_request else 'none'})")

    def _prime_stop_hold_pose(self) -> None:
        """Seed STOP with the nominal stand pose before live feedback arrives.

        In HTTP simulation mode, the FSM boots before the first Isaac feedback
        sample is injected. Without this seed, STOP latches an all-zero pose
        and relies on Isaac's startup hold to keep the robot standing.
        """
        stop_state = self._robot_fsm._states.get(FSMStateName.STOP)
        if not isinstance(stop_state, StateStop):
            return
        self._robot_data.q_d[:] = self.cfg.default_dof_pos_np
        self._last_output_targets[:] = self.cfg.default_dof_pos_np
        stop_state.request_hold_pose(self.cfg.default_dof_pos_np)
        if self._robot_fsm.current_state == FSMStateName.STOP:
            stop_state.on_enter()

    def _load_model(self) -> None:
        import openvino as ov

        core = ov.Core()
        model = core.read_model(self.cfg.model_xml_path, self.cfg.model_bin_path)
        compiled = core.compile_model(model, "CPU")
        self._infer_request = compiled.create_infer_request()
        # 使用 compiled model 的 input 对象作为 key（兼容 OpenVINO 2026+）
        self._input_tensor = compiled.input(0)

        # Warmup inference
        for _ in range(3):
            self._infer_request.infer({self._input_tensor: np.zeros(750, dtype=np.float32)})
        print("[RLPolicyController] OpenVINO model loaded and warmed up")

    def _try_create_publishers(self) -> None:
        try:
            from bodyctrl_msgs.msg import CmdMotorCtrl  # type: ignore
            self._cmd_motor_ctrl_type = CmdMotorCtrl
            self._leg_pub = self._node.create_publisher(CmdMotorCtrl, "/leg/cmd_ctrl", 10)
            self._arm_pub = self._node.create_publisher(CmdMotorCtrl, "/arm/cmd_ctrl", 10)
        except Exception as e:
            print(f"[RLPolicyController] CmdMotorCtrl unavailable: {e}")

    def _create_subscribers(self) -> None:
        try:
            from bodyctrl_msgs.msg import Imu, MotorStatusMsg  # type: ignore

            self._sub_leg = self._node.create_subscription(
                MotorStatusMsg, "/leg/status", self._on_leg_status, 10)
            self._sub_arm = self._node.create_subscription(
                MotorStatusMsg, "/arm/status", self._on_arm_status, 10)
            self._sub_imu = self._node.create_subscription(
                Imu, "/imu/status", self._on_imu_status, 10)
        except Exception as e:
            print(f"[RLPolicyController] Feedback topics unavailable: {e}")

    # --- ROS2 callbacks ---

    def _on_leg_status(self, msg: Any) -> None:
        with self._lock:
            for s in msg.status:
                idx = CAN_ID_TO_INDEX.get(int(s.name), -1)
                if 0 <= idx < 20:
                    self._feedback_pos[idx] = float(s.pos)
                    self._feedback_vel[idx] = float(s.speed)
                    self._feedback_tor[idx] = float(s.current)

    def _on_arm_status(self, msg: Any) -> None:
        with self._lock:
            for s in msg.status:
                idx = CAN_ID_TO_INDEX.get(int(s.name), -1)
                if 0 <= idx < 20:
                    self._feedback_pos[idx] = float(s.pos)
                    self._feedback_vel[idx] = float(s.speed)
                    self._feedback_tor[idx] = float(s.current)

    def _on_imu_status(self, msg: Any) -> None:
        with self._lock:
            self._feedback_imu[0] = float(msg.euler.yaw)
            self._feedback_imu[1] = float(msg.euler.pitch)
            self._feedback_imu[2] = float(msg.euler.roll)
            self._feedback_imu[3] = float(msg.angular_velocity.x)
            self._feedback_imu[4] = float(msg.angular_velocity.y)
            self._feedback_imu[5] = float(msg.angular_velocity.z)
            self._feedback_imu[6] = float(msg.linear_acceleration.x)
            self._feedback_imu[7] = float(msg.linear_acceleration.y)
            self._feedback_imu[8] = float(msg.linear_acceleration.z)

    # --- Direct feedback injection (no ROS2) ---

    def set_joint_feedback(self, positions: list[float], velocities: list[float] | None = None,
                           efforts: list[float] | None = None) -> None:
        """Inject 20-joint feedback directly (bypasses ROS2 subscribers)."""
        pos = np.array(list(positions[:20]), dtype=np.float64)
        vel = np.array(list((velocities or [0.0] * 20)[:20]), dtype=np.float64)
        tor = np.array(list((efforts or [0.0] * 20)[:20]), dtype=np.float64)

        if self._should_apply_sp_feedback_transform():
            pos, vel, tor = self._apply_sp_forward(pos, vel, tor)

        with self._lock:
            for i in range(min(20, len(pos))):
                self._feedback_pos[i] = float(pos[i])
                self._feedback_vel[i] = float(vel[i])
                self._feedback_tor[i] = float(tor[i])

    def set_imu_feedback(self, yaw: float, pitch: float, roll: float,
                         omega: tuple[float, float, float] = (0.0, 0.0, 0.0),
                         accel: tuple[float, float, float] = (0.0, 0.0, 9.81)) -> None:
        """Inject IMU feedback directly (bypasses ROS2 subscribers)."""
        with self._lock:
            self._feedback_imu[0] = float(yaw)
            self._feedback_imu[1] = float(pitch)
            self._feedback_imu[2] = float(roll)
            self._feedback_imu[3] = float(omega[0])
            self._feedback_imu[4] = float(omega[1])
            self._feedback_imu[5] = float(omega[2])
            self._feedback_imu[6] = float(accel[0])
            self._feedback_imu[7] = float(accel[1])
            self._feedback_imu[8] = float(accel[2])

    # --- Public interface for main.py ---

    @property
    def joint_names(self) -> tuple[str, ...]:
        return JOINT_NAMES

    def set_command(self, linear_x: float, angular_z: float) -> None:
        """Map bridge (linear_x, angular_z) to policy (x_vel, y_vel, yaw_vel).

        Mapping from Joystick.cpp:
          x_vel = y1 * 0.8 (forward) / * 0.5 (backward)
          y_vel = x1 * -0.4 (lateral, unused from bridge)
          yaw_vel = y2 * -0.4
        """
        if linear_x >= 0:
            self._target_x_vel = float(linear_x) * 0.8
        else:
            self._target_x_vel = float(linear_x) * 0.5
        self._target_y_vel = 0.0
        self._target_yaw_vel = float(angular_z) * -0.4

    def request_gait_transition(self, hold_s: float) -> None:
        """Latch a short-lived gait request so ZERO has time to reach MLP safely."""
        self._pending_gait_transition = True
        self._transition_request_until = time.monotonic() + max(0.0, float(hold_s))

    def clear_gait_transition_request(self) -> None:
        self._pending_gait_transition = False
        self._transition_request_until = 0.0

    def _has_gait_transition_request(self) -> bool:
        return time.monotonic() < self._transition_request_until

    def stand_pose(self) -> dict[str, float]:
        """Return 20-joint default standing pose."""
        return {name: float(self.cfg.default_dof_pos[i]) for i, name in enumerate(JOINT_NAMES)}

    def force_stop_hold(self) -> None:
        """Force the FSM back to STOP with the nominal standing pose latched.

        This is used by the HTTP bridge when Isaac Sim feedback is unavailable
        during startup/restart, so we do not keep streaming stale MLP targets
        into a robot that has not re-primed its articulation yet.
        """
        self.clear_gait_transition_request()
        self._target_x_vel = 0.0
        self._target_y_vel = 0.0
        self._target_yaw_vel = 0.0

        stop_state = self._robot_fsm._states.get(FSMStateName.STOP)
        if not isinstance(stop_state, StateStop):
            return
        stop_state.request_hold_pose(self.cfg.default_dof_pos_np)
        self._robot_fsm._current_name = FSMStateName.STOP
        self._robot_fsm._current_state = stop_state
        self._robot_fsm._current_state.on_enter()
        self._last_output_targets[:] = self.cfg.default_dof_pos_np

    def update(self, dt: float) -> dict[str, float]:
        """Advance the RL FSM and refresh policy output at the official 50 Hz cadence."""
        step_dt = max(1e-4, float(dt))
        control_dt = max(1e-4, float(self.cfg.control_dt))
        substeps = max(1, int(round(step_dt / control_dt)))
        substeps = min(max(1, int(self.cfg.max_control_substeps)), substeps)
        substep_dt = step_dt / float(substeps)

        # Update feedback into robot_data
        with self._lock:
            self._robot_data.q_a[:] = self._feedback_pos
            self._robot_data.q_dot_a[:] = self._feedback_vel
            self._robot_data.tau_a[:] = self._feedback_tor
            self._robot_data.imu_data[:] = self._feedback_imu

        flag = XboxFlag(
            fsm_state_command=self._get_fsm_command(),
            x_speed_command=self._target_x_vel,
            y_speed_command=self._target_y_vel,
            yaw_speed_command=self._target_yaw_vel,
        )
        self._robot_fsm.set_step_dt(substep_dt)
        for _ in range(substeps):
            self._robot_fsm.run(flag)
        if self._robot_fsm.current_state == FSMStateName.MLP:
            self._pending_gait_transition = False
            self._transition_request_until = 0.0

        # Get desired joint positions
        q_d = self._robot_data.q_d.copy()

        # Apply SP transform on ankle joints (if real robot)
        if not self.cfg.simulation:
            q_d = self._apply_sp_inverse(q_d)
        elif self.cfg.clamp_joint_targets:
            q_d = np.clip(q_d, self._joint_pos_lower, self._joint_pos_upper)
        elif self._selective_clamp_indices.size > 0:
            q_d = q_d.copy()
            q_d[self._selective_clamp_indices] = np.clip(
                q_d[self._selective_clamp_indices],
                self._joint_pos_lower[self._selective_clamp_indices],
                self._joint_pos_upper[self._selective_clamp_indices],
            )
        if self._selective_upper_only_clamp_indices.size > 0:
            q_d = q_d.copy()
            indices = self._selective_upper_only_clamp_indices
            upper = self._joint_pos_upper[indices]
            should_apply = (
                self._current_mlp_elapsed_s() >= self._selective_upper_only_clamp_delay_s
            )
            if should_apply:
                overflow = q_d[indices] - upper
                clamp_mask = overflow > self._selective_upper_only_clamp_margin_rad
                if np.any(clamp_mask):
                    limited = q_d[indices].copy()
                    limited[clamp_mask] = upper[clamp_mask]
                    q_d[indices] = limited
        q_d = self._apply_selective_slew_limits(q_d, step_dt)
        self._last_output_targets[:] = q_d

        # Publish CmdMotorCtrl
        self._publish_motor_commands(q_d)

        # Return as dict
        return {JOINT_NAMES[i]: float(q_d[i]) for i in range(20)}

    def _resolve_joint_indices(self, joint_names: list[str]) -> NDArray[np.int64]:
        indices: list[int] = []
        unknown: list[str] = []
        for name in joint_names:
            idx = NAME_TO_INDEX.get(str(name).strip(), -1)
            if idx < 0:
                unknown.append(str(name))
                continue
            indices.append(idx)
        if unknown:
            print(f"[RLPolicyController] Ignoring unknown configured joints: {unknown}")
        if not indices:
            return np.array([], dtype=np.int64)
        return np.array(sorted(set(indices)), dtype=np.int64)

    def _current_mlp_elapsed_s(self) -> float:
        if self._robot_fsm.current_state != FSMStateName.MLP:
            return 0.0
        try:
            return max(0.0, float(self._robot_fsm._current_state.timer))
        except Exception:
            return 0.0

    def debug_snapshot(self) -> dict[str, Any]:
        return {
            "fsm_state": self._robot_fsm.current_state.name,
            "policy_command": {
                "x_vel": float(self._target_x_vel),
                "y_vel": float(self._target_y_vel),
                "yaw_vel": float(self._target_yaw_vel),
            },
            "post_controller_targets": {
                JOINT_NAMES[i]: float(self._last_output_targets[i]) for i in range(20)
            },
            "fsm_debug": self._robot_fsm.debug_snapshot(),
        }

    def _apply_selective_slew_limits(
        self,
        q_d: NDArray[np.float64],
        dt: float,
    ) -> NDArray[np.float64]:
        if self._slew_limit_indices.size == 0 or self._slew_limit_rate_rad_s <= 1e-9:
            return q_d
        q_d = q_d.copy()
        max_delta = self._slew_limit_rate_rad_s * max(1e-4, float(dt))
        deltas = q_d[self._slew_limit_indices] - self._last_output_targets[self._slew_limit_indices]
        q_d[self._slew_limit_indices] = (
            self._last_output_targets[self._slew_limit_indices]
            + np.clip(deltas, -max_delta, max_delta)
        )
        return q_d

    def _get_fsm_command(self) -> str:
        """Determine FSM command based on current state and command activity."""
        current = self._robot_fsm.current_state
        has_velocity_command = (abs(self._target_x_vel) > 0.01 or abs(self._target_yaw_vel) > 0.01)
        has_transition_request = (
            has_velocity_command
            or self._pending_gait_transition
            or self._has_gait_transition_request()
        )

        if current == FSMStateName.STOP:
            if has_transition_request:
                return "gotoZero"
            return ""
        elif current == FSMStateName.ZERO:
            if has_transition_request:
                return "gotoMLP"
            return ""
        elif current == FSMStateName.MLP:
            return ""
        return ""

    def _apply_sp_inverse(self, q_d: NDArray[np.float64]) -> NDArray[np.float64]:
        """Apply serial→parallel transform on ankle joints (indices 4,5,10,11)."""
        q_s_ankles = np.concatenate((q_d[4:6].copy(), q_d[10:12].copy()))
        q_p_ankles, _, _ = self._sp_transform.inverse(
            q_s_ankles, np.zeros(4, dtype=np.float64), np.zeros(4, dtype=np.float64))

        result = q_d.copy()
        result[4:6] = q_p_ankles[:2]
        result[10:12] = q_p_ankles[2:4]
        return result

    def _apply_sp_forward(
        self,
        q_p: NDArray[np.float64],
        qdot_p: NDArray[np.float64],
        tor_p: NDArray[np.float64],
    ) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
        """Apply parallel-to-serial transform on ankle joints (indices 4,5,10,11)."""
        q_s = q_p.copy()
        qdot_s = qdot_p.copy()
        tor_s = tor_p.copy()

        q_s_ankles, qdot_s_ankles, tor_s_ankles = self._sp_transform.forward(
            np.concatenate((q_p[4:6].copy(), q_p[10:12].copy())),
            np.concatenate((qdot_p[4:6].copy(), qdot_p[10:12].copy())),
            np.concatenate((tor_p[4:6].copy(), tor_p[10:12].copy())),
        )

        q_s[4:6] = q_s_ankles[:2]
        q_s[10:12] = q_s_ankles[2:4]
        qdot_s[4:6] = qdot_s_ankles[:2]
        qdot_s[10:12] = qdot_s_ankles[2:4]
        tor_s[4:6] = tor_s_ankles[:2]
        tor_s[10:12] = tor_s_ankles[2:4]
        return q_s, qdot_s, tor_s

    def _should_apply_sp_feedback_transform(self) -> bool:
        return (not self.cfg.simulation) or bool(self.cfg.enable_sim_sp_transform)

    def _publish_motor_commands(self, q_d: NDArray[np.float64]) -> None:
        """Publish CmdMotorCtrl messages to /leg/cmd_ctrl and /arm/cmd_ctrl."""
        if self._cmd_motor_ctrl_type is None or self._leg_pub is None:
            return

        cfg = self.cfg
        zero_offset = np.array(cfg.zero_pos_offset, dtype=np.float64)
        kp = np.array(cfg.joint_kp_p, dtype=np.float64)
        kd = np.array(cfg.joint_kd_p, dtype=np.float64)

        # Leg commands (indices 0-11)
        leg_msg = self._cmd_motor_ctrl_type()
        leg_msg.header.stamp = self._node.get_clock().now().to_msg()
        for i in range(12):
            ctrl = self._cmd_motor_ctrl_type.MotorCtrl()
            ctrl.name = int(INDEX_TO_CAN_ID[i])
            ctrl.pos = float(q_d[i] - zero_offset[i])
            ctrl.spd = 0.0
            ctrl.tor = 0.0
            ctrl.kp = float(kp[i])
            ctrl.kd = float(kd[i])
            leg_msg.cmds.append(ctrl)
        self._leg_pub.publish(leg_msg)

        # Arm commands (indices 12-19)
        arm_msg = self._cmd_motor_ctrl_type()
        arm_msg.header.stamp = self._node.get_clock().now().to_msg()
        for i in range(12, 20):
            ctrl = self._cmd_motor_ctrl_type.MotorCtrl()
            ctrl.name = int(INDEX_TO_CAN_ID[i])
            ctrl.pos = float(q_d[i] - zero_offset[i])
            ctrl.spd = 0.0
            ctrl.tor = 0.0
            ctrl.kp = float(kp[i])
            ctrl.kd = float(kd[i])
            arm_msg.cmds.append(ctrl)
        self._arm_pub.publish(arm_msg)
