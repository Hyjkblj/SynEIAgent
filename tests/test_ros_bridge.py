"""
Tests for ros_bridge_lite — /health response structure.
Feature: joystick-sim-integration-test
Requirements: 1.3, 1.5, 5.3, 7.3, 8.1, 8.2

Run in ROS Bridge environment:
  C:\\pixi_ws\\.pixi\\envs\\default\\python.exe -m pytest tests/test_ros_bridge.py -v
"""
from __future__ import annotations

import asyncio
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

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

sys.modules["rclpy"] = _rclpy_mock
sys.modules["geometry_msgs"] = _geo_mod
sys.modules["geometry_msgs.msg"] = _geo_msg_mod

# Also mock hric_msgs so the optional import doesn't fail in unexpected ways
_hric_mod = types.ModuleType("hric_msgs")
_hric_srv_mod = types.ModuleType("hric_msgs.srv")
_hric_mod.srv = _hric_srv_mod
sys.modules["hric_msgs"] = _hric_mod
sys.modules["hric_msgs.srv"] = _hric_srv_mod

# Now it's safe to import
from ros_bridge_lite.main import BridgeConfig, IsaacSimFeedbackAdapter, Ros2BridgeRuntime  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _install_ros_bridge_mocks() -> None:
    """Re-install this module's ROS mocks after other tests mutate sys.modules."""
    sys.modules["rclpy"] = _rclpy_mock
    sys.modules["geometry_msgs"] = _geo_mod
    sys.modules["geometry_msgs.msg"] = _geo_msg_mod
    sys.modules["hric_msgs"] = _hric_mod
    sys.modules["hric_msgs.srv"] = _hric_srv_mod


def _make_runtime(
    enabled: bool = False,
    *,
    control_mode: str = "cmd_vel",
    isaac_sim_url: str = "",
) -> Ros2BridgeRuntime:
    """Return a Ros2BridgeRuntime.

    When enabled=False we want ROS2 initialisation to fail gracefully so the
    runtime stays in disabled mode — achieved by making rclpy.ok() raise.
    When enabled=True we let the mock succeed normally.
    """
    _install_ros_bridge_mocks()
    cfg = BridgeConfig(
        cmd_vel_topic="/cmd_vel",
        control_mode=control_mode,
        isaac_sim_url=isaac_sim_url,
    )

    if not enabled:
        # Force __init__ to land in the except branch → self.enabled = False
        with patch.object(_rclpy_mock, "ok", side_effect=RuntimeError("ros_disabled_for_test")):
            rt = Ros2BridgeRuntime(cfg)
        expect_http_fallback = control_mode == "rl_policy" and bool(isaac_sim_url)
        assert rt.enabled is expect_http_fallback
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


def test_isaac_http_adapter_disables_env_routing() -> None:
    """Isaac HTTP feedback adapter must bypass ambient env/proxy routing."""

    created_kwargs = {}

    class _DummyClient:
        def __init__(self, *args, **kwargs) -> None:
            created_kwargs.update(kwargs)

        async def aclose(self) -> None:
            return None

    with patch("httpx.AsyncClient", _DummyClient):
        adapter = IsaacSimFeedbackAdapter("http://127.0.0.1:9200")

    assert created_kwargs["trust_env"] is False
    asyncio.run(adapter.close())


def test_isaac_http_adapter_normalizes_localhost_to_ipv4_loopback() -> None:
    class _DummyClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        async def aclose(self) -> None:
            return None

    with patch("httpx.AsyncClient", _DummyClient):
        adapter = IsaacSimFeedbackAdapter("http://localhost:9200")

    assert adapter._url == "http://127.0.0.1:9200"
    asyncio.run(adapter.close())


