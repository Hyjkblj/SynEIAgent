"""
Tests for SafetyGuard — example-based and property-based.
Feature: joystick-sim-integration-test
"""
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from gateway_lite.safety import SafetyGuard


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def default_safety_guard() -> SafetyGuard:
    """SafetyGuard with default config values (max_linear=0.6, max_angular=1.2)."""
    return SafetyGuard(
        max_linear=0.6,
        max_angular=1.2,
        voice_max_duration_ms=1000,
    )


# ---------------------------------------------------------------------------
# Task 2.1 — Example-based tests
# Requirements: 3.1, 3.2, 3.5
# ---------------------------------------------------------------------------

def test_clamp_linear_zero(default_safety_guard: SafetyGuard) -> None:
    """clamp_linear(0.0) must return 0.0."""
    assert default_safety_guard.clamp_linear(0.0) == 0.0


def test_clamp_linear_overflow(default_safety_guard: SafetyGuard) -> None:
    """clamp_linear(999.0) must be clamped to max_linear (0.6)."""
    assert default_safety_guard.clamp_linear(999.0) == default_safety_guard.max_linear


def test_joystick_zero_input(default_safety_guard: SafetyGuard) -> None:
    """joystick_to_velocity(0.0, 0.0) must return (0.0, 0.0)."""
    assert default_safety_guard.joystick_to_velocity(0.0, 0.0) == (0.0, 0.0)


# ---------------------------------------------------------------------------
# Task 2.2 — Property 1: SafetyGuard linear velocity clamping
# Validates: Requirements 3.1, 3.5
# ---------------------------------------------------------------------------

# Feature: joystick-sim-integration-test, Property 1: SafetyGuard 线速度限幅
@given(st.floats(allow_nan=False, allow_infinity=False))
@settings(max_examples=200)
def test_clamp_linear_bounds(v: float) -> None:
    """For any float, clamp_linear output must be within [-max_linear, max_linear]
    and the sign must be preserved (truncation, not rejection)."""
    guard = SafetyGuard(max_linear=0.6, max_angular=1.2, voice_max_duration_ms=1000)
    result = guard.clamp_linear(v)

    # Bound invariant
    assert abs(result) <= guard.max_linear

    # Sign preservation: if input is non-zero, sign of output matches sign of input
    if v > 0:
        assert result >= 0.0
    elif v < 0:
        assert result <= 0.0


# ---------------------------------------------------------------------------
# Task 2.3 — Property 2: SafetyGuard angular velocity clamping
# Validates: Requirements 3.2
# ---------------------------------------------------------------------------

# Feature: joystick-sim-integration-test, Property 2: SafetyGuard 角速度限幅
@given(st.floats(allow_nan=False, allow_infinity=False))
@settings(max_examples=200)
def test_clamp_angular_bounds(v: float) -> None:
    """For any float, clamp_angular output must be within [-max_angular, max_angular]."""
    guard = SafetyGuard(max_linear=0.6, max_angular=1.2, voice_max_duration_ms=1000)
    result = guard.clamp_angular(v)

    assert abs(result) <= guard.max_angular


# ---------------------------------------------------------------------------
# Task 2.4 — Property 3: Joystick-to-velocity invariant
# Validates: Requirements 3.1, 3.2
# ---------------------------------------------------------------------------

# Feature: joystick-sim-integration-test, Property 3: 摇杆到速度的映射不变量
@given(st.floats(-1, 1), st.floats(-1, 1))
@settings(max_examples=200)
def test_joystick_to_velocity_invariant(x: float, y: float) -> None:
    """For any normalised joystick input (x, y) in [-1, 1]^2,
    joystick_to_velocity must return |linear| <= max_linear and |angular| <= max_angular."""
    guard = SafetyGuard(max_linear=0.6, max_angular=1.2, voice_max_duration_ms=1000)
    linear, angular = guard.joystick_to_velocity(x, y)

    assert abs(linear) <= guard.max_linear
    assert abs(angular) <= guard.max_angular
