"""Simulation feedback adapter: bridges Isaac Sim <-> official RL control.

Subscribes to Isaac Sim's /joint_states (sensor_msgs/JointState with URDF names)
and converts to /leg/status, /arm/status (bodyctrl_msgs/MotorStatusMsg with CAN
IDs) and /imu/status (bodyctrl_msgs/Imu).

It also accepts two command forms and republishes them as URDF-named JointState
messages for Isaac Sim consumption:

- bodyIdMap-named /joint_command
- official rl_control /leg/cmd_ctrl + /arm/cmd_ctrl
"""

from __future__ import annotations

import signal
import sys
from typing import Any

from .motor_id_map import CAN_ID_TO_INDEX, INDEX_TO_CAN_ID, INDEX_TO_NAME, NAME_TO_INDEX


URDF_TO_BODYIDMAP: dict[str, str] = {
    "hip_roll_l_joint": "l_hip_roll",
    "hip_pitch_l_joint": "l_hip_pitch",
    "hip_yaw_l_joint": "l_hip_yaw",
    "knee_pitch_l_joint": "l_knee",
    "ankle_pitch_l_joint": "l_ankle_pitch",
    "ankle_roll_l_joint": "l_ankle_roll",
    "hip_roll_r_joint": "r_hip_roll",
    "hip_pitch_r_joint": "r_hip_pitch",
    "hip_yaw_r_joint": "r_hip_yaw",
    "knee_pitch_r_joint": "r_knee",
    "ankle_pitch_r_joint": "r_ankle_pitch",
    "ankle_roll_r_joint": "r_ankle_roll",
    "shoulder_pitch_l_joint": "l_shoulder_pitch",
    "shoulder_roll_l_joint": "l_shoulder_roll",
    "shoulder_yaw_l_joint": "l_shoulder_yaw",
    "elbow_l_joint": "l_elbow",
    "elbow_pitch_l_joint": "l_elbow",
    "shoulder_pitch_r_joint": "r_shoulder_pitch",
    "shoulder_roll_r_joint": "r_shoulder_roll",
    "shoulder_yaw_r_joint": "r_shoulder_yaw",
    "elbow_r_joint": "r_elbow",
    "elbow_pitch_r_joint": "r_elbow",
}

BODYIDMAP_TO_URDF: dict[str, str] = {
    "l_hip_roll": "hip_roll_l_joint",
    "l_hip_pitch": "hip_pitch_l_joint",
    "l_hip_yaw": "hip_yaw_l_joint",
    "l_knee": "knee_pitch_l_joint",
    "l_ankle_pitch": "ankle_pitch_l_joint",
    "l_ankle_roll": "ankle_roll_l_joint",
    "r_hip_roll": "hip_roll_r_joint",
    "r_hip_pitch": "hip_pitch_r_joint",
    "r_hip_yaw": "hip_yaw_r_joint",
    "r_knee": "knee_pitch_r_joint",
    "r_ankle_pitch": "ankle_pitch_r_joint",
    "r_ankle_roll": "ankle_roll_r_joint",
    "l_shoulder_pitch": "shoulder_pitch_l_joint",
    "l_shoulder_roll": "shoulder_roll_l_joint",
    "l_shoulder_yaw": "shoulder_yaw_l_joint",
    "l_elbow": "elbow_pitch_l_joint",
    "r_shoulder_pitch": "shoulder_pitch_r_joint",
    "r_shoulder_roll": "shoulder_roll_r_joint",
    "r_shoulder_yaw": "shoulder_yaw_r_joint",
    "r_elbow": "elbow_pitch_r_joint",
}


def _can_id_for_name(bodyidmap_name: str) -> int:
    idx = NAME_TO_INDEX.get(bodyidmap_name, -1)
    if idx < 0:
        return -1
    return INDEX_TO_CAN_ID.get(idx, -1)


def _urdf_name_for_can_id(can_id: int) -> str:
    idx = CAN_ID_TO_INDEX.get(int(can_id), -1)
    if idx < 0:
        return ""
    bodyidmap_name = INDEX_TO_NAME.get(idx, "")
    if not bodyidmap_name:
        return ""
    return BODYIDMAP_TO_URDF.get(bodyidmap_name, "")


def cmd_motor_ctrl_to_urdf_targets(msg: Any) -> dict[str, float]:
    """Convert bodyctrl_msgs/CmdMotorCtrl into URDF joint targets."""
    cmds = list(getattr(msg, "cmds", []) or [])
    targets: dict[str, float] = {}
    for cmd in cmds:
        urdf_name = _urdf_name_for_can_id(getattr(cmd, "name", -1))
        if not urdf_name:
            continue
        targets[urdf_name] = float(getattr(cmd, "pos", 0.0))
    return targets