def test_isaac_http_adapter_prefers_policy_euler_when_present() -> None:
    class _Response:
        def __init__(self, payload) -> None:
            self.status_code = 200
            self._payload = payload

        def json(self):
            return self._payload

    class _Client:
        async def get(self, url):
            if url.endswith("/feedback"):
                return _Response({
                    "joint_states": {
                        "name": [],
                        "position": [],
                        "velocity": [],
                        "effort": [],
                    },
                    "imu": {
                        "euler": {"yaw": 1.0, "pitch": 2.0, "roll": 3.0},
                        "policy_euler": {"yaw": 0.1, "pitch": 0.2, "roll": 0.3},
                        "angular_velocity": [0.0, 0.0, 0.0],
                        "linear_acceleration": [0.0, 0.0, 9.81],
                    },
                })
            raise AssertionError(f"unexpected url: {url}")

        async def aclose(self) -> None:
            return None

    adapter = IsaacSimFeedbackAdapter("http://127.0.0.1:9200")
    adapter._client = _Client()
    captured = {}

    class _Controller:
        def set_joint_feedback(self, positions, velocities, efforts):
            captured["joint_feedback"] = (positions, velocities, efforts)

        def set_imu_feedback(self, yaw, pitch, roll, omega, accel):
            captured["imu_feedback"] = {
                "yaw": yaw,
                "pitch": pitch,
                "roll": roll,
                "omega": omega,
                "accel": accel,
            }

    ok = asyncio.run(adapter.fetch_and_inject(_Controller()))
    asyncio.run(adapter.close())

    assert ok is True
    assert captured["imu_feedback"]["yaw"] == pytest.approx(0.1)
    assert captured["imu_feedback"]["pitch"] == pytest.approx(0.2)
    assert captured["imu_feedback"]["roll"] == pytest.approx(0.3)


def test_isaac_http_adapter_accepts_official_lite_elbow_joint_names() -> None:
    class _Response:
        def __init__(self, payload) -> None:
            self.status_code = 200
            self._payload = payload

        def json(self):
            return self._payload

    class _Client:
        async def get(self, url):
            if url.endswith("/feedback"):
                return _Response({
                    "joint_states": {
                        "name": ["elbow_pitch_l_joint", "elbow_pitch_r_joint"],
                        "position": [0.25, -0.35],
                        "velocity": [0.01, -0.02],
                        "effort": [0.0, 0.0],
                    },
                    "imu": {
                        "euler": {"yaw": 0.0, "pitch": 0.0, "roll": 0.0},
                        "angular_velocity": [0.0, 0.0, 0.0],
                        "linear_acceleration": [0.0, 0.0, 9.81],
                    },
                })
            raise AssertionError(f"unexpected url: {url}")

        async def aclose(self) -> None:
            return None

    adapter = IsaacSimFeedbackAdapter("http://127.0.0.1:9200")
    adapter._client = _Client()
    captured = {}

    class _Controller:
        def set_joint_feedback(self, positions, velocities, efforts):
            captured["positions"] = list(positions)
            captured["velocities"] = list(velocities)
            captured["efforts"] = list(efforts)

        def set_imu_feedback(self, yaw, pitch, roll, omega, accel):
            return None

    ok = asyncio.run(adapter.fetch_and_inject(_Controller()))
    asyncio.run(adapter.close())

    assert ok is True
    assert captured["positions"][15] == pytest.approx(0.25)
    assert captured["positions"][19] == pytest.approx(-0.35)
    assert captured["velocities"][15] == pytest.approx(0.01)
    assert captured["velocities"][19] == pytest.approx(-0.02)


