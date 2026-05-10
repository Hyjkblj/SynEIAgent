"""
Tests for ros_bridge_lite — /health response structure.
Feature: joystick-sim-integration-test
Requirements: 1.3, 1.5, 5.3, 7.3, 8.1, 8.2

Run in ROS Bridge environment:
  C:\\pixi_ws\\.pixi\\envs\\default\\python.exe -m pytest tests/test_ros_bridge.py -v
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Module-level mock setup — must happen before importing ros_bridge_lite.main
# ---------------------------------------------------------------------------

def _make_rclpy_mock() -> types.ModuleType:
    """Build a minimal rclpy mock that satisfies Ros2BridgeRuntime.__init__."""
    rclpy_mod = types.ModuleType("rclpy")
    rclpy_mod.ok = MagicMock(return_value=True)
    rclpy_mod.init = MagicMock()
    rclpy_mod.create_node = MagicMock()
    rclpy_mod.spin_once = MagicMock()
    rclpy_mod.spin_until_future_complete = MagicMock()
    return rclpy_mod


def _make_geometry_msgs_mock() -> types.ModuleType:
    """Build a minimal geometry_msgs mock."""
    # geometry_msgs
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


# Install mocks into sys.modules before any import of ros_bridge_lite
_rclpy_mock = _make_rclpy_mock()
_geo_mod, _geo_msg_mod = _make_geometry_msgs_mock()

sys.modules.setdefault("rclpy", _rclpy_mock)
sys.modules.setdefault("geometry_msgs", _geo_mod)
sys.modules.setdefault("geometry_msgs.msg", _geo_msg_mod)

# Also mock hric_msgs so the optional import doesn't fail in unexpected ways
_hric_mod = types.ModuleType("hric_msgs")
_hric_srv_mod = types.ModuleType("hric_msgs.srv")
_hric_mod.srv = _hric_srv_mod
sys.modules.setdefault("hric_msgs", _hric_mod)
sys.modules.setdefault("hric_msgs.srv", _hric_srv_mod)

# Now it's safe to import
from ros_bridge_lite.main import BridgeConfig, Ros2BridgeRuntime  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_runtime(enabled: bool = False) -> Ros2BridgeRuntime:
    """Return a Ros2BridgeRuntime.

    When enabled=False we want ROS2 initialisation to fail gracefully so the
    runtime stays in disabled mode — achieved by making rclpy.ok() raise.
    When enabled=True we let the mock succeed normally.
    """
    cfg = BridgeConfig(cmd_vel_topic="/cmd_vel")

    if not enabled:
        # Force __init__ to land in the except branch → self.enabled = False
        with patch.object(_rclpy_mock, "ok", side_effect=RuntimeError("ros_disabled_for_test")):
            rt = Ros2BridgeRuntime(cfg)
        assert not rt.enabled, "Expected runtime to be disabled"
    else:
        # Provide a mock publisher so cmd_vel_subscription_count() works
        mock_node = MagicMock()
        mock_pub = MagicMock()
        mock_pub.get_subscription_count.return_value = 0
        mock_node.create_publisher.return_value = mock_pub
        _rclpy_mock.ok.return_value = True
        _rclpy_mock.create_node = MagicMock(return_value=mock_node)

        rt = Ros2BridgeRuntime(cfg)
        # Patch the publisher directly in case create_node path differs
        rt._cmd_pub = mock_pub
    return rt


# ---------------------------------------------------------------------------
# Task 5.2 — Example-based tests: /health response structure
# Requirements: 1.3, 1.5, 5.3, 7.3, 8.1, 8.2
# ---------------------------------------------------------------------------

class TestHealthResponseStructure:
    """Verify that cmd_vel_debug() returns the required fields."""

    def test_cmd_vel_debug_has_subscription_count(self) -> None:
        """cmd_vel_debug must contain 'subscription_count'."""
        rt = _make_runtime(enabled=False)
        debug = rt.cmd_vel_debug()
        assert "subscription_count" in debug

    def test_cmd_vel_debug_has_publish_count(self) -> None:
        """cmd_vel_debug must contain 'publish_count'."""
        rt = _make_runtime(enabled=False)
        debug = rt.cmd_vel_debug()
        assert "publish_count" in debug

    def test_cmd_vel_debug_has_last_linear(self) -> None:
        """cmd_vel_debug must contain 'last_linear'."""
        rt = _make_runtime(enabled=False)
        debug = rt.cmd_vel_debug()
        assert "last_linear" in debug

    def test_cmd_vel_debug_has_last_angular(self) -> None:
        """cmd_vel_debug must contain 'last_angular'."""
        rt = _make_runtime(enabled=False)
        debug = rt.cmd_vel_debug()
        assert "last_angular" in debug

    def test_cmd_vel_debug_has_last_age_ms(self) -> None:
        """cmd_vel_debug must contain 'last_age_ms'."""
        rt = _make_runtime(enabled=False)
        debug = rt.cmd_vel_debug()
        assert "last_age_ms" in debug

    def test_cmd_vel_debug_all_required_fields(self) -> None:
        """cmd_vel_debug must contain all five required fields at once."""
        rt = _make_runtime(enabled=False)
        debug = rt.cmd_vel_debug()
        required = {"subscription_count", "publish_count", "last_linear", "last_angular", "last_age_ms"}
        missing = required - debug.keys()
        assert not missing, f"cmd_vel_debug missing fields: {missing}"

    def test_health_contains_ros_enabled(self) -> None:
        """Simulated /health payload must contain 'ros_enabled'."""
        rt = _make_runtime(enabled=False)
        payload = {
            "ok": True,
            "ros_enabled": rt.enabled,
            "ros_error": rt.error,
            "cmd_vel_debug": rt.cmd_vel_debug(),
        }
        assert "ros_enabled" in payload

    def test_health_contains_cmd_vel_debug(self) -> None:
        """Simulated /health payload must contain 'cmd_vel_debug'."""
        rt = _make_runtime(enabled=False)
        payload = {
            "ok": True,
            "ros_enabled": rt.enabled,
            "ros_error": rt.error,
            "cmd_vel_debug": rt.cmd_vel_debug(),
        }
        assert "cmd_vel_debug" in payload

    def test_health_cmd_vel_debug_is_dict(self) -> None:
        """cmd_vel_debug value in /health payload must be a dict."""
        rt = _make_runtime(enabled=False)
        payload = {
            "ok": True,
            "ros_enabled": rt.enabled,
            "cmd_vel_debug": rt.cmd_vel_debug(),
        }
        assert isinstance(payload["cmd_vel_debug"], dict)

    def test_disabled_runtime_ros_enabled_false(self) -> None:
        """When ROS2 is unavailable, ros_enabled must be False."""
        rt = _make_runtime(enabled=False)
        assert rt.enabled is False

    def test_disabled_runtime_publish_count_zero(self) -> None:
        """A freshly created disabled runtime must have publish_count == 0."""
        rt = _make_runtime(enabled=False)
        assert rt.cmd_vel_debug()["publish_count"] == 0

    def test_disabled_runtime_last_age_ms_none(self) -> None:
        """Before any publish, last_age_ms must be None."""
        rt = _make_runtime(enabled=False)
        assert rt.cmd_vel_debug()["last_age_ms"] is None

    def test_disabled_runtime_subscription_count_zero(self) -> None:
        """Disabled runtime must report subscription_count == 0."""
        rt = _make_runtime(enabled=False)
        assert rt.cmd_vel_debug()["subscription_count"] == 0


# ---------------------------------------------------------------------------
# Helpers for enabled-runtime property tests (Tasks 6.2, 6.3, 6.4)
# ---------------------------------------------------------------------------

from hypothesis import given, settings
import hypothesis.strategies as st


def _make_enabled_runtime() -> tuple["Ros2BridgeRuntime", list]:
    """Return an enabled Ros2BridgeRuntime with a capturing mock publisher.

    The second element is a list that accumulates every Twist message passed
    to publish(), so tests can inspect field values.
    """
    cfg = BridgeConfig(cmd_vel_topic="/cmd_vel")
    published: list = []

    mock_node = MagicMock()
    mock_pub = MagicMock()
    mock_pub.get_subscription_count.return_value = 0

    def _capture_publish(msg):
        published.append(msg)

    mock_pub.publish.side_effect = _capture_publish
    mock_node.create_publisher.return_value = mock_pub
    _rclpy_mock.ok.return_value = True
    _rclpy_mock.create_node = MagicMock(return_value=mock_node)

    rt = Ros2BridgeRuntime(cfg)
    rt._cmd_pub = mock_pub
    assert rt.enabled, "Expected runtime to be enabled"
    return rt, published


# ---------------------------------------------------------------------------
# Task 6.2 — Property 6: Twist message field mapping correctness
# Requirements: 5.1
# ---------------------------------------------------------------------------

# Feature: joystick-sim-integration-test, Property 6: Twist message field mapping correctness
@given(st.floats(allow_nan=False), st.floats(allow_nan=False))
@settings(max_examples=200)
def test_twist_field_mapping(linear: float, angular: float) -> None:
    """Validates: Requirements 5.1

    For any (linear, angular) pair, the published Twist must have
    msg.linear.x == linear, msg.angular.z == angular, and all other
    velocity fields == 0.0.
    """
    rt, published = _make_enabled_runtime()
    ok, _ = rt.move(linear, angular)
    assert ok, "move() should succeed on enabled runtime"
    assert len(published) == 1
    msg = published[0]
    assert msg.linear.x == float(linear)
    assert msg.angular.z == float(angular)
    assert msg.linear.y == 0.0
    assert msg.linear.z == 0.0
    assert msg.angular.x == 0.0
    assert msg.angular.y == 0.0


# ---------------------------------------------------------------------------
# Task 6.3 — Property 7: publish_count monotonically increases
# Requirements: 8.1
# ---------------------------------------------------------------------------

# Feature: joystick-sim-integration-test, Property 7: publish_count monotonically increases
@given(st.integers(min_value=1, max_value=50))
@settings(max_examples=200)
def test_publish_count_monotonic(n: int) -> None:
    """Validates: Requirements 8.1

    After N successful move() calls, publish_count must equal N.
    """
    rt, _ = _make_enabled_runtime()
    for i in range(n):
        ok, _ = rt.move(0.1, 0.0)
        assert ok, f"move() call {i} should succeed"
    assert rt.cmd_vel_debug()["publish_count"] == n


# ---------------------------------------------------------------------------
# Task 6.4 — Property 8: last_linear/last_angular reflect most recent values
# Requirements: 8.2
# ---------------------------------------------------------------------------

# Feature: joystick-sim-integration-test, Property 8: last_linear/last_angular reflect most recent published values
@given(st.floats(allow_nan=False), st.floats(allow_nan=False))
@settings(max_examples=200)
def test_last_linear_angular_reflect_recent(linear: float, angular: float) -> None:
    """Validates: Requirements 8.2

    After move(linear, angular), cmd_vel_debug() must report
    last_linear == linear and last_angular == angular.
    """
    rt, _ = _make_enabled_runtime()
    ok, _ = rt.move(linear, angular)
    assert ok, "move() should succeed on enabled runtime"
    debug = rt.cmd_vel_debug()
    assert debug["last_linear"] == float(linear)
    assert debug["last_angular"] == float(angular)
