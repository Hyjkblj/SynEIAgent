from __future__ import annotations

import argparse
import asyncio
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

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
    control_mode: str = "cmd_vel"  # cmd_vel | joint_gait | rl_policy
    control_hz: float = 50.0
    command_timeout_ms: int = 350
    stop_ramp_time_ms: int = 260
    rl_transition_grace_ms: int = 2500
    gait_joint_names: tuple[str, ...] = DEFAULT_GAIT_JOINT_NAMES

    # RL policy config (only used when control_mode == "rl_policy")
    policy_model_xml: str = ""
    policy_model_bin: str = ""
    policy_config_path: str = ""
    simulation: bool = True
    sp_lib_path: str = ""
    isaac_sim_url: str = ""  # e.g. "http://localhost:9200" for HTTP feedback mode
    prefer_ros2_http_rl: bool = False

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
        "shoulder_yaw_l_joint": 14, "elbow_l_joint": 15, "elbow_pitch_l_joint": 15,
        "shoulder_pitch_r_joint": 16, "shoulder_roll_r_joint": 17,
        "shoulder_yaw_r_joint": 18, "elbow_r_joint": 19, "elbow_pitch_r_joint": 19,
    }

    def __init__(self, base_url: str) -> None:
        import httpx
        self._url = self._normalize_loopback_url(base_url)
        # Isaac Sim is expected to be local; bypass proxy/env routing for stability.
        self._client = httpx.AsyncClient(timeout=0.2, trust_env=False)
        self._supports_control_frame: bool | None = None
        self._supports_combined_feedback: bool | None = None
        self._last_positions = [0.0] * 20
        self._last_velocities = [0.0] * 20
        self._last_efforts = [0.0] * 20
        self._ok = False

    @staticmethod
    def _normalize_loopback_url(base_url: str) -> str:
        parsed = urlsplit(str(base_url).strip())
        host = (parsed.hostname or "").lower()
        if host == "localhost":
            netloc = "127.0.0.1"
            if parsed.port:
                netloc = f"{netloc}:{parsed.port}"
            if parsed.username or parsed.password:
                userinfo = parsed.username or ""
                if parsed.password:
                    userinfo += f":{parsed.password}"
                netloc = f"{userinfo}@{netloc}"
            return urlunsplit((parsed.scheme or "http", netloc, parsed.path.rstrip("/"), parsed.query, parsed.fragment)).rstrip("/")
        return str(base_url).rstrip("/")

    async def fetch_and_inject(self, controller: Any) -> bool:
        """Fetch feedback from Isaac Sim HTTP and inject into RLPolicyController."""
        try:
            js: dict[str, Any] | None = None
            imu: dict[str, Any] | None = None

            if self._supports_combined_feedback is not False:
                feedback_resp = await self._client.get(f"{self._url}/feedback")
                if feedback_resp.status_code == 200:
                    feedback = feedback_resp.json()
                    js = feedback.get("joint_states", {})
                    imu = feedback.get("imu", {})
                    self._supports_combined_feedback = True
                elif feedback_resp.status_code == 404:
                    self._supports_combined_feedback = False

            if js is None:
                js_resp = await self._client.get(f"{self._url}/joint_states")
                if js_resp.status_code == 200:
                    js = js_resp.json()
            if imu is None:
                imu_resp = await self._client.get(f"{self._url}/imu")
                if imu_resp.status_code == 200:
                    imu = imu_resp.json()

            self._inject_feedback_payload(controller, js, imu)

            self._ok = True
            return True
        except Exception:
            self._ok = False
            return False

    def _inject_feedback_payload(
        self,
        controller: Any,
        js: dict[str, Any] | None,
        imu: dict[str, Any] | None,
    ) -> None:
        if js is not None:
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

        if imu is not None:
            omega = imu.get("angular_velocity", [0, 0, 0])
            accel = imu.get("linear_acceleration", [0, 0, 9.81])
            euler = imu.get("policy_euler") or imu.get("euler", {})
            yaw = float(euler.get("yaw", 0.0))
            pitch = float(euler.get("pitch", 0.0))
            roll = float(euler.get("roll", 0.0))
            controller.set_imu_feedback(yaw, pitch, roll, tuple(omega), tuple(accel))

    @staticmethod
    def _body_targets_to_urdf_payload(joint_positions: dict[str, float]) -> dict[str, list[float] | list[str]] | None:
        from .sim_feedback_adapter import BODYIDMAP_TO_URDF

        urdf_names: list[str] = []
        urdf_positions: list[float] = []
        for name, pos in joint_positions.items():
            urdf_name = BODYIDMAP_TO_URDF.get(name)
            if urdf_name:
                urdf_names.append(urdf_name)
                urdf_positions.append(float(pos))
        if not urdf_names:
            return None
        return {"name": urdf_names, "position": urdf_positions}

    async def send_control_frame_and_fetch_feedback(
        self,
        joint_positions: dict[str, float],
        controller: Any,
    ) -> bool | None:
        """Send joint targets and fetch feedback in a single HTTP round-trip.

        Returns:
          True/False when the combined endpoint exists and the request succeeded/failed.
          None when the endpoint is unsupported and the caller should fall back.
        """
        if self._supports_control_frame is False:
            return None
        try:
            payload = self._body_targets_to_urdf_payload(joint_positions)
            if payload is None:
                return False
            resp = await self._client.post(f"{self._url}/control_frame", json=payload)
            if resp.status_code == 404:
                self._supports_control_frame = False
                return None
            if resp.status_code != 200:
                self._supports_control_frame = True
                self._ok = False
                return False
            data = resp.json()
            self._inject_feedback_payload(
                controller,
                data.get("joint_states", {}),
                data.get("imu", {}),
            )
            self._supports_control_frame = True
            self._ok = True
            return True
        except Exception:
            self._ok = False
            if self._supports_control_frame is True:
                return False
            return None

    def uses_separate_command_channel(self) -> bool:
        return self._supports_control_frame is not True

    async def send_joint_command(self, joint_positions: dict[str, float]) -> bool:
        """Send joint targets to Isaac Sim via HTTP POST /joint_command."""
        try:
            payload = self._body_targets_to_urdf_payload(joint_positions)
            if payload is None:
                return False
            resp = await self._client.post(f"{self._url}/joint_command", json=payload)
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
        self._feedback_task: asyncio.Task | None = None
        self._http_command_task: asyncio.Task | None = None
        self._control_state = "STANDING"
        self._state_changed_time = time.time()
        self._rl_state_changed_time = self._state_changed_time
        self._last_rl_fsm_state = "N/A"
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
        self._http_latest_targets: dict[str, float] = {}
        self._http_latest_target_time = 0.0
        self._http_feedback_attempt_count = 0
        self._http_feedback_success_count = 0
        self._http_feedback_last_time = 0.0
        self._http_feedback_last_success_time = 0.0
        self._http_command_attempt_count = 0
        self._http_command_success_count = 0
        self._http_command_last_time = 0.0
        self._http_last_command_ok: bool | None = None

        if self._should_bypass_ros2_for_http_rl():
            try:
                self._init_http_rl_runtime()
                self.enabled = True
            except Exception as e:
                self.error = str(e)
            return

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
                    self._init_http_rl_runtime()
                    self.enabled = True
                    print(f"[RL] HTTP feedback mode (no ROS2): {cfg.isaac_sim_url}")
                    print(f"[RL] ROS2 unavailable: {e}")
                except Exception as e2:
                    self.error = str(e2)
            else:
                self.error = str(e)

    def _should_bypass_ros2_for_http_rl(self) -> bool:
        return (
            self.cfg.control_mode == "rl_policy"
            and bool(self.cfg.isaac_sim_url)
            and not bool(self.cfg.prefer_ros2_http_rl)
        )

    def _init_http_rl_runtime(self) -> None:
        from .policy_config import PolicyConfig as _PC
        from .rl_policy_controller import RLPolicyController as _RLC

        policy_cfg = _PC.from_yaml(self.cfg.policy_config_path)
        policy_cfg.model_xml_path = self.cfg.policy_model_xml
        policy_cfg.model_bin_path = self.cfg.policy_model_bin
        policy_cfg.simulation = self.cfg.simulation
        self._rl_controller = _RLC(policy_cfg, None)
        self._isaac_feedback = IsaacSimFeedbackAdapter(self.cfg.isaac_sim_url)
        print(f"[RL] HTTP feedback mode (ROS2 bypass): {self.cfg.isaac_sim_url}")

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
                if abs(linear) > 1e-4 or abs(angular) > 1e-4:
                    self._rl_controller.request_gait_transition(
                        float(self.cfg.rl_transition_grace_ms) / 1000.0
                    )
                else:
                    self._rl_controller.clear_gait_transition_request()
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
                self._rl_controller.clear_gait_transition_request()
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
        if self.uses_http_feedback():
            self._feedback_task = asyncio.create_task(self._http_feedback_loop(), name="isaac-feedback-loop")
            self._http_command_task = asyncio.create_task(self._http_command_loop(), name="isaac-command-loop")
        self._control_task = asyncio.create_task(self._joint_control_loop(), name="joint-gait-loop")

    async def shutdown(self) -> None:
        tasks = [self._control_task, self._feedback_task, self._http_command_task]
        self._control_task = None
        self._feedback_task = None
        self._http_command_task = None
        for t in tasks:
            if t is None or t.done():
                continue
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

    def uses_http_feedback(self) -> bool:
        return self.cfg.control_mode == "rl_policy" and self._isaac_feedback is not None

    def _control_loop_period_s(self) -> float:
        period = self.cfg.loop_period_s
        if self.uses_http_feedback():
            # In local HTTP mode the transport tops out around 60-100 Hz.
            # Keeping the outer control loop near twice the 50 Hz policy
            # refresh avoids starving the async feedback/send workers.
            period = max(period, 0.01)
        return period

    def _http_transport_period_s(self) -> float:
        period = self.cfg.loop_period_s
        if self.uses_http_feedback():
            # Match the capped outer loop cadence so HTTP I/O stays aligned
            # with the transport budget instead of chasing the nominal 400 Hz.
            period = max(period, 0.01)
        return period

    @staticmethod
    def _age_ms(last_time: float) -> int | None:
        if last_time <= 0.0:
            return None
        return int((time.time() - last_time) * 1000.0)

    def _http_transport_debug(self) -> dict[str, Any] | None:
        if not self.uses_http_feedback():
            return None
        return {
            "feedback_attempt_count": self._http_feedback_attempt_count,
            "feedback_success_count": self._http_feedback_success_count,
            "feedback_last_age_ms": self._age_ms(self._http_feedback_last_time),
            "feedback_success_last_age_ms": self._age_ms(self._http_feedback_last_success_time),
            "command_attempt_count": self._http_command_attempt_count,
            "command_success_count": self._http_command_success_count,
            "command_last_age_ms": self._age_ms(self._http_command_last_time),
            "last_command_ok": self._http_last_command_ok,
            "latest_target_age_ms": self._age_ms(self._http_latest_target_time),
        }

    def _http_feedback_ready(self) -> bool:
        if not self.uses_http_feedback():
            return True
        if self._http_feedback_success_count <= 0:
            return False
        age_ms = self._age_ms(self._http_feedback_last_success_time)
        if age_ms is None:
            return False
        ready_window_ms = max(250, int(self.cfg.loop_period_s * 4000.0))
        return age_ms <= ready_window_ms

    def cmd_vel_debug(self) -> dict[str, Any]:
        return {
            "topic": self.cfg.cmd_vel_topic,
            "subscription_count": self.cmd_vel_subscription_count(),
            "publish_count": self._cmd_vel_publish_count,
            "last_linear": self._last_cmd_vel_linear,
            "last_angular": self._last_cmd_vel_angular,
            "last_age_ms": self._age_ms(self._last_cmd_vel_time),
        }

    def joint_command_debug(self) -> dict[str, Any]:
        if self.cfg.control_mode == "rl_policy":
            state = self.rl_fsm_state()
            if state != self._last_rl_fsm_state:
                self._last_rl_fsm_state = state
                self._rl_state_changed_time = time.time()
            state_age_ms = int((time.time() - self._rl_state_changed_time) * 1000.0)
        else:
            state = self._control_state
            state_age_ms = int((time.time() - self._state_changed_time) * 1000.0)
        debug = {
            "topic": self.cfg.joint_command_topic,
            "subscription_count": self.joint_subscription_count(),
            "publish_count": self._joint_publish_count,
            "state": state,
            "state_age_ms": state_age_ms,
            "move_timeout_active": self._move_timeout_active,
            "target_linear": self._target_linear,
            "target_angular": self._target_angular,
            "smoothed_linear": self._smoothed_linear,
            "smoothed_angular": self._smoothed_angular,
            "last_age_ms": self._age_ms(self._last_joint_publish_time),
            "last_targets": self._last_joint_targets,
        }
        http_transport_debug = self._http_transport_debug()
        if http_transport_debug is not None:
            debug["http_transport_debug"] = http_transport_debug
        return debug

    def rl_debug_snapshot(self) -> dict[str, Any] | None:
        if self.cfg.control_mode != "rl_policy" or self._rl_controller is None:
            return None
        return {
            "uses_http_feedback": self.uses_http_feedback(),
            "http_feedback_ready": self._http_feedback_ready(),
            "http_transport_debug": self._http_transport_debug(),
            "controller_debug": self._rl_controller.debug_snapshot(),
        }

    @staticmethod
    async def _sleep_to_period(period: float, tick_start: float) -> None:
        elapsed = time.perf_counter() - tick_start
        sleep_s = period - elapsed
        if sleep_s > 0:
            await asyncio.sleep(sleep_s)
        else:
            await asyncio.sleep(0)

    async def _joint_control_loop(self) -> None:
        period = self._control_loop_period_s()
        last_time = time.perf_counter()
        while True:
            tick_start = time.perf_counter()
            now = time.time()
            dt = max(1e-4, min(0.1, tick_start - last_time))
            last_time = tick_start

            self._apply_command_timeout(now)
            self._sync_rl_policy_command()
            self._smooth_targets(dt)
            self._update_state_machine()

            # Fallback for direct/in-test execution where the background task
            # has not been started yet.
            if (
                self._isaac_feedback is not None
                and self._rl_controller is not None
                and (self._feedback_task is None or self._feedback_task.done())
            ):
                await self._isaac_feedback.fetch_and_inject(self._rl_controller)

            await self._publish_joint_targets(dt)

            if self._rclpy is not None and self._node is not None:
                self._rclpy.spin_once(self._node, timeout_sec=0.0)

            await self._sleep_to_period(period, tick_start)

    async def _http_feedback_loop(self) -> None:
        period = self._http_transport_period_s()
        while True:
            tick_start = time.perf_counter()
            ok = False
            if self._isaac_feedback is not None and self._rl_controller is not None:
                transport_now = time.time()
                targets = dict(self._http_latest_targets) if self._http_latest_targets else None
                if targets:
                    combined_ok = await self._isaac_feedback.send_control_frame_and_fetch_feedback(
                        targets,
                        self._rl_controller,
                    )
                    if combined_ok is not None:
                        self._http_feedback_attempt_count += 1
                        self._http_feedback_last_time = transport_now
                        self._http_command_attempt_count += 1
                        self._http_command_last_time = transport_now
                        self._http_last_command_ok = combined_ok
                        if combined_ok:
                            self._http_feedback_success_count += 1
                            self._http_feedback_last_success_time = transport_now
                            self._http_command_success_count += 1
                        ok = combined_ok
                    else:
                        ok = await self._isaac_feedback.fetch_and_inject(self._rl_controller)
                        self._http_feedback_attempt_count += 1
                        self._http_feedback_last_time = time.time()
                        if ok:
                            self._http_feedback_success_count += 1
                            self._http_feedback_last_success_time = self._http_feedback_last_time
                else:
                    ok = await self._isaac_feedback.fetch_and_inject(self._rl_controller)
                    self._http_feedback_attempt_count += 1
                    self._http_feedback_last_time = time.time()
                    if ok:
                        self._http_feedback_success_count += 1
                        self._http_feedback_last_success_time = self._http_feedback_last_time
            await self._sleep_to_period(period, tick_start)

    async def _http_command_loop(self) -> None:
        period = self._http_transport_period_s()
        while True:
            tick_start = time.perf_counter()
            if (
                self._isaac_feedback is not None
                and self._http_latest_targets
                and self._isaac_feedback.uses_separate_command_channel()
            ):
                targets = dict(self._http_latest_targets)
                self._http_command_attempt_count += 1
                self._http_command_last_time = time.time()
                ok = await self._isaac_feedback.send_joint_command(targets)
                self._http_last_command_ok = ok
                if ok:
                    self._http_command_success_count += 1
            await self._sleep_to_period(period, tick_start)

    def _apply_command_timeout(self, now: float) -> None:
        if self._last_move_command_time <= 0.0:
            return
        timeout_s = max(0.05, float(self.cfg.command_timeout_ms) / 1000.0)
        if (now - self._last_move_command_time) > timeout_s:
            self._target_linear = 0.0
            self._target_angular = 0.0
            self._move_timeout_active = True

    def _sync_rl_policy_command(self) -> None:
        if self.cfg.control_mode != "rl_policy" or self._rl_controller is None:
            return
        self._rl_controller.set_command(self._target_linear, self._target_angular)

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

        if self._isaac_feedback is not None and not self._http_feedback_ready():
            self._rl_controller.force_stop_hold()
            targets = self._rl_controller.stand_pose()
        else:
            targets = self._rl_controller.update(dt)
        self._last_joint_targets = targets
        self._last_joint_publish_time = time.time()
        self._joint_publish_count += 1

        # HTTP mode: send via HTTP to Isaac Sim
        if self._isaac_feedback is not None:
            self._http_latest_targets = dict(targets)
            self._http_latest_target_time = time.time()
            if self._http_command_task is None or self._http_command_task.done():
                self._http_command_attempt_count += 1
                self._http_command_last_time = time.time()
                ok = await self._isaac_feedback.send_joint_command(targets)
                self._http_last_command_ok = ok
                if ok:
                    self._http_command_success_count += 1
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
        if runtime.enabled and runtime.active_subscription_count() == 0 and not runtime.uses_http_feedback():
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
        if runtime.enabled and payload["subscription_count"] == 0 and not runtime.uses_http_feedback():
            warn_topic = cfg.joint_command_topic if cfg.control_mode in ("joint_gait", "rl_policy") else cfg.cmd_vel_topic
            payload["warning"] = f"no_subscribers:{warn_topic}"
        return web.json_response(payload)

    async def motion(req: web.Request) -> web.Response:
        body = await req.json()
        number = int(body.get("number", 0))
        active = bool(body.get("active", True))
        ok, detail = runtime.motion(number, active)
        return web.json_response({"success": ok, "detail": detail, "number": number, "active": active})

    async def rl_debug(_: web.Request) -> web.Response:
        debug = runtime.rl_debug_snapshot()
        if debug is None:
            return web.json_response({"ok": False, "detail": "rl_debug_unavailable"}, status=404)
        payload: dict[str, Any] = {
            "ok": True,
            "control_mode": cfg.control_mode,
            "rl_fsm_state": runtime.rl_fsm_state(),
        }
        payload.update(debug)
        return web.json_response(payload)

    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_get("/debug/rl", rl_debug)
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
    parser.add_argument(
        "--rl-transition-grace-ms",
        type=int,
        default=2500,
        help="Keep the STOP->ZERO->MLP transition request alive for this long after a non-zero RL command",
    )
    parser.add_argument("--joint-names", default=",".join(DEFAULT_GAIT_JOINT_NAMES))
    # RL policy options
    parser.add_argument("--policy-model-xml", default="", help="Path to OpenVINO model .xml")
    parser.add_argument("--policy-model-bin", default="", help="Path to OpenVINO model .bin")
    parser.add_argument("--policy-config", default="", help="Path to tg22_config.yaml")
    parser.add_argument("--simulation", action="store_true", default=True, help="Simulation mode (skip SP transform)")
    parser.add_argument("--no-simulation", dest="simulation", action="store_false", help="Real robot mode")
    parser.add_argument("--sp-lib-path", default="", help="Path to libfuncSPTrans.so")
    parser.add_argument("--isaac-sim-url", default="", help="Isaac Sim HTTP URL for feedback (e.g. http://localhost:9200)")
    parser.add_argument(
        "--prefer-ros2-http-rl",
        action="store_true",
        help="When rl_policy uses Isaac HTTP transport, still initialize ROS2 instead of bypassing it",
    )
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
        rl_transition_grace_ms=max(0, int(args.rl_transition_grace_ms)),
        gait_joint_names=_parse_joint_names(args.joint_names),
        policy_model_xml=args.policy_model_xml,
        policy_model_bin=args.policy_model_bin,
        policy_config_path=args.policy_config,
        simulation=args.simulation,
        sp_lib_path=args.sp_lib_path,
        isaac_sim_url=args.isaac_sim_url,
        prefer_ros2_http_rl=bool(args.prefer_ros2_http_rl),
    )


def main() -> None:
    cfg = parse_args()
    asyncio.run(run_bridge(cfg))


if __name__ == "__main__":
    main()
