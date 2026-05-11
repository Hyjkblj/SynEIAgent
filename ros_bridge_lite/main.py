from __future__ import annotations

import argparse
import asyncio
import time
from dataclasses import dataclass
from typing import Any

from aiohttp import web

from .gait_controller import GaitConfig, GaitController
from .motor_id_map import JOINT_NAMES as RL_JOINT_NAMES


DEFAULT_GAIT_JOINT_NAMES = (
    "hip_pitch_l_joint",
    "knee_pitch_l_joint",
    "ankle_pitch_l_joint",
    "hip_pitch_r_joint",
    "knee_pitch_r_joint",
    "ankle_pitch_r_joint",
)


@dataclass(slots=True)
class BridgeConfig:
    host: str = "0.0.0.0"
    port: int = 8080
    cmd_vel_topic: str = "/cmd_vel"
    joint_command_topic: str = "/joint_command"
    node_name: str = "gateway_lite_bridge"
    set_motion_service: str = "/set_motion_number"
    control_mode: str = "cmd_vel"  # cmd_vel | joint_gait
    control_hz: float = 50.0
    command_timeout_ms: int = 3000
    stop_ramp_time_ms: int = 260
    gait_joint_names: tuple[str, ...] = DEFAULT_GAIT_JOINT_NAMES

    # RL policy config (only used when control_mode == "rl_policy")
    policy_model_xml: str = ""
    policy_model_bin: str = ""
    policy_config_path: str = ""
    simulation: bool = True
    sp_lib_path: str = ""
    isaac_sim_url: str = ""  # e.g. "http://localhost:9200" for HTTP feedback mode

    @property
    def loop_period_s(self) -> float:
        return 1.0 / max(1.0, float(self.control_hz))


class IsaacSimFeedbackAdapter:
    """Polls Isaac Sim HTTP API for joint feedback and IMU data."""

    # URDF name → bodyIdMap index (same order as motor_id_map)
    _URDF_TO_INDEX: dict[str, int] = {
        "hip_roll_l_joint": 0, "hip_pitch_l_joint": 1, "hip_yaw_l_joint": 2,
        "knee_pitch_l_joint": 3, "ankle_pitch_l_joint": 4, "ankle_roll_l_joint": 5,
        "hip_roll_r_joint": 6, "hip_pitch_r_joint": 7, "hip_yaw_r_joint": 8,
        "knee_pitch_r_joint": 9, "ankle_pitch_r_joint": 10, "ankle_roll_r_joint": 11,
        "shoulder_pitch_l_joint": 12, "shoulder_roll_l_joint": 13,
        "shoulder_yaw_l_joint": 14, "elbow_l_joint": 15,
        "shoulder_pitch_r_joint": 16, "shoulder_roll_r_joint": 17,
        "shoulder_yaw_r_joint": 18, "elbow_r_joint": 19,
    }

    def __init__(self, base_url: str) -> None:
        import httpx
        self._url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=0.2)
        self._last_positions = [0.0] * 20
        self._last_velocities = [0.0] * 20
        self._last_efforts = [0.0] * 20
        self._ok = False

    async def fetch_and_inject(self, controller: Any) -> bool:
        """Fetch feedback from Isaac Sim HTTP and inject into RLPolicyController."""
        try:
            # Fetch joint states
            js_resp = await self._client.get(f"{self._url}/joint_states")
            if js_resp.status_code == 200:
                js = js_resp.json()
                names = js.get("name", [])
                positions = js.get("position", [])
                velocities = js.get("velocity", [])
                efforts = js.get("effort", [])
                for i, name in enumerate(names):
                    idx = self._URDF_TO_INDEX.get(name, -1)
                    if 0 <= idx < 20:
                        self._last_positions[idx] = float(positions[i]) if i < len(positions) else 0.0
                        self._last_velocities[idx] = float(velocities[i]) if i < len(velocities) else 0.0
                        self._last_efforts[idx] = float(efforts[i]) if i < len(efforts) else 0.0
                controller.set_joint_feedback(self._last_positions, self._last_velocities, self._last_efforts)

            # Fetch IMU
            imu_resp = await self._client.get(f"{self._url}/imu")
            if imu_resp.status_code == 200:
                imu = imu_resp.json()
                omega = imu.get("angular_velocity", [0, 0, 0])
                accel = imu.get("linear_acceleration", [0, 0, 9.81])
                euler = imu.get("euler", {})
                yaw = float(euler.get("yaw", 0.0))
                pitch = float(euler.get("pitch", 0.0))
                roll = float(euler.get("roll", 0.0))
                controller.set_imu_feedback(yaw, pitch, roll, tuple(omega), tuple(accel))

            self._ok = True
            return True
        except Exception:
            self._ok = False
            return False

    async def send_joint_command(self, joint_positions: dict[str, float]) -> bool:
        """Send joint targets to Isaac Sim via HTTP POST /joint_command."""
        try:
            from .sim_feedback_adapter import BODYIDMAP_TO_URDF
            urdf_names = []
            urdf_positions = []
            for name, pos in joint_positions.items():
                urdf_name = BODYIDMAP_TO_URDF.get(name)
                if urdf_name:
                    urdf_names.append(urdf_name)
                    urdf_positions.append(pos)
            if not urdf_names:
                return False
            resp = await self._client.post(f"{self._url}/joint_command", json={
                "name": urdf_names, "position": urdf_positions,
            })
            return resp.status_code == 200
        except Exception:
            return False

    async def close(self) -> None:
        await self._client.aclose()


