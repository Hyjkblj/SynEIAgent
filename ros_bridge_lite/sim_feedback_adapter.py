"""Simulation feedback adapter: bridges Isaac Sim <-> RLPolicyController.

Subscribes to Isaac Sim's /joint_states (sensor_msgs/JointState with URDF names)
and converts to /leg/status, /arm/status (bodyctrl_msgs/MotorStatusMsg with CAN IDs)
and /imu/status (bodyctrl_msgs/Imu).

Also subscribes to bodyIdMap-named /joint_command and republishes as URDF-named
/joint_command_urdf for Isaac Sim consumption.
"""

from __future__ import annotations

import signal
import sys
from typing import Any

from .motor_id_map import INDEX_TO_CAN_ID, INDEX_TO_NAME, NAME_TO_INDEX

# --- URDF name <-> bodyIdMap name mapping ---

URDF_TO_BODYIDMAP: dict[str, str] = {
    # Left leg
    "hip_roll_l_joint": "l_hip_roll",
    "hip_pitch_l_joint": "l_hip_pitch",
    "hip_yaw_l_joint": "l_hip_yaw",
    "knee_pitch_l_joint": "l_knee",
    "ankle_pitch_l_joint": "l_ankle_pitch",
    "ankle_roll_l_joint": "l_ankle_roll",
    # Right leg
    "hip_roll_r_joint": "r_hip_roll",
    "hip_pitch_r_joint": "r_hip_pitch",
    "hip_yaw_r_joint": "r_hip_yaw",
    "knee_pitch_r_joint": "r_knee",
    "ankle_pitch_r_joint": "r_ankle_pitch",
    "ankle_roll_r_joint": "r_ankle_roll",
    # Left arm
    "shoulder_pitch_l_joint": "l_shoulder_pitch",
    "shoulder_roll_l_joint": "l_shoulder_roll",
    "shoulder_yaw_l_joint": "l_shoulder_yaw",
    "elbow_l_joint": "l_elbow",
    # Right arm
    "shoulder_pitch_r_joint": "r_shoulder_pitch",
    "shoulder_roll_r_joint": "r_shoulder_roll",
    "shoulder_yaw_r_joint": "r_shoulder_yaw",
    "elbow_r_joint": "r_elbow",
}

BODYIDMAP_TO_URDF: dict[str, str] = {v: k for k, v in URDF_TO_BODYIDMAP.items()}


def _can_id_for_name(bodyidmap_name: str) -> int:
    idx = NAME_TO_INDEX.get(bodyidmap_name, -1)
    if idx < 0:
        return -1
    return INDEX_TO_CAN_ID.get(idx, -1)