def test_isaac_http_adapter_falls_back_when_combined_feedback_is_unavailable() -> None:
    class _Response:
        def __init__(self, status_code, payload) -> None:
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    urls = []

    class _Client:
        async def get(self, url):
            urls.append(url)
            if url.endswith("/feedback"):
                return _Response(404, {"error": "not found"})
            if url.endswith("/joint_states"):
                return _Response(200, {
                    "name": ["hip_pitch_l_joint"],
                    "position": [-0.4],
                    "velocity": [0.2],
                    "effort": [0.0],
                })
            if url.endswith("/imu"):
                return _Response(200, {
                    "policy_euler": {"yaw": 0.4, "pitch": 0.5, "roll": 0.6},
                    "angular_velocity": [0.1, 0.2, 0.3],
                    "linear_acceleration": [0.0, 0.0, 9.81],
                })
            raise AssertionError(f"unexpected url: {url}")

        async def aclose(self) -> None:
            return None

    adapter = IsaacSimFeedbackAdapter("http://127.0.0.1:9200")
    adapter._client = _Client()
    captured = {}

    class _Controller:
        def set_joint_feedback(self, positions, velocities, efforts):
            captured["positions"] = list(positions)
            captured["velocities"] = list(velocities)

        def set_imu_feedback(self, yaw, pitch, roll, omega, accel):
            captured["imu"] = (yaw, pitch, roll, omega, accel)

    ok = asyncio.run(adapter.fetch_and_inject(_Controller()))
    asyncio.run(adapter.close())

    assert ok is True
    assert any(url.endswith("/feedback") for url in urls)
    assert any(url.endswith("/joint_states") for url in urls)
    assert any(url.endswith("/imu") for url in urls)
    assert captured["positions"][1] == pytest.approx(-0.4)
    assert captured["velocities"][1] == pytest.approx(0.2)
    assert captured["imu"][0] == pytest.approx(0.4)
    assert adapter._supports_combined_feedback is False


def test_isaac_http_adapter_sends_official_lite_elbow_joint_names() -> None:
    captured = {}

    class _Response:
        status_code = 200

    class _Client:
        async def post(self, url, json):
            captured["url"] = url
            captured["json"] = json
            return _Response()

        async def aclose(self) -> None:
            return None

    adapter = IsaacSimFeedbackAdapter("http://127.0.0.1:9200")
    adapter._client = _Client()

    ok = asyncio.run(adapter.send_joint_command({
        "l_elbow": 0.4,
        "r_elbow": -0.6,
    }))
    asyncio.run(adapter.close())

    assert ok is True
    assert captured["url"].endswith("/joint_command")
    assert captured["json"]["name"] == ["elbow_pitch_l_joint", "elbow_pitch_r_joint"]
    assert captured["json"]["position"] == pytest.approx([0.4, -0.6])


def test_isaac_http_adapter_control_frame_round_trip_updates_feedback() -> None:
    captured = {}

    class _Response:
        status_code = 200

        def json(self):
            return {
                "joint_states": {
                    "name": ["elbow_pitch_l_joint", "elbow_pitch_r_joint"],
                    "position": [0.25, -0.35],
                    "velocity": [0.01, -0.02],
                    "effort": [0.0, 0.0],
                },
                "imu": {
                    "policy_euler": {"yaw": 0.4, "pitch": 0.5, "roll": 0.6},
                    "angular_velocity": [0.1, 0.2, 0.3],
                    "linear_acceleration": [0.0, 0.0, 9.81],
                },
            }

    class _Client:
        async def post(self, url, json):
            captured["url"] = url
            captured["json"] = json
            return _Response()

        async def aclose(self) -> None:
            return None

    adapter = IsaacSimFeedbackAdapter("http://127.0.0.1:9200")
    adapter._client = _Client()
    observed = {}

    class _Controller:
        def set_joint_feedback(self, positions, velocities, efforts):
            observed["positions"] = list(positions)
            observed["velocities"] = list(velocities)
            observed["efforts"] = list(efforts)

        def set_imu_feedback(self, yaw, pitch, roll, omega, accel):
            observed["imu"] = (yaw, pitch, roll, omega, accel)

    ok = asyncio.run(adapter.send_control_frame_and_fetch_feedback(
        {"l_elbow": 0.4, "r_elbow": -0.6},
        _Controller(),
    ))
    asyncio.run(adapter.close())

    assert ok is True
    assert captured["url"].endswith("/control_frame")
    assert captured["json"]["name"] == ["elbow_pitch_l_joint", "elbow_pitch_r_joint"]
    assert captured["json"]["position"] == pytest.approx([0.4, -0.6])
    assert observed["positions"][15] == pytest.approx(0.25)
    assert observed["positions"][19] == pytest.approx(-0.35)
    assert observed["imu"][0] == pytest.approx(0.4)
    assert adapter._supports_control_frame is True
    assert adapter.uses_separate_command_channel() is False