class Ros2BridgeRuntime:
    def __init__(self, cfg: BridgeConfig) -> None:
        self.cfg = cfg
        self.enabled = False
        self.error = ""

        self._rclpy: Any = None
        self._node: Any = None
        self._twist_type: Any = None
        self._joint_state_type: Any = None
        self._motion_srv_type: Any = None
        self._cmd_pub: Any = None
        self._joint_pub: Any = None
        self._motion_client: Any = None
        self._gait_controller: GaitController | None = None
        self._control_task: asyncio.Task | None = None
        self._control_state = "STANDING"
        self._state_changed_time = time.time()
        self._move_timeout_active = False
        self._target_linear = 0.0
        self._target_angular = 0.0
        self._smoothed_linear = 0.0
        self._smoothed_angular = 0.0
        self._last_move_command_time = 0.0

        self._motion_available = False
        self._motion_error = ""

        self._rl_controller: Any = None
        self._isaac_feedback: IsaacSimFeedbackAdapter | None = None

        self._cmd_vel_publish_count = 0
        self._last_cmd_vel_linear = 0.0
        self._last_cmd_vel_angular = 0.0
        self._last_cmd_vel_time = 0.0

        self._joint_publish_count = 0
        self._last_joint_targets: dict[str, float] = {}
        self._last_joint_publish_time = 0.0

        try:
            import rclpy  # type: ignore

            self._rclpy = rclpy

            if not rclpy.ok():
                rclpy.init(args=None)
            self._node = rclpy.create_node(cfg.node_name)

            if cfg.control_mode == "joint_gait":
                from sensor_msgs.msg import JointState  # type: ignore

                self._joint_state_type = JointState
                self._joint_pub = self._node.create_publisher(JointState, cfg.joint_command_topic, 10)
                self._gait_controller = GaitController(
                    GaitConfig(
                        joint_names=cfg.gait_joint_names,
                    )
                )
            elif cfg.control_mode == "rl_policy":
                from .policy_config import PolicyConfig as _PC
                from .rl_policy_controller import RLPolicyController as _RLC
                policy_cfg = _PC.from_yaml(cfg.policy_config_path)
                policy_cfg.model_xml_path = cfg.policy_model_xml
                policy_cfg.model_bin_path = cfg.policy_model_bin
                policy_cfg.simulation = cfg.simulation

                if cfg.isaac_sim_url:
                    # HTTP feedback mode: no ROS2 topics needed for RL controller
                    self._rl_controller = _RLC(policy_cfg, None)
                    self._isaac_feedback = IsaacSimFeedbackAdapter(cfg.isaac_sim_url)
                    print(f"[RL] HTTP feedback mode: {cfg.isaac_sim_url}")
                else:
                    # ROS2 mode: subscribe to /leg/status, /arm/status, /imu/status
                    from sensor_msgs.msg import JointState  # type: ignore
                    self._joint_state_type = JointState
                    self._joint_pub = self._node.create_publisher(JointState, cfg.joint_command_topic, 10)
                    self._rl_controller = _RLC(policy_cfg, self._node)
            else:
                from geometry_msgs.msg import Twist  # type: ignore

                self._twist_type = Twist
                self._cmd_pub = self._node.create_publisher(Twist, cfg.cmd_vel_topic, 10)

            # hric_msgs is optional. Keep /move available even if /motion is unavailable.
            try:
                from hric_msgs.srv import SetMotionNumber  # type: ignore

                self._motion_srv_type = SetMotionNumber
                self._motion_client = self._node.create_client(SetMotionNumber, cfg.set_motion_service)
                self._motion_available = True
            except Exception as e:
                self._motion_available = False
                self._motion_error = str(e)

            self.enabled = True
        except Exception as e:
            # If rl_policy + HTTP mode, allow running without ROS2
            if cfg.control_mode == "rl_policy" and cfg.isaac_sim_url:
                self.error = ""
                try:
                    from .policy_config import PolicyConfig as _PC
                    from .rl_policy_controller import RLPolicyController as _RLC
                    policy_cfg = _PC.from_yaml(cfg.policy_config_path)
                    policy_cfg.model_xml_path = cfg.policy_model_xml
                    policy_cfg.model_bin_path = cfg.policy_model_bin
                    policy_cfg.simulation = cfg.simulation
                    self._rl_controller = _RLC(policy_cfg, None)
                    self._isaac_feedback = IsaacSimFeedbackAdapter(cfg.isaac_sim_url)
                    self.enabled = True
                    print(f"[RL] HTTP feedback mode (no ROS2): {cfg.isaac_sim_url}")
                    print(f"[RL] ROS2 unavailable: {e}")
                except Exception as e2:
                    self.error = str(e2)
            else:
                self.error = str(e)

    def move(self, linear: float, angular: float) -> tuple[bool, str]:
        if not self.enabled:
            return False, f"ros_disabled:{self.error}"

        if self.cfg.control_mode == "joint_gait":
            self._target_linear = float(linear)
            self._target_angular = float(angular)
            self._last_move_command_time = time.time()
            self._move_timeout_active = False
            return True, "ok"

        if self.cfg.control_mode == "rl_policy":
            self._target_linear = float(linear)
            self._target_angular = float(angular)
            self._last_move_command_time = time.time()
            self._move_timeout_active = False
            if self._rl_controller is not None:
                self._rl_controller.set_command(float(linear), float(angular))
            return True, "ok"

        try:
            msg = self._twist_type()
            msg.linear.x = float(linear)
            msg.angular.z = float(angular)
            self._cmd_pub.publish(msg)
            self._cmd_vel_publish_count += 1
            self._last_cmd_vel_linear = float(linear)
            self._last_cmd_vel_angular = float(angular)
            self._last_cmd_vel_time = time.time()
            self._rclpy.spin_once(self._node, timeout_sec=0.0)
            return True, "ok"
        except Exception as e:
            return False, str(e)

    def stop(self) -> tuple[bool, str]:
        if self.cfg.control_mode in ("joint_gait", "rl_policy"):
            self._target_linear = 0.0
            self._target_angular = 0.0
            self._last_move_command_time = time.time()
            self._move_timeout_active = False
            if self._rl_controller is not None:
                self._rl_controller.set_command(0.0, 0.0)
            return True, "ok"
        return self.move(0.0, 0.0)

    def motion(self, number: int, active: bool) -> tuple[bool, str]:
        if not self.enabled:
            return False, f"ros_disabled:{self.error}"
        if not self._motion_available or not self._motion_client or not self._motion_srv_type:
            reason = self._motion_error or "hric_msgs_missing"
            return False, f"set_motion_number_unavailable:{reason}"

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

    async def start(self) -> None:
        if not self.enabled:
            return
        if self.cfg.control_mode not in ("joint_gait", "rl_policy"):
            return
        if self._control_task is not None and not self._control_task.done():
            return
        self._control_task = asyncio.create_task(self._joint_control_loop(), name="joint-gait-loop")

    async def shutdown(self) -> None:
        t = self._control_task
        self._control_task = None
        if t is not None and not t.done():
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        if self._isaac_feedback is not None:
            await self._isaac_feedback.close()
        self.close()

    def close(self) -> None:
        if not self.enabled:
            return
        try:
            self._node.destroy_node()
        except Exception:
            pass

    def cmd_vel_subscription_count(self) -> int:
        if not self.enabled or self._cmd_pub is None:
            return 0
        try:
            return int(self._cmd_pub.get_subscription_count())
        except Exception:
            return 0

    def joint_subscription_count(self) -> int:
        if not self.enabled or self._joint_pub is None:
            return 0
        try:
            return int(self._joint_pub.get_subscription_count())
        except Exception:
            return 0

    def active_subscription_count(self) -> int:
        if self.cfg.control_mode in ("joint_gait", "rl_policy"):
            return self.joint_subscription_count()
        return self.cmd_vel_subscription_count()

    def cmd_vel_debug(self) -> dict[str, Any]:
        last_age_ms: int | None = None
        if self._last_cmd_vel_time > 0.0:
            last_age_ms = int((time.time() - self._last_cmd_vel_time) * 1000.0)
        return {
            "topic": self.cfg.cmd_vel_topic,
            "subscription_count": self.cmd_vel_subscription_count(),
            "publish_count": self._cmd_vel_publish_count,
            "last_linear": self._last_cmd_vel_linear,
            "last_angular": self._last_cmd_vel_angular,
            "last_age_ms": last_age_ms,
        }

    def joint_command_debug(self) -> dict[str, Any]:
        last_age_ms: int | None = None
        if self._last_joint_publish_time > 0.0:
            last_age_ms = int((time.time() - self._last_joint_publish_time) * 1000.0)
        return {
            "topic": self.cfg.joint_command_topic,
            "subscription_count": self.joint_subscription_count(),
            "publish_count": self._joint_publish_count,
            "state": self._control_state,
            "state_age_ms": int((time.time() - self._state_changed_time) * 1000.0),
            "move_timeout_active": self._move_timeout_active,
            "target_linear": self._target_linear,
            "target_angular": self._target_angular,
            "smoothed_linear": self._smoothed_linear,
            "smoothed_angular": self._smoothed_angular,
            "last_age_ms": last_age_ms,
            "last_targets": self._last_joint_targets,
        }

    async def _joint_control_loop(self) -> None:
        period = self.cfg.loop_period_s
        last_time = time.perf_counter()
        while True:
            tick_start = time.perf_counter()
            now = time.time()
            dt = max(1e-4, min(0.1, tick_start - last_time))
            last_time = tick_start

            self._apply_command_timeout(now)
            self._smooth_targets(dt)
            self._update_state_machine()

            # Fetch HTTP feedback before RL inference (if using HTTP mode)
            if self._isaac_feedback is not None and self._rl_controller is not None:
                await self._isaac_feedback.fetch_and_inject(self._rl_controller)

            await self._publish_joint_targets(dt)

            if self._rclpy is not None and self._node is not None:
                self._rclpy.spin_once(self._node, timeout_sec=0.0)

            elapsed = time.perf_counter() - tick_start
            sleep_s = period - elapsed
            if sleep_s > 0:
                await asyncio.sleep(sleep_s)
            else:
                await asyncio.sleep(0)

    def _apply_command_timeout(self, now: float) -> None:
        if self._last_move_command_time <= 0.0:
            return
        timeout_s = max(0.05, float(self.cfg.command_timeout_ms) / 1000.0)
        if (now - self._last_move_command_time) > timeout_s:
            self._target_linear = 0.0
            self._target_angular = 0.0
            self._move_timeout_active = True

    def _smooth_targets(self, dt: float) -> None:
        tau = max(0.01, float(self.cfg.stop_ramp_time_ms) / 1000.0)
        alpha = max(0.0, min(1.0, dt / tau))
        self._smoothed_linear += (self._target_linear - self._smoothed_linear) * alpha
        self._smoothed_angular += (self._target_angular - self._smoothed_angular) * alpha

    def _update_state_machine(self) -> None:
        if self.cfg.control_mode == "rl_policy":
            return  # FSM managed internally by RLPolicyController

        speed_metric = abs(self._smoothed_linear) + 0.2 * abs(self._smoothed_angular)
        if speed_metric > 0.03:
            next_state = "WALKING"
        elif speed_metric > 0.005:
            next_state = "STOPPING"
        else:
            next_state = "STANDING"

        if next_state != self._control_state:
            self._control_state = next_state
            self._state_changed_time = time.time()

    async def _publish_joint_targets(self, dt: float) -> None:
        if self.cfg.control_mode == "rl_policy":
            await self._publish_rl_policy_targets(dt)
            return

        if self._joint_pub is None or self._joint_state_type is None or self._gait_controller is None:
            return

        if self._control_state == "STANDING":
            targets = self._gait_controller.stand_pose()
        else:
            targets = self._gait_controller.update(
                linear_x=self._smoothed_linear,
                angular_z=self._smoothed_angular,
                dt=dt,
            )

        names = list(self._gait_controller.joint_names)
        positions = [float(targets.get(name, 0.0)) for name in names]

        msg = self._joint_state_type()
        if hasattr(msg, "header") and self._node is not None and hasattr(self._node, "get_clock"):
            try:
                msg.header.stamp = self._node.get_clock().now().to_msg()
            except Exception:
                pass
        msg.name = names
        msg.position = positions
        msg.velocity = []
        msg.effort = []

        self._joint_pub.publish(msg)
        self._joint_publish_count += 1
        self._last_joint_targets = dict(zip(names, positions, strict=False))
        self._last_joint_publish_time = time.time()

    async def _publish_rl_policy_targets(self, dt: float) -> None:
        if self._rl_controller is None:
            return

        targets = self._rl_controller.update(dt)
        self._last_joint_targets = targets
        self._last_joint_publish_time = time.time()
        self._joint_publish_count += 1

        # HTTP mode: send via HTTP to Isaac Sim
        if self._isaac_feedback is not None:
            await self._isaac_feedback.send_joint_command(targets)
            return

        # ROS2 mode: publish JointState
        if self._joint_pub is None or self._joint_state_type is None:
            return

        names = list(self._rl_controller.joint_names)
        positions = [float(targets.get(name, 0.0)) for name in names]

        msg = self._joint_state_type()
        if hasattr(msg, "header") and self._node is not None and hasattr(self._node, "get_clock"):
            try:
                msg.header.stamp = self._node.get_clock().now().to_msg()
            except Exception:
                pass
        msg.name = names
        msg.position = positions
        msg.velocity = []
        msg.effort = []

        self._joint_pub.publish(msg)
        self._joint_publish_count += 1
        self._last_joint_targets = dict(zip(names, positions, strict=False))
        self._last_joint_publish_time = time.time()

    def rl_fsm_state(self) -> str:
        if self._rl_controller is not None:
            try:
                from .fsm_states import FSMStateName
                return self._rl_controller._robot_fsm.current_state.name
            except Exception:
                return "unknown"
        return "N/A"


