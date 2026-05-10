"""
Shared pytest fixtures for joystick-sim-integration-test suite.
"""
import pytest

from gateway_lite.safety import SafetyGuard
from gateway_lite.state import ControlRouter


@pytest.fixture
def default_safety_guard() -> SafetyGuard:
    """SafetyGuard with default config values (max_linear=0.6, max_angular=1.2)."""
    return SafetyGuard(
        max_linear=0.6,
        max_angular=1.2,
        voice_max_duration_ms=1000,
    )


@pytest.fixture
def default_router(default_safety_guard: SafetyGuard) -> ControlRouter:
    """ControlRouter with default config values."""
    return ControlRouter(
        safety=default_safety_guard,
        deadman_timeout_ms=250,
        joystick_min_interval_ms=50,  # 1000 ms / joystick_max_hz(20)
    )