def test_isaac_http_adapter_control_frame_404_falls_back_to_separate_channel() -> None:
    class _Response:
        status_code = 404

        def json(self):
            return {"error": "not found"}

    class _Client:
        async def post(self, url, json):
            return _Response()

        async def aclose(self) -> None:
            return None

    adapter = IsaacSimFeedbackAdapter("http://127.0.0.1:9200")
    adapter._client = _Client()

    result = asyncio.run(adapter.send_control_frame_and_fetch_feedback(
        {"l_hip_roll": 0.1},
        types.SimpleNamespace(
            set_joint_feedback=lambda *args, **kwargs: None,
            set_imu_feedback=lambda *args, **kwargs: None,
        ),
    ))
    asyncio.run(adapter.close())

    assert result is None
    assert adapter._supports_control_frame is False
    assert adapter.uses_separate_command_channel() is True


def test_rl_policy_http_mode_stays_enabled_without_ros2() -> None:
    rt = _make_runtime(
        enabled=False,
        control_mode="rl_policy",
        isaac_sim_url="http://127.0.0.1:9200",
    )

    assert rt.enabled is True
    assert rt.error == ""


def test_rl_policy_http_mode_bypasses_ros2_even_when_rclpy_is_available() -> None:
    rt = _make_runtime(
        enabled=True,
        control_mode="rl_policy",
        isaac_sim_url="http://127.0.0.1:9200",
    )

    assert rt.enabled is True
    assert rt._node is None
    assert rt._rclpy is None
    assert rt.uses_http_feedback() is True


def test_rl_policy_http_mode_uses_http_feedback_transport() -> None:
    rt = _make_runtime(
        enabled=False,
        control_mode="rl_policy",
        isaac_sim_url="http://127.0.0.1:9200",
    )

    assert rt.uses_http_feedback() is True


def test_rl_policy_http_mode_exposes_transport_debug() -> None:
    rt = _make_runtime(
        enabled=False,
        control_mode="rl_policy",
        isaac_sim_url="http://127.0.0.1:9200",
    )

    debug = rt.joint_command_debug()
    assert "http_transport_debug" in debug
    assert debug["http_transport_debug"]["feedback_attempt_count"] == 0
    assert debug["http_transport_debug"]["command_attempt_count"] == 0


def test_rl_policy_http_mode_exposes_rl_debug_snapshot() -> None:
    rt = _make_runtime(
        enabled=False,
        control_mode="rl_policy",
        isaac_sim_url="http://127.0.0.1:9200",
    )
    rt._rl_controller = types.SimpleNamespace(
        debug_snapshot=lambda: {
            "fsm_state": "MLP",
            "fsm_debug": {"state": "MLP", "inference_count": 3},
        }
    )

    snapshot = rt.rl_debug_snapshot()

    assert snapshot is not None
    assert snapshot["uses_http_feedback"] is True
    assert snapshot["http_feedback_ready"] is False
    assert snapshot["controller_debug"]["fsm_debug"]["inference_count"] == 3


def test_rl_policy_http_mode_caps_control_loop_period_to_transport_budget() -> None:
    rt = _make_runtime(
        enabled=False,
        control_mode="rl_policy",
        isaac_sim_url="http://127.0.0.1:9200",
    )
    rt.cfg.control_hz = 400.0

    assert rt._control_loop_period_s() == pytest.approx(0.01)


def test_rl_policy_http_mode_caps_transport_loop_period_to_transport_budget() -> None:
    rt = _make_runtime(
        enabled=False,
        control_mode="rl_policy",
        isaac_sim_url="http://127.0.0.1:9200",
    )
    rt.cfg.control_hz = 400.0

    assert rt._http_transport_period_s() == pytest.approx(0.01)


