from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

from aiohttp import WSMsgType, web
from aiortc import RTCPeerConnection, RTCIceCandidate, RTCSessionDescription
from aiortc.contrib.media import MediaBlackhole

from .config import GatewayConfig
from .protocol import CommandKind, RouterOutput, event_payload
from .ros_client import HttpRosBridgeClient, MockRosBridgeClient, RosBridgeClient
from .safety import SafetyGuard
from .state import ControlRouter
from .video_track import SharedVideoTrack


@dataclass(slots=True)
class PeerSession:
    chat_id: str
    sender_id: str
    pc: RTCPeerConnection
    router: ControlRouter
    dc: Any = None
    closed: bool = False
    tasks: set[asyncio.Task] = field(default_factory=set)

    def dc_send(self, payload: dict[str, Any]) -> None:
        if self.dc is None:
            return
        if getattr(self.dc, "readyState", "closed") != "open":
            return
        try:
            self.dc.send(json.dumps(payload, ensure_ascii=False))
        except Exception:
            pass

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        for t in list(self.tasks):
            t.cancel()
        self.tasks.clear()
        try:
            await self.pc.close()
        except Exception:
            pass


class GatewayServer:
    def __init__(self, config: GatewayConfig) -> None:
        self.cfg = config
        self._sessions: dict[str, PeerSession] = {}
        self._runner: web.AppRunner | None = None

        self._safety = SafetyGuard(
            max_linear=self.cfg.max_linear,
            max_angular=self.cfg.max_angular,
            voice_max_duration_ms=self.cfg.voice_max_duration_ms,
        )

        self._video_track: SharedVideoTrack | None = SharedVideoTrack() if self.cfg.video_enabled else None
        self._ros: RosBridgeClient = self._build_ros_client()

    def _build_ros_client(self) -> RosBridgeClient:
        if self.cfg.ros_bridge.mode == "mock":
            return MockRosBridgeClient()
        return HttpRosBridgeClient(
            base_url=self.cfg.ros_bridge.base_url,
            timeout_s=self.cfg.ros_bridge.timeout_s,
        )

    async def start(self) -> None:
        app = web.Application()
        app.router.add_get("/signal", self._ws_signal_handler)
        app.router.add_get("/health", self._health_handler)
        app.router.add_get("/status", self._status_handler)
        if self.cfg.video_enabled:
            app.router.add_post("/push_frame", self._push_frame_handler)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.cfg.host, self.cfg.port)
        await site.start()
        print(f"Gateway ready on ws://{self.cfg.host}:{self.cfg.port}/signal")

    async def stop(self) -> None:
        for _, session in list(self._sessions.items()):
            await session.close()
        self._sessions.clear()

        if self._runner:
            await self._runner.cleanup()
            self._runner = None

    async def _health_handler(self, _: web.Request) -> web.Response:
        return web.json_response(
            {
                "ok": True,
                "sessions": len(self._sessions),
                "video_enabled": self.cfg.video_enabled,
            }
        )

    async def _status_handler(self, _: web.Request) -> web.Response:
        states = {
            chat_id: session.router.state.value
            for chat_id, session in self._sessions.items()
        }
        peers = {
            chat_id: {
                "ice_state": session.pc.iceConnectionState,
                "connection_state": session.pc.connectionState,
                "dc_state": getattr(session.dc, "readyState", None),
            }
            for chat_id, session in self._sessions.items()
        }
        payload: dict[str, Any] = {
            "ok": True,
            "sessions": len(self._sessions),
            "states": states,
            "peers": peers,
            "control": {
                "deadman_timeout_ms": self.cfg.deadman_timeout_ms,
                "joystick_max_hz": self.cfg.joystick_max_hz,
                "voice_max_duration_ms": self.cfg.voice_max_duration_ms,
            },
        }
        if self._video_track is not None:
            payload["video"] = self._video_track.get_metrics()
        return web.json_response(payload)

    async def _push_frame_handler(self, request: web.Request) -> web.Response:
        if self._video_track is None:
            return web.json_response({"ok": False, "error": "video_disabled"}, status=404)

        token = self.cfg.video_push_token
        if token:
            got = request.headers.get("X-Push-Token", "")
            if got != token:
                return web.json_response({"ok": False, "error": "unauthorized"}, status=401)

        body = await request.read()
        accepted = self._video_track.push_jpeg(body)
        return web.json_response({"ok": accepted, "video": self._video_track.get_metrics()})

    async def _ws_signal_handler(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)

        chat_id: str | None = None
        session: PeerSession | None = None

        try:
            async for msg in ws:
                if msg.type == WSMsgType.ERROR:
                    break
                if msg.type != WSMsgType.TEXT:
                    continue

                try:
                    data = json.loads(msg.data)
                except json.JSONDecodeError:
                    await ws.send_json({"type": "error", "content": "invalid json"})
                    continue

                sig_type = str(data.get("type", "")).strip().lower()

                if sig_type == "offer":
                    chat_id = str(data.get("chat_id") or "").strip() or f"chat-{int(time.time() * 1000)}"
                    sender_id = str(data.get("sender_id") or chat_id)

                    old = self._sessions.pop(chat_id, None)
                    if old:
                        await old.close()

                    session = self._new_session(chat_id=chat_id, sender_id=sender_id)
                    self._sessions[chat_id] = session

                    self._setup_peer(session, ws)

                    offer_sdp = str(data.get("sdp", ""))
                    await session.pc.setRemoteDescription(
                        RTCSessionDescription(sdp=offer_sdp, type="offer")
                    )
                    answer = await session.pc.createAnswer()
                    await session.pc.setLocalDescription(answer)

                    await ws.send_json(
                        {
                            "type": "answer",
                            "sdp": session.pc.localDescription.sdp,
                            "chat_id": chat_id,
                        }
                    )

                elif sig_type == "ice" and session is not None:
                    c = _parse_ice_candidate(data.get("candidate"))
                    if c is not None:
                        await session.pc.addIceCandidate(c)

                elif sig_type == "bye":
                    break

        finally:
            if chat_id:
                s = self._sessions.pop(chat_id, None)
                if s:
                    await s.close()
            await ws.close()

        return ws

    def _new_session(self, *, chat_id: str, sender_id: str) -> PeerSession:
        router = ControlRouter(
            safety=self._safety,
            deadman_timeout_ms=self.cfg.deadman_timeout_ms,
            joystick_min_interval_ms=self.cfg.joystick_min_interval_ms,
        )
        session = PeerSession(
            chat_id=chat_id,
            sender_id=sender_id,
            pc=RTCPeerConnection(),
            router=router,
        )
        t = asyncio.create_task(self._watchdog(session), name=f"watchdog-{chat_id}")
        session.tasks.add(t)
        t.add_done_callback(session.tasks.discard)
        return session

    def _setup_peer(self, session: PeerSession, ws: web.WebSocketResponse) -> None:
        pc = session.pc

        if self._video_track is not None:
            pc.addTrack(self._video_track)

        @pc.on("datachannel")
        def on_datachannel(channel: Any) -> None:
            if channel.label != self.cfg.datachannel_label:
                return
            session.dc = channel

            @channel.on("close")
            def on_close() -> None:
                task = asyncio.create_task(self._close_session(session.chat_id))
                session.tasks.add(task)
                task.add_done_callback(session.tasks.discard)

            @channel.on("message")
            def on_message(raw: str) -> None:
                task = asyncio.create_task(self._on_dc_message(session, raw))
                session.tasks.add(task)
                task.add_done_callback(session.tasks.discard)

        @pc.on("track")
        def on_track(track: Any) -> None:
            if track.kind != "audio":
                MediaBlackhole().addTrack(track)
                return
            # Server-side ASR can be added here later.
            MediaBlackhole().addTrack(track)

        @pc.on("icecandidate")
        async def on_icecandidate(candidate: Any) -> None:
            if candidate is None:
                return
            try:
                await ws.send_json(
                    {
                        "type": "ice",
                        "candidate": {
                            "component": candidate.component,
                            "foundation": candidate.foundation,
                            "ip": candidate.ip,
                            "port": candidate.port,
                            "priority": candidate.priority,
                            "protocol": candidate.protocol,
                            "type": candidate.type,
                            "sdpMid": candidate.sdpMid,
                            "sdpMLineIndex": candidate.sdpMLineIndex,
                        },
                    }
                )
            except Exception:
                pass

        @pc.on("iceconnectionstatechange")
        async def on_ice_state() -> None:
            if pc.iceConnectionState in ("failed", "closed", "disconnected"):
                await self._close_session(session.chat_id)

        @pc.on("connectionstatechange")
        async def on_connection_state() -> None:
            if pc.connectionState in ("failed", "closed", "disconnected"):
                await self._close_session(session.chat_id)

    async def _watchdog(self, session: PeerSession) -> None:
        while not session.closed:
            await asyncio.sleep(0.05)
            out = session.router.tick()
            if out.commands or out.events:
                await self._apply_router_output(session, out)

    async def _on_dc_message(self, session: PeerSession, raw: str) -> None:
        if session.closed:
            return

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            session.dc_send({"type": "error", "content": "invalid json"})
            return

        out = session.router.handle(data)
        await self._apply_router_output(session, out)

    async def _apply_router_output(self, session: PeerSession, out: RouterOutput) -> None:
        for ack in out.acks:
            session.dc_send(ack)

        for ev in out.events:
            session.dc_send(ev)

        for err in out.errors:
            session.dc_send({"type": "error", "content": err})

        for cmd in out.commands:
            ok, detail = await self._execute_command(cmd)
            if ok:
                session.dc_send(event_payload("command_applied", kind=cmd.kind.value, source=cmd.source, detail=detail))
            else:
                session.dc_send({"type": "error", "content": f"command_failed:{cmd.kind.value}:{detail}"})

    async def _execute_command(self, cmd) -> tuple[bool, str]:
        if cmd.kind == CommandKind.MOVE:
            return await self._ros.move(linear=cmd.linear, angular=cmd.angular)
        if cmd.kind == CommandKind.STOP:
            return await self._ros.stop()
        if cmd.kind == CommandKind.MOTION:
            return await self._ros.motion(motion_number=cmd.motion_number, active=cmd.active)
        return False, "unsupported_command"

    async def _close_session(self, chat_id: str) -> None:
        s = self._sessions.pop(chat_id, None)
        if s:
            await s.close()


def _parse_ice_candidate(raw: Any) -> RTCIceCandidate | None:
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
