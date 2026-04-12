from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CommandKind(str, Enum):
    MOVE = "move"
    STOP = "stop"
    MOTION = "motion"


@dataclass(slots=True)
class ControlCommand:
    kind: CommandKind
    source: str
    linear: float = 0.0
    angular: float = 0.0
    duration_ms: int = 0
    motion_number: int = 0
    active: bool = True
    reason: str = ""


@dataclass(slots=True)
class RouterOutput:
    commands: list[ControlCommand] = field(default_factory=list)
    acks: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def ack_payload(
    *,
    seq: int | None,
    request_id: str | None,
    reason: str,
    source: str,
    ts: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": "ack",
        "reason": reason,
        "source": source,
    }
    if seq is not None:
        payload["seq"] = seq
    if request_id:
        payload["request_id"] = request_id
    if ts is not None:
        payload["ts"] = ts
    return payload


def event_payload(name: str, **kwargs: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"type": "event", "name": name}
    payload.update(kwargs)
    return payload
