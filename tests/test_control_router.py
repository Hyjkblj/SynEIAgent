"""
Tests for ControlRouter example-based and property-based behavior.
Feature: joystick-sim-integration-test
"""
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from gateway_lite.protocol import CommandKind
from gateway_lite.safety import SafetyGuard
from gateway_lite.state import ControlRouter, ControlState


def make_router(
    deadman_timeout_ms: int = 250,
    joystick_min_interval_ms: int = 50,
) -> ControlRouter:
    guard = SafetyGuard(max_linear=0.6, max_angular=1.2, voice_max_duration_ms=1000)
    return ControlRouter(
        safety=guard,
        deadman_timeout_ms=deadman_timeout_ms,
        joystick_min_interval_ms=joystick_min_interval_ms,
    )


def joystick_msg(x: float = 0.5, y: float = 0.5, seq: int = 1, ts: int = 1000) -> dict:
    return {"type": "joystick", "x": x, "y": y, "seq": seq, "ts": ts}


def test_nonzero_joystick_produces_move_command() -> None:
    """Non-zero joystick input must produce a CommandKind.MOVE command."""
    router = make_router()
    out = router.handle(joystick_msg(x=0.5, y=0.5, seq=1), now_ms=1000)
    kinds = [cmd.kind for cmd in out.commands]
    assert CommandKind.MOVE in kinds


def test_zero_joystick_produces_stop_command() -> None:
    """Zero joystick input must produce a CommandKind.STOP command."""
    router = make_router()
    out = router.handle(joystick_msg(x=0.0, y=0.0, seq=1), now_ms=1000)
    kinds = [cmd.kind for cmd in out.commands]
    assert CommandKind.STOP in kinds


def test_old_seq_returns_drop_old_seq_ack() -> None:
    """A message with a seq <= latest_seq must be ACKed with reason 'drop_old_seq'."""
    router = make_router()
    router.handle(joystick_msg(seq=5), now_ms=1000)
    out = router.handle(joystick_msg(seq=5), now_ms=1100)
    reasons = [ack["reason"] for ack in out.acks]
    assert "drop_old_seq" in reasons


def test_old_seq_strictly_less_returns_drop_old_seq_ack() -> None:
    """A message with seq strictly less than latest_seq must also be dropped."""
    router = make_router()
    router.handle(joystick_msg(seq=10), now_ms=1000)
    out = router.handle(joystick_msg(seq=3), now_ms=1100)
    reasons = [ack["reason"] for ack in out.acks]
    assert "drop_old_seq" in reasons


def test_rate_limited_ack_when_interval_too_short() -> None:
    """Second joystick message within joystick_min_interval_ms must get 'rate_limited' ACK."""
    router = make_router(joystick_min_interval_ms=50)
    router.handle(joystick_msg(seq=1), now_ms=1000)
    out = router.handle(joystick_msg(seq=2), now_ms=1010)
    reasons = [ack["reason"] for ack in out.acks]
    assert "rate_limited" in reasons


def test_text_walk_produces_zero_then_mlp_fsm_commands() -> None:
    """Text walk intent must emit gotoZero immediately and defer gotoMLP."""
    router = make_router()

    out = router.handle({"type": "text", "content": "walk now", "seq": 1}, now_ms=1000)

    assert [cmd.kind for cmd in out.commands] == [CommandKind.FSM_CMD]
    assert [cmd.fsm_cmd for cmd in out.commands] == ["gotoZero"]
    assert out.acks[0]["reason"] == "accepted"

    out = router.tick(now_ms=3199)
    assert out.commands == []

    out = router.tick(now_ms=3200)
    assert [cmd.kind for cmd in out.commands] == [CommandKind.FSM_CMD]
    assert [cmd.fsm_cmd for cmd in out.commands] == ["gotoMLP"]


def test_explicit_fsm_cmd_intent_produces_single_fsm_command() -> None:
    """Explicit fsm_cmd intent should pass through canonical goto commands."""
    router = make_router()

    out = router.handle(
        {"type": "voice_intent", "intent": "fsm_cmd", "fsm_cmd": "gotoStop", "seq": 1},
        now_ms=1000,
    )

    assert len(out.commands) == 1
    assert out.commands[0].kind == CommandKind.FSM_CMD
    assert out.commands[0].fsm_cmd == "gotoStop"
    assert out.acks[0]["reason"] == "accepted"


@given(st.integers(min_value=1, max_value=500))
@settings(max_examples=200)
def test_deadman_timeout_triggers_stop(offset: int) -> None:
    """Ticking past deadman must produce a STOP command and return to IDLE."""
    deadman = 250
    router = make_router(deadman_timeout_ms=deadman)

    t0 = 10_000
    router.handle(joystick_msg(x=0.5, y=0.5, seq=1), now_ms=t0)
    assert router.state == ControlState.JOYSTICK_ACTIVE

    last_nonzero = router.last_nonzero_joystick_ms
    tick_time = last_nonzero + deadman + offset
    out = router.tick(now_ms=tick_time)

    kinds = [cmd.kind for cmd in out.commands]
    assert CommandKind.STOP in kinds
    assert router.state == ControlState.IDLE


@given(st.integers(min_value=0, max_value=49))
@settings(max_examples=200)
def test_rate_limiting_drops_second_message(interval: int) -> None:
    """Intervals under joystick_min_interval_ms must be dropped with rate_limited ACK."""
    min_interval = 50
    router = make_router(joystick_min_interval_ms=min_interval)

    t0 = 10_000
    router.handle(joystick_msg(x=0.5, y=0.5, seq=1), now_ms=t0)

    t1 = t0 + interval
    out = router.handle(joystick_msg(x=0.5, y=0.5, seq=2), now_ms=t1)

    reasons = [ack["reason"] for ack in out.acks]
    assert "rate_limited" in reasons