async def run_bridge(cfg: BridgeConfig) -> None:
    runtime = Ros2BridgeRuntime(cfg)
    await runtime.start()

    async def health(_: web.Request) -> web.Response:
        payload: dict[str, Any] = {
            "ok": True,
            "control_mode": cfg.control_mode,
            "ros_enabled": runtime.enabled,
            "ros_error": runtime.error,
            "cmd_vel_topic": cfg.cmd_vel_topic,
            "joint_command_topic": cfg.joint_command_topic,
            "cmd_vel_debug": runtime.cmd_vel_debug(),
            "joint_command_debug": runtime.joint_command_debug(),
            "set_motion_service": cfg.set_motion_service,
            "motion_available": runtime._motion_available,
            "motion_error": runtime._motion_error,
        }
        if cfg.control_mode == "rl_policy":
            payload["rl_fsm_state"] = runtime.rl_fsm_state()
            payload["simulation"] = cfg.simulation
        if runtime.enabled and runtime.active_subscription_count() == 0:
            warn_topic = cfg.joint_command_topic if cfg.control_mode in ("joint_gait", "rl_policy") else cfg.cmd_vel_topic
            payload["warning"] = f"no_subscribers:{warn_topic}"
        return web.json_response(payload)

    async def move(req: web.Request) -> web.Response:
        try:
            body = await req.json()
        except Exception as e:
            return web.json_response({"success": False, "detail": f"json_error:{e}"}, status=400)
        linear = float(body.get("linear_x", body.get("linear", 0.0)))
        angular = float(body.get("angular_z", body.get("angular", 0.0)))
        ok, detail = runtime.move(linear, angular)
        payload: dict[str, Any] = {
            "success": ok,
            "detail": detail,
            "control_mode": cfg.control_mode,
            "linear": linear,
            "angular": angular,
            "linear_x": linear,
            "angular_z": angular,
            "subscription_count": runtime.active_subscription_count(),
        }
        if runtime.enabled and payload["subscription_count"] == 0:
            warn_topic = cfg.joint_command_topic if cfg.control_mode in ("joint_gait", "rl_policy") else cfg.cmd_vel_topic
            payload["warning"] = f"no_subscribers:{warn_topic}"
        return web.json_response(payload)

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
        await runtime.shutdown()
        await runner.cleanup()


