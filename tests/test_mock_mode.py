"""
Tests for gateway_lite mock mode (MockRosBridgeClient).

Task 7.1 — Validates: Requirements 4.4, 8.5
Task 7.2 — Validates: Requirements 4.4
"""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from gateway_lite.config import GatewayConfig, RosBridgeConfig
from gateway_lite.ros_client import MockRosBridgeClient
from gateway_lite.server import GatewayServer


# ---------------------------------------------------------------------------
# Task 7.1 — MockRosBridgeClient behaviour
# ---------------------------------------------------------------------------

def test_mock_move_returns_true_ok():
    """MockRosBridgeClient.move() must return (True, 'ok')."""
    client = MockRosBridgeClient()
    result = asyncio.get_event_loop().run_until_complete(client.move(0.3, 0.5))
    assert result == (True, "ok")


def test_mock_stop_returns_true_ok():
    """MockRosBridgeClient.stop() must return (True, 'ok')."""
    client = MockRosBridgeClient()
    result = asyncio.get_event_loop().run_until_complete(client.stop())
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
        asyncio.get_event_loop().run_until_complete(client.move(0.1, 0.2))
        mock_post.assert_not_called()


def test_mock_mode_stop_does_not_call_httpx_post():
    """In mock mode, calling stop() must NOT trigger httpx.AsyncClient.post."""
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        client = MockRosBridgeClient()
        asyncio.get_event_loop().run_until_complete(client.stop())
        mock_post.assert_not_called()
