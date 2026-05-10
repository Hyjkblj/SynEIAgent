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
from unittest.mock import MagicMock

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

sys.modules.setdefault("rclpy", _rclpy_mock)
sys.modules.setdefault("rclpy.node", _rclpy_mock.node)

# We do NOT replace numpy globally — the source file imports numpy at module
# level, so we patch it only for the target module's namespace after import.

sys.modules.setdefault("geometry_msgs", _geo_mod)
sys.modules.setdefault("geometry_msgs.msg", _geo_msg_mod)
sys.modules.setdefault("nav_msgs", _nav_mod)
sys.modules.setdefault("nav_msgs.msg", _nav_msg_mod)
sys.modules.setdefault("sensor_msgs", _sen_mod)
sys.modules.setdefault("sensor_msgs.msg", _sen_msg_mod)

# Now safe to import
from TGrobot4s.isaac_sim.ros2_control_bridge import (  # noqa: E402
    IsaacSimRobotController,
    RobotControlConfig,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_controller(**kwargs) -> IsaacSimRobotController:
    """Instantiate IsaacSimRobotController with rclpy.ok() returning False
    so _init_ros2 fails gracefully (no real ROS2 node created)."""
    config = RobotControlConfig(**kwargs)
    # rclpy.ok() already returns False from our mock, so _init_ros2 will
    # catch the ImportError / exception and set enabled=False.
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
