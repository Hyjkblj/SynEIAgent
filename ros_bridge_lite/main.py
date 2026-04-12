from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from typing import Any

from aiohttp import web


@dataclass(slots=True)
class BridgeConfig:
    host: str = "0.0.0.0"
    port: int = 8080
    cmd_vel_topic: str = "/cmd_vel"
    node_name: str = "gateway_lite_bridge"
    set_motion_service: str = "/set_motion_number"


class Ros2BridgeRuntime:
    def __init__(self, cfg: BridgeConfig) -> None:
        self.cfg = cfg
        self.enabled = False
        self.error = ""

        self._rclpy: Any = None
        self._node: Any = None
        self._twist_type: Any = None
        self._motion_srv_type: Any = None
        self._cmd_pub: Any = None
        self._motion_client: Any = None

        try:
            import rclpy  # type: ignore
            from geometry_msgs.msg import Twist  # type: ignore
            from hric_msgs.srv import SetMotionNumber  # type: ignore

            self._rclpy = rclpy
            self._twist_type = Twist
            self._motion_srv_type = SetMotionNumber

            if not rclpy.ok():
                rclpy.init(args=None)
            self._node = rclpy.create_node(cfg.node_name)
            self._cmd_pub = self._node.create_publisher(Twist, cfg.cmd_vel_topic, 10)
            self._motion_client = self._node.create_client(SetMotionNumber, cfg.set_motion_service)
            self.enabled = True
        except Exception as e:
            self.error = str(e)

    def move(self, linear: float, angular: float) -> tuple[bool, str]:
        if not self.enabled:
            return False, f"ros_disabled:{self.error}"
        try:
            msg = self._twist_type()
            msg.linear.x = float(linear)
            msg.angular.z = float(angular)
            self._cmd_pub.publish(msg)
            self._rclpy.spin_once(self._node, timeout_sec=0.0)
            return True, "ok"
        except Exception as e:
            return False, str(e)

    def stop(self) -> tuple[bool, str]:
        return self.move(0.0, 0.0)

    def motion(self, number: int, active: bool) -> tuple[bool, str]:
        if not self.enabled:
            return False, f"ros_disabled:{self.error}"
        try:
            if not self._motion_client.wait_for_service(timeout_sec=0.3):
                return False, "set_motion_number_unavailable"

            req = self._motion_srv_type.Request()
            req.is_motion = bool(active)
            req.motion_number = int(number)

            fut = self._motion_client.call_async(req)
            self._rclpy.spin_until_future_complete(self._node, fut, timeout_sec=1.0)
            if fut.done() and fut.result() is not None:
                return True, "ok"
            return False, "service_timeout"
        except Exception as e:
            return False, str(e)

    def close(self) -> None:
        if not self.enabled:
            return
        try:
            self._node.destroy_node()
        except Exception:
            pass


async def run_bridge(cfg: BridgeConfig) -> None:
    runtime = Ros2BridgeRuntime(cfg)

    async def health(_: web.Request) -> web.Response:
        return web.json_response(
            {
                "ok": True,
                "ros_enabled": runtime.enabled,
                "ros_error": runtime.error,
                "cmd_vel_topic": cfg.cmd_vel_topic,
                "set_motion_service": cfg.set_motion_service,
            }
        )

    async def move(req: web.Request) -> web.Response:
        body = await req.json()
        linear = float(body.get("linear", 0.0))
        angular = float(body.get("angular", 0.0))
        ok, detail = runtime.move(linear, angular)
        return web.json_response({"success": ok, "detail": detail, "linear": linear, "angular": angular})

    async def motion(req: web.Request) -> web.Response:
        body = await req.json()
        number = int(body.get("number", 0))
        active = bool(body.get("active", True))
        ok, detail = runtime.motion(number, active)
        return web.json_response({"success": ok, "detail": detail, "number": number, "active": active})

    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_post("/move", move)
    app.router.add_post("/motion", motion)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, cfg.host, cfg.port)
    await site.start()

    print(f"ROS Bridge Lite ready on http://{cfg.host}:{cfg.port}")
    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        runtime.close()
        await runner.cleanup()


def parse_args() -> BridgeConfig:
    parser = argparse.ArgumentParser(description="SynEIAgent ROS Bridge")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--cmd-vel-topic", default="/cmd_vel")
    parser.add_argument("--node-name", default="gateway_lite_bridge")
    parser.add_argument("--set-motion-service", default="/set_motion_number")
    args = parser.parse_args()
    return BridgeConfig(
        host=args.host,
        port=args.port,
        cmd_vel_topic=args.cmd_vel_topic,
        node_name=args.node_name,
        set_motion_service=args.set_motion_service,
    )


def main() -> None:
    cfg = parse_args()
    asyncio.run(run_bridge(cfg))


if __name__ == "__main__":
    main()
