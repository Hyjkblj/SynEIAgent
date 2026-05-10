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

from .fsm_states import FSMStateName, RobotData, RobotFSM, XboxFlag
from .motor_id_map import CAN_ID_TO_INDEX, INDEX_TO_CAN_ID, INDEX_TO_NAME, JOINT_NAMES
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

        # --- OpenVINO model ---
        self._infer_request = None
        self._input_tensor = None
        if cfg.model_xml_path:
            self._load_model()

        # --- Serial-parallel transform ---
        self._sp_transform: SPTransformBase = create_sp_transform(cfg.simulation)

        # --- FSM ---
        self._robot_fsm = RobotFSM(cfg, self._robot_data, self._infer_request, self._input_tensor)

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
        with self._lock:
            for i in range(min(20, len(positions))):
                self._feedback_pos[i] = float(positions[i])
            if velocities:
                for i in range(min(20, len(velocities))):
                    self._feedback_vel[i] = float(velocities[i])
            if efforts:
                for i in range(min(20, len(efforts))):
                    self._feedback_tor[i] = float(efforts[i])

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

    def stand_pose(self) -> dict[str, float]:
        """Return 20-joint default standing pose."""
        return {name: float(self.cfg.default_dof_pos[i]) for i, name in enumerate(JOINT_NAMES)}

    def update(self, dt: float) -> dict[str, float]:
        """Run one FSM tick and return 20-joint targets.

        Called from bridge's _joint_control_loop at 50Hz.
        """
        # Update feedback into robot_data
        with self._lock:
            self._robot_data.q_a[:] = self._feedback_pos
            self._robot_data.q_dot_a[:] = self._feedback_vel
            self._robot_data.tau_a[:] = self._feedback_tor
            self._robot_data.imu_data[:] = self._feedback_imu

        # Build flag
        flag = XboxFlag(
            fsm_state_command=self._get_fsm_command(),
            x_speed_command=self._target_x_vel,
            y_speed_command=self._target_y_vel,
            yaw_speed_command=self._target_yaw_vel,
        )

        # Run FSM
        self._robot_fsm.run(flag)

        # Get desired joint positions
        q_d = self._robot_data.q_d.copy()

        # Apply SP transform on ankle joints (if real robot)
        if not self.cfg.simulation:
            q_d = self._apply_sp_inverse(q_d)

        # Publish CmdMotorCtrl
        self._publish_motor_commands(q_d)

        # Return as dict
        return {JOINT_NAMES[i]: float(q_d[i]) for i in range(20)}

    def _get_fsm_command(self) -> str:
        """Determine FSM command based on current state and command activity."""
        current = self._robot_fsm.current_state
        has_command = (abs(self._target_x_vel) > 0.01 or abs(self._target_yaw_vel) > 0.01)

        if current == FSMStateName.STOP:
            if has_command:
                return "gotoZero"
            return ""
        elif current == FSMStateName.ZERO:
            if has_command:
                return "gotoMLP"
            return "gotoStop" if not has_command else ""
        elif current == FSMStateName.MLP:
            return ""
        return ""

    def _apply_sp_inverse(self, q_d: NDArray[np.float64]) -> NDArray[np.float64]:
        """Apply serial→parallel transform on ankle joints (indices 4,5,10,11)."""
        # Left ankle (indices 4,5)
        q_s_left = q_d[4:6].copy()
        q_p_left, _, _ = self._sp_transform.inverse(
            q_s_left, np.zeros(2), np.zeros(2))
        # Right ankle (indices 10,11)
        q_s_right = q_d[10:12].copy()
        q_p_right, _, _ = self._sp_transform.inverse(
            q_s_right, np.zeros(2), np.zeros(2))

        result = q_d.copy()
        result[4:6] = q_p_left
        result[10:12] = q_p_right
        return result

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
