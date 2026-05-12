"""
Tests for ros2_control_bridge — velocity clamping in _cmd_vel_callback.
Feature: joystick-sim-integration-test
Requirements: 6.1, 6.4, 6.5, 6.6

Run in ROS Bridge environment:
  C:\\pixi_ws\\.pixi\\envs\\default\\python.exe -m pytest tests/test_ros2_control_bridge.py -v
"""
from __future__ import annotations

import sys
import time
import types
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Module-level mock setup — must happen before importing ros2_control_bridge
# ---------------------------------------------------------------------------

def _make_rclpy_mock() -> types.ModuleType:
    """Build a minimal rclpy mock."""
    rclpy_mod = types.ModuleType("rclpy")
    rclpy_mod.ok = MagicMock(return_value=False)
    rclpy_mod.init = MagicMock()
    rclpy_mod.create_node = MagicMock(return_value=MagicMock())
    rclpy_mod.spin_once = MagicMock()

    node_mod = types.ModuleType("rclpy.node")
    node_mod.Node = MagicMock()
    rclpy_mod.node = node_mod

    return rclpy_mod


def _make_numpy_mock() -> types.ModuleType:
    """Build a numpy mock that delegates clip() to the real numpy."""
    import numpy as _real_np

    np_mod = types.ModuleType("numpy")
    # Delegate clip to real numpy so clamping logic works correctly
    np_mod.clip = _real_np.clip
    np_mod.zeros = _real_np.zeros
    np_mod.array = _real_np.array
    return np_mod


def _make_geometry_msgs_mock() -> tuple[types.ModuleType, types.ModuleType]:
    geo_mod = types.ModuleType("geometry_msgs")
    geo_msg_mod = types.ModuleType("geometry_msgs.msg")

    class _Vec3:
        def __init__(self) -> None:
            self.x = 0.0
            self.y = 0.0
            self.z = 0.0

    class _Twist:
        def __init__(self) -> None:
            self.linear = _Vec3()
            self.angular = _Vec3()

    geo_msg_mod.Twist = _Twist
    geo_mod.msg = geo_msg_mod
    return geo_mod, geo_msg_mod


def _make_nav_msgs_mock() -> tuple[types.ModuleType, types.ModuleType]:
    nav_mod = types.ModuleType("nav_msgs")
    nav_msg_mod = types.ModuleType("nav_msgs.msg")
    nav_msg_mod.Odometry = MagicMock()
    nav_mod.msg = nav_msg_mod
    return nav_mod, nav_msg_mod


def _make_sensor_msgs_mock() -> tuple[types.ModuleType, types.ModuleType]:
    sen_mod = types.ModuleType("sensor_msgs")
    sen_msg_mod = types.ModuleType("sensor_msgs.msg")
    sen_msg_mod.JointState = MagicMock()
    sen_mod.msg = sen_msg_mod
    return sen_mod, sen_msg_mod


# Install mocks before importing the module under test
_rclpy_mock = _make_rclpy_mock()
_np_mock = _make_numpy_mock()
_geo_mod, _geo_msg_mod = _make_geometry_msgs_mock()
_nav_mod, _nav_msg_mod = _make_nav_msgs_mock()
_sen_mod, _sen_msg_mod = _make_sensor_msgs_mock()

sys.modules["rclpy"] = _rclpy_mock
sys.modules["rclpy.node"] = _rclpy_mock.node

# We do NOT replace numpy globally — the source file imports numpy at module
# level, so we patch it only for the target module's namespace after import.

sys.modules["geometry_msgs"] = _geo_mod
sys.modules["geometry_msgs.msg"] = _geo_msg_mod
sys.modules["nav_msgs"] = _nav_mod
sys.modules["nav_msgs.msg"] = _nav_msg_mod
sys.modules["sensor_msgs"] = _sen_mod
sys.modules["sensor_msgs.msg"] = _sen_msg_mod

