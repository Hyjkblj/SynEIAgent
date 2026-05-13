"""
Tests for gateway_lite mock mode (MockRosBridgeClient).

Task 7.1 — Validates: Requirements 4.4, 8.5
Task 7.2 — Validates: Requirements 4.4
"""
import asyncio
import types
from unittest.mock import AsyncMock, patch

import pytest

from gateway_lite.config import GatewayConfig, RosBridgeConfig
from gateway_lite.protocol import CommandKind, ControlCommand
from gateway_lite.ros_client import HttpRosBridgeClient, MockRosBridgeClient
from gateway_lite.server import GatewayServer


# ---------------------------------------------------------------------------
# Task 7.1 — MockRosBridgeClient behaviour
# ---------------------------------------------------------------------------

def test_mock_move_returns_true_ok():
    """MockRosBridgeClient.move() must return (True, 'ok')."""
    client = MockRosBridgeClient()
    result = asyncio.run(client.move(0.3, 0.5))
    assert result == (True, "ok")


def test_mock_stop_returns_true_ok():
    """MockRosBridgeClient.stop() must return (True, 'ok')."""
    client = MockRosBridgeClient()
    result = asyncio.run(client.stop())
    assert result == (True, "ok")


def test_mock_fsm_cmd_returns_true_ok():
    """MockRosBridgeClient.fsm_cmd() must return (True, 'ok')."""
    client = MockRosBridgeClient()
    result = asyncio.run(client.fsm_cmd("gotoMLP"))
    assert result == (True, "ok")


def test_build_ros_client_returns_mock_when_mode_is_mock():
    """GatewayServer._build_ros_client() returns MockRosBridgeClient when mode='mock'."""
    cfg = GatewayConfig(
        ros_bridge=RosBridgeConfig(mode="mock"),
        video_enabled=False,
    )
    server = GatewayServer(cfg)
    assert isinstance(server._ros, MockRosBridgeClient)


def test_build_ros_client_returns_http_when_mode_is_http():
    """GatewayServer._build_ros_client() returns HttpRosBridgeClient when mode='http'."""
    from gateway_lite.ros_client import HttpRosBridgeClient

    cfg = GatewayConfig(
        ros_bridge=RosBridgeConfig(mode="http"),
        video_enabled=False,
    )
    server = GatewayServer(cfg)
    assert isinstance(server._ros, HttpRosBridgeClient)


# ---------------------------------------------------------------------------
# Task 7.2 — Mock mode must NOT send real HTTP requests
# ---------------------------------------------------------------------------

def test_mock_mode_does_not_call_httpx_post():
    """In mock mode, calling move() must NOT trigger httpx.AsyncClient.post."""
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        client = MockRosBridgeClient()
        asyncio.run(client.move(0.1, 0.2))
        mock_post.assert_not_called()


def test_mock_mode_stop_does_not_call_httpx_post():
    """In mock mode, calling stop() must NOT trigger httpx.AsyncClient.post."""
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        client = MockRosBridgeClient()
        asyncio.run(client.stop())
        mock_post.assert_not_called()


def test_http_ros_client_disables_env_routing_for_loopback_calls():
    """HTTP mode must bypass ambient env/proxy routing for local bridge calls."""

    created_kwargs = {}

    class _Resp:
        status_code = 200

    class _DummyClient:
        def __init__(self, *args, **kwargs):
            created_kwargs.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json):
            return _Resp()

    with patch("gateway_lite.ros_client.httpx.AsyncClient", _DummyClient):
        client = HttpRosBridgeClient(base_url="http://127.0.0.1:8080", timeout_s=0.8)
        result = asyncio.run(client.move(0.1, 0.2))

    assert result == (True, "ok")
    assert created_kwargs["trust_env"] is False


def test_http_ros_client_fsm_cmd_posts_expected_payload():
    """HTTP mode must forward FSM commands to /fsm_cmd."""

    captured = {}

    class _Resp:
        status_code = 200

    class _DummyClient:
        def __init__(self, *args, **kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json):
            captured["url"] = url
            captured["json"] = json
            return _Resp()

    with patch("gateway_lite.ros_client.httpx.AsyncClient", _DummyClient):
        client = HttpRosBridgeClient(base_url="http://127.0.0.1:8080", timeout_s=0.8)
        result = asyncio.run(client.fsm_cmd("gotoZero"))

    assert result == (True, "ok")
    assert captured["url"] == "http://127.0.0.1:8080/fsm_cmd"
    assert captured["json"] == {"cmd": "gotoZero"}


def test_http_ros_client_returns_failure_when_bridge_rejects_request():
    """HTTP mode must surface bridge-side success=false payloads as failures."""

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"success": False, "detail": "not_in_tienkung_mode"}

    class _DummyClient:
        def __init__(self, *args, **kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json):
            return _Resp()

    with patch("gateway_lite.ros_client.httpx.AsyncClient", _DummyClient):
        client = HttpRosBridgeClient(base_url="http://127.0.0.1:8080", timeout_s=0.8)
        result = asyncio.run(client.fsm_cmd("gotoMLP"))

    assert result == (False, "not_in_tienkung_mode")


def test_gateway_server_executes_fsm_cmd_via_ros_client():
    """GatewayServer must route FSM_CMD commands to ros_client.fsm_cmd()."""
    cfg = GatewayConfig(
        ros_bridge=RosBridgeConfig(mode="mock"),
        video_enabled=False,
    )
    server = GatewayServer(cfg)
    fsm_cmd = AsyncMock(return_value=(True, "ok"))
    server._ros = types.SimpleNamespace(
        move=AsyncMock(return_value=(True, "ok")),
        stop=AsyncMock(return_value=(True, "ok")),
        motion=AsyncMock(return_value=(True, "ok")),
        fsm_cmd=fsm_cmd,
    )

    result = asyncio.run(
        server._execute_command(
            ControlCommand(kind=CommandKind.FSM_CMD, source="voice", fsm_cmd="gotoMLP")
        )
    )

    assert result == (True, "ok")
    fsm_cmd.assert_awaited_once_with("gotoMLP")
