from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .protocol import CommandKind, ControlCommand, RouterOutput, ack_payload, event_payload
from .safety import SafetyGuard


class ControlState(str, Enum):
    IDLE = "IDLE"
    JOYSTICK_ACTIVE = "JOYSTICK_ACTIVE"
    VOICE_ACTION = "VOICE_ACTION"
    EMERGENCY_STOP = "EMERGENCY_STOP"


ACTION_MAP: dict[str, int] = {
    "wave_hand": 1,
    "hand_shake": 2,
    "bow": 3,
    "dance_1": 4,
    "dance_2": 5,
}

WALK_ZERO_TO_MLP_DELAY_MS = 2200


@dataclass(slots=True)
class ControlRouter:
    safety: SafetyGuard
    deadman_timeout_ms: int
    joystick_min_interval_ms: int

    state: ControlState = ControlState.IDLE
    emergency_latched: bool = False
    latest_seq: int = -1
    last_nonzero_joystick_ms: int = 0
    last_joystick_accept_ms: int = 0
    voice_action_deadline_ms: int = 0
    pending_fsm_command: str = ""
    pending_fsm_due_ms: int = 0

    def handle(self, raw: dict[str, Any], now_ms: int | None = None) -> RouterOutput:
        now_ms = int(now_ms or time.time() * 1000)
        out = RouterOutput()

        msg_type = str(raw.get("type", "")).strip().lower()
        if msg_type == "joystick":
            self._handle_joystick(raw, now_ms, out)
            return out

        if msg_type in {"voice_intent", "action", "text"}:
            self._handle_voice(raw, now_ms, out)
            return out

        out.errors.append(f"unknown type: {msg_type or '<empty>'}")
        return out

    def tick(self, now_ms: int | None = None) -> RouterOutput:
        now_ms = int(now_ms or time.time() * 1000)
        out = RouterOutput()

        if self.state == ControlState.JOYSTICK_ACTIVE:
            elapsed = now_ms - self.last_nonzero_joystick_ms
            if elapsed >= self.deadman_timeout_ms:
                self._transition(ControlState.IDLE, out)
                out.commands.append(
                    ControlCommand(
                        kind=CommandKind.STOP,
                        source="watchdog",
                        reason="deadman_timeout",
                    )
                )

        if self.pending_fsm_command and self.pending_fsm_due_ms > 0 and now_ms >= self.pending_fsm_due_ms:
            out.commands.append(
                ControlCommand(
                    kind=CommandKind.FSM_CMD,
                    source="voice",
                    fsm_cmd=self.pending_fsm_command,
                )
            )
            self._clear_pending_fsm()
            if self.state == ControlState.VOICE_ACTION:
                self._transition(ControlState.IDLE, out)

        if self.state == ControlState.VOICE_ACTION and self.voice_action_deadline_ms > 0:
            if now_ms >= self.voice_action_deadline_ms:
                self.voice_action_deadline_ms = 0
                self._transition(ControlState.IDLE, out)
                out.commands.append(
                    ControlCommand(
                        kind=CommandKind.STOP,
                        source="voice",
                        reason="voice_duration_end",
                    )
                )

        return out

    def _handle_joystick(self, raw: dict[str, Any], now_ms: int, out: RouterOutput) -> None:
        seq = _to_int(raw.get("seq"))
        request_id = _to_str_or_none(raw.get("request_id"))
        ts = _to_int(raw.get("ts"))

        if seq is None:
            out.acks.append(
                ack_payload(seq=None, request_id=request_id, reason="missing_seq", source="joystick", ts=ts)
            )
            return

        if seq <= self.latest_seq:
            out.acks.append(
                ack_payload(seq=seq, request_id=request_id, reason="drop_old_seq", source="joystick", ts=ts)
            )
            return
        self.latest_seq = seq

        if self.emergency_latched:
            out.acks.append(
                ack_payload(seq=seq, request_id=request_id, reason="blocked_emergency", source="joystick", ts=ts)
            )
            return

        if self.last_joystick_accept_ms > 0:
            if (now_ms - self.last_joystick_accept_ms) < self.joystick_min_interval_ms:
                out.acks.append(
                    ack_payload(seq=seq, request_id=request_id, reason="rate_limited", source="joystick", ts=ts)
                )
                return

        x = float(raw.get("x", 0.0))
        y = float(raw.get("y", 0.0))
        linear, angular = self.safety.joystick_to_velocity(x=x, y=y)

        self.last_joystick_accept_ms = now_ms
        self._clear_pending_fsm()

        if abs(linear) <= 1e-4 and abs(angular) <= 1e-4:
            self.last_nonzero_joystick_ms = 0
            self.voice_action_deadline_ms = 0
            self._transition(ControlState.IDLE, out)
            out.commands.append(ControlCommand(kind=CommandKind.STOP, source="joystick", reason="zero_input"))
        else:
            self.last_nonzero_joystick_ms = now_ms
            self.voice_action_deadline_ms = 0
            self._transition(ControlState.JOYSTICK_ACTIVE, out)
            out.commands.append(
                ControlCommand(
                    kind=CommandKind.MOVE,
                    source="joystick",
                    linear=linear,
                    angular=angular,
                )
            )

        out.acks.append(
            ack_payload(seq=seq, request_id=request_id, reason="accepted", source="joystick", ts=ts)
        )

    def _handle_voice(self, raw: dict[str, Any], now_ms: int, out: RouterOutput) -> None:
        seq = _to_int(raw.get("seq"))
        request_id = _to_str_or_none(raw.get("request_id"))

        if seq is not None and seq <= self.latest_seq:
            out.acks.append(
                ack_payload(seq=seq, request_id=request_id, reason="drop_old_seq", source="voice")
            )
            return
        if seq is not None:
            self.latest_seq = seq

        intent = _resolve_voice_intent(raw)
        if not intent:
            out.errors.append("voice intent missing")
            return

        if self.emergency_latched and intent not in {"reset_emergency"}:
            out.acks.append(
                ack_payload(seq=seq, request_id=request_id, reason="blocked_emergency", source="voice")
            )
            return

        joystick_busy = self.state == ControlState.JOYSTICK_ACTIVE and self.last_nonzero_joystick_ms > 0
        if joystick_busy and (now_ms - self.last_nonzero_joystick_ms) < self.deadman_timeout_ms:
            if intent not in {"stop", "reset_emergency", "gait_stop"}:
                out.acks.append(
                    ack_payload(seq=seq, request_id=request_id, reason="blocked_by_joystick", source="voice")
                )
                return

        if intent == "stop":
            self.emergency_latched = True
            self.voice_action_deadline_ms = 0
            self.last_nonzero_joystick_ms = 0
            self._clear_pending_fsm()
            self._transition(ControlState.EMERGENCY_STOP, out)
            out.commands.append(ControlCommand(kind=CommandKind.STOP, source="voice", reason="emergency_stop"))
            out.acks.append(ack_payload(seq=seq, request_id=request_id, reason="accepted", source="voice"))
            return

        if intent == "reset_emergency":
            self.emergency_latched = False
            self._clear_pending_fsm()
            self._transition(ControlState.IDLE, out)
            out.acks.append(ack_payload(seq=seq, request_id=request_id, reason="accepted", source="voice"))
            return

        if intent == "walk":
            self.voice_action_deadline_ms = 0
            self._schedule_pending_fsm("gotoMLP", now_ms + WALK_ZERO_TO_MLP_DELAY_MS)
            self._transition(ControlState.VOICE_ACTION, out)
            out.commands.append(
                ControlCommand(kind=CommandKind.FSM_CMD, source="voice", fsm_cmd="gotoZero")
            )
            out.acks.append(ack_payload(seq=seq, request_id=request_id, reason="accepted", source="voice"))
            return

        if intent in {"zero", "gait_stop", "fsm_cmd"}:
            fsm_cmd = _fsm_command_from_voice(raw, intent)
            if not fsm_cmd:
                out.errors.append("unknown_fsm_cmd")
                return
            self.voice_action_deadline_ms = 0
            self._clear_pending_fsm()
            self._transition(ControlState.VOICE_ACTION, out)
            out.commands.append(
                ControlCommand(kind=CommandKind.FSM_CMD, source="voice", fsm_cmd=fsm_cmd)
            )
            out.acks.append(ack_payload(seq=seq, request_id=request_id, reason="accepted", source="voice"))
            return

        if intent == "move":
            linear = self.safety.clamp_linear(float(raw.get("linear", 0.0)))
            angular = self.safety.clamp_angular(float(raw.get("angular", 0.0)))
            duration_ms = self.safety.clamp_voice_duration(raw.get("duration_ms"))
            self._clear_pending_fsm()
            self.voice_action_deadline_ms = now_ms + duration_ms
            self._transition(ControlState.VOICE_ACTION, out)
            out.commands.append(
                ControlCommand(
                    kind=CommandKind.MOVE,
                    source="voice",
                    linear=linear,
                    angular=angular,
                    duration_ms=duration_ms,
                )
            )
            out.acks.append(ack_payload(seq=seq, request_id=request_id, reason="accepted", source="voice"))
            return

        if intent == "action":
            motion_number = _motion_number_from_action(raw)
            if motion_number is None:
                out.errors.append("unknown action_id")
                return
            self.voice_action_deadline_ms = 0
            self._clear_pending_fsm()
            self._transition(ControlState.VOICE_ACTION, out)
            out.commands.append(
                ControlCommand(
                    kind=CommandKind.MOTION,
                    source="voice",
                    motion_number=motion_number,
                    active=True,
                )
            )
            out.acks.append(ack_payload(seq=seq, request_id=request_id, reason="accepted", source="voice"))
            return

        out.errors.append(f"unsupported voice intent: {intent}")

    def _transition(self, new_state: ControlState, out: RouterOutput) -> None:
        if self.state == new_state:
            return
        old = self.state
        self.state = new_state
        out.events.append(event_payload("state_changed", old_state=old.value, state=new_state.value))

    def _schedule_pending_fsm(self, cmd: str, due_ms: int) -> None:
        self.pending_fsm_command = str(cmd)
        self.pending_fsm_due_ms = int(due_ms)

    def _clear_pending_fsm(self) -> None:
        self.pending_fsm_command = ""
        self.pending_fsm_due_ms = 0