# Now safe to import
from TGrobot4s.isaac_sim.ros2_control_bridge import (  # noqa: E402
    IsaacSimRobotController,
    LEGACY_STARTUP_STAND_ORIENTATION_WXYZ,
    RobotControlConfig,
    STARTUP_STAND_ORIENTATION_WXYZ,
    _warm_up_articulation_handle,
    get_default_official_lite_usd_path,
    parse_joint_sign_overrides,
    quat_wxyz_to_euler,
    relative_quat_wxyz,
    world_vector_to_local,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_controller(**kwargs) -> IsaacSimRobotController:
    """Instantiate IsaacSimRobotController with rclpy.ok() returning False
    so _init_ros2 fails gracefully (no real ROS2 node created)."""
    config = RobotControlConfig(**kwargs)
    # Keep tests thread-safe: the production controller always exposes an
    # HTTP API, but starting a real server on every test case exhausts
    # resources under Hypothesis.
    with patch.object(IsaacSimRobotController, "_start_http_server", return_value=None):
        ctrl = IsaacSimRobotController(config)
    return ctrl


def _make_twist(linear_x: float, angular_z: float):
    """Return a mock Twist-like object."""
    msg = _geo_msg_mod.Twist()
    msg.linear.x = linear_x
    msg.angular.z = angular_z
    return msg


# ---------------------------------------------------------------------------
# Task 10.1 — Example-based tests
# Requirements: 6.1, 6.4, 6.5, 6.6
# ---------------------------------------------------------------------------

class TestCmdVelCallbackClamping:
    """Verify _cmd_vel_callback clamps velocities to configured limits."""

    def test_linear_x_clamped_above_max(self) -> None:
        """linear.x > max_linear_velocity must be clamped to max_linear_velocity."""
        ctrl = _make_controller(max_linear_velocity=1.0)
        msg = _make_twist(linear_x=999.0, angular_z=0.0)
        ctrl._cmd_vel_callback(msg)
        assert ctrl._target_linear == pytest.approx(1.0)

    def test_linear_x_clamped_below_neg_max(self) -> None:
        """linear.x < -max_linear_velocity must be clamped to -max_linear_velocity."""
        ctrl = _make_controller(max_linear_velocity=1.0)
        msg = _make_twist(linear_x=-999.0, angular_z=0.0)
        ctrl._cmd_vel_callback(msg)
        assert ctrl._target_linear == pytest.approx(-1.0)

    def test_angular_z_clamped_above_max(self) -> None:
        """angular.z > max_angular_velocity must be clamped to max_angular_velocity."""
        ctrl = _make_controller(max_angular_velocity=1.5)
        msg = _make_twist(linear_x=0.0, angular_z=999.0)
        ctrl._cmd_vel_callback(msg)
        assert ctrl._target_angular == pytest.approx(1.5)

    def test_angular_z_clamped_below_neg_max(self) -> None:
        """angular.z < -max_angular_velocity must be clamped to -max_angular_velocity."""
        ctrl = _make_controller(max_angular_velocity=1.5)
        msg = _make_twist(linear_x=0.0, angular_z=-999.0)
        ctrl._cmd_vel_callback(msg)
        assert ctrl._target_angular == pytest.approx(-1.5)

    def test_in_range_linear_unchanged(self) -> None:
        """linear.x within bounds must not be altered."""
        ctrl = _make_controller(max_linear_velocity=1.0)
        msg = _make_twist(linear_x=0.5, angular_z=0.0)
        ctrl._cmd_vel_callback(msg)
        assert ctrl._target_linear == pytest.approx(0.5)

    def test_in_range_angular_unchanged(self) -> None:
        """angular.z within bounds must not be altered."""
        ctrl = _make_controller(max_angular_velocity=1.5)
        msg = _make_twist(linear_x=0.0, angular_z=1.0)
        ctrl._cmd_vel_callback(msg)
        assert ctrl._target_angular == pytest.approx(1.0)

    def test_zero_velocity_unchanged(self) -> None:
        """Zero velocity must remain zero after callback."""
        ctrl = _make_controller()
        msg = _make_twist(linear_x=0.0, angular_z=0.0)
        ctrl._cmd_vel_callback(msg)
        assert ctrl._target_linear == pytest.approx(0.0)
        assert ctrl._target_angular == pytest.approx(0.0)


class TestCommandTimeout:
    """Verify update() resets targets to 0.0 after _cmd_timeout expires."""

    def test_timeout_resets_target_linear(self) -> None:
        """After cmd_timeout, _target_linear must be reset to 0.0."""
        ctrl = _make_controller()
        msg = _make_twist(linear_x=0.5, angular_z=0.3)
        ctrl._cmd_vel_callback(msg)
        assert ctrl._target_linear != 0.0

        # Simulate timeout by backdating _last_cmd_time
        ctrl._last_cmd_time = time.time() - (ctrl._cmd_timeout + 1.0)
        ctrl.update(dt=0.01)

        assert ctrl._target_linear == pytest.approx(0.0)

    def test_timeout_resets_target_angular(self) -> None:
        """After cmd_timeout, _target_angular must be reset to 0.0."""
        ctrl = _make_controller()
        msg = _make_twist(linear_x=0.5, angular_z=0.3)
        ctrl._cmd_vel_callback(msg)
        assert ctrl._target_angular != 0.0

        ctrl._last_cmd_time = time.time() - (ctrl._cmd_timeout + 1.0)
        ctrl.update(dt=0.01)

        assert ctrl._target_angular == pytest.approx(0.0)


class TestPosePayload:
    """Verify pose payload is JSON-safe and exposes control state."""

    def test_pose_payload_uses_cached_world_pose_and_velocity(self) -> None:
        ctrl = _make_controller()

        class _Robot:
            def get_world_pose(self):
                raise AssertionError("pose payload should use cached pose data")

            def get_linear_velocity(self):
                raise AssertionError("pose payload should use cached velocity data")

        ctrl._robot = _Robot()
        ctrl._cached_world_position = _np_mock.array([1.0, 2.0, 3.0])
        ctrl._cached_world_orientation = _np_mock.array([0.0, 0.0, 0.5, 0.866])
        ctrl._cached_linear_velocity = _np_mock.array([0.1, 0.0, -0.2])
        ctrl._target_linear = 0.42
        ctrl._target_angular = 0.15
        ctrl._current_linear = 0.30
        ctrl._current_angular = 0.10

        payload = ctrl.get_pose_payload()

        assert payload["ok"] is True
        assert payload["position"] == [1.0, 2.0, 3.0]
        assert payload["orientation"] == [0.0, 0.0, 0.5, 0.866]
        assert payload["orientation_order"] == "wxyz"
        assert payload["euler"]["yaw"] == pytest.approx(3.1415926535, abs=1e-5)
        assert "policy_euler" in payload
        assert payload["linear_velocity"] == [0.1, 0.0, -0.2]
        assert payload["target_linear"] == pytest.approx(0.42)
        assert payload["current_linear"] == pytest.approx(0.30)
        assert payload["joint_targets_active"] is False
        assert payload["startup_pose_hold_active"] is False
        assert payload["stand_error"]["ok"] is False

    def test_update_imu_refreshes_cached_pose_snapshot(self) -> None:
        ctrl = _make_controller()

        class _Robot:
            def get_world_pose(self):
                return [1.0, 2.0, 3.0], [0.0, 0.0, 0.5, 0.866]

            def get_angular_velocity(self):
                return [0.01, 0.02, 0.03]

            def get_linear_velocity(self):
                return [0.1, 0.0, -0.2]

        ctrl._robot = _Robot()
        ctrl._update_imu(0.1)

        payload = ctrl.get_pose_payload()

        assert payload["position"] == pytest.approx([1.0, 2.0, 3.0])
        assert payload["orientation"] == pytest.approx([0.0, 0.0, 0.5, 0.866])
        assert payload["linear_velocity"] == pytest.approx([0.1, 0.0, -0.2])

    def test_update_imu_rotates_world_angular_velocity_into_body_frame(self) -> None:
        ctrl = _make_controller()

        class _Robot:
            def get_world_pose(self):
                return [0.0, 0.0, 0.0], [0.70710678, 0.0, 0.0, 0.70710678]

            def get_angular_velocity(self):
                return [1.0, 0.0, 0.0]

            def get_linear_velocity(self):
                return [0.0, 0.0, 0.0]

        ctrl._robot = _Robot()
        ctrl._update_imu(0.1)

        expected = world_vector_to_local([0.70710678, 0.0, 0.0, 0.70710678], [1.0, 0.0, 0.0])
        assert ctrl._cached_angular_velocity.tolist() == pytest.approx([1.0, 0.0, 0.0])
        assert ctrl._imu_omega == pytest.approx(expected.tolist(), abs=1e-6)

    def test_no_timeout_preserves_targets(self) -> None:
        """Before cmd_timeout, targets must not be reset."""
        ctrl = _make_controller()
        msg = _make_twist(linear_x=0.5, angular_z=0.3)
        ctrl._cmd_vel_callback(msg)

        # Simulate a recent command (no timeout)
        ctrl._last_cmd_time = time.time()
        ctrl.update(dt=0.01)

        # Targets should still be non-zero (lerp moves them toward target)
        assert ctrl._target_linear == pytest.approx(0.5)
        assert ctrl._target_angular == pytest.approx(0.3)


class TestHttpFeedbackPayload:
    """Verify the HTTP feedback/control-frame payload helpers."""

    def test_get_feedback_payload_contains_joint_states_and_imu(self) -> None:
        ctrl = _make_controller()
        ctrl._joint_names = ["hip_pitch_l_joint", "hip_pitch_r_joint"]
        ctrl._joint_positions = {"hip_pitch_l_joint": -0.4, "hip_pitch_r_joint": -0.5}
        ctrl._joint_velocities = {"hip_pitch_l_joint": 0.1, "hip_pitch_r_joint": -0.2}
        ctrl._imu_quat = [1.0, 0.0, 0.0, 0.0]
        ctrl._imu_omega = [0.01, 0.02, 0.03]
        ctrl._imu_accel = [0.0, 0.0, 9.81]
        ctrl._cached_world_position = _np_mock.array([0.0, 0.0, 0.77255])
        ctrl._cached_world_orientation = _np_mock.array([1.0, 0.0, 0.0, 0.0])

        payload = ctrl.get_feedback_payload()

        assert payload["joint_states"]["name"] == ["hip_pitch_l_joint", "hip_pitch_r_joint"]
        assert payload["joint_states"]["position"] == pytest.approx([-0.4, -0.5])
        assert payload["joint_states"]["velocity"] == pytest.approx([0.1, -0.2])
        assert payload["joint_states"]["effort"] == pytest.approx([0.0, 0.0])
        assert payload["imu"]["orientation"] == pytest.approx([1.0, 0.0, 0.0, 0.0])
        assert payload["imu"]["policy_euler"]["yaw"] == pytest.approx(0.0)

    def test_apply_joint_command_payload_updates_targets_and_timestamp(self) -> None:
        ctrl = _make_controller()

        ok, payload = ctrl.apply_joint_command_payload({
            "name": ["hip_pitch_l_joint", "hip_pitch_r_joint"],
            "position": [-0.4, -0.5],
        })

        assert ok is True
        assert payload == {"success": True, "joints": 2}
        assert ctrl._target_joint_positions == {
            "hip_pitch_l_joint": pytest.approx(-0.4),
            "hip_pitch_r_joint": pytest.approx(-0.5),
        }
        assert ctrl._last_joint_cmd_time > 0.0

    def test_apply_joint_command_payload_rejects_name_position_mismatch(self) -> None:
        ctrl = _make_controller()

        ok, payload = ctrl.apply_joint_command_payload({
            "name": ["hip_pitch_l_joint"],
            "position": [],
        })

        assert ok is False
        assert payload == {"success": False, "error": "name/position mismatch"}
        assert ctrl._target_joint_positions == {}
        assert ctrl._last_joint_cmd_time == pytest.approx(0.0)


class TestJointSignOverrides:
    """Verify sim-only joint sign overrides preserve raw articulation visibility."""

    def test_parse_joint_sign_overrides_accepts_common_separators(self) -> None:
        overrides = parse_joint_sign_overrides(
            "ankle_pitch_l_joint=-1; ankle_pitch_r_joint:1"
        )

        assert overrides == {
            "ankle_pitch_l_joint": -1.0,
            "ankle_pitch_r_joint": 1.0,
        }

    def test_refresh_joint_state_cache_applies_feedback_sign_overrides_without_mutating_raw_cache(self) -> None:
        ctrl = _make_controller(joint_feedback_sign_overrides={"ankle_pitch_l_joint": -1.0})
        ctrl._joint_names = ["joint_a", "ankle_pitch_l_joint"]
        ctrl._joint_name_to_index = {name: i for i, name in enumerate(ctrl._joint_names)}

        class _Articulation:
            def get_joint_positions(self):
                return [1.0, -2.0]

            def get_joint_velocities(self):
                return [0.25, -0.5]

        ctrl._articulation = _Articulation()
        ctrl.refresh_joint_state_cache(0.02)

        assert ctrl._cached_joint_pos.tolist() == pytest.approx([1.0, -2.0])
        assert ctrl._cached_joint_vel.tolist() == pytest.approx([0.25, -0.5])
        assert ctrl._joint_positions_raw == {
            "joint_a": 1.0,
            "ankle_pitch_l_joint": -2.0,
        }
        assert ctrl._joint_velocities_raw == {
            "joint_a": 0.25,
            "ankle_pitch_l_joint": -0.5,
        }
        assert ctrl._joint_positions == {
            "joint_a": 1.0,
            "ankle_pitch_l_joint": 2.0,
        }
        assert ctrl._joint_velocities == {
            "joint_a": 0.25,
            "ankle_pitch_l_joint": 0.5,
        }

    def test_apply_joint_targets_applies_target_sign_overrides_and_exposes_debug_payload(self) -> None:
        ctrl = _make_controller(
            joint_target_sign_overrides={"ankle_pitch_l_joint": -1.0},
            joint_feedback_sign_overrides={"ankle_pitch_l_joint": -1.0},
        )
        ctrl._joint_names = ["hip_pitch_l_joint", "ankle_pitch_l_joint", "ankle_pitch_r_joint"]
        ctrl._joint_name_to_index = {name: i for i, name in enumerate(ctrl._joint_names)}
        ctrl._cached_joint_pos = [0.1, 0.2, -0.3]
        ctrl._cached_joint_vel = [0.0, 0.0, 0.0]
        ctrl._joint_positions_raw = {
            "hip_pitch_l_joint": 0.1,
            "ankle_pitch_l_joint": 0.2,
            "ankle_pitch_r_joint": -0.3,
        }
        ctrl._joint_velocities_raw = {
            "hip_pitch_l_joint": 0.0,
            "ankle_pitch_l_joint": 0.0,
            "ankle_pitch_r_joint": 0.0,
        }
        ctrl._joint_positions = {
            "hip_pitch_l_joint": 0.1,
            "ankle_pitch_l_joint": -0.2,
            "ankle_pitch_r_joint": -0.3,
        }
        ctrl._joint_velocities = {
            "hip_pitch_l_joint": 0.0,
            "ankle_pitch_l_joint": 0.0,
            "ankle_pitch_r_joint": 0.0,
        }
        ctrl._target_joint_positions = {"ankle_pitch_l_joint": 0.9}
        ctrl._articulation_setup_complete = True

        captured: dict[str, list[float]] = {}

        class _Articulation:
            def set_joint_position_targets(self, values):
                row = values[0] if len(values) > 0 else []
                captured["joint_positions"] = [float(v) for v in row]

        ctrl._articulation = _Articulation()
        ctrl._apply_joint_targets()

        assert captured["joint_positions"] == pytest.approx([0.1, -0.9, -0.3])

        payload = ctrl.get_joint_debug_payload()

        assert payload["joint_target_sign_overrides"] == {"ankle_pitch_l_joint": -1.0}
        assert payload["joint_feedback_sign_overrides"] == {"ankle_pitch_l_joint": -1.0}
        assert payload["last_target_positions_logical"]["ankle_pitch_l_joint"] == pytest.approx(0.9)
        assert payload["last_target_positions_raw"]["ankle_pitch_l_joint"] == pytest.approx(-0.9)
        assert payload["last_target_array_logical"] == pytest.approx([0.1, 0.9, -0.3])
        assert payload["last_target_array_raw"] == pytest.approx([0.1, -0.9, -0.3])
        assert payload["last_target_apply_method"] == "articulation.set_joint_position_targets"
        focus = payload["ankle_focus"]["ankle_pitch_l_joint"]
        assert focus["index"] == 1
        assert focus["feedback_position_logical"] == pytest.approx(-0.2)
        assert focus["feedback_position_raw"] == pytest.approx(0.2)
        assert focus["feedback_velocity_logical"] == pytest.approx(0.0)
        assert focus["feedback_velocity_raw"] == pytest.approx(0.0)
        assert focus["target_position_logical"] == pytest.approx(0.9)
        assert focus["last_applied_target_position_logical"] == pytest.approx(0.9)
        assert focus["last_applied_target_position_raw"] == pytest.approx(-0.9)


class TestJointGainMapping:
    """Verify policy gains are remapped by joint name before being applied."""

    def test_policy_gains_follow_joint_names_not_articulation_index(self) -> None:
        ctrl = _make_controller(
            joint_kp=[
                700.0, 700.0, 500.0, 700.0, 15.0, 15.0,
                700.0, 700.0, 500.0, 700.0, 15.0, 15.0,
                60.0, 20.0, 10.0, 10.0,
                60.0, 20.0, 10.0, 10.0,
            ],
            joint_kd=[
                20.0, 20.0, 15.0, 10.0, 1.25, 1.25,
                20.0, 20.0, 15.0, 10.0, 1.25, 1.25,
                3.0, 1.5, 1.0, 1.0,
                3.0, 1.5, 1.0, 1.0,
            ],
        )
        applied: dict[str, list[float]] = {}

        class _ArticulationController:
            def set_gains(self, kps, kds):
                applied["kps"] = [float(v) for v in kps]
                applied["kds"] = [float(v) for v in kds]

        class _Robot:
            dof_names = [
                "hip_roll_l_joint",
                "hip_roll_r_joint",
                "hip_yaw_l_joint",
                "hip_yaw_r_joint",
                "shoulder_pitch_l_joint",
                "shoulder_pitch_r_joint",
                "hip_pitch_l_joint",
                "hip_pitch_r_joint",
                "shoulder_roll_l_joint",
                "shoulder_roll_r_joint",
                "knee_pitch_l_joint",
                "knee_pitch_r_joint",
                "shoulder_yaw_l_joint",
                "shoulder_yaw_r_joint",
                "ankle_pitch_l_joint",
                "ankle_pitch_r_joint",
                "elbow_pitch_l_joint",
                "elbow_pitch_r_joint",
                "ankle_roll_l_joint",
                "ankle_roll_r_joint",
            ]

            def get_articulation_controller(self):
                return _ArticulationController()

        ctrl.set_robot(_Robot())

        assert applied["kps"][4] == pytest.approx(60.0)
        assert applied["kds"][4] == pytest.approx(3.0)
        assert applied["kps"][10] == pytest.approx(700.0)
        assert applied["kds"][10] == pytest.approx(10.0)
        assert applied["kps"][14] == pytest.approx(15.0)
        assert applied["kds"][14] == pytest.approx(1.25)
        assert applied["kps"][16] == pytest.approx(10.0)
        assert applied["kds"][16] == pytest.approx(1.0)

    def test_official_lite_gain_profile_matches_checked_in_isaac_lab_actuators(self) -> None:
        ctrl = _make_controller(actuator_gain_profile="official_lite")
        applied: dict[str, list[float]] = {}

        class _ArticulationController:
            def set_gains(self, kps, kds):
                applied["kps"] = [float(v) for v in kps]
                applied["kds"] = [float(v) for v in kds]

        class _Robot:
            dof_names = [
                "ankle_pitch_l_joint",
                "ankle_roll_l_joint",
                "hip_yaw_r_joint",
                "shoulder_roll_r_joint",
                "elbow_pitch_l_joint",
            ]

            def get_articulation_controller(self):
                return _ArticulationController()

        ctrl.set_robot(_Robot())

        assert ctrl._gain_profile_name == "official_lite"
        assert applied["kps"] == pytest.approx([30.0, 16.8, 500.0, 20.0, 10.0])
        assert applied["kds"] == pytest.approx([2.5, 1.4, 5.0, 1.5, 1.0])
        assert ctrl._limit_profile_name == "not_configured"

    def test_official_lite_limit_profile_matches_checked_in_isaac_lab_actuators(self) -> None:
        ctrl = _make_controller(
            actuator_gain_profile="official_lite",
            actuator_limit_profile="official_lite",
        )
        applied: dict[str, object] = {}

        class _View:
            count = 2

            def is_physics_handle_valid(self):
                return True

            def set_max_efforts(self, values):
                applied["max_efforts"] = values

            def set_max_joint_velocities(self, values):
                applied["max_velocities"] = values

        view = _View()

        class _ArticulationController:
            def set_gains(self, kps, kds):
                applied["kps"] = [float(v) for v in kps]
                applied["kds"] = [float(v) for v in kds]

        class _Robot:
            _articulation_view = view
            dof_names = [
                "ankle_pitch_l_joint",
                "ankle_roll_l_joint",
                "hip_yaw_r_joint",
                "shoulder_roll_r_joint",
                "elbow_pitch_l_joint",
            ]

            def get_articulation_controller(self):
                return _ArticulationController()

        ctrl.set_robot(_Robot())

        assert ctrl._limit_profile_name == "official_lite"
        assert ctrl._limit_apply_method == "articulation_view.set_max_efforts+set_max_joint_velocities"
        assert ctrl._limit_apply_error == ""
        assert ctrl._applied_joint_max_effort == {
            "ankle_pitch_l_joint": 60.0,
            "ankle_roll_l_joint": 30.0,
            "hip_yaw_r_joint": 180.0,
            "shoulder_roll_r_joint": 52.5,
            "elbow_pitch_l_joint": 52.5,
        }
        assert ctrl._applied_joint_max_velocity == {
            "ankle_pitch_l_joint": 12.8,
            "ankle_roll_l_joint": 7.8,
            "hip_yaw_r_joint": 15.6,
            "shoulder_roll_r_joint": 14.1,
            "elbow_pitch_l_joint": 14.1,
        }
        assert applied["max_efforts"].reshape(-1).tolist() == pytest.approx(
            [
                60.0, 30.0, 180.0, 52.5, 52.5,
                60.0, 30.0, 180.0, 52.5, 52.5,
            ]
        )
        assert applied["max_velocities"].reshape(-1).tolist() == pytest.approx(
            [
                12.8, 7.8, 15.6, 14.1, 14.1,
                12.8, 7.8, 15.6, 14.1, 14.1,
            ]
        )

    def test_set_robot_primes_nominal_standing_pose(self) -> None:
        ctrl = _make_controller()
        captured: dict[str, object] = {}

        class _ArticulationController:
            def set_gains(self, kps, kds):
                captured["kps"] = [float(v) for v in kps]
                captured["kds"] = [float(v) for v in kds]

        class _Robot:
            prim_path = "/World/humanoid/base_link"
            dof_names = [
                "hip_pitch_l_joint",
                "knee_pitch_l_joint",
                "ankle_pitch_l_joint",
                "shoulder_roll_r_joint",
                "elbow_pitch_l_joint",
            ]

            def get_articulation_controller(self):
                return _ArticulationController()

            def set_default_state(self, position, orientation):
                captured["default_state_position"] = [float(v) for v in position]
                captured["default_state_orientation"] = [float(v) for v in orientation]

            def set_joints_default_state(self, positions, velocities, efforts):
                captured["default_joint_positions"] = [float(v) for v in positions]
                captured["default_joint_velocities"] = [float(v) for v in velocities]
                captured["default_joint_efforts"] = [float(v) for v in efforts]

            def post_reset(self):
                captured["post_reset_called"] = True

            def set_world_pose(self, position, orientation):
                captured["world_position"] = [float(v) for v in position]
                captured["world_orientation"] = [float(v) for v in orientation]

            def set_joint_positions(self, positions):
                captured["joint_positions"] = [float(v) for v in positions]

            def set_joint_velocities(self, velocities):
                captured["joint_velocities"] = [float(v) for v in velocities]

            def set_linear_velocity(self, velocity):
                captured["linear_velocity"] = [float(v) for v in velocity]

            def set_angular_velocity(self, velocity):
                captured["angular_velocity"] = [float(v) for v in velocity]

        ctrl.set_robot(_Robot())

        assert ctrl._articulation_prim_path == "/World/humanoid/base_link"
        assert captured["world_position"] == pytest.approx([0.0, 0.0, 0.77255])
        assert captured["world_orientation"] == pytest.approx([1.0, 0.0, 0.0, 0.0])
        assert captured["default_state_position"] == pytest.approx([0.0, 0.0, 0.77255])
        assert captured["default_state_orientation"] == pytest.approx([1.0, 0.0, 0.0, 0.0])
        assert captured["default_joint_positions"] == pytest.approx([-0.5, 1.0, -0.5, -0.1, -0.3])
        assert captured["default_joint_velocities"] == pytest.approx([0.0, 0.0, 0.0, 0.0, 0.0])
        assert captured["default_joint_efforts"] == pytest.approx([0.0, 0.0, 0.0, 0.0, 0.0])
        assert captured["post_reset_called"] is True
        assert captured["joint_positions"] == pytest.approx([-0.5, 1.0, -0.5, -0.1, -0.3])
        assert captured["joint_velocities"] == pytest.approx([0.0, 0.0, 0.0, 0.0, 0.0])
        assert captured["linear_velocity"] == pytest.approx([0.0, 0.0, 0.0])
        assert captured["angular_velocity"] == pytest.approx([0.0, 0.0, 0.0])
        assert ctrl._target_joint_positions == {
            "hip_pitch_l_joint": -0.5,
            "knee_pitch_l_joint": 1.0,
            "ankle_pitch_l_joint": -0.5,
            "shoulder_roll_r_joint": -0.1,
            "elbow_pitch_l_joint": -0.3,
        }
        assert ctrl._startup_pose_primed is True
        assert ctrl._startup_pose_error == ""
        assert ctrl._startup_pose_info["orientation_source"] == "default_identity_grounded"
        assert ctrl._startup_hold_active is True
        assert ctrl._startup_pose_info["hold_duration_s"] == pytest.approx(0.75)
        assert ctrl._startup_pose_info["nominal_hold_tolerance_rad"] == pytest.approx(0.08)

    def test_reset_to_standing_pose_clears_motion_and_reapplies_nominal_targets(self) -> None:
        ctrl = _make_controller()
        captured: dict[str, object] = {}

        class _ArticulationController:
            def set_gains(self, kps, kds):
                captured["kps"] = [float(v) for v in kps]
                captured["kds"] = [float(v) for v in kds]

        class _Robot:
            prim_path = "/World/humanoid/base_link"
            dof_names = [
                "hip_pitch_l_joint",
                "knee_pitch_l_joint",
                "ankle_pitch_l_joint",
            ]

            def get_articulation_controller(self):
                return _ArticulationController()

            def set_default_state(self, position, orientation):
                captured["default_state_position"] = [float(v) for v in position]
                captured["default_state_orientation"] = [float(v) for v in orientation]

            def set_joints_default_state(self, positions, velocities, efforts):
                captured["default_joint_positions"] = [float(v) for v in positions]
                captured["default_joint_velocities"] = [float(v) for v in velocities]
                captured["default_joint_efforts"] = [float(v) for v in efforts]

            def post_reset(self):
                captured["post_reset_called"] = True

            def set_world_pose(self, position, orientation):
                captured["world_position"] = [float(v) for v in position]
                captured["world_orientation"] = [float(v) for v in orientation]

            def set_joint_positions(self, positions):
                captured["joint_positions"] = [float(v) for v in positions]

            def set_joint_velocities(self, velocities):
                captured["joint_velocities"] = [float(v) for v in velocities]

            def set_linear_velocity(self, velocity):
                captured["linear_velocity"] = [float(v) for v in velocity]

            def set_angular_velocity(self, velocity):
                captured["angular_velocity"] = [float(v) for v in velocity]

        ctrl.set_robot(_Robot())
        ctrl._target_linear = 0.6
        ctrl._target_angular = -0.3
        ctrl._current_linear = 0.4
        ctrl._current_angular = -0.2
        ctrl._last_cmd_time = time.time()
        ctrl._joint_positions = {
            "hip_pitch_l_joint": 0.2,
            "knee_pitch_l_joint": 0.3,
            "ankle_pitch_l_joint": 0.1,
        }

        ok, payload = ctrl.reset_to_standing_pose()

        assert ok is True
        assert payload["success"] is True
        assert payload["startup_pose_hold_active"] is True
        assert payload["pose"]["position"] == pytest.approx([0.0, 0.0, 0.77255])
        assert payload["stand_error"]["ok"] is True
        assert ctrl._target_linear == pytest.approx(0.0)
        assert ctrl._target_angular == pytest.approx(0.0)
        assert ctrl._current_linear == pytest.approx(0.0)
        assert ctrl._current_angular == pytest.approx(0.0)
        assert ctrl._last_cmd_time == pytest.approx(0.0)
        assert captured["world_position"] == pytest.approx([0.0, 0.0, 0.77255])
        assert captured["joint_positions"] == pytest.approx([-0.5, 1.0, -0.5])
        assert captured["linear_velocity"] == pytest.approx([0.0, 0.0, 0.0])
        assert captured["angular_velocity"] == pytest.approx([0.0, 0.0, 0.0])
        assert ctrl._target_joint_positions == {
            "hip_pitch_l_joint": -0.5,
            "knee_pitch_l_joint": 1.0,
            "ankle_pitch_l_joint": -0.5,
        }

    def test_controller_can_opt_into_legacy_startup_orientation_via_env(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ISAAC_USE_LEGACY_STARTUP_ORIENTATION", "1")
        ctrl = _make_controller()

        assert ctrl._startup_orientation_wxyz.tolist() == pytest.approx(
            LEGACY_STARTUP_STAND_ORIENTATION_WXYZ.tolist()
        )
        assert ctrl._startup_pose_info["orientation_source"] == "env:ISAAC_USE_LEGACY_STARTUP_ORIENTATION"

    def test_startup_pose_hold_reapplies_seed_pose_until_window_expires(self) -> None:
        ctrl = _make_controller()
        ctrl._joint_names = ["hip_pitch_l_joint", "knee_pitch_l_joint"]
        ctrl._startup_joint_positions = _np_mock.array([-0.5, 1.0])
        ctrl._startup_joint_velocities = _np_mock.array([0.0, 0.0])
        ctrl._startup_hold_active = True
        ctrl._startup_hold_deadline = time.time() + 10.0
        ctrl._startup_base_position = _np_mock.array([0.0, 0.0, 0.77255])
        ctrl._startup_orientation_wxyz = _np_mock.array(STARTUP_STAND_ORIENTATION_WXYZ)
        ctrl._joint_positions = {name: 0.0 for name in ctrl._joint_names}
        ctrl._joint_velocities = {name: 0.0 for name in ctrl._joint_names}
        captured: dict[str, list[float]] = {}

        class _Robot:
            def set_world_pose(self, position, orientation):
                captured["position"] = [float(v) for v in position]
                captured["orientation"] = [float(v) for v in orientation]

            def set_joint_positions(self, positions):
                captured["joint_positions"] = [float(v) for v in positions]

            def set_joint_velocities(self, velocities):
                captured["joint_velocities"] = [float(v) for v in velocities]

            def set_linear_velocity(self, velocity):
                captured["linear_velocity"] = [float(v) for v in velocity]

            def set_angular_velocity(self, velocity):
                captured["angular_velocity"] = [float(v) for v in velocity]

        ctrl._articulation = _Robot()

        assert ctrl._maintain_startup_pose(time.time()) is True
        assert captured["position"] == pytest.approx([0.0, 0.0, 0.77255])
        assert captured["orientation"] == pytest.approx(STARTUP_STAND_ORIENTATION_WXYZ.tolist())
        assert captured["joint_positions"] == pytest.approx([-0.5, 1.0])
        assert captured["joint_velocities"] == pytest.approx([0.0, 0.0])
        assert captured["linear_velocity"] == pytest.approx([0.0, 0.0, 0.0])
        assert captured["angular_velocity"] == pytest.approx([0.0, 0.0, 0.0])

    def test_startup_pose_hold_persists_while_targets_still_match_nominal_stand(self) -> None:
        ctrl = _make_controller()
        ctrl._joint_names = ["hip_pitch_l_joint", "knee_pitch_l_joint"]
        ctrl._startup_joint_positions = _np_mock.array([-0.5, 1.0])
        ctrl._startup_joint_velocities = _np_mock.array([0.0, 0.0])
        ctrl._startup_hold_active = True
        ctrl._startup_hold_deadline = time.time() - 1.0
        ctrl._target_joint_positions = {
            "hip_pitch_l_joint": -0.5,
            "knee_pitch_l_joint": 1.0,
        }
        ctrl._joint_positions = {name: 0.0 for name in ctrl._joint_names}
        ctrl._joint_velocities = {name: 0.0 for name in ctrl._joint_names}

        class _Robot:
            def set_world_pose(self, position, orientation):
                return None

            def set_joint_positions(self, positions):
                return None

            def set_joint_velocities(self, velocities):
                return None

            def set_linear_velocity(self, velocity):
                return None

            def set_angular_velocity(self, velocity):
                return None

        ctrl._articulation = _Robot()

        assert ctrl._maintain_startup_pose(time.time()) is True
        assert ctrl._startup_hold_active is True

    def test_startup_pose_hold_persists_for_fresh_nominal_stand_commands(self) -> None:
        ctrl = _make_controller()
        ctrl._joint_names = ["hip_pitch_l_joint", "knee_pitch_l_joint"]
        ctrl._startup_joint_positions = _np_mock.array([-0.5, 1.0])
        ctrl._startup_joint_velocities = _np_mock.array([0.0, 0.0])
        ctrl._startup_hold_active = True
        ctrl._startup_hold_deadline = time.time() - 1.0
        ctrl._last_joint_cmd_time = time.time()
        ctrl._target_joint_positions = {
            "hip_pitch_l_joint": -0.5,
            "knee_pitch_l_joint": 1.0,
        }
        ctrl._joint_positions = {name: 0.0 for name in ctrl._joint_names}
        ctrl._joint_velocities = {name: 0.0 for name in ctrl._joint_names}

        class _Robot:
            def set_world_pose(self, position, orientation):
                return None

            def set_joint_positions(self, positions):
                return None

            def set_joint_velocities(self, velocities):
                return None

            def set_linear_velocity(self, velocity):
                return None

            def set_angular_velocity(self, velocity):
                return None

        ctrl._articulation = _Robot()

        assert ctrl._maintain_startup_pose(time.time()) is True
        assert ctrl._startup_hold_active is True

    def test_startup_pose_hold_tolerates_small_joint_offsets_within_configured_threshold(self) -> None:
        ctrl = _make_controller(startup_nominal_hold_tolerance_rad=0.08)
        ctrl._joint_names = ["hip_pitch_l_joint", "knee_pitch_l_joint"]
        ctrl._startup_joint_positions = _np_mock.array([-0.5, 1.0])
        ctrl._startup_joint_velocities = _np_mock.array([0.0, 0.0])
        ctrl._startup_hold_active = True
        ctrl._startup_hold_deadline = time.time() - 1.0
        ctrl._last_joint_cmd_time = time.time()
        ctrl._target_joint_positions = {
            "hip_pitch_l_joint": -0.48,
            "knee_pitch_l_joint": 0.98,
        }
        ctrl._joint_positions = {name: 0.0 for name in ctrl._joint_names}
        ctrl._joint_velocities = {name: 0.0 for name in ctrl._joint_names}

        class _Robot:
            def set_world_pose(self, position, orientation):
                return None

            def set_joint_positions(self, positions):
                return None

            def set_joint_velocities(self, velocities):
                return None

            def set_linear_velocity(self, velocity):
                return None

            def set_angular_velocity(self, velocity):
                return None

        ctrl._articulation = _Robot()

        assert ctrl._maintain_startup_pose(time.time()) is True
        assert ctrl._startup_hold_active is True

    def test_startup_pose_hold_yields_to_fresh_non_nominal_joint_commands(self) -> None:
        ctrl = _make_controller()
        ctrl._joint_names = ["hip_pitch_l_joint", "knee_pitch_l_joint"]
        ctrl._startup_joint_positions = _np_mock.array([-0.5, 1.0])
        ctrl._startup_joint_velocities = _np_mock.array([0.0, 0.0])
        ctrl._startup_hold_active = True
        ctrl._startup_hold_deadline = time.time() - 1.0
        ctrl._last_joint_cmd_time = time.time()
        ctrl._target_joint_positions = {
            "hip_pitch_l_joint": -0.35,
            "knee_pitch_l_joint": 0.85,
        }
        ctrl._joint_positions = {name: 0.0 for name in ctrl._joint_names}
        ctrl._joint_velocities = {name: 0.0 for name in ctrl._joint_names}

        assert ctrl._maintain_startup_pose(time.time()) is False
        assert ctrl._startup_hold_active is False

    def test_stand_error_payload_reports_largest_joint_deviations(self) -> None:
        ctrl = _make_controller()
        ctrl._joint_names = [
            "hip_pitch_l_joint",
            "knee_pitch_l_joint",
            "ankle_pitch_l_joint",
        ]
        ctrl._joint_positions = {
            "hip_pitch_l_joint": -0.25,
            "knee_pitch_l_joint": 0.7,
            "ankle_pitch_l_joint": -1.1,
        }

        payload = ctrl.get_stand_error_payload()

        assert payload["ok"] is True
        assert payload["joint_count"] == 3
        assert payload["max_abs_error"] == pytest.approx(0.6)
        assert payload["top_errors"][0]["joint"] == "ankle_pitch_l_joint"
        assert payload["top_errors"][0]["delta"] == pytest.approx(-0.6)


class TestArticulationHandleReadiness:
    """Verify articulation setup waits for a valid physics handle."""

    def test_warm_up_articulation_handle_retries_until_view_is_valid(self) -> None:
        state = {"initialize_calls": 0, "step_calls": 0}

        class _View:
            valid = False

            def is_physics_handle_valid(self):
                return self.valid

        view = _View()

        class _Robot:
            _articulation_view = view

            def initialize(self):
                state["initialize_calls"] += 1
                if state["initialize_calls"] >= 2:
                    view.valid = True

        class _World:
            def step(self, render):
                state["step_calls"] += 1

        ready, error = _warm_up_articulation_handle(_Robot(), _World(), render=False, max_attempts=4)

        assert ready is True
        assert error == ""
        assert state["initialize_calls"] >= 2
        assert state["step_calls"] >= 1

    def test_set_robot_defers_standing_pose_priming_until_handle_is_valid(self) -> None:
        ctrl = _make_controller()
        captured = {
            "set_default_state_calls": 0,
            "set_joint_positions_calls": 0,
        }

        class _View:
            valid = False

            def is_physics_handle_valid(self):
                return self.valid

        view = _View()

        class _ArticulationController:
            def set_gains(self, kps, kds):
                return None

        class _Robot:
            prim_path = "/World/humanoid/pelvis"
            dof_names = ["hip_pitch_l_joint", "knee_pitch_l_joint"]
            _articulation_view = view

            def initialize(self):
                return None

            def get_articulation_controller(self):
                return _ArticulationController()

            def set_default_state(self, position, orientation):
                captured["set_default_state_calls"] += 1

            def set_joints_default_state(self, positions, velocities, efforts):
                return None

            def post_reset(self):
                return None

            def set_world_pose(self, position, orientation):
                return None

            def set_joint_positions(self, positions):
                captured["set_joint_positions_calls"] += 1

            def set_joint_velocities(self, velocities):
                return None

            def set_linear_velocity(self, velocity):
                return None

            def set_angular_velocity(self, velocity):
                return None

            def get_joint_positions(self):
                return [-0.5, 1.0]

            def get_joint_velocities(self):
                return [0.0, 0.0]

        robot = _Robot()
        ctrl.set_robot(robot)

        assert ctrl._startup_pose_primed is False
        assert ctrl._articulation_setup_complete is False
        assert captured["set_default_state_calls"] == 0
        assert captured["set_joint_positions_calls"] == 0

        view.valid = True
        ctrl.refresh_joint_state_cache(0.02)

        assert ctrl._startup_pose_primed is True
        assert ctrl._articulation_setup_complete is True
        assert captured["set_default_state_calls"] == 1
        assert captured["set_joint_positions_calls"] >= 1


class TestQuaternionOrder:
    """Verify Isaac Sim scalar-first quaternions are interpreted correctly."""

    def test_quat_wxyz_to_euler_identity_is_zero(self) -> None:
        yaw, pitch, roll = quat_wxyz_to_euler([1.0, 0.0, 0.0, 0.0])
        assert yaw == pytest.approx(0.0)
        assert pitch == pytest.approx(0.0)
        assert roll == pytest.approx(0.0)

    def test_quat_wxyz_to_euler_pitch_rotation_uses_scalar_first_order(self) -> None:
        yaw, pitch, roll = quat_wxyz_to_euler([0.70710678, 0.0, 0.70710678, 0.0])
        assert yaw == pytest.approx(0.0, abs=1e-6)
        assert pitch == pytest.approx(1.5707963, abs=1e-4)
        assert roll == pytest.approx(0.0, abs=1e-6)

    def test_relative_quaternion_removes_nominal_startup_tilt(self) -> None:
        neutral = STARTUP_STAND_ORIENTATION_WXYZ.tolist()
        relative = relative_quat_wxyz(neutral, neutral)
        assert relative.tolist() == pytest.approx([1.0, 0.0, 0.0, 0.0], abs=1e-6)


class TestJointTargetApplication:
    """Verify joint targets are sent through the real Isaac articulation API shape."""

    def test_apply_joint_targets_prefers_set_joint_position_targets_when_available(self) -> None:
        ctrl = _make_controller()
        ctrl._joint_names = ["joint_a", "joint_b", "joint_c"]
        ctrl._cached_joint_pos = [0.1, 0.2, 0.3]
        ctrl._target_joint_positions = {"joint_b": 0.9}

        captured: dict[str, list[float]] = {}

        class _Articulation:
            def set_joint_position_targets(self, values):
                row = values[0] if len(values) > 0 else []
                captured["joint_positions"] = [float(v) for v in row]

        ctrl._articulation = _Articulation()
        ctrl._apply_joint_targets()

        assert captured["joint_positions"] == pytest.approx([0.1, 0.9, 0.3])

    def test_apply_joint_targets_uses_articulation_apply_action_when_controller_has_no_target_method(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake_isaacsim = types.ModuleType("isaacsim")
        fake_core = types.ModuleType("isaacsim.core")
        fake_utils = types.ModuleType("isaacsim.core.utils")
        fake_types = types.ModuleType("isaacsim.core.utils.types")

        class _ArticulationAction:
            def __init__(self, joint_positions=None):
                self.joint_positions = joint_positions

        fake_types.ArticulationAction = _ArticulationAction
        fake_utils.types = fake_types
        fake_core.utils = fake_utils
        fake_isaacsim.core = fake_core
        monkeypatch.setitem(sys.modules, "isaacsim", fake_isaacsim)
        monkeypatch.setitem(sys.modules, "isaacsim.core", fake_core)
        monkeypatch.setitem(sys.modules, "isaacsim.core.utils", fake_utils)
        monkeypatch.setitem(sys.modules, "isaacsim.core.utils.types", fake_types)

        ctrl = _make_controller()
        ctrl._joint_names = ["joint_a", "joint_b", "joint_c"]
        ctrl._cached_joint_pos = [0.1, 0.2, 0.3]
        ctrl._target_joint_positions = {"joint_b": 0.9}

        captured: dict[str, list[float]] = {}

        class _ArticulationController:
            pass

        class _Articulation:
            def get_articulation_controller(self):
                return _ArticulationController()

            def apply_action(self, action):
                captured["joint_positions"] = [float(v) for v in action.joint_positions]

        ctrl._articulation = _Articulation()
        ctrl._apply_joint_targets()

        assert captured["joint_positions"] == pytest.approx([0.1, 0.9, 0.3])


class TestStandaloneControlArbitration:
    """Verify standalone/headless control does not let priming targets mask /move."""

    def test_update_prefers_velocity_when_move_command_is_active(self) -> None:
        ctrl = _make_controller()
        ctrl._target_joint_positions = {"hip_pitch_l_joint": -0.5}
        ctrl._last_joint_cmd_time = time.time() - 10.0
        ctrl._target_linear = 0.4
        ctrl._last_cmd_time = time.time()
        ctrl._apply_joint_targets = MagicMock()
        ctrl._apply_velocity = MagicMock()

        ctrl.update(dt=0.01)

        ctrl._apply_joint_targets.assert_not_called()
        ctrl._apply_velocity.assert_called_once()

    def test_refresh_joint_state_cache_uses_articulation_velocity_when_available(self) -> None:
        ctrl = _make_controller()
        ctrl._joint_names = ["joint_a", "joint_b"]

        class _Articulation:
            def get_joint_positions(self):
                return [1.0, -2.0]

            def get_joint_velocities(self):
                return [0.25, -0.5]

        ctrl._articulation = _Articulation()
        ctrl.refresh_joint_state_cache(0.02)

        assert ctrl._cached_joint_pos.tolist() == pytest.approx([1.0, -2.0])
        assert ctrl._cached_joint_vel.tolist() == pytest.approx([0.25, -0.5])
        assert ctrl._joint_positions == {"joint_a": 1.0, "joint_b": -2.0}
        assert ctrl._joint_velocities == {"joint_a": 0.25, "joint_b": -0.5}


class TestPhysicsConfiguration:
    """Verify physics configuration degrades gracefully when Isaac APIs are absent."""

    def test_configure_simulation_physics_without_stage_records_warning(self) -> None:
        ctrl = _make_controller()

        ctrl._configure_simulation_physics()

        assert ctrl._physics_config_info["configured"] is False
        assert "stage_unavailable" in ctrl._physics_config_warnings


class TestOfficialLiteAssetPath:
    """Verify the helper targets the checked-in official Lite asset bundle."""

    def test_default_official_lite_usd_path_has_expected_suffix(self) -> None:
        path = get_default_official_lite_usd_path()

        assert path.replace("\\", "/").endswith(
            "third_party/TienKung-Lab/legged_lab/assets/tienkung2_lite/usd/tienkung2_lite.usd"
        )


# ---------------------------------------------------------------------------
# Task 10.2 — Property 10: ROS2_Control_Bridge velocity clamping
# Requirements: 6.5, 6.6
# ---------------------------------------------------------------------------

from hypothesis import given, settings  # noqa: E402
import hypothesis.strategies as st  # noqa: E402


# Feature: joystick-sim-integration-test, Property 10: ROS2_Control_Bridge velocity clamping
@given(
    st.floats(allow_nan=False, allow_infinity=False),
    st.floats(allow_nan=False, allow_infinity=False),
)
@settings(max_examples=200)
def test_cmd_vel_callback_velocity_clamping(linear_x: float, angular_z: float) -> None:
    """Validates: Requirements 6.5, 6.6

    For any finite float velocity inputs, _cmd_vel_callback must clamp
    _target_linear to [-max_linear_velocity, max_linear_velocity] and
    _target_angular to [-max_angular_velocity, max_angular_velocity].
    """
    ctrl = _make_controller(max_linear_velocity=1.0, max_angular_velocity=1.5)
    msg = _make_twist(linear_x=linear_x, angular_z=angular_z)
    ctrl._cmd_vel_callback(msg)

    assert abs(ctrl._target_linear) <= ctrl.config.max_linear_velocity, (
        f"_target_linear={ctrl._target_linear} exceeds max={ctrl.config.max_linear_velocity}"
    )
    assert abs(ctrl._target_angular) <= ctrl.config.max_angular_velocity, (
        f"_target_angular={ctrl._target_angular} exceeds max={ctrl.config.max_angular_velocity}"
    )