def test_rl_policy_http_mode_start_spawns_feedback_and_command_tasks() -> None:
    rt = _make_runtime(
        enabled=False,
        control_mode="rl_policy",
        isaac_sim_url="http://127.0.0.1:9200",
    )

    async def _runner() -> tuple[bool, bool, bool]:
        await rt.start()
        control_ok = rt._control_task is not None and not rt._control_task.done()
        feedback_ok = rt._feedback_task is not None and not rt._feedback_task.done()
        command_ok = rt._http_command_task is not None and not rt._http_command_task.done()
        await rt.shutdown()
        return control_ok, feedback_ok, command_ok

    control_ok, feedback_ok, command_ok = asyncio.run(_runner())

    assert control_ok is True
    assert feedback_ok is True
    assert command_ok is True


def test_rl_policy_http_feedback_loop_prefers_control_frame_and_updates_both_debug_paths() -> None:
    rt = _make_runtime(
        enabled=False,
        control_mode="rl_policy",
        isaac_sim_url="http://127.0.0.1:9200",
    )
    rt._rl_controller = object()
    rt._http_latest_targets = {"l_hip_roll": 0.12}
    combined_called = asyncio.Event()
    combined_mock = AsyncMock()
    fetch_mock = AsyncMock()

    async def _combined(targets, controller):
        combined_called.set()
        return True

    combined_mock.side_effect = _combined
    rt._isaac_feedback = types.SimpleNamespace(
        send_control_frame_and_fetch_feedback=combined_mock,
        fetch_and_inject=fetch_mock,
        uses_separate_command_channel=lambda: False,
    )

    async def _runner() -> None:
        task = asyncio.create_task(rt._http_feedback_loop())
        await asyncio.wait_for(combined_called.wait(), timeout=0.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(_runner())

    combined_mock.assert_awaited_once()
    fetch_mock.assert_not_awaited()
    assert rt._http_feedback_attempt_count == 1
    assert rt._http_feedback_success_count == 1
    assert rt._http_command_attempt_count == 1
    assert rt._http_command_success_count == 1
    assert rt._http_last_command_ok is True


def test_rl_policy_http_feedback_loop_falls_back_when_control_frame_is_unavailable() -> None:
    rt = _make_runtime(
        enabled=False,
        control_mode="rl_policy",
        isaac_sim_url="http://127.0.0.1:9200",
    )
    rt._rl_controller = object()
    rt._http_latest_targets = {"l_hip_roll": 0.12}
    fetch_called = asyncio.Event()
    combined_mock = AsyncMock(return_value=None)
    fetch_mock = AsyncMock()

    async def _fetch(controller):
        fetch_called.set()
        return True

    fetch_mock.side_effect = _fetch
    rt._isaac_feedback = types.SimpleNamespace(
        send_control_frame_and_fetch_feedback=combined_mock,
        fetch_and_inject=fetch_mock,
        uses_separate_command_channel=lambda: True,
    )

    async def _runner() -> None:
        task = asyncio.create_task(rt._http_feedback_loop())
        await asyncio.wait_for(fetch_called.wait(), timeout=0.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(_runner())

    combined_mock.assert_awaited_once()
    fetch_mock.assert_awaited_once()
    assert rt._http_feedback_attempt_count == 1
    assert rt._http_feedback_success_count == 1
    assert rt._http_command_attempt_count == 0
    assert rt._http_command_success_count == 0


def test_rl_policy_http_command_loop_skips_separate_sender_after_control_frame_support_is_confirmed() -> None:
    rt = _make_runtime(
        enabled=False,
        control_mode="rl_policy",
        isaac_sim_url="http://127.0.0.1:9200",
    )
    send_mock = AsyncMock(return_value=True)
    rt._isaac_feedback = types.SimpleNamespace(
        send_joint_command=send_mock,
        uses_separate_command_channel=lambda: False,
    )
    rt._http_latest_targets = {"l_hip_roll": 0.12}

    async def _runner() -> None:
        task = asyncio.create_task(rt._http_command_loop())
        await asyncio.sleep(0.03)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(_runner())

    send_mock.assert_not_awaited()
    assert rt._http_command_attempt_count == 0


def test_rl_policy_http_command_loop_keeps_separate_sender_until_control_frame_is_confirmed() -> None:
    rt = _make_runtime(
        enabled=False,
        control_mode="rl_policy",
        isaac_sim_url="http://127.0.0.1:9200",
    )
    send_called = asyncio.Event()
    send_mock = AsyncMock()

    async def _send(targets):
        send_called.set()
        return True

    send_mock.side_effect = _send
    rt._isaac_feedback = types.SimpleNamespace(
        send_joint_command=send_mock,
        uses_separate_command_channel=lambda: True,
    )
    rt._http_latest_targets = {"l_hip_roll": 0.12}

    async def _runner() -> None:
        task = asyncio.create_task(rt._http_command_loop())
        await asyncio.wait_for(send_called.wait(), timeout=0.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(_runner())

    send_mock.assert_awaited_once_with({"l_hip_roll": 0.12})
    assert rt._http_command_attempt_count == 1
    assert rt._http_command_success_count == 1
    assert rt._http_last_command_ok is True


def test_rl_policy_http_publish_queues_targets_when_background_sender_is_running() -> None:
    rt = _make_runtime(
        enabled=False,
        control_mode="rl_policy",
        isaac_sim_url="http://127.0.0.1:9200",
    )
    rt._rl_controller = types.SimpleNamespace(
        update=lambda dt: {"l_hip_roll": 0.12, "r_hip_roll": -0.12},
        joint_names=("l_hip_roll", "r_hip_roll"),
    )
    send_mock = AsyncMock(return_value=True)
    rt._isaac_feedback = types.SimpleNamespace(send_joint_command=send_mock)
    rt._http_command_task = types.SimpleNamespace(done=lambda: False)
    rt._http_feedback_success_count = 1
    rt._http_feedback_last_success_time = __import__("time").time()

    asyncio.run(rt._publish_rl_policy_targets(0.02))

    assert rt._http_latest_targets == {"l_hip_roll": 0.12, "r_hip_roll": -0.12}
    send_mock.assert_not_awaited()


def test_rl_policy_http_publish_holds_nominal_pose_until_feedback_is_ready() -> None:
    rt = _make_runtime(
        enabled=False,
        control_mode="rl_policy",
        isaac_sim_url="http://127.0.0.1:9200",
    )
    force_stop = MagicMock()
    stand_pose = {"l_hip_roll": 0.0, "r_hip_roll": 0.0}
    rt._rl_controller = types.SimpleNamespace(
        force_stop_hold=force_stop,
        stand_pose=lambda: stand_pose,
        update=lambda dt: {"l_hip_roll": 0.12, "r_hip_roll": -0.12},
        joint_names=("l_hip_roll", "r_hip_roll"),
    )
    send_mock = AsyncMock(return_value=True)
    rt._isaac_feedback = types.SimpleNamespace(send_joint_command=send_mock)
    rt._http_feedback_success_count = 0

    asyncio.run(rt._publish_rl_policy_targets(0.02))

    force_stop.assert_called_once()
    send_mock.assert_awaited_once_with(stand_pose)
    assert rt._http_latest_targets == stand_pose


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

    def test_rl_policy_joint_debug_reports_fsm_state(self) -> None:
        """RL mode joint debug should surface the live FSM state, not legacy STANDING."""
        rt = _make_runtime(enabled=False)
        rt.cfg.control_mode = "rl_policy"

        fake_state = types.SimpleNamespace(name="MLP")
        fake_fsm = types.SimpleNamespace(current_state=fake_state)
        rt._rl_controller = types.SimpleNamespace(_robot_fsm=fake_fsm)

        debug = rt.joint_command_debug()
        assert debug["state"] == "MLP"
        assert isinstance(debug["state_age_ms"], int)


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
    _install_ros_bridge_mocks()
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