class SimFeedbackAdapter:
    """ROS2 node that bridges Isaac Sim feedback to RLPolicyController format."""

    def __init__(
        self,
        joint_states_topic: str = "/joint_states",
        leg_status_topic: str = "/leg/status",
        arm_status_topic: str = "/arm/status",
        imu_status_topic: str = "/imu/status",
        joint_cmd_in_topic: str = "/joint_command",
        joint_cmd_out_topic: str = "/joint_command_urdf",
    ) -> None:
        import rclpy  # type: ignore
        from rclpy.node import Node  # type: ignore
        from sensor_msgs.msg import JointState  # type: ignore

        self._rclpy = rclpy
        if not rclpy.ok():
            rclpy.init(args=None)
        self._node: Node = rclpy.create_node("sim_feedback_adapter")
        self._joint_state_type = JointState

        # Try importing bodyctrl_msgs
        self._motor_status_type: Any = None
        self._imu_type: Any = None
        try:
            from bodyctrl_msgs.msg import Imu, MotorStatusMsg  # type: ignore

            self._motor_status_type = MotorStatusMsg
            self._imu_type = Imu
        except Exception as e:
            print(f"[SimAdapter] bodyctrl_msgs unavailable: {e}")
            print("[SimAdapter] Cannot start without bodyctrl_msgs (MotorStatusMsg, Imu)")
            sys.exit(1)

        # Publishers
        self._leg_pub = self._node.create_publisher(
            self._motor_status_type, leg_status_topic, 10)
        self._arm_pub = self._node.create_publisher(
            self._motor_status_type, arm_status_topic, 10)
        self._imu_pub = self._node.create_publisher(
            self._imu_type, imu_status_topic, 10)
        self._joint_cmd_pub = self._node.create_publisher(
            JointState, joint_cmd_out_topic, 10)

        # Subscribers
        self._node.create_subscription(
            JointState, joint_states_topic, self._on_joint_states, 10)
        self._node.create_subscription(
            JointState, joint_cmd_in_topic, self._on_joint_command, 10)

        # Stats
        self._js_count = 0
        self._cmd_count = 0

        print(f"[SimAdapter] Ready")
        print(f"  Subscribing: {joint_states_topic}, {joint_cmd_in_topic}")
        print(f"  Publishing:  {leg_status_topic}, {arm_status_topic}, "
              f"{imu_status_topic}, {joint_cmd_out_topic}")

    # --- Callbacks ---

    def _on_joint_states(self, msg: Any) -> None:
        """Convert sensor_msgs/JointState (URDF names) → MotorStatusMsg (CAN IDs)."""
        names = list(getattr(msg, "name", []) or [])
        positions = list(getattr(msg, "position", []) or [])
        velocities = list(getattr(msg, "velocity", []) or [])
        efforts = list(getattr(msg, "effort", []) or [])
        if not names or not positions:
            return

        # Build lookup: URDF name → (pos, vel, effort)
        js_data: dict[str, tuple[float, float, float]] = {}
        for i, name in enumerate(names):
            pos = float(positions[i]) if i < len(positions) else 0.0
            vel = float(velocities[i]) if i < len(velocities) else 0.0
            eff = float(efforts[i]) if i < len(efforts) else 0.0
            js_data[name] = (pos, vel, eff)

        # Group by leg/arm using CAN ID ranges
        leg_statuses: list[tuple[int, float, float, float]] = []
        arm_statuses: list[tuple[int, float, float, float]] = []

        for urdf_name, (pos, vel, eff) in js_data.items():
            bodyidmap_name = URDF_TO_BODYIDMAP.get(urdf_name)
            if bodyidmap_name is None:
                continue
            can_id = _can_id_for_name(bodyidmap_name)
            if can_id < 0:
                continue
            idx = NAME_TO_INDEX[bodyidmap_name]
            entry = (can_id, pos, vel, eff)
            if idx < 12:
                leg_statuses.append(entry)
            else:
                arm_statuses.append(entry)

        # Publish leg status
        if leg_statuses:
            leg_msg = self._motor_status_type()
            if hasattr(leg_msg, "header") and hasattr(self._node, "get_clock"):
                try:
                    leg_msg.header.stamp = self._node.get_clock().now().to_msg()
                except Exception:
                    pass
            for can_id, pos, vel, eff in leg_statuses:
                s = self._motor_status_type.MotorStatus()
                s.name = int(can_id)
                s.pos = pos
                s.speed = vel
                s.current = eff
                leg_msg.status.append(s)
            self._leg_pub.publish(leg_msg)

        # Publish arm status
        if arm_statuses:
            arm_msg = self._motor_status_type()
            if hasattr(arm_msg, "header") and hasattr(self._node, "get_clock"):
                try:
                    arm_msg.header.stamp = self._node.get_clock().now().to_msg()
                except Exception:
                    pass
            for can_id, pos, vel, eff in arm_statuses:
                s = self._motor_status_type.MotorStatus()
                s.name = int(can_id)
                s.pos = pos
                s.speed = vel
                s.current = eff
                arm_msg.status.append(s)
            self._arm_pub.publish(arm_msg)

        # Publish synthetic IMU (zero values for simulation)
        self._publish_imu()

        self._js_count += 1

    def _on_joint_command(self, msg: Any) -> None:
        """Convert bodyIdMap-named JointState → URDF-named JointState."""
        names = list(getattr(msg, "name", []) or [])
        positions = list(getattr(msg, "position", []) or [])
        if not names or not positions:
            return

        urdf_names: list[str] = []
        urdf_positions: list[float] = []

        for i, name in enumerate(names):
            urdf_name = BODYIDMAP_TO_URDF.get(str(name))
            if urdf_name is None:
                continue
            urdf_names.append(urdf_name)
            urdf_positions.append(float(positions[i]) if i < len(positions) else 0.0)

        if not urdf_names:
            return

        out = self._joint_state_type()
        if hasattr(out, "header") and hasattr(self._node, "get_clock"):
            try:
                out.header.stamp = self._node.get_clock().now().to_msg()
            except Exception:
                pass
        out.name = urdf_names
        out.position = urdf_positions
        out.velocity = []
        out.effort = []
        self._joint_cmd_pub.publish(out)
        self._cmd_count += 1

    def _publish_imu(self) -> None:
        """Publish synthetic zero IMU for simulation."""
        msg = self._imu_type()
        if hasattr(msg, "header") and hasattr(self._node, "get_clock"):
            try:
                msg.header.stamp = self._node.get_clock().now().to_msg()
            except Exception:
                pass
        # Euler: yaw=0, pitch=0, roll=0
        msg.euler.yaw = 0.0
        msg.euler.pitch = 0.0
        msg.euler.roll = 0.0
        # Angular velocity: zero
        msg.angular_velocity.x = 0.0
        msg.angular_velocity.y = 0.0
        msg.angular_velocity.z = 0.0
        # Linear acceleration: gravity only
        msg.linear_acceleration.x = 0.0
        msg.linear_acceleration.y = 0.0
        msg.linear_acceleration.z = 9.81
        self._imu_pub.publish(msg)

    def spin(self) -> None:
        """Run the adapter node until interrupted."""
        print(f"[SimAdapter] Spinning... (Ctrl+C to stop)")
        try:
            self._rclpy.spin(self._node)
        except KeyboardInterrupt:
            pass
        finally:
            print(f"[SimAdapter] Stopped (joint_states={self._js_count}, cmd={self._cmd_count})")
            self._node.destroy_node()


def main() -> None:
    adapter = SimFeedbackAdapter()

    # Graceful shutdown
    def _shutdown(signum: int, frame: Any) -> None:
        raise KeyboardInterrupt()
    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    adapter.spin()


if __name__ == "__main__":
    main()
