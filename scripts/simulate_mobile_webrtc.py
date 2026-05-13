from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

from aiortc import RTCIceCandidate, RTCPeerConnection, RTCSessionDescription
from aiohttp import ClientSession, WSMsgType


def _candidate_to_payload(candidate: RTCIceCandidate) -> dict[str, Any]:
    return {
        "component": int(candidate.component),
        "foundation": str(candidate.foundation),
        "ip": str(candidate.ip),
        "port": int(candidate.port),
        "priority": int(candidate.priority),
        "protocol": str(candidate.protocol),
        "type": str(candidate.type),
        "sdpMid": candidate.sdpMid,
        "sdpMLineIndex": candidate.sdpMLineIndex,
    }


def _payload_to_candidate(raw: Any) -> RTCIceCandidate | None:
    if not isinstance(raw, dict):
        return None
    try:
        return RTCIceCandidate(
            component=int(raw.get("component", 1)),
            foundation=str(raw.get("foundation", "")),
            ip=str(raw.get("ip", "")),
            port=int(raw.get("port", 0)),
            priority=int(raw.get("priority", 0)),
            protocol=str(raw.get("protocol", "udp")),
            type=str(raw.get("type", "host")),
            sdpMid=raw.get("sdpMid"),
            sdpMLineIndex=int(raw.get("sdpMLineIndex", 0)),
        )
    except Exception:
        return None


@dataclass(slots=True)
class ScenarioResult:
    sent_messages: list[dict[str, Any]]
    received_messages: list[dict[str, Any]]