def _to_int(v: Any) -> int | None:
    try:
        if v is None:
            return None
        return int(v)
    except (TypeError, ValueError):
        return None


def _to_str_or_none(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _resolve_voice_intent(raw: dict[str, Any]) -> str:
    msg_type = str(raw.get("type", "")).strip().lower()

    if msg_type == "action":
        return "action"

    intent = str(raw.get("intent", "")).strip().lower()
    if intent:
        return intent

    if msg_type == "text":
        text = str(raw.get("content", "")).strip().lower()
        if not text:
            return ""
        if any(k in text for k in ("停步", "停止步态", "gait stop", "stop gait")):
            return "gait_stop"
        if any(k in text for k in ("归零", "回零", "zero pose", "gotozero", "goto zero")):
            return "zero"
        if any(k in text for k in ("走路", "行走", "walk", "开始走", "开始行走")):
            return "walk"
        if any(k in text for k in ("停", "stop", "停止", "急停")):
            return "stop"
        if any(k in text for k in ("挥手", "wave")):
            raw["action_id"] = "wave_hand"
            return "action"
        if any(k in text for k in ("握手", "handshake")):
            raw["action_id"] = "hand_shake"
            return "action"
        if any(k in text for k in ("鞠躬", "bow")):
            raw["action_id"] = "bow"
            return "action"
        if any(k in text for k in ("跳舞", "dance")):
            raw["action_id"] = "dance_1"
            return "action"
        if any(k in text for k in ("前进", "forward")):
            raw["linear"] = 0.35
            raw["angular"] = 0.0
            return "move"
        if any(k in text for k in ("后退", "back")):
            raw["linear"] = -0.25
            raw["angular"] = 0.0
            return "move"
        if any(k in text for k in ("左转", "left")):
            raw["linear"] = 0.0
            raw["angular"] = 0.6
            return "move"
        if any(k in text for k in ("右转", "right")):
            raw["linear"] = 0.0
            raw["angular"] = -0.6
            return "move"

    return ""


def _motion_number_from_action(raw: dict[str, Any]) -> int | None:
    n = _to_int(raw.get("motion_number"))
    if n is not None and 1 <= n <= 5:
        return n

    action_id = str(raw.get("action_id", "")).strip().lower()
    if action_id in ACTION_MAP:
        return ACTION_MAP[action_id]
    return None


def _fsm_command_from_voice(raw: dict[str, Any], intent: str) -> str:
    if intent == "zero":
        return "gotoZero"
    if intent == "gait_stop":
        return "gotoStop"
    if intent == "fsm_cmd":
        value = str(raw.get("fsm_cmd", raw.get("cmd", ""))).strip().lower()
        mapping = {
            "gotozero": "gotoZero",
            "gotomlp": "gotoMLP",
            "gotostop": "gotoStop",
        }
        return mapping.get(value, "")
    return ""
