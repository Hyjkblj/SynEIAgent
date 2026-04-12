from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class RosBridgeConfig:
    mode: str = "http"  # http | mock
    base_url: str = "http://127.0.0.1:8080"
    timeout_s: float = 0.8


@dataclass(slots=True)
class GatewayConfig:
    host: str = "0.0.0.0"
    port: int = 9100
    allow_from: list[str] = field(default_factory=lambda: ["*"])
    datachannel_label: str = "control"
    video_enabled: bool = True
    video_push_token: str = ""

    deadman_timeout_ms: int = 250
    joystick_max_hz: int = 20
    max_linear: float = 0.6
    max_angular: float = 1.2

    voice_max_duration_ms: int = 1000
    voice_priority: int = 60
    joystick_priority: int = 80

    ros_bridge: RosBridgeConfig = field(default_factory=RosBridgeConfig)

    @property
    def joystick_min_interval_ms(self) -> int:
        hz = max(1, int(self.joystick_max_hz))
        return int(1000 / hz)


_DEF = GatewayConfig()


def _as_str_list(raw: Any, default: list[str]) -> list[str]:
    if not isinstance(raw, list):
        return list(default)
    out = [str(x).strip() for x in raw if str(x).strip()]
    return out or list(default)


def _load_dict(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8-sig")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Config root must be a JSON object")
    return data


def load_config(path: str | Path | None) -> GatewayConfig:
    if path is None:
        return GatewayConfig()

    p = Path(path)
    data = _load_dict(p)

    raw_rb = data.get("ros_bridge") if isinstance(data.get("ros_bridge"), dict) else {}
    rb = RosBridgeConfig(
        mode=str(raw_rb.get("mode", _DEF.ros_bridge.mode)).strip().lower() or _DEF.ros_bridge.mode,
        base_url=str(raw_rb.get("base_url", _DEF.ros_bridge.base_url)).strip() or _DEF.ros_bridge.base_url,
        timeout_s=float(raw_rb.get("timeout_s", _DEF.ros_bridge.timeout_s)),
    )

    cfg = GatewayConfig(
        host=str(data.get("host", _DEF.host)).strip() or _DEF.host,
        port=int(data.get("port", _DEF.port)),
        allow_from=_as_str_list(data.get("allow_from"), _DEF.allow_from),
        datachannel_label=str(data.get("datachannel_label", _DEF.datachannel_label)).strip() or _DEF.datachannel_label,
        video_enabled=bool(data.get("video_enabled", _DEF.video_enabled)),
        video_push_token=str(data.get("video_push_token", _DEF.video_push_token)).strip(),
        deadman_timeout_ms=max(50, int(data.get("deadman_timeout_ms", _DEF.deadman_timeout_ms))),
        joystick_max_hz=max(1, int(data.get("joystick_max_hz", _DEF.joystick_max_hz))),
        max_linear=float(data.get("max_linear", _DEF.max_linear)),
        max_angular=float(data.get("max_angular", _DEF.max_angular)),
        voice_max_duration_ms=max(100, int(data.get("voice_max_duration_ms", _DEF.voice_max_duration_ms))),
        voice_priority=int(data.get("voice_priority", _DEF.voice_priority)),
        joystick_priority=int(data.get("joystick_priority", _DEF.joystick_priority)),
        ros_bridge=rb,
    )

    return cfg