def _parse_joint_names(raw: str) -> tuple[str, ...]:
    names = tuple(x.strip() for x in str(raw).split(",") if x.strip())
    if len(names) != 6:
        raise ValueError("--joint-names must contain exactly 6 comma-separated joint names")
    return names


def parse_args() -> BridgeConfig:
    parser = argparse.ArgumentParser(description="SynEIAgent ROS Bridge")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--cmd-vel-topic", default="/cmd_vel")
    parser.add_argument("--joint-command-topic", default="/joint_command")
    parser.add_argument("--node-name", default="gateway_lite_bridge")
    parser.add_argument("--set-motion-service", default="/set_motion_number")
    parser.add_argument("--control-mode", choices=["cmd_vel", "joint_gait", "rl_policy"], default="cmd_vel")
    parser.add_argument("--control-hz", type=float, default=50.0)
    parser.add_argument("--command-timeout-ms", type=int, default=350)
    parser.add_argument("--stop-ramp-time-ms", type=int, default=260)
    parser.add_argument("--joint-names", default=",".join(DEFAULT_GAIT_JOINT_NAMES))
    # RL policy options
    parser.add_argument("--policy-model-xml", default="", help="Path to OpenVINO model .xml")
    parser.add_argument("--policy-model-bin", default="", help="Path to OpenVINO model .bin")
    parser.add_argument("--policy-config", default="", help="Path to tg22_config.yaml")
    parser.add_argument("--simulation", action="store_true", default=True, help="Simulation mode (skip SP transform)")
    parser.add_argument("--no-simulation", dest="simulation", action="store_false", help="Real robot mode")
    parser.add_argument("--sp-lib-path", default="", help="Path to libfuncSPTrans.so")
    parser.add_argument("--isaac-sim-url", default="", help="Isaac Sim HTTP URL for feedback (e.g. http://localhost:9200)")
    args = parser.parse_args()
    return BridgeConfig(
        host=args.host,
        port=args.port,
        cmd_vel_topic=args.cmd_vel_topic,
        joint_command_topic=args.joint_command_topic,
        node_name=args.node_name,
        set_motion_service=args.set_motion_service,
        control_mode=str(args.control_mode).strip().lower(),
        control_hz=max(1.0, float(args.control_hz)),
        command_timeout_ms=max(50, int(args.command_timeout_ms)),
        stop_ramp_time_ms=max(40, int(args.stop_ramp_time_ms)),
        gait_joint_names=_parse_joint_names(args.joint_names),
        policy_model_xml=args.policy_model_xml,
        policy_model_bin=args.policy_model_bin,
        policy_config_path=args.policy_config,
        simulation=args.simulation,
        sp_lib_path=args.sp_lib_path,
        isaac_sim_url=args.isaac_sim_url,
    )


def main() -> None:
    cfg = parse_args()
    asyncio.run(run_bridge(cfg))


if __name__ == "__main__":
    main()