URDF_JOINT_ORDER: tuple[str, ...] = tuple(
    BODYIDMAP_TO_URDF[INDEX_TO_NAME[i]]
    for i in range(len(INDEX_TO_NAME))
    if INDEX_TO_NAME[i] in BODYIDMAP_TO_URDF
)


class SimFeedbackAdapter:
    """ROS2 node that bridges Isaac Sim feedback to RL-compatible topics."""

    def __init__(
        self,
        joint_states_topic: str = "/joint_states",
        leg_status_topic: str = "/leg/status",
        arm_status_topic: str = "/arm/status",
        imu_status_topic: str = "/imu/status",
        joint_cmd_in_topic: str = "/joint_command",
        joint_cmd_out_topic: str = "/joint_command_urdf",
        leg_cmd_ctrl_topic: str = "/leg/cmd_ctrl",
        arm_cmd_ctrl_topic: str = "/arm/cmd_ctrl",
    ) -> None:
        import rclpy  # type: ignore
        from rclpy.node import Node  # type: ignore
        from sensor_msgs.msg import JointState  # type: ignore

        self._rclpy = rclpy
        if not rclpy.ok():
            rclpy.init(args=None)
        self._node: Node = rclpy.create_node("sim_feedback_adapter")
        self._joint_state_type = JointState

        self._motor_status_type: Any = None
        self._motor_status_item_type: Any = None
        self._imu_type: Any = None
        self._cmd_motor_ctrl_type: Any = None
        try:
            from bodyctrl_msgs.msg import CmdMotorCtrl, Imu, MotorStatus, MotorStatusMsg  # type: ignore

            self._cmd_motor_ctrl_type = CmdMotorCtrl
            self._motor_status_item_type = MotorStatus
            self._motor_status_type = MotorStatusMsg
            self._imu_type = Imu
        except Exception as e:
            print(f"[SimAdapter] bodyctrl_msgs unavailable: {e}")
            print("[SimAdapter] Cannot start without bodyctrl_msgs (CmdMotorCtrl, MotorStatusMsg, Imu)")
            sys.exit(1)

        self._leg_pub = self._node.create_publisher(self._motor_status_type, leg_status_topic, 10)
        self._arm_pub = self._node.create_publisher(self._motor_status_type, arm_status_topic, 10)
        self._imu_pub = self._node.create_publisher(self._imu_type, imu_status_topic, 10)
        self._joint_cmd_pub = self._node.create_publisher(JointState, joint_cmd_out_topic, 10)

        self._node.create_subscription(JointState, joint_states_topic, self._on_joint_states, 10)
        self._node.create_subscription(JointState, joint_cmd_in_topic, self._on_joint_command, 10)
        self._node.create_subscription(self._cmd_motor_ctrl_type, leg_cmd_ctrl_topic, self._on_leg_cmd_ctrl, 10)
        self._node.create_subscription(self._cmd_motor_ctrl_type, arm_cmd_ctrl_topic, self._on_arm_cmd_ctrl, 10)

        self._js_count = 0
        self._cmd_count = 0
        self._latest_joint_targets: dict[str, float] = {}
        self._have_leg_cmd = False
        self._have_arm_cmd = False

        print("[SimAdapter] Ready")
        print(
            f"  Subscribing: {joint_states_topic}, {joint_cmd_in_topic}, "
            f"{leg_cmd_ctrl_topic}, {arm_cmd_ctrl_topic}"
        )
        print(
            f"  Publishing:  {leg_status_topic}, {arm_status_topic}, "
            f"{imu_status_topic}, {joint_cmd_out_topic}"
        )

    def _on_joint_states(self, msg: Any) -> None:
        """Convert URDF JointState feedback into RL-compatible motor status."""
        names = list(getattr(msg, "name", []) or [])
        positions = list(getattr(msg, "position", []) or [])
        velocities = list(getattr(msg, "velocity", []) or [])
        efforts = list(getattr(msg, "effort", []) or [])
        if not names or not positions:
            return

        js_data: dict[str, tuple[float, float, float]] = {}
        for i, name in enumerate(names):
            pos = float(positions[i]) if i < len(positions) else 0.0
            vel = float(velocities[i]) if i < len(velocities) else 0.0
            eff = float(efforts[i]) if i < len(efforts) else 0.0
            js_data[str(name)] = (pos, vel, eff)

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

        if leg_statuses:
            leg_msg = self._motor_status_type()
            if hasattr(leg_msg, "header") and hasattr(self._node, "get_clock"):
                try:
                    leg_msg.header.stamp = self._node.get_clock().now().to_msg()
                except Exception:
                    pass
            for can_id, pos, vel, eff in leg_statuses:
                status = self._motor_status_item_type()
                status.name = int(can_id)
                status.pos = pos
                status.speed = vel
                status.current = eff
                leg_msg.status.append(status)
            self._leg_pub.publish(leg_msg)

        if arm_statuses:
            arm_msg = self._motor_status_type()
            if hasattr(arm_msg, "header") and hasattr(self._node, "get_clock"):
                try:
                    arm_msg.header.stamp = self._node.get_clock().now().to_msg()
                except Exception:
                    pass
            for can_id, pos, vel, eff in arm_statuses:
                status = self._motor_status_item_type()
                status.name = int(can_id)
                status.pos = pos
                status.speed = vel
                status.current = eff
                arm_msg.status.append(status)
            self._arm_pub.publish(arm_msg)

        self._publish_imu()
        self._js_count += 1

    def _on_joint_command(self, msg: Any) -> None:
        """Convert bodyIdMap-named JointState into URDF-named JointState."""
        names = list(getattr(msg, "name", []) or [])
        positions = list(getattr(msg, "position", []) or [])
        if not names or not positions:
            return

        joint_targets: dict[str, float] = {}
        for i, name in enumerate(names):
            urdf_name = BODYIDMAP_TO_URDF.get(str(name))
            if urdf_name is None:
                continue
            joint_targets[urdf_name] = float(positions[i]) if i < len(positions) else 0.0

        if joint_targets:
            self._publish_joint_targets(joint_targets)

    def _on_leg_cmd_ctrl(self, msg: Any) -> None:
        self._have_leg_cmd = True
        self._on_cmd_motor_ctrl(msg)

    def _on_arm_cmd_ctrl(self, msg: Any) -> None:
        self._have_arm_cmd = True
        self._on_cmd_motor_ctrl(msg)

    def _on_cmd_motor_ctrl(self, msg: Any) -> None:
        """Convert official rl_control CmdMotorCtrl into merged URDF targets."""
        joint_targets = cmd_motor_ctrl_to_urdf_targets(msg)
        if not joint_targets:
            return

        self._latest_joint_targets.update(joint_targets)
        if not (self._have_leg_cmd and self._have_arm_cmd):
            return

        ordered_targets = {
            name: self._latest_joint_targets[name]
            for name in URDF_JOINT_ORDER
            if name in self._latest_joint_targets
        }
        if ordered_targets:
            self._publish_joint_targets(ordered_targets)

    def _publish_joint_targets(self, joint_targets: dict[str, float]) -> None:
        out = self._joint_state_type()
        if hasattr(out, "header") and hasattr(self._node, "get_clock"):
            try:
                out.header.stamp = self._node.get_clock().now().to_msg()
            except Exception:
                pass
        out.name = list(joint_targets.keys())
        out.position = [float(joint_targets[name]) for name in out.name]
        out.velocity = []
        out.effort = []
        self._joint_cmd_pub.publish(out)
        self._cmd_count += 1

    def _publish_imu(self) -> None:
        """Publish a synthetic IMU for Isaac-only simulation runs."""
        msg = self._imu_type()
        if hasattr(msg, "header") and hasattr(self._node, "get_clock"):
            try:
                msg.header.stamp = self._node.get_clock().now().to_msg()
            except Exception:
                pass
        msg.euler.yaw = 0.0
        msg.euler.pitch = 0.0
        msg.euler.roll = 0.0
        msg.angular_velocity.x = 0.0
        msg.angular_velocity.y = 0.0
        msg.angular_velocity.z = 0.0
        msg.linear_acceleration.x = 0.0
        msg.linear_acceleration.y = 0.0
        msg.linear_acceleration.z = 9.81
        self._imu_pub.publish(msg)

    def spin(self) -> None:
        print("[SimAdapter] Spinning... (Ctrl+C to stop)")
        try:
            self._rclpy.spin(self._node)
        except KeyboardInterrupt:
            pass
        finally:
            print(f"[SimAdapter] Stopped (joint_states={self._js_count}, cmd={self._cmd_count})")
            self._node.destroy_node()


def main() -> None:
    adapter = SimFeedbackAdapter()

    def _shutdown(signum: int, frame: Any) -> None:
        raise KeyboardInterrupt()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)
    adapter.spin()


if __name__ == "__main__":
    main()