class MobileWebRtcSimulator:
    def __init__(self, signal_url: str, *, timeout_s: float = 8.0) -> None:
        self.signal_url = signal_url
        self.timeout_s = timeout_s
        self.pc = RTCPeerConnection()
        self.data_channel = self.pc.createDataChannel("control")
        self._dc_open = asyncio.Event()
        self._answer_ready = asyncio.Event()
        self._sent: list[dict[str, Any]] = []
        self._received: list[dict[str, Any]] = []
        self._chat_id = f"sim-{int(time.time() * 1000)}"
        self._sender_id = f"mobile-{int(time.time() * 1000)}"
        self._seq = 1
        self._ws = None

        @self.data_channel.on("open")
        def _on_open() -> None:
            self._dc_open.set()

        @self.data_channel.on("message")
        def _on_message(raw: str) -> None:
            try:
                message = json.loads(str(raw))
            except Exception:
                message = {"type": "raw", "payload": str(raw)}
            self._received.append(message)

        @self.pc.on("icecandidate")
        async def _on_icecandidate(candidate: Any) -> None:
            if candidate is None or self._ws is None:
                return
            await self._ws.send_json(
                {
                    "type": "ice",
                    "candidate": _candidate_to_payload(candidate),
                }
            )

    async def __aenter__(self) -> "MobileWebRtcSimulator":
        self._session = ClientSession()
        self._ws = await self._session.ws_connect(self.signal_url, heartbeat=20)
        self._signal_task = asyncio.create_task(self._signal_loop(), name="mobile-webrtc-signal-loop")
        await self._negotiate()
        await asyncio.wait_for(self._dc_open.wait(), timeout=self.timeout_s)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        try:
            if self._ws is not None and not self._ws.closed:
                await self._ws.send_json({"type": "bye"})
        except Exception:
            pass
        if hasattr(self, "_signal_task"):
            self._signal_task.cancel()
            try:
                await self._signal_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        await self.pc.close()
        if self._ws is not None:
            await self._ws.close()
        await self._session.close()

    async def _signal_loop(self) -> None:
        assert self._ws is not None
        async for msg in self._ws:
            if msg.type == WSMsgType.TEXT:
                data = json.loads(msg.data)
                msg_type = str(data.get("type", "")).strip().lower()
                if msg_type == "answer":
                    sdp = str(data.get("sdp", ""))
                    if sdp:
                        await self.pc.setRemoteDescription(
                            RTCSessionDescription(sdp=sdp, type="answer")
                        )
                        self._answer_ready.set()
                elif msg_type == "ice":
                    candidate = _payload_to_candidate(data.get("candidate"))
                    if candidate is not None:
                        await self.pc.addIceCandidate(candidate)
                else:
                    self._received.append(data)
            elif msg.type in {WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR}:
                break

    async def _negotiate(self) -> None:
        offer = await self.pc.createOffer()
        await self.pc.setLocalDescription(offer)
        assert self._ws is not None
        await self._ws.send_json(
            {
                "type": "offer",
                "sdp": self.pc.localDescription.sdp,
                "chat_id": self._chat_id,
                "sender_id": self._sender_id,
            }
        )
        await asyncio.wait_for(self._answer_ready.wait(), timeout=self.timeout_s)

    def _next_seq(self) -> int:
        value = self._seq
        self._seq += 1
        return value

    def _send_dc(self, payload: dict[str, Any]) -> None:
        self._sent.append(payload)
        self.data_channel.send(json.dumps(payload, ensure_ascii=False))

    async def send_voice_intent(
        self,
        intent: str,
        *,
        fsm_cmd: str = "",
        linear: float | None = None,
        angular: float | None = None,
        duration_ms: int | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "type": "voice_intent",
            "seq": self._next_seq(),
            "request_id": f"voice-{int(time.time() * 1000)}",
            "intent": intent,
        }
        if fsm_cmd:
            payload["fsm_cmd"] = fsm_cmd
        if linear is not None:
            payload["linear"] = float(linear)
        if angular is not None:
            payload["angular"] = float(angular)
        if duration_ms is not None:
            payload["duration_ms"] = int(duration_ms)
        self._send_dc(payload)

    async def send_joystick(self, *, x: float, y: float, linear: float, angular: float) -> None:
        payload = {
            "type": "joystick",
            "seq": self._next_seq(),
            "request_id": f"joy-{int(time.time() * 1000)}",
            "x": float(x),
            "y": float(y),
            "linear": float(linear),
            "angular": float(angular),
            "ts": int(time.time() * 1000),
        }
        self._send_dc(payload)

    async def run_scenario(
        self,
        scenario: str,
        *,
        joystick_seconds: float = 1.0,
        joystick_interval_s: float = 0.1,
    ) -> ScenarioResult:
        scenario_key = scenario.strip().lower()
        if scenario_key == "walk":
            await self.send_voice_intent("walk")
        elif scenario_key == "zero":
            await self.send_voice_intent("zero")
        elif scenario_key == "gait_stop":
            await self.send_voice_intent("gait_stop")
        elif scenario_key == "gotomlp":
            await self.send_voice_intent("fsm_cmd", fsm_cmd="gotoMLP")
        elif scenario_key == "gotozero":
            await self.send_voice_intent("fsm_cmd", fsm_cmd="gotoZero")
        elif scenario_key == "gotostop":
            await self.send_voice_intent("fsm_cmd", fsm_cmd="gotoStop")
        elif scenario_key == "joystick_forward":
            deadline = time.time() + max(0.0, float(joystick_seconds))
            while time.time() < deadline:
                await self.send_joystick(x=0.0, y=0.6, linear=0.36, angular=0.0)
                await asyncio.sleep(max(0.02, float(joystick_interval_s)))
            await self.send_joystick(x=0.0, y=0.0, linear=0.0, angular=0.0)
        else:
            raise ValueError(f"unsupported scenario: {scenario}")

        await asyncio.sleep(1.0)
        return ScenarioResult(sent_messages=list(self._sent), received_messages=list(self._received))


async def _main_async(args: argparse.Namespace) -> int:
    async with MobileWebRtcSimulator(args.signal_url, timeout_s=args.timeout_s) as client:
        result = await client.run_scenario(
            args.scenario,
            joystick_seconds=args.joystick_seconds,
            joystick_interval_s=args.joystick_interval_s,
        )
    print(
        json.dumps(
            {
                "ok": True,
                "signal_url": args.signal_url,
                "scenario": args.scenario,
                "sent_messages": result.sent_messages,
                "received_messages": result.received_messages,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simulate the mobile WebRTC control client.")
    parser.add_argument("--signal-url", default="ws://127.0.0.1:9100/signal")
    parser.add_argument(
        "--scenario",
        default="walk",
        choices=[
            "walk",
            "zero",
            "gait_stop",
            "gotoMLP",
            "gotoZero",
            "gotoStop",
            "joystick_forward",
        ],
    )
    parser.add_argument("--timeout-s", type=float, default=8.0)
    parser.add_argument("--joystick-seconds", type=float, default=1.0)
    parser.add_argument("--joystick-interval-s", type=float, default=0.1)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
