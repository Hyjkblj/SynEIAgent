"""
Isaac Sim ROS2 控制桥接节点

功能：
- 订阅 ROS2 /cmd_vel (geometry_msgs/Twist)
- 控制仿真机器人移动（支持差速底盘和人形机器人）
- 发布 /odom (nav_msgs/Odometry) 和 /joint_states (sensor_msgs/JointState)

运行方式：
  在 Isaac Sim 的 Python 环境中运行：
  <IsaacSim>/python.sh ros2_control_bridge.py --robot-prim /World/tienkung

依赖：
  - Isaac Sim 4.x/5.x
  - ROS2 Humble/Iron
  - geometry_msgs, nav_msgs, sensor_msgs
"""
from __future__ import annotations

import argparse
import asyncio
import math
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Sequence

import numpy as np

POLICY_GAIN_URDF_ORDER: tuple[str, ...] = (
    "hip_roll_l_joint",
    "hip_pitch_l_joint",
    "hip_yaw_l_joint",
    "knee_pitch_l_joint",
    "ankle_pitch_l_joint",
    "ankle_roll_l_joint",
    "hip_roll_r_joint",
    "hip_pitch_r_joint",
    "hip_yaw_r_joint",
    "knee_pitch_r_joint",
    "ankle_pitch_r_joint",
    "ankle_roll_r_joint",
    "shoulder_pitch_l_joint",
    "shoulder_roll_l_joint",
    "shoulder_yaw_l_joint",
    "elbow_l_joint",
    "shoulder_pitch_r_joint",
    "shoulder_roll_r_joint",
    "shoulder_yaw_r_joint",
    "elbow_r_joint",
)

JOINT_NAME_EQUIVALENT_GROUPS: tuple[tuple[str, ...], ...] = (
    ("elbow_l_joint", "elbow_pitch_l_joint"),
    ("elbow_r_joint", "elbow_pitch_r_joint"),
)


def _expand_joint_name_aliases(values_by_name: dict[str, float]) -> dict[str, float]:
    expanded = dict(values_by_name)
    for group in JOINT_NAME_EQUIVALENT_GROUPS:
        resolved_value: float | None = None
        for name in group:
            if name in expanded:
                resolved_value = float(expanded[name])
                break
        if resolved_value is None:
            continue
        for name in group:
            expanded.setdefault(name, resolved_value)
    return expanded


OFFICIAL_LITE_ACTUATOR_KP_BY_NAME: dict[str, float] = _expand_joint_name_aliases(
    {
        "hip_roll_l_joint": 700.0,
        "hip_pitch_l_joint": 700.0,
        "hip_yaw_l_joint": 500.0,
        "knee_pitch_l_joint": 700.0,
        "ankle_pitch_l_joint": 30.0,
        "ankle_roll_l_joint": 16.8,
        "hip_roll_r_joint": 700.0,
        "hip_pitch_r_joint": 700.0,
        "hip_yaw_r_joint": 500.0,
        "knee_pitch_r_joint": 700.0,
        "ankle_pitch_r_joint": 30.0,
        "ankle_roll_r_joint": 16.8,
        "shoulder_pitch_l_joint": 60.0,
        "shoulder_roll_l_joint": 20.0,
        "shoulder_yaw_l_joint": 10.0,
        "elbow_l_joint": 10.0,
        "shoulder_pitch_r_joint": 60.0,
        "shoulder_roll_r_joint": 20.0,
        "shoulder_yaw_r_joint": 10.0,
        "elbow_r_joint": 10.0,
    }
)

OFFICIAL_LITE_ACTUATOR_KD_BY_NAME: dict[str, float] = _expand_joint_name_aliases(
    {
        "hip_roll_l_joint": 10.0,
        "hip_pitch_l_joint": 10.0,
        "hip_yaw_l_joint": 5.0,
        "knee_pitch_l_joint": 10.0,
        "ankle_pitch_l_joint": 2.5,
        "ankle_roll_l_joint": 1.4,
        "hip_roll_r_joint": 10.0,
        "hip_pitch_r_joint": 10.0,
        "hip_yaw_r_joint": 5.0,
        "knee_pitch_r_joint": 10.0,
        "ankle_pitch_r_joint": 2.5,
        "ankle_roll_r_joint": 1.4,
        "shoulder_pitch_l_joint": 3.0,
        "shoulder_roll_l_joint": 1.5,
        "shoulder_yaw_l_joint": 1.0,
        "elbow_l_joint": 1.0,
        "shoulder_pitch_r_joint": 3.0,
        "shoulder_roll_r_joint": 1.5,
        "shoulder_yaw_r_joint": 1.0,
        "elbow_r_joint": 1.0,
    }
)

OFFICIAL_LITE_ACTUATOR_MAX_EFFORT_BY_NAME: dict[str, float] = _expand_joint_name_aliases(
    {
        "hip_roll_l_joint": 180.0,
        "hip_pitch_l_joint": 300.0,
        "hip_yaw_l_joint": 180.0,
        "knee_pitch_l_joint": 300.0,
        "ankle_pitch_l_joint": 60.0,
        "ankle_roll_l_joint": 30.0,
        "hip_roll_r_joint": 180.0,
        "hip_pitch_r_joint": 300.0,
        "hip_yaw_r_joint": 180.0,
        "knee_pitch_r_joint": 300.0,
        "ankle_pitch_r_joint": 60.0,
        "ankle_roll_r_joint": 30.0,
        "shoulder_pitch_l_joint": 52.5,
        "shoulder_roll_l_joint": 52.5,
        "shoulder_yaw_l_joint": 52.5,
        "elbow_l_joint": 52.5,
        "shoulder_pitch_r_joint": 52.5,
        "shoulder_roll_r_joint": 52.5,
        "shoulder_yaw_r_joint": 52.5,
        "elbow_r_joint": 52.5,
    }
)

OFFICIAL_LITE_ACTUATOR_MAX_VELOCITY_BY_NAME: dict[str, float] = _expand_joint_name_aliases(
    {
        "hip_roll_l_joint": 15.6,
        "hip_pitch_l_joint": 15.6,
        "hip_yaw_l_joint": 15.6,
        "knee_pitch_l_joint": 15.6,
        "ankle_pitch_l_joint": 12.8,
        "ankle_roll_l_joint": 7.8,
        "hip_roll_r_joint": 15.6,
        "hip_pitch_r_joint": 15.6,
        "hip_yaw_r_joint": 15.6,
        "knee_pitch_r_joint": 15.6,
        "ankle_pitch_r_joint": 12.8,
        "ankle_roll_r_joint": 7.8,
        "shoulder_pitch_l_joint": 14.1,
        "shoulder_roll_l_joint": 14.1,
        "shoulder_yaw_l_joint": 14.1,
        "elbow_l_joint": 14.1,
        "shoulder_pitch_r_joint": 14.1,
        "shoulder_roll_r_joint": 14.1,
        "shoulder_yaw_r_joint": 14.1,
        "elbow_r_joint": 14.1,
    }
)


DEFAULT_STAND_BODY_ORDER: tuple[float, ...] = (
    0.0, -0.5, 0.0, 1.0, -0.5, 0.0,
    0.0, -0.5, 0.0, 1.0, -0.5, 0.0,
    0.0, 0.1, 0.0, -0.3,
    0.0, -0.1, 0.0, -0.3,
)

DEFAULT_STAND_URDF_BY_NAME: dict[str, float] = _expand_joint_name_aliases(
    {
        name: float(DEFAULT_STAND_BODY_ORDER[i])
        for i, name in enumerate(POLICY_GAIN_URDF_ORDER)
    }
)

DEFAULT_BASE_POSITION = np.array([0.0, 0.0, 0.77255], dtype=np.float64)
IDENTITY_QUAT_WXYZ = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)
LEGACY_STARTUP_STAND_ORIENTATION_WXYZ = np.array(
    [0.6965205669403076, 0.11503928899765015, 0.6989028453826904, 0.11471724510192871],
    dtype=np.float64,
)
STARTUP_STAND_ORIENTATION_WXYZ = IDENTITY_QUAT_WXYZ.copy()
DEFAULT_STARTUP_POSE_HOLD_S = 0.75
DEFAULT_STARTUP_NOMINAL_HOLD_TOLERANCE_RAD = 0.08
ENV_STARTUP_BASE_POSITION = "ISAAC_STARTUP_BASE_POSITION"
ENV_STARTUP_ORIENTATION_WXYZ = "ISAAC_STARTUP_ORIENTATION_WXYZ"
ENV_USE_LEGACY_STARTUP_ORIENTATION = "ISAAC_USE_LEGACY_STARTUP_ORIENTATION"
ENV_STARTUP_POSE_HOLD_S = "ISAAC_STARTUP_POSE_HOLD_S"
ENV_STARTUP_NOMINAL_HOLD_TOLERANCE_RAD = "ISAAC_STARTUP_NOMINAL_HOLD_TOLERANCE_RAD"
ENV_JOINT_TARGET_SIGN_OVERRIDES = "ISAAC_JOINT_TARGET_SIGN_OVERRIDES"
ENV_JOINT_FEEDBACK_SIGN_OVERRIDES = "ISAAC_JOINT_FEEDBACK_SIGN_OVERRIDES"


def get_default_official_lite_usd_path() -> str:
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(
        repo_root,
        "third_party",
        "TienKung-Lab",
        "legged_lab",
        "assets",
        "tienkung2_lite",
        "usd",
        "tienkung2_lite.usd",
    )


def quat_wxyz_to_euler(quat: Sequence[float]) -> tuple[float, float, float]:
    """Convert Isaac Sim's scalar-first quaternion into yaw/pitch/roll."""
    if len(quat) != 4:
        return 0.0, 0.0, 0.0

    qw, qx, qy, qz = (float(v) for v in quat)
    sinr_cosp = 2.0 * (qw * qx + qy * qz)
    cosr_cosp = 1.0 - 2.0 * (qx * qx + qy * qy)
    roll = math.atan2(sinr_cosp, cosr_cosp)

    sinp = 2.0 * (qw * qy - qz * qx)
    pitch = math.asin(max(-1.0, min(1.0, sinp)))

    siny_cosp = 2.0 * (qw * qz + qx * qy)
    cosy_cosp = 1.0 - 2.0 * (qy * qy + qz * qz)
    yaw = math.atan2(siny_cosp, cosy_cosp)
    return yaw, pitch, roll


def quat_conjugate_wxyz(quat: Sequence[float]) -> np.ndarray:
    qw, qx, qy, qz = (float(v) for v in quat)
    return np.array([qw, -qx, -qy, -qz], dtype=np.float64)


def quat_multiply_wxyz(lhs: Sequence[float], rhs: Sequence[float]) -> np.ndarray:
    lw, lx, ly, lz = (float(v) for v in lhs)
    rw, rx, ry, rz = (float(v) for v in rhs)
    return np.array(
        [
            lw * rw - lx * rx - ly * ry - lz * rz,
            lw * rx + lx * rw + ly * rz - lz * ry,
            lw * ry - lx * rz + ly * rw + lz * rx,
            lw * rz + lx * ry - ly * rx + lz * rw,
        ],
        dtype=np.float64,
    )


def _normalize_quat_wxyz(quat: Sequence[float]) -> np.ndarray:
    arr = np.array([float(v) for v in quat], dtype=np.float64)
    norm = float(np.linalg.norm(arr))
    if norm <= 1e-9:
        return IDENTITY_QUAT_WXYZ.copy()
    return arr / norm


def quat_wxyz_to_matrix(quat: Sequence[float]) -> np.ndarray:
    qw, qx, qy, qz = _normalize_quat_wxyz(quat)
    return np.array(
        [
            [1.0 - 2.0 * (qy * qy + qz * qz), 2.0 * (qx * qy - qz * qw), 2.0 * (qx * qz + qy * qw)],
            [2.0 * (qx * qy + qz * qw), 1.0 - 2.0 * (qx * qx + qz * qz), 2.0 * (qy * qz - qx * qw)],
            [2.0 * (qx * qz - qy * qw), 2.0 * (qy * qz + qx * qw), 1.0 - 2.0 * (qx * qx + qy * qy)],
        ],
        dtype=np.float64,
    )


def world_vector_to_local(quat_wxyz: Sequence[float], vector_world: Sequence[float]) -> np.ndarray:
    rotation_world_from_body = quat_wxyz_to_matrix(quat_wxyz)
    return rotation_world_from_body.T @ np.array(vector_world, dtype=np.float64)


def relative_quat_wxyz(reference: Sequence[float], current: Sequence[float]) -> np.ndarray:
    return _normalize_quat_wxyz(quat_multiply_wxyz(quat_conjugate_wxyz(reference), current))


def _parse_env_float_vector(var_name: str, expected_len: int) -> tuple[np.ndarray | None, str]:
    raw = os.getenv(var_name, "").strip()
    if not raw:
        return None, ""

    normalized = raw.replace(";", ",").replace(" ", ",")
    parts = [part for part in normalized.split(",") if part]
    if len(parts) != expected_len:
        return None, f"{var_name} expected {expected_len} floats, got {len(parts)}"

    try:
        values = np.array([float(part) for part in parts], dtype=np.float64)
    except ValueError as exc:
        return None, f"{var_name} parse error: {exc}"
    return values, ""


def _parse_env_float(var_name: str) -> tuple[float | None, str]:
    raw = os.getenv(var_name, "").strip()
    if not raw:
        return None, ""
    try:
        return float(raw), ""
    except ValueError as exc:
        return None, f"{var_name} parse error: {exc}"


def resolve_startup_pose_config() -> tuple[np.ndarray, np.ndarray, dict[str, str], list[str]]:
    position = DEFAULT_BASE_POSITION.copy()
    orientation = STARTUP_STAND_ORIENTATION_WXYZ.copy()
    meta = {
        "position_source": "default",
        "orientation_source": "default_identity_grounded",
    }
    warnings: list[str] = []

    position_override, position_error = _parse_env_float_vector(ENV_STARTUP_BASE_POSITION, 3)
    if position_override is not None:
        position = position_override
        meta["position_source"] = f"env:{ENV_STARTUP_BASE_POSITION}"
    elif position_error:
        warnings.append(position_error)

    orientation_override, orientation_error = _parse_env_float_vector(ENV_STARTUP_ORIENTATION_WXYZ, 4)
    if orientation_override is not None:
        orientation = _normalize_quat_wxyz(orientation_override)
        meta["orientation_source"] = f"env:{ENV_STARTUP_ORIENTATION_WXYZ}"
    elif orientation_error:
        warnings.append(orientation_error)
    elif os.getenv(ENV_USE_LEGACY_STARTUP_ORIENTATION, "").strip().lower() in {"1", "true", "yes", "on"}:
        orientation = LEGACY_STARTUP_STAND_ORIENTATION_WXYZ.copy()
        meta["orientation_source"] = f"env:{ENV_USE_LEGACY_STARTUP_ORIENTATION}"

    return position, orientation, meta, warnings


def resolve_startup_pose_hold_config() -> tuple[float, str]:
    hold_override, hold_error = _parse_env_float(ENV_STARTUP_POSE_HOLD_S)
    if hold_override is not None:
        return max(0.0, float(hold_override)), f"env:{ENV_STARTUP_POSE_HOLD_S}"
    if hold_error:
        print(f"[Control] {hold_error}")
    return DEFAULT_STARTUP_POSE_HOLD_S, "default"


def resolve_startup_nominal_hold_tolerance_config(config_override: float | None = None) -> tuple[float, str]:
    tolerance_override, tolerance_error = _parse_env_float(ENV_STARTUP_NOMINAL_HOLD_TOLERANCE_RAD)
    if tolerance_override is not None:
        return max(0.0, float(tolerance_override)), f"env:{ENV_STARTUP_NOMINAL_HOLD_TOLERANCE_RAD}"
    if tolerance_error:
        print(f"[Control] {tolerance_error}")
    if config_override is not None:
        return max(0.0, float(config_override)), "config"
    return DEFAULT_STARTUP_NOMINAL_HOLD_TOLERANCE_RAD, "default"


def _normalize_joint_sign_value(raw_value: Any) -> float:
    value = float(raw_value)
    if abs(value) <= 1.0e-9:
        raise ValueError("joint sign override cannot be zero")
    return -1.0 if value < 0.0 else 1.0


def parse_joint_sign_overrides(raw: Any) -> dict[str, float]:
    if raw is None:
        return {}

    if isinstance(raw, dict):
        normalized = {
            str(name).strip(): _normalize_joint_sign_value(value)
            for name, value in raw.items()
            if str(name).strip()
        }
        return _expand_joint_name_aliases(normalized)

    text = str(raw).strip()
    if not text:
        return {}

    overrides: dict[str, float] = {}
    for token in text.replace(";", ",").split(","):
        entry = token.strip()
        if not entry:
            continue
        if "=" in entry:
            name, value_text = entry.split("=", 1)
        elif ":" in entry:
            name, value_text = entry.split(":", 1)
        else:
            raise ValueError(
                "joint sign overrides must look like "
                "'ankle_pitch_l_joint=-1,ankle_pitch_r_joint=-1'"
            )
        joint_name = str(name).strip()
        if not joint_name:
            raise ValueError("joint sign override is missing a joint name")
        overrides[joint_name] = _normalize_joint_sign_value(value_text.strip())
    return _expand_joint_name_aliases(overrides)


def _to_float_list(values: Sequence[float] | np.ndarray) -> list[float]:
    raw_values = values.tolist() if hasattr(values, "tolist") else values
    return [float(v) for v in raw_values]


def _safe_set_usd_attr(api: Any, method_name: str, value: Any) -> bool:
    creator = getattr(api, method_name, None)
    if creator is None:
        return False
    try:
        attr = creator()
        if attr is None:
            return False
        attr.Set(value)
        return True
    except Exception:
        return False


def _safe_apply_schema(schema_cls: Any, prim: Any) -> Any:
    if prim is None:
        return None
    try:
        if hasattr(prim, "IsValid") and not prim.IsValid():
            return None
    except Exception:
        return None

    can_apply = getattr(schema_cls, "CanApply", None)
    apply_fn = getattr(schema_cls, "Apply", None)
    if callable(can_apply) and callable(apply_fn):
        try:
            if can_apply(prim):
                return apply_fn(prim)
        except Exception:
            pass
    if callable(apply_fn):
        try:
            return apply_fn(prim)
        except Exception:
            pass
    try:
        return schema_cls(prim)
    except Exception:
        return None


def _resolve_stage_from_world(world: Any) -> Any:
    if world is None:
        return None
    for attr_name in ("stage", "_stage"):
        stage = getattr(world, attr_name, None)
        if stage is not None:
            return stage
    scene = getattr(world, "scene", None)
    if scene is not None:
        for attr_name in ("stage", "_stage"):
            stage = getattr(scene, attr_name, None)
            if stage is not None:
                return stage
    return None


def _resolve_articulation_root_prim_path(prim_path: str) -> str:
    if not prim_path:
        return prim_path
    try:
        from isaacsim.core.utils.prims import get_articulation_root_api_prim_path

        resolved = get_articulation_root_api_prim_path(str(prim_path))
        return str(resolved or prim_path)
    except Exception:
        return str(prim_path)


def _get_articulation_view(articulation: Any) -> Any:
    if articulation is None:
        return None
    return getattr(articulation, "_articulation_view", None)


def _is_articulation_handle_valid(articulation: Any) -> bool:
    view = _get_articulation_view(articulation)
    if view is None:
        initializer = getattr(articulation, "initialize", None)
        return not callable(initializer)
    checker = getattr(view, "is_physics_handle_valid", None)
    if not callable(checker):
        return True
    try:
        valid = checker()
    except Exception:
        return False
    return valid is not None and bool(valid)


def _warm_up_articulation_handle(
    articulation: Any,
    world: Any,
    *,
    render: bool,
    max_attempts: int = 60,
) -> tuple[bool, str]:
    if articulation is None:
        return False, "articulation_unavailable"
    if _is_articulation_handle_valid(articulation):
        return True, ""

    last_error = ""
    for _ in range(max_attempts):
        try:
            if hasattr(articulation, "initialize"):
                articulation.initialize()
        except Exception as exc:
            last_error = f"initialize_failed:{exc}"

        if _is_articulation_handle_valid(articulation):
            return True, ""

        if world is not None and hasattr(world, "step"):
            try:
                world.step(render=render)
            except Exception as exc:
                if not last_error:
                    last_error = f"world_step_failed:{exc}"

        if _is_articulation_handle_valid(articulation):
            return True, ""
        time.sleep(0.01)

    return False, last_error or "physics_handle_invalid"


def _reference_usd_robot(stage: Any, usd_path: str, prim_path: str) -> tuple[bool, str]:
    if stage is None:
        return False, "stage_unavailable"
    if not usd_path or not os.path.isfile(usd_path):
        return False, f"USD not found: {usd_path}"

    try:
        from pxr import UsdGeom

        normalized_usd_path = os.path.abspath(usd_path).replace("\\", "/")
        prim = UsdGeom.Xform.Define(stage, str(prim_path)).GetPrim()
        refs = prim.GetReferences()
        if hasattr(refs, "ClearReferences"):
            refs.ClearReferences()
        refs.AddReference(normalized_usd_path)
        return True, str(prim_path)
    except Exception as e:
        return False, str(e)


@dataclass
class RobotControlConfig:
    """机器人控制配置"""
    robot_prim_path: str = "/World/robot"
    cmd_vel_topic: str = "/cmd_vel"
    joint_command_topic: str = "/joint_command"
    odom_topic: str = "/odom"
    joint_states_topic: str = "/joint_states"
    odom_frame: str = "odom"
    base_frame: str = "base_link"
    
    # 运动学参数
    max_linear_velocity: float = 1.0  # m/s
    max_angular_velocity: float = 1.5  # rad/s
    wheel_base: float = 0.4  # 轮距（差速底盘）
    
    # 发布频率
    odom_publish_hz: float = 50.0
    joint_states_publish_hz: float = 50.0
    
    # 速度衰减（模拟）
    linear_decay: float = 0.95
    angular_decay: float = 0.95
    joint_command_timeout_s: float = 0.4
    joint_stiffness: float = 180.0
    joint_damping: float = 8.0
    ground_static_friction: float = 1.2
    ground_dynamic_friction: float = 1.0
    ground_restitution: float = 0.0
    articulation_solver_position_iterations: int = 16
    articulation_solver_velocity_iterations: int = 4
    # 逐关节 PD 增益（来自 tg22_config.yaml），优先级高于 joint_stiffness/damping
    joint_kp: Optional[list[float]] = None
    joint_kd: Optional[list[float]] = None
    actuator_gain_profile: str = ""
    actuator_limit_profile: str = ""
    joint_target_sign_overrides: Optional[dict[str, float]] = None
    joint_feedback_sign_overrides: Optional[dict[str, float]] = None
    startup_nominal_hold_tolerance_rad: Optional[float] = None


class IsaacSimRobotController:
    """
    Isaac Sim 机器人控制器
    
    支持两种模式：
    1. 差速底盘模式：直接控制 base 的线速度和角速度
    2. 人形机器人模式：通过关节控制实现行走
    """
    
    def __init__(self, config: RobotControlConfig):
        self.config = config
        self.enabled = False
        self.error = ""
        
        # ROS2 相关
        self._rclpy: Any = None
        self._node: Any = None
        self._cmd_vel_sub: Any = None
        self._joint_command_sub: Any = None
        self._odom_pub: Any = None
        self._joint_states_pub: Any = None
        self._twist_type: Any = None
        self._odom_type: Any = None
        self._joint_state_type: Any = None
        
        # Isaac Sim 相关
        self._world: Any = None
        self._robot: Any = None
        self._articulation: Any = None
        
        # 状态
        self._current_linear: float = 0.0
        self._current_angular: float = 0.0
        self._target_linear: float = 0.0
        self._target_angular: float = 0.0
        self._last_cmd_time: float = 0.0
        self._cmd_timeout: float = 0.5  # 秒
        
        # 里程计
        self._odom_x: float = 0.0
        self._odom_y: float = 0.0
        self._odom_theta: float = 0.0
        self._last_odom_time: float = 0.0
        
        # 关节状态
        self._joint_names: list[str] = []
        self._joint_name_to_index: dict[str, int] = {}
        self._joint_positions: dict[str, float] = {}
        self._joint_velocities: dict[str, float] = {}
        self._joint_positions_raw: dict[str, float] = {}
        self._joint_velocities_raw: dict[str, float] = {}
        self._target_joint_positions: dict[str, float] = {}
        self._last_joint_cmd_time: float = 0.0
        self._cached_joint_pos: np.ndarray = np.zeros(0, dtype=np.float64)
        self._cached_joint_vel: np.ndarray = np.zeros(0, dtype=np.float64)
        self._last_target_array_logical: list[float] = []
        self._last_target_array_physical: list[float] = []
        self._last_target_positions_logical: dict[str, float] = {}
        self._last_target_positions_physical: dict[str, float] = {}
        self._last_joint_target_apply_method: str = "not_applied"
        self._last_joint_target_apply_error: str = ""
        self._applied_joint_kp: dict[str, float] = {}
        self._applied_joint_kd: dict[str, float] = {}
        self._applied_joint_max_effort: dict[str, float] = {}
        self._applied_joint_max_velocity: dict[str, float] = {}
        self._gain_profile_name: str = "not_configured"
        self._gain_apply_method: str = "not_configured"
        self._gain_apply_error: str = ""
        self._limit_profile_name: str = "not_configured"
        self._limit_apply_method: str = "not_configured"
        self._limit_apply_error: str = ""
        self._configured_robot_prim_path: str = str(config.robot_prim_path)
        self._articulation_prim_path: str = str(config.robot_prim_path)
        self._articulation_setup_complete: bool = False
        self._articulation_setup_error: str = ""
        self._last_articulation_not_ready_log_s: float = 0.0
        self._joint_target_sign_overrides = parse_joint_sign_overrides(
            self.config.joint_target_sign_overrides
        )
        self._joint_feedback_sign_overrides = parse_joint_sign_overrides(
            self.config.joint_feedback_sign_overrides
        )

        # IMU 状态缓存（从物理引擎实时读取）
        self._imu_quat: list[float] = [1.0, 0.0, 0.0, 0.0]  # Isaac Sim returns [w, x, y, z]
        self._imu_omega: list[float] = [0.0, 0.0, 0.0]  # rad/s
        self._imu_accel: list[float] = [0.0, 0.0, 9.81]  # m/s^2
        self._prev_linear_vel: np.ndarray = np.zeros(3)
        self._quaternion_order: str = "wxyz"
        self._startup_pose_primed: bool = False
        self._startup_pose_error: str = ""
        self._startup_pose_info: dict[str, Any] = {}
        self._startup_base_position, self._startup_orientation_wxyz, pose_meta, pose_warnings = (
            resolve_startup_pose_config()
        )
        self._startup_pose_hold_duration_s, self._startup_pose_hold_source = (
            resolve_startup_pose_hold_config()
        )
        self._startup_nominal_hold_tolerance_rad, self._startup_nominal_hold_tolerance_source = (
            resolve_startup_nominal_hold_tolerance_config(self.config.startup_nominal_hold_tolerance_rad)
        )
        self._startup_hold_deadline: float = 0.0
        self._startup_hold_active: bool = False
        self._startup_joint_positions = np.zeros(0, dtype=np.float64)
        self._startup_joint_velocities = np.zeros(0, dtype=np.float64)
        self._cached_world_position: np.ndarray = self._startup_base_position.copy()
        self._cached_world_orientation: np.ndarray = self._startup_orientation_wxyz.copy()
        self._cached_linear_velocity: np.ndarray = np.zeros(3, dtype=np.float64)
        self._cached_angular_velocity: np.ndarray = np.zeros(3, dtype=np.float64)
        self._imu_quat = [float(v) for v in self._startup_orientation_wxyz.tolist()]
        self._startup_pose_info = {
            "position": [float(v) for v in self._startup_base_position.tolist()],
            "orientation": [float(v) for v in self._startup_orientation_wxyz.tolist()],
            "orientation_order": self._quaternion_order,
            "hold_duration_s": float(self._startup_pose_hold_duration_s),
            "hold_source": self._startup_pose_hold_source,
            "nominal_hold_tolerance_rad": float(self._startup_nominal_hold_tolerance_rad),
            "nominal_hold_tolerance_source": self._startup_nominal_hold_tolerance_source,
            **pose_meta,
        }
        self._startup_pose_config_warnings = pose_warnings
        self._physics_config_info: dict[str, Any] = {}
        self._physics_config_warnings: list[str] = []

        self._init_ros2()
        # Always start HTTP server for external access (main.py feedback polling)
        if not hasattr(self, '_http_thread') or self._http_thread is None:
            self._start_http_server()

    def _start_http_server(self, port: int = 9200) -> None:
        """Start HTTP server providing health, feedback, and joint-debug endpoints."""
        import threading
        import json
        from http.server import BaseHTTPRequestHandler, HTTPServer
        try:
            from http.server import ThreadingHTTPServer as _ThreadingHTTPServer
        except ImportError:
            _ThreadingHTTPServer = HTTPServer

        controller = self

        class ControlHandler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                pass

            def _json_response(self, code: int, data: dict) -> None:
                try:
                    self.send_response(code)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(json.dumps(data).encode())
                except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, OSError):
                    pass  # 客户端已断开，忽略

            def do_GET(self):
                if self.path == "/health":
                    pose = controller.get_pose_payload()
                    self._json_response(200, {
                        "ok": True,
                        "ros_enabled": controller.enabled,
                        "error": controller.error,
                        "joints": len(controller._joint_names),
                        "configured_robot_prim_path": controller._configured_robot_prim_path,
                        "articulation_prim_path": controller._articulation_prim_path,
                        "quaternion_order": controller._quaternion_order,
                        "gain_profile": controller._gain_profile_name,
                        "gain_apply_method": controller._gain_apply_method,
                        "gain_apply_error": controller._gain_apply_error,
                        "applied_joint_kp": controller._applied_joint_kp,
                        "applied_joint_kd": controller._applied_joint_kd,
                        "limit_profile": controller._limit_profile_name,
                        "limit_apply_method": controller._limit_apply_method,
                        "limit_apply_error": controller._limit_apply_error,
                        "applied_joint_max_effort": controller._applied_joint_max_effort,
                        "applied_joint_max_velocity": controller._applied_joint_max_velocity,
                        "joint_target_sign_overrides": controller._joint_target_sign_overrides,
                        "joint_feedback_sign_overrides": controller._joint_feedback_sign_overrides,
                        "startup_pose_primed": controller._startup_pose_primed,
                        "startup_pose_hold_active": controller._startup_hold_active,
                        "startup_pose_error": controller._startup_pose_error,
                        "startup_pose_config_warnings": controller._startup_pose_config_warnings,
                        "startup_pose_info": controller._startup_pose_info,
                        "physics_config_info": controller._physics_config_info,
                        "physics_config_warnings": controller._physics_config_warnings,
                        "stand_error": controller.get_stand_error_payload(),
                        "pose": pose,
                    })
                elif self.path == "/pose":
                    self._json_response(200, controller.get_pose_payload())
                elif self.path == "/joint_states":
                    names = list(controller._joint_names)
                    # 使用缓存数据，避免物理步进期间调用 get_joint_positions()
                    positions = [controller._joint_positions.get(n, 0.0) for n in names]
                    velocities = [controller._joint_velocities.get(n, 0.0) for n in names]
                    self._json_response(200, {
                        "name": names,
                        "position": positions,
                        "velocity": velocities,
                    })
                elif self.path == "/feedback":
                    names = list(controller._joint_names)
                    positions = [controller._joint_positions.get(n, 0.0) for n in names]
                    velocities = [controller._joint_velocities.get(n, 0.0) for n in names]
                    yaw, pitch, roll = quat_wxyz_to_euler(controller._imu_quat)
                    policy_quat = controller.get_policy_orientation_quat()
                    policy_yaw, policy_pitch, policy_roll = quat_wxyz_to_euler(policy_quat.tolist())
                    self._json_response(200, {
                        "joint_states": {
                            "name": names,
                            "position": positions,
                            "velocity": velocities,
                        },
                        "imu": {
                            "orientation": controller._imu_quat,
                            "orientation_order": controller._quaternion_order,
                            "euler": {"yaw": yaw, "pitch": pitch, "roll": roll},
                            "policy_orientation": [float(v) for v in policy_quat.tolist()],
                            "policy_euler": {
                                "yaw": policy_yaw,
                                "pitch": policy_pitch,
                                "roll": policy_roll,
                            },
                            "angular_velocity": controller._imu_omega,
                            "linear_acceleration": controller._imu_accel,
                        },
                    })
                elif self.path == "/imu":
                    yaw, pitch, roll = quat_wxyz_to_euler(controller._imu_quat)
                    policy_quat = controller.get_policy_orientation_quat()
                    policy_yaw, policy_pitch, policy_roll = quat_wxyz_to_euler(policy_quat.tolist())
                    self._json_response(200, {
                        "orientation": controller._imu_quat,
                        "orientation_order": controller._quaternion_order,
                        "euler": {"yaw": yaw, "pitch": pitch, "roll": roll},
                        "policy_orientation": [float(v) for v in policy_quat.tolist()],
                        "policy_euler": {
                            "yaw": policy_yaw,
                            "pitch": policy_pitch,
                            "roll": policy_roll,
                        },
                        "angular_velocity": controller._imu_omega,
                        "linear_acceleration": controller._imu_accel,
                    })
                elif self.path == "/debug/joints":
                    self._json_response(200, controller.get_joint_debug_payload())
                else:
                    self._json_response(404, {"error": "not found"})

            def do_POST(self):
                if self.path == "/move":
                    try:
                        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                        linear = float(body.get("linear", 0.0))
                        angular = float(body.get("angular", 0.0))
                        controller._target_linear = float(np.clip(linear,
                            -controller.config.max_linear_velocity, controller.config.max_linear_velocity))
                        controller._target_angular = float(np.clip(angular,
                            -controller.config.max_angular_velocity, controller.config.max_angular_velocity))
                        controller._last_cmd_time = time.time()
                        self._json_response(200, {"success": True, "linear": controller._target_linear, "angular": controller._target_angular})
                    except Exception as ex:
                        self._json_response(400, {"success": False, "error": str(ex)})
                elif self.path == "/joint_command":
                    try:
                        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                        ok, payload = controller.apply_joint_command_payload(body)
                        self._json_response(200 if ok else 400, payload)
                    except Exception as ex:
                        self._json_response(400, {"success": False, "error": str(ex)})
                elif self.path == "/control_frame":
                    try:
                        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                        ok, payload = controller.apply_joint_command_payload(body)
                        if not ok:
                            self._json_response(400, payload)
                        else:
                            self._json_response(200, controller.get_feedback_payload())
                    except Exception as ex:
                        self._json_response(400, {"success": False, "error": str(ex)})
                elif self.path == "/reset_pose":
                    ok, payload = controller.reset_to_standing_pose()
                    self._json_response(200 if ok else 503, payload)
                elif self.path == "/stop":
                    controller.stop()
                    self._json_response(200, {"success": True})
                else:
                    self._json_response(404, {"error": "not found"})

        def run_server():
            server = _ThreadingHTTPServer(("0.0.0.0", port), ControlHandler)
            server.serve_forever()

        self._http_thread = threading.Thread(target=run_server, daemon=True)
        self._http_thread.start()
        print(
            f"[HTTP] API ready on http://0.0.0.0:{port} "
            "(/health /pose /feedback /control_frame /joint_states /imu "
            "/debug/joints /joint_command /move /reset_pose /stop)"
        )

    def _init_ros2(self) -> None:
        """初始化 ROS2 节点和话题"""
        try:
            import rclpy
            from rclpy.node import Node
            from geometry_msgs.msg import Twist
            from nav_msgs.msg import Odometry
            from sensor_msgs.msg import JointState
            
            self._rclpy = rclpy
            self._twist_type = Twist
            self._odom_type = Odometry
            self._joint_state_type = JointState
            
            if not rclpy.ok():
                rclpy.init(args=None)
            
            self._node = rclpy.create_node("isaac_sim_control_bridge")
            
            # 订阅 /cmd_vel
            self._cmd_vel_sub = self._node.create_subscription(
                Twist,
                self.config.cmd_vel_topic,
                self._cmd_vel_callback,
                10
            )

            self._joint_command_sub = self._node.create_subscription(
                JointState,
                self.config.joint_command_topic,
                self._joint_command_callback,
                10
            )
            
            # 发布 /odom
            self._odom_pub = self._node.create_publisher(
                Odometry,
                self.config.odom_topic,
                10
            )
            
            # 发布 /joint_states
            self._joint_states_pub = self._node.create_publisher(
                JointState,
                self.config.joint_states_topic,
                10
            )
            
            self.enabled = True
            print(f"[ROS2] Control bridge initialized")
            print(f"[ROS2] Subscribed to: {self.config.cmd_vel_topic}, {self.config.joint_command_topic}")
            print(f"[ROS2] Publishing: {self.config.odom_topic}, {self.config.joint_states_topic}")
            
        except Exception as e:
            self.error = str(e)
            print(f"[ROS2] Initialization failed: {e}")
            print(f"[HTTP] Using HTTP control interface (already running)")
            self.enabled = True
    
    def _init_http_fallback(self) -> None:
        """初始化 HTTP 回退接口（当 ROS2 不可用时）"""
        import threading
        import json
        from http.server import BaseHTTPRequestHandler, HTTPServer
        try:
            from http.server import ThreadingHTTPServer as _ThreadingHTTPServer
        except ImportError:
            _ThreadingHTTPServer = HTTPServer
        
        controller = self  # 闭包捕获
        
        class ControlHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass  # 静默日志
            
            def do_GET(self):
                if self.path == "/health":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "ok": True,
                        "mode": "http_fallback",
                        "ros_enabled": False,
                        "error": controller.error
                    }).encode())
                else:
                    self.send_response(404)
                    self.end_headers()
            
            def do_POST(self):
                if self.path == "/move":
                    content_length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(content_length)
                    try:
                        data = json.loads(body)
                        linear = float(data.get("linear", 0.0))
                        angular = float(data.get("angular", 0.0))
                        
                        # 直接设置目标速度
                        controller._target_linear = float(np.clip(
                            linear,
                            -controller.config.max_linear_velocity,
                            controller.config.max_linear_velocity
                        ))
                        controller._target_angular = float(np.clip(
                            angular,
                            -controller.config.max_angular_velocity,
                            controller.config.max_angular_velocity
                        ))
                        controller._last_cmd_time = time.time()
                        
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps({
                            "success": True,
                            "linear": controller._target_linear,
                            "angular": controller._target_angular
                        }).encode())
                    except Exception as ex:
                        self.send_response(400)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps({
                            "success": False,
                            "error": str(ex)
                        }).encode())
                else:
                    self.send_response(404)
                    self.end_headers()
        
        def run_server():
            server = _ThreadingHTTPServer(("0.0.0.0", 9200), ControlHandler)
            server.serve_forever()
        
        self._http_thread = threading.Thread(target=run_server, daemon=True)
        self._http_thread.start()
        self.enabled = True  # 启用控制器
        print(f"[HTTP] Control interface ready on http://0.0.0.0:9200/move")

    def _cmd_vel_callback(self, msg: Any) -> None:
        """Handle /cmd_vel velocity command."""
        self._target_linear = float(msg.linear.x)
        self._target_angular = float(msg.angular.z)
        self._last_cmd_time = time.time()

        self._target_linear = np.clip(
            self._target_linear,
            -self.config.max_linear_velocity,
            self.config.max_linear_velocity,
        )
        self._target_linear = np.clip(
            self._target_linear,
            -self.config.max_linear_velocity,
            self.config.max_linear_velocity,
        )
        self._target_angular = np.clip(
            self._target_angular,
            -self.config.max_angular_velocity,
            self.config.max_angular_velocity,
        )

    def _joint_command_callback(self, msg: Any) -> None:
        """Handle /joint_command (sensor_msgs/JointState) messages."""
        names = list(getattr(msg, "name", []) or [])
        positions = list(getattr(msg, "position", []) or [])
        if not positions:
            return

        if names and len(names) == len(positions):
            self._target_joint_positions = {str(n): float(p) for n, p in zip(names, positions)}
        elif self._joint_names and len(self._joint_names) == len(positions):
            self._target_joint_positions = {
                str(n): float(p) for n, p in zip(self._joint_names, positions)
            }
        else:
            return

        self._last_joint_cmd_time = time.time()

    def set_robot(self, robot: Any) -> None:

        """设置机器人 Articulation 对象"""
        self._robot = robot
        self._articulation = robot
        self._articulation_setup_complete = False
        self._articulation_setup_error = ""
        prim_path = getattr(robot, "prim_path", None)
        if prim_path is None:
            prim_path = getattr(robot, "_prim_path", None)
        self._articulation_prim_path = str(prim_path or self._configured_robot_prim_path)

        # 获取关节名称（兼容不同 Isaac Sim 版本）
        if hasattr(robot, 'dof_names'):
            names = robot.dof_names
            self._joint_names = list(names) if not callable(names) else list(names())
        elif hasattr(robot, 'get_joint_names'):
            self._joint_names = list(robot.get_joint_names())
        elif hasattr(robot, 'joint_names'):
            names = robot.joint_names
            self._joint_names = list(names) if not callable(names) else list(names())
        self._joint_name_to_index = {name: i for i, name in enumerate(self._joint_names)}

        print(f"[Control] Robot set with {len(self._joint_names)} joints")
        self._cached_joint_pos = np.zeros(len(self._joint_names), dtype=np.float64)
        self._cached_joint_vel = np.zeros(len(self._joint_names), dtype=np.float64)
        self._joint_positions = {name: 0.0 for name in self._joint_names}
        self._joint_velocities = {name: 0.0 for name in self._joint_names}
        self._joint_positions_raw = {name: 0.0 for name in self._joint_names}
        self._joint_velocities_raw = {name: 0.0 for name in self._joint_names}
        self._finalize_robot_setup_if_ready("set_robot")
    
    def set_world(self, world: Any) -> None:
        """设置 Isaac Sim World 对象"""
        self._world = world
        if self._articulation is None:
            self._configure_simulation_physics()

    def _log_articulation_not_ready(self, context: str) -> None:
        now = time.time()
        if now - self._last_articulation_not_ready_log_s < 1.0:
            return
        detail = f": {self._articulation_setup_error}" if self._articulation_setup_error else ""
        print(f"[Control] Articulation handle not ready during {context}{detail}")
        self._last_articulation_not_ready_log_s = now

    def _ensure_articulation_ready(self, context: str) -> bool:
        if self._articulation is None:
            return False
        if _is_articulation_handle_valid(self._articulation):
            return True

        self._articulation_setup_error = ""
        try:
            if hasattr(self._articulation, "initialize"):
                self._articulation.initialize()
        except Exception as exc:
            self._articulation_setup_error = str(exc)

        if _is_articulation_handle_valid(self._articulation):
            return True

        if not self._articulation_setup_error:
            self._articulation_setup_error = "physics_handle_invalid"
        self._log_articulation_not_ready(context)
        return False

    def _finalize_robot_setup_if_ready(self, context: str) -> bool:
        if self._articulation is None:
            return False
        if self._articulation_setup_complete:
            return True
        if not self._ensure_articulation_ready(context):
            return False

        self._configure_joint_drive()
        self._prime_standing_pose()
        self._articulation_setup_complete = True
        self._articulation_setup_error = ""
        return True

    def _prepare_articulation_access(self, context: str) -> bool:
        if self._articulation is None:
            return False
        if not self._articulation_setup_complete and not self._finalize_robot_setup_if_ready(context):
            return False
        return self._ensure_articulation_ready(context)

    def _get_joint_index_map(self) -> dict[str, int]:
        if len(self._joint_name_to_index) != len(self._joint_names):
            self._joint_name_to_index = {name: i for i, name in enumerate(self._joint_names)}
        return self._joint_name_to_index

    def _joint_sign(self, joint_name: str, overrides: dict[str, float]) -> float:
        return float(overrides.get(joint_name, 1.0))

    def _transform_joint_array(self, values: Sequence[float], overrides: dict[str, float]) -> np.ndarray:
        arr = np.array(values, dtype=np.float64, copy=True)
        for idx, joint_name in enumerate(self._joint_names):
            if idx >= len(arr):
                break
            arr[idx] = float(arr[idx]) * self._joint_sign(joint_name, overrides)
        return arr

    def _logical_joint_array_to_physical(self, values: Sequence[float]) -> np.ndarray:
        return self._transform_joint_array(values, self._joint_target_sign_overrides)

    def _physical_joint_array_to_logical(self, values: Sequence[float]) -> np.ndarray:
        return self._transform_joint_array(values, self._joint_feedback_sign_overrides)

    def _logical_joint_value_to_physical(self, joint_name: str, value: float) -> float:
        return float(value) * self._joint_sign(joint_name, self._joint_target_sign_overrides)

    def _physical_joint_value_to_logical(self, joint_name: str, value: float) -> float:
        return float(value) * self._joint_sign(joint_name, self._joint_feedback_sign_overrides)

    def refresh_joint_state_cache(self, dt: float) -> None:
        """Refresh cached joint positions/velocities outside the physics step."""
        if self._articulation is None or not self._joint_names:
            return
        if not self._prepare_articulation_access("refresh_joint_state_cache"):
            return
        if not hasattr(self._articulation, "get_joint_positions"):
            return

        try:
            positions_raw = np.array(self._articulation.get_joint_positions(), dtype=np.float64)
        except Exception:
            return
        if len(positions_raw) != len(self._joint_names):
            return

        velocities_raw: np.ndarray | None = None
        if hasattr(self._articulation, "get_joint_velocities"):
            try:
                read_velocities = np.array(self._articulation.get_joint_velocities(), dtype=np.float64)
                if len(read_velocities) == len(self._joint_names):
                    velocities_raw = read_velocities
            except Exception:
                velocities_raw = None

        if velocities_raw is None:
            if len(self._cached_joint_pos) == len(positions_raw) and dt > 1e-6:
                velocities_raw = (positions_raw - self._cached_joint_pos) / float(dt)
            else:
                velocities_raw = np.zeros(len(self._joint_names), dtype=np.float64)

        positions_logical = self._physical_joint_array_to_logical(positions_raw)
        velocities_logical = self._physical_joint_array_to_logical(velocities_raw)
        self._cached_joint_pos = positions_raw.copy()
        self._cached_joint_vel = velocities_raw.copy()
        for i, name in enumerate(self._joint_names):
            self._joint_positions_raw[name] = float(positions_raw[i])
            self._joint_velocities_raw[name] = float(velocities_raw[i])
            self._joint_positions[name] = float(positions_logical[i])
            self._joint_velocities[name] = float(velocities_logical[i])


    def _prime_standing_pose(self) -> None:
        """Lift the base and seed a nominal standing joint pose before teleop starts."""
        if self._articulation is None or not self._joint_names:
            return

        stand_targets = {
            name: float(DEFAULT_STAND_URDF_BY_NAME[name])
            for name in self._joint_names
            if name in DEFAULT_STAND_URDF_BY_NAME
        }
        if not stand_targets:
            return

        positions_logical = np.array(
            [stand_targets.get(name, 0.0) for name in self._joint_names],
            dtype=np.float64,
        )
        positions_physical = self._logical_joint_array_to_physical(positions_logical)
        joint_zeros = np.zeros(len(self._joint_names), dtype=np.float64)
        self._startup_pose_info = {
            "position": [float(v) for v in self._startup_base_position.tolist()],
            "orientation": [float(v) for v in self._startup_orientation_wxyz.tolist()],
            "orientation_order": self._quaternion_order,
            "position_source": self._startup_pose_info.get("position_source", "default"),
            "orientation_source": self._startup_pose_info.get("orientation_source", "default_identity_grounded"),
            "hold_duration_s": float(self._startup_pose_hold_duration_s),
            "hold_source": self._startup_pose_hold_source,
            "nominal_hold_tolerance_rad": float(self._startup_nominal_hold_tolerance_rad),
            "nominal_hold_tolerance_source": self._startup_nominal_hold_tolerance_source,
            "joint_count": len(self._joint_names),
            "methods": [],
        }
        errors: list[str] = []
        self._startup_joint_positions = positions_logical.copy()
        self._startup_joint_velocities = joint_zeros.copy()
        self._cached_world_position = self._startup_base_position.copy()
        self._cached_world_orientation = self._startup_orientation_wxyz.copy()
        self._cached_linear_velocity = np.zeros(3, dtype=np.float64)
        self._cached_angular_velocity = np.zeros(3, dtype=np.float64)
        self._imu_quat = [float(v) for v in self._startup_orientation_wxyz.tolist()]
        self._imu_omega = [0.0, 0.0, 0.0]
        self._imu_accel = [0.0, 0.0, 9.81]
        self._prev_linear_vel = np.zeros(3, dtype=np.float64)

        if hasattr(self._articulation, "set_default_state"):
            try:
                self._articulation.set_default_state(
                    position=self._startup_base_position.copy(),
                    orientation=self._startup_orientation_wxyz.copy(),
                )
                self._startup_pose_info["methods"].append("set_default_state")
            except Exception as e:
                errors.append(f"set_default_state: {e}")

        if hasattr(self._articulation, "set_joints_default_state"):
            try:
                self._articulation.set_joints_default_state(
                    positions=positions_physical.copy(),
                    velocities=joint_zeros.copy(),
                    efforts=joint_zeros.copy(),
                )
                self._startup_pose_info["methods"].append("set_joints_default_state")
            except Exception as e:
                errors.append(f"set_joints_default_state: {e}")

        if hasattr(self._articulation, "post_reset"):
            try:
                self._articulation.post_reset()
                self._startup_pose_info["methods"].append("post_reset")
            except Exception as e:
                errors.append(f"post_reset: {e}")

        if hasattr(self._articulation, "set_world_pose"):
            try:
                self._articulation.set_world_pose(
                    position=self._startup_base_position.copy(),
                    orientation=self._startup_orientation_wxyz.copy(),
                )
                self._startup_pose_info["methods"].append("set_world_pose")
            except Exception as e:
                errors.append(f"set_world_pose: {e}")

        if hasattr(self._articulation, "set_joint_positions"):
            try:
                self._articulation.set_joint_positions(positions_physical.copy())
                self._startup_pose_info["methods"].append("set_joint_positions")
                self._cached_joint_pos = positions_physical.copy()
                self._joint_positions = {
                    name: float(positions_logical[i]) for i, name in enumerate(self._joint_names)
                }
                self._joint_positions_raw = {
                    name: float(positions_physical[i]) for i, name in enumerate(self._joint_names)
                }
            except Exception as e:
                errors.append(f"set_joint_positions: {e}")

        if hasattr(self._articulation, "set_joint_velocities"):
            try:
                self._articulation.set_joint_velocities(joint_zeros.copy())
                self._startup_pose_info["methods"].append("set_joint_velocities")
                self._cached_joint_vel = joint_zeros.copy()
                self._joint_velocities = {name: 0.0 for name in self._joint_names}
                self._joint_velocities_raw = {name: 0.0 for name in self._joint_names}
            except Exception as e:
                errors.append(f"set_joint_velocities: {e}")

        if hasattr(self._articulation, "set_linear_velocity"):
            try:
                self._articulation.set_linear_velocity(np.zeros(3, dtype=np.float64))
                self._startup_pose_info["methods"].append("set_linear_velocity")
            except Exception as e:
                errors.append(f"set_linear_velocity: {e}")

        if hasattr(self._articulation, "set_angular_velocity"):
            try:
                self._articulation.set_angular_velocity(np.zeros(3, dtype=np.float64))
                self._startup_pose_info["methods"].append("set_angular_velocity")
            except Exception as e:
                errors.append(f"set_angular_velocity: {e}")

        self._target_joint_positions = stand_targets
        self._last_joint_cmd_time = time.time()
        self._startup_hold_deadline = self._last_joint_cmd_time + float(self._startup_pose_hold_duration_s)
        self._startup_hold_active = self._startup_pose_hold_duration_s > 1e-6
        self._prev_linear_vel = np.zeros(3, dtype=np.float64)
        self._startup_pose_primed = bool(self._startup_pose_info["methods"])
        self._startup_pose_error = "; ".join(errors)
        if errors:
            print(f"[Control] Standing-pose priming warnings: {self._startup_pose_error}")
        else:
            print("[Control] Standing-pose priming applied")

    def get_stand_error_payload(self) -> dict[str, Any]:
        if not self._joint_names:
            return {
                "ok": False,
                "reason": "no_joints",
            }

        compared: list[tuple[str, float]] = []
        for joint_name in self._joint_names:
            if joint_name not in DEFAULT_STAND_URDF_BY_NAME:
                continue
            actual = float(self._joint_positions.get(joint_name, 0.0))
            target = float(DEFAULT_STAND_URDF_BY_NAME[joint_name])
            compared.append((joint_name, actual - target))

        if not compared:
            return {
                "ok": False,
                "reason": "no_default_targets",
            }

        diffs = np.array([delta for _, delta in compared], dtype=np.float64)
        sorted_errors = sorted(compared, key=lambda item: abs(item[1]), reverse=True)
        return {
            "ok": True,
            "joint_count": len(compared),
            "max_abs_error": float(np.max(np.abs(diffs))),
            "rms_error": float(np.sqrt(np.mean(np.square(diffs)))),
            "top_errors": [
                {"joint": joint_name, "delta": float(delta)}
                for joint_name, delta in sorted_errors[:6]
            ],
        }

    def _startup_targets_match_nominal_stand(self, tolerance: float | None = None) -> bool:
        if not self._target_joint_positions:
            return False
        effective_tolerance = (
            float(self._startup_nominal_hold_tolerance_rad)
            if tolerance is None
            else max(0.0, float(tolerance))
        )
        compared = 0
        for joint_name, target in self._target_joint_positions.items():
            nominal = DEFAULT_STAND_URDF_BY_NAME.get(joint_name)
            if nominal is None:
                continue
            compared += 1
            if abs(float(target) - nominal) > effective_tolerance:
                return False
        return compared > 0

    def _configure_joint_drive(self) -> None:
        """
        Try to increase joint stiffness/damping for position commands.
        Safe no-op when API is unavailable.
        """
        if self._articulation is None:
            return
        if not self._joint_names:
            return

        n = len(self._joint_names)
        gain_profile = str(self.config.actuator_gain_profile or "").strip().lower()
        limit_profile = str(self.config.actuator_limit_profile or "").strip().lower()
        if gain_profile == "official_lite":
            kps, kds = self._official_lite_actuator_gains()
            self._gain_profile_name = "official_lite"
            print(f"[Control] Per-joint gains from official Lite actuator profile ({n} joints)")
        elif self.config.joint_kp and self.config.joint_kd and len(self.config.joint_kp) >= n:
            kps, kds = self._reorder_policy_gains_to_joint_names()
            self._gain_profile_name = "policy_config"
            print(f"[Control] Per-joint gains from policy config ({n} joints, name-mapped)")
        else:
            kps = np.full(n, float(self.config.joint_stiffness))
            kds = np.full(n, float(self.config.joint_damping))
            self._gain_profile_name = "uniform"
            print(
                f"[Control] Uniform gains: stiffness={self.config.joint_stiffness}, "
                f"damping={self.config.joint_damping}"
            )
        self._applied_joint_kp = {name: float(kps[i]) for i, name in enumerate(self._joint_names)}
        self._applied_joint_kd = {name: float(kds[i]) for i, name in enumerate(self._joint_names)}
        self._gain_apply_method = "prepared"
        self._gain_apply_error = ""
        self._applied_joint_max_effort = {}
        self._applied_joint_max_velocity = {}
        self._limit_profile_name = "not_configured"
        self._limit_apply_method = "not_configured"
        self._limit_apply_error = ""

        # 尝试设置增益（不同 Isaac Sim 版本 API 不同）
        if hasattr(self._articulation, "set_gains"):
            try:
                self._articulation.set_gains(kps, kds)
                self._gain_apply_method = "articulation.set_gains"
                print("[Control] Joint gains applied via set_gains()")
            except Exception as e:
                self._gain_apply_method = "articulation.set_gains_failed"
                self._gain_apply_error = str(e)
                print(f"[Control] set_gains() failed: {e}")
        elif hasattr(self._articulation, "get_articulation_controller"):
            try:
                ctrl = self._articulation.get_articulation_controller()
                if ctrl and hasattr(ctrl, "set_gains"):
                    ctrl.set_gains(kps, kds)
                    self._gain_apply_method = "controller.set_gains"
                    print("[Control] Joint gains applied via controller.set_gains()")
                else:
                    self._gain_apply_method = "controller.set_gains_unavailable"
            except Exception as e:
                self._gain_apply_method = "controller.set_gains_failed"
                self._gain_apply_error = str(e)
                print(f"[Control] controller.set_gains() failed: {e}")
        else:
            self._gain_apply_method = "set_gains_unavailable"
            print("[Control] set_gains not available, using URDF defaults")

        if limit_profile == "official_lite":
            self._apply_official_lite_actuator_limits()

    def _resolve_stage(self) -> Any:
        stage = _resolve_stage_from_world(self._world)
        if stage is not None:
            return stage
        try:
            import omni.usd
            return omni.usd.get_context().get_stage()
        except Exception:
            return None

    def _iter_collision_paths(self, stage: Any) -> list[str]:
        paths: list[str] = []
        try:
            from pxr import UsdPhysics
        except Exception:
            return paths

        for prim in stage.Traverse():
            try:
                if prim is None or (hasattr(prim, "IsValid") and not prim.IsValid()):
                    continue
                if hasattr(prim, "HasAPI") and prim.HasAPI(UsdPhysics.CollisionAPI):
                    paths.append(str(prim.GetPath()))
            except Exception:
                continue
        return paths

    def _bind_physics_material(
        self,
        stage: Any,
        prim_path: str,
        material_path: str,
        static_friction: float,
        dynamic_friction: float,
        restitution: float,
    ) -> bool:
        try:
            from pxr import PhysxSchema, UsdPhysics, UsdShade
        except Exception:
            return False

        prim = stage.GetPrimAtPath(prim_path)
        if prim is None:
            return False
        try:
            if hasattr(prim, "IsValid") and not prim.IsValid():
                return False
        except Exception:
            return False

        material = UsdShade.Material.Define(stage, material_path)
        material_prim = material.GetPrim()
        usd_material_api = _safe_apply_schema(UsdPhysics.MaterialAPI, material_prim)
        physx_material_api = _safe_apply_schema(PhysxSchema.PhysxMaterialAPI, material_prim)

        for api in (usd_material_api, physx_material_api):
            if api is None:
                continue
            _safe_set_usd_attr(api, "CreateStaticFrictionAttr", float(static_friction))
            _safe_set_usd_attr(api, "CreateDynamicFrictionAttr", float(dynamic_friction))
            _safe_set_usd_attr(api, "CreateRestitutionAttr", float(restitution))
            _safe_set_usd_attr(api, "CreateImprovePatchFrictionAttr", True)
            _safe_set_usd_attr(api, "CreateFrictionCombineModeAttr", "max")
            _safe_set_usd_attr(api, "CreateRestitutionCombineModeAttr", "min")

        try:
            UsdShade.MaterialBindingAPI.Apply(prim).Bind(material)
            return True
        except Exception:
            return False

    def _configure_simulation_physics(self) -> None:
        stage = self._resolve_stage()
        info: dict[str, Any] = {
            "configured": False,
            "articulation_prim_path": self._articulation_prim_path,
            "ground_static_friction": float(self.config.ground_static_friction),
            "ground_dynamic_friction": float(self.config.ground_dynamic_friction),
            "ground_restitution": float(self.config.ground_restitution),
            "solver_position_iterations": int(self.config.articulation_solver_position_iterations),
            "solver_velocity_iterations": int(self.config.articulation_solver_velocity_iterations),
            "ground_paths": [],
            "foot_paths": [],
            "all_collision_paths": [],
            "material_bindings": [],
            "articulation_solver_attrs": [],
        }
        warnings: list[str] = []

        if stage is None:
            warnings.append("stage_unavailable")
            self._physics_config_info = info
            self._physics_config_warnings = warnings
            return

        collision_paths = self._iter_collision_paths(stage)
        info["all_collision_paths"] = collision_paths
        articulation_path_candidates = {self._articulation_prim_path}
        if self._articulation_prim_path.startswith("/World/"):
            articulation_path_candidates.add(self._articulation_prim_path[len("/World"):])
        elif self._articulation_prim_path.startswith("/"):
            articulation_path_candidates.add(f"/World{self._articulation_prim_path}")

        ground_paths = [
            path for path in collision_paths
            if any(token in path.lower() for token in ("ground", "plane"))
        ]
        foot_paths = [
            path for path in collision_paths
            if any(token in path.lower() for token in ("foot", "ankle"))
        ]
        if not foot_paths:
            foot_paths = [
                path for path in collision_paths
                if any(path.startswith(candidate) for candidate in articulation_path_candidates)
            ]

        info["ground_paths"] = ground_paths
        info["foot_paths"] = foot_paths

        if ground_paths:
            for path in ground_paths:
                if self._bind_physics_material(
                    stage,
                    path,
                    "/World/PhysicsMaterials/teleop_ground",
                    self.config.ground_static_friction,
                    self.config.ground_dynamic_friction,
                    self.config.ground_restitution,
                ):
                    info["material_bindings"].append({"prim": path, "material": "teleop_ground"})
        else:
            warnings.append("ground_collision_not_found")

        if foot_paths:
            for path in foot_paths:
                if self._bind_physics_material(
                    stage,
                    path,
                    "/World/PhysicsMaterials/teleop_feet",
                    self.config.ground_static_friction,
                    self.config.ground_dynamic_friction,
                    self.config.ground_restitution,
                ):
                    info["material_bindings"].append({"prim": path, "material": "teleop_feet"})
        else:
            warnings.append("foot_collision_not_found")

        articulation_prim = None
        for candidate in articulation_path_candidates:
            try:
                articulation_prim = stage.GetPrimAtPath(candidate)
            except Exception:
                articulation_prim = None
            if articulation_prim is not None:
                try:
                    if not hasattr(articulation_prim, "IsValid") or articulation_prim.IsValid():
                        break
                except Exception:
                    break

        if articulation_prim is not None:
            try:
                from pxr import PhysxSchema
                articulation_api = _safe_apply_schema(PhysxSchema.PhysxArticulationAPI, articulation_prim)
                if articulation_api is not None:
                    if _safe_set_usd_attr(
                        articulation_api,
                        "CreateSolverPositionIterationCountAttr",
                        int(self.config.articulation_solver_position_iterations),
                    ):
                        info["articulation_solver_attrs"].append("solver_position_iteration_count")
                    if _safe_set_usd_attr(
                        articulation_api,
                        "CreateSolverVelocityIterationCountAttr",
                        int(self.config.articulation_solver_velocity_iterations),
                    ):
                        info["articulation_solver_attrs"].append("solver_velocity_iteration_count")
                else:
                    warnings.append("articulation_api_unavailable")
            except Exception as exc:
                warnings.append(f"articulation_solver_config_failed:{exc}")

        info["configured"] = bool(info["material_bindings"] or info["articulation_solver_attrs"])
        self._physics_config_info = info
        self._physics_config_warnings = warnings
        if warnings:
            print(f"[Control] Physics config warnings: {'; '.join(warnings)}")

    def _reorder_policy_gains_to_joint_names(self) -> tuple[np.ndarray, np.ndarray]:
        """Map policy-config gains from body order into the articulation's joint-name order."""
        default_kp = float(self.config.joint_stiffness)
        default_kd = float(self.config.joint_damping)
        kp_by_name = _expand_joint_name_aliases(
            {
                name: float(self.config.joint_kp[i])
                for i, name in enumerate(POLICY_GAIN_URDF_ORDER)
                if i < len(self.config.joint_kp or [])
            }
        )
        kd_by_name = _expand_joint_name_aliases(
            {
                name: float(self.config.joint_kd[i])
                for i, name in enumerate(POLICY_GAIN_URDF_ORDER)
                if i < len(self.config.joint_kd or [])
            }
        )
        mapped_names = [name for name in self._joint_names if name in kp_by_name and name in kd_by_name]
        if len(mapped_names) != len(self._joint_names):
            missing = [name for name in self._joint_names if name not in kp_by_name or name not in kd_by_name]
            print(f"[Control] Gain mapping missing joints, falling back to defaults for: {missing}")

        kps = np.array([kp_by_name.get(name, default_kp) for name in self._joint_names], dtype=np.float64)
        kds = np.array([kd_by_name.get(name, default_kd) for name in self._joint_names], dtype=np.float64)
        return kps, kds

    def _official_lite_actuator_gains(self) -> tuple[np.ndarray, np.ndarray]:
        """Match the checked-in Isaac Lab Lite actuator profile for simulation validation."""
        default_kp = float(self.config.joint_stiffness)
        default_kd = float(self.config.joint_damping)
        kps = np.array(
            [OFFICIAL_LITE_ACTUATOR_KP_BY_NAME.get(name, default_kp) for name in self._joint_names],
            dtype=np.float64,
        )
        kds = np.array(
            [OFFICIAL_LITE_ACTUATOR_KD_BY_NAME.get(name, default_kd) for name in self._joint_names],
            dtype=np.float64,
        )
        return kps, kds

    def _official_lite_actuator_limits(self) -> tuple[np.ndarray, np.ndarray]:
        """Match the checked-in Isaac Lab Lite actuator effort and velocity limits."""
        fallback_effort = 1.0e9
        fallback_velocity = 1.0e9
        max_effort = np.array(
            [OFFICIAL_LITE_ACTUATOR_MAX_EFFORT_BY_NAME.get(name, fallback_effort) for name in self._joint_names],
            dtype=np.float64,
        )
        max_velocity = np.array(
            [OFFICIAL_LITE_ACTUATOR_MAX_VELOCITY_BY_NAME.get(name, fallback_velocity) for name in self._joint_names],
            dtype=np.float64,
        )
        missing = [
            name for name in self._joint_names
            if name not in OFFICIAL_LITE_ACTUATOR_MAX_EFFORT_BY_NAME
            or name not in OFFICIAL_LITE_ACTUATOR_MAX_VELOCITY_BY_NAME
        ]
        if missing:
            print(f"[Control] Official Lite limit mapping missing joints, using large fallbacks for: {missing}")
        return max_effort, max_velocity

    def _reshape_joint_values_for_articulation_view(self, values: np.ndarray, view: Any) -> np.ndarray:
        count = getattr(view, "count", 1)
        try:
            env_count = max(1, int(count))
        except Exception:
            env_count = 1
        return np.tile(np.expand_dims(np.array(values, dtype=np.float32), axis=0), (env_count, 1))

    def _apply_official_lite_actuator_limits(self) -> None:
        """Apply the checked-in Lite actuator limits to the active articulation view."""
        self._limit_profile_name = "official_lite"
        self._limit_apply_method = "prepared"
        self._limit_apply_error = ""
        max_effort, max_velocity = self._official_lite_actuator_limits()
        self._applied_joint_max_effort = {
            name: float(max_effort[i]) for i, name in enumerate(self._joint_names)
        }
        self._applied_joint_max_velocity = {
            name: float(max_velocity[i]) for i, name in enumerate(self._joint_names)
        }

        view = _get_articulation_view(self._articulation)
        if view is None:
            self._limit_apply_method = "articulation_view_unavailable"
            print("[Control] Articulation view unavailable, skipping joint effort/velocity limits")
            return
        if not hasattr(view, "set_max_efforts") or not hasattr(view, "set_max_joint_velocities"):
            self._limit_apply_method = "articulation_view_limit_api_unavailable"
            print("[Control] Articulation view limit API unavailable, skipping joint effort/velocity limits")
            return

        max_effort_values = self._reshape_joint_values_for_articulation_view(max_effort, view)
        max_velocity_values = self._reshape_joint_values_for_articulation_view(max_velocity, view)
        try:
            view.set_max_efforts(max_effort_values)
        except Exception as exc:
            self._limit_apply_method = "articulation_view.set_max_efforts_failed"
            self._limit_apply_error = str(exc)
            print(f"[Control] articulation_view.set_max_efforts() failed: {exc}")
            return

        try:
            from omni.physx import get_physx_simulation_interface

            get_physx_simulation_interface().flush_changes()
        except Exception:
            pass

        try:
            view.set_max_joint_velocities(max_velocity_values)
            self._limit_apply_method = "articulation_view.set_max_efforts+set_max_joint_velocities"
            print("[Control] Joint effort/velocity limits applied via articulation view")
        except Exception as exc:
            self._limit_apply_method = "articulation_view.set_max_joint_velocities_failed"
            self._limit_apply_error = str(exc)
            print(f"[Control] articulation_view.set_max_joint_velocities() failed: {exc}")
    
    def update(self, dt: float) -> None:
        """
        每帧更新
        
        Args:
            dt: 时间步长（秒）
        """
        if not self.enabled:
            return
        if self._articulation is not None and not self._articulation_setup_complete:
            self._finalize_robot_setup_if_ready("update")

        now = time.time()
        if self._maintain_startup_pose(now):
            self._target_linear = 0.0
            self._target_angular = 0.0
            self._current_linear = 0.0
            self._current_angular = 0.0
        else:
            self._apply_pending_motion(dt)

        # 从物理引擎读取 IMU 数据
        self._update_imu(dt)

        # 更新里程计
        self._update_odometry(dt)
        
        # ROS2 spin (仅在 ROS2 可用时)
        if self._rclpy and self._node:
            self._rclpy.spin_once(self._node, timeout_sec=0.0)

    def _maintain_startup_pose(self, now: float) -> bool:
        if not self._startup_hold_active:
            return False
        # The startup hold is only meant to stabilize the articulation for a
        # short, bounded window after reset. If we keep extending it whenever
        # the current joint targets still match the nominal stand pose, a STOP
        # publisher can pin the robot in the primed pose forever and external
        # joint commands never get a chance to apply.
        if now >= self._startup_hold_deadline:
            self._startup_hold_active = False
            return False
        if self._articulation is None or len(self._startup_joint_positions) != len(self._joint_names):
            self._startup_hold_active = False
            return False
        if not self._prepare_articulation_access("startup_pose_hold"):
            return False

        try:
            startup_positions_physical = self._logical_joint_array_to_physical(self._startup_joint_positions)
            if hasattr(self._articulation, "set_world_pose"):
                self._articulation.set_world_pose(
                    position=self._startup_base_position.copy(),
                    orientation=self._startup_orientation_wxyz.copy(),
                )
            if hasattr(self._articulation, "set_joint_positions"):
                self._articulation.set_joint_positions(startup_positions_physical.copy())
                self._cached_joint_pos = startup_positions_physical.copy()
            if hasattr(self._articulation, "set_joint_velocities"):
                self._articulation.set_joint_velocities(self._startup_joint_velocities.copy())
                self._cached_joint_vel = self._startup_joint_velocities.copy()
            if hasattr(self._articulation, "set_linear_velocity"):
                self._articulation.set_linear_velocity(np.zeros(3, dtype=np.float64))
            if hasattr(self._articulation, "set_angular_velocity"):
                self._articulation.set_angular_velocity(np.zeros(3, dtype=np.float64))

            for i, joint_name in enumerate(self._joint_names):
                self._joint_positions[joint_name] = float(self._startup_joint_positions[i])
                self._joint_positions_raw[joint_name] = float(startup_positions_physical[i])
                self._joint_velocities[joint_name] = 0.0
                self._joint_velocities_raw[joint_name] = 0.0
            self._cached_world_position = self._startup_base_position.copy()
            self._cached_world_orientation = self._startup_orientation_wxyz.copy()
            self._cached_linear_velocity = np.zeros(3, dtype=np.float64)
            self._cached_angular_velocity = np.zeros(3, dtype=np.float64)
            self._imu_quat = [float(v) for v in self._startup_orientation_wxyz.tolist()]
            self._imu_omega = [0.0, 0.0, 0.0]
            self._imu_accel = [0.0, 0.0, 9.81]
            self._prev_linear_vel = np.zeros(3, dtype=np.float64)
            return True
        except Exception as exc:
            self._startup_hold_active = False
            self._startup_pose_error = f"{self._startup_pose_error}; startup_hold: {exc}".strip("; ")
            return False

    def _lerp(self, current: float, target: float, alpha: float) -> float:
        """Linear interpolation helper."""
        return current + (target - current) * alpha

    def _has_recent_joint_command(self, now: float) -> bool:
        if not self._target_joint_positions:
            return False
        return (now - self._last_joint_cmd_time) <= float(self.config.joint_command_timeout_s)

    def _has_active_velocity_command(self, now: float) -> bool:
        if self._last_cmd_time <= 0.0:
            return abs(self._current_linear) > 1e-4 or abs(self._current_angular) > 1e-4
        if (now - self._last_cmd_time) > self._cmd_timeout:
            return abs(self._current_linear) > 1e-4 or abs(self._current_angular) > 1e-4
        return (
            abs(self._target_linear) > 1e-4
            or abs(self._target_angular) > 1e-4
            or abs(self._current_linear) > 1e-4
            or abs(self._current_angular) > 1e-4
        )

    def _should_apply_joint_targets(self, now: float | None = None) -> bool:
        if not self._target_joint_positions:
            return False
        now = time.time() if now is None else now
        if self._has_recent_joint_command(now):
            return True
        return not self._has_active_velocity_command(now)

    def _apply_pending_motion(self, dt: float) -> None:
        current_time = time.time()
        if current_time - self._last_cmd_time > self._cmd_timeout:
            self._target_linear = 0.0
            self._target_angular = 0.0

        self._current_linear = self._lerp(
            self._current_linear,
            self._target_linear,
            0.1,
        )
        self._current_angular = self._lerp(
            self._current_angular,
            self._target_angular,
            0.1,
        )

        if self._should_apply_joint_targets(current_time):
            self._apply_joint_targets()
        else:
            self._apply_velocity(self._current_linear, self._current_angular)

    def _apply_joint_targets(self) -> None:
        """Apply joint position targets via Isaac Sim's articulation action API."""
        if self._articulation is None:
            return
        if not self._target_joint_positions:
            return
        if not self._prepare_articulation_access("apply_joint_targets"):
            return

        try:
            ctrl = None
            if hasattr(self._articulation, "get_articulation_controller"):
                ctrl = self._articulation.get_articulation_controller()

            if len(self._cached_joint_pos) == len(self._joint_names):
                targets_physical = np.array(self._cached_joint_pos, dtype=np.float64, copy=True)
            else:
                targets_physical = np.zeros(len(self._joint_names), dtype=np.float64)
            if self._joint_positions:
                targets_logical = np.array(
                    [self._joint_positions.get(name, 0.0) for name in self._joint_names],
                    dtype=np.float64,
                )
            else:
                targets_logical = self._physical_joint_array_to_logical(targets_physical)

            joint_index = self._get_joint_index_map()
            has_any = False
            applied_logical: dict[str, float] = {}
            applied_physical: dict[str, float] = {}
            for joint_name, target in self._target_joint_positions.items():
                idx = joint_index.get(joint_name)
                if idx is None:
                    continue
                logical_target = float(target)
                physical_target = self._logical_joint_value_to_physical(joint_name, logical_target)
                targets_logical[idx] = logical_target
                targets_physical[idx] = physical_target
                applied_logical[joint_name] = logical_target
                applied_physical[joint_name] = physical_target
                has_any = True
            self._last_target_array_logical = _to_float_list(targets_logical)
            self._last_target_array_physical = _to_float_list(targets_physical)
            self._last_target_positions_logical = applied_logical
            self._last_target_positions_physical = applied_physical
            self._last_joint_target_apply_method = "prepared"
            self._last_joint_target_apply_error = ""
            if has_any:
                # Isaac Sim 5.1 Linux headless can expose an articulation
                # wrapper whose set_joint_position_targets path dereferences a
                # missing internal action buffer. Prefer the controller path
                # first and only fall back to other APIs if it is unavailable.
                apply_errors: list[str] = []
                if ctrl is not None and hasattr(ctrl, "set_joint_position_targets"):
                    try:
                        ctrl.set_joint_position_targets(targets_physical.copy())
                        self._last_joint_target_apply_method = "controller.set_joint_position_targets"
                        return
                    except Exception as exc:
                        apply_errors.append(f"controller.set_joint_position_targets: {exc}")
                if hasattr(self._articulation, "set_joint_position_targets"):
                    try:
                        self._articulation.set_joint_position_targets(targets_physical.copy())
                        self._last_joint_target_apply_method = "articulation.set_joint_position_targets"
                        return
                    except Exception as exc:
                        apply_errors.append(f"articulation.set_joint_position_targets: {exc}")
                if hasattr(self._articulation, "set_joint_positions"):
                    try:
                        # Isaac Sim 5.1 headless can expose a broken
                        # apply_action/get_applied_actions path. Fall back to
                        # directly writing joint positions so we can still
                        # validate command/feedback wiring on Linux.
                        self._articulation.set_joint_positions(targets_physical.copy())
                        self._last_joint_target_apply_method = "articulation.set_joint_positions_fallback"
                        return
                    except Exception as exc:
                        apply_errors.append(f"articulation.set_joint_positions: {exc}")

                action = None
                try:
                    from isaacsim.core.utils.types import ArticulationAction
                except ImportError:
                    try:
                        from omni.isaac.core.utils.types import ArticulationAction  # type: ignore
                    except ImportError:
                        ArticulationAction = None  # type: ignore[assignment]

                if ArticulationAction is not None:
                    action = ArticulationAction(joint_positions=targets_physical.copy())
                    if ctrl is not None and hasattr(ctrl, "apply_action"):
                        try:
                            ctrl.apply_action(action)
                            self._last_joint_target_apply_method = "controller.apply_action"
                            return
                        except Exception as exc:
                            apply_errors.append(f"controller.apply_action: {exc}")
                    if hasattr(self._articulation, "apply_action"):
                        try:
                            self._articulation.apply_action(action)
                            self._last_joint_target_apply_method = "articulation.apply_action"
                            return
                        except Exception as exc:
                            apply_errors.append(f"articulation.apply_action: {exc}")
                if apply_errors:
                    self._last_joint_target_apply_method = "error"
                    self._last_joint_target_apply_error = "; ".join(apply_errors)
                    print(f"[Control] Error applying joint targets: {self._last_joint_target_apply_error}")
                    return
                self._last_joint_target_apply_method = "target_api_unavailable"
            else:
                self._last_joint_target_apply_method = "ignored:no_matching_joints"
        except Exception as e:
            self._last_joint_target_apply_method = "error"
            self._last_joint_target_apply_error = str(e)
            print(f"[Control] Error applying joint targets: {e}")

    def _apply_velocity(self, linear: float, angular: float) -> None:

        """应用速度到机器人"""
        if self._robot is None:
            return
        
        try:
            # 方式1：直接设置速度（适用于差速底盘）
            if hasattr(self._robot, 'set_linear_velocity'):
                self._robot.set_linear_velocity([linear, 0.0, 0.0])
            if hasattr(self._robot, 'set_angular_velocity'):
                self._robot.set_angular_velocity([0.0, 0.0, angular])
            
            # 方式2：通过关节控制（适用于人形机器人）
            # 这里可以添加步态控制逻辑
            # self._apply_walking_gait(linear, angular)
            
        except Exception as e:
            print(f"[Control] Error applying velocity: {e}")
    
    def _apply_walking_gait(self, linear: float, angular: float) -> None:
        """
        应用行走步态（人形机器人）
        
        这是一个简化的步态控制器，实际应用中需要更复杂的实现
        """
        if not self._joint_names or self._articulation is None:
            return
        
        # 简化：根据速度调整关节目标
        # 实际实现需要完整的步态规划
        pass
    
    def _update_imu(self, dt: float) -> None:
        """从物理引擎读取真实 IMU 数据"""
        if self._robot is None:
            return
        if self._articulation is not None and not self._prepare_articulation_access("update_imu"):
            return
        try:
            # 方向四元数（兼容 get_world_pose / get_world_poses）
            if hasattr(self._robot, 'get_world_pose'):
                pos, quat = self._robot.get_world_pose()
                self._cached_world_position = np.array(pos, dtype=np.float64)
                self._cached_world_orientation = np.array(quat, dtype=np.float64)
                self._imu_quat = [float(q) for q in quat]
            elif hasattr(self._robot, 'get_world_poses'):
                positions, quats = self._robot.get_world_poses()
                if len(positions) > 0:
                    self._cached_world_position = np.array(positions[0], dtype=np.float64)
                if len(quats) > 0:
                    self._cached_world_orientation = np.array(quats[0], dtype=np.float64)
                    self._imu_quat = [float(q) for q in quats[0]]
            # 角速度
            if hasattr(self._robot, 'get_angular_velocity'):
                omega_world = np.array(self._robot.get_angular_velocity(), dtype=np.float64)
                self._cached_angular_velocity = omega_world.copy()
                omega_local = world_vector_to_local(self._cached_world_orientation.tolist(), omega_world)
                self._imu_omega = [float(v) for v in omega_local]
            # 线加速度（数值微分 + 重力补偿）
            if hasattr(self._robot, 'get_linear_velocity') and dt > 0:
                vel = np.array(self._robot.get_linear_velocity(), dtype=np.float64)
                self._cached_linear_velocity = vel.copy()
                accel_world = (vel - self._prev_linear_vel) / dt
                accel_local = world_vector_to_local(
                    self._cached_world_orientation.tolist(),
                    accel_world + np.array([0.0, 0.0, 9.81], dtype=np.float64),
                )
                self._imu_accel = [float(accel_local[0]), float(accel_local[1]), float(accel_local[2])]
                self._prev_linear_vel = vel
        except Exception:
            pass

    def _update_odometry(self, dt: float) -> None:
        """更新里程计"""
        # 积分更新位置
        self._odom_x += self._current_linear * math.cos(self._odom_theta) * dt
        self._odom_y += self._current_linear * math.sin(self._odom_theta) * dt
        self._odom_theta += self._current_angular * dt
        
        # 归一化角度
        self._odom_theta = math.atan2(
            math.sin(self._odom_theta), 
            math.cos(self._odom_theta)
        )
        
        # 发布里程计消息
        self._publish_odometry()
        
        # 发布关节状态
        self._publish_joint_states()
    
    def _publish_odometry(self) -> None:
        """发布里程计消息"""
        if not self._odom_pub:
            return
        
        msg = self._odom_type()
        msg.header.stamp = self._node.get_clock().now().to_msg()
        msg.header.frame_id = self.config.odom_frame
        msg.child_frame_id = self.config.base_frame
        
        # 位置
        msg.pose.pose.position.x = self._odom_x
        msg.pose.pose.position.y = self._odom_y
        msg.pose.pose.position.z = 0.0
        
        # 姿态（四元数）
        half_theta = self._odom_theta / 2.0
        msg.pose.pose.orientation.x = 0.0
        msg.pose.pose.orientation.y = 0.0
        msg.pose.pose.orientation.z = math.sin(half_theta)
        msg.pose.pose.orientation.w = math.cos(half_theta)
        
        # 速度
        msg.twist.twist.linear.x = self._current_linear
        msg.twist.twist.angular.z = self._current_angular
        
        self._odom_pub.publish(msg)
    
    def _publish_joint_states(self) -> None:
        """发布关节状态消息（使用缓存数据）"""
        if not self._joint_states_pub or not self._joint_names:
            return

        msg = self._joint_state_type()
        msg.header.stamp = self._node.get_clock().now().to_msg()
        msg.name = self._joint_names
        msg.position = [self._joint_positions.get(n, 0.0) for n in self._joint_names]
        msg.velocity = [self._joint_velocities.get(n, 0.0) for n in self._joint_names]
        msg.effort = [0.0] * len(self._joint_names)

        self._joint_states_pub.publish(msg)
    
    def get_robot_pose(self) -> tuple[np.ndarray, np.ndarray]:
        """获取机器人位姿"""
        return self._cached_world_position.copy(), self._cached_world_orientation.copy()

    def get_policy_orientation_quat(self) -> np.ndarray:
        """Express the root orientation relative to the nominal standing frame."""
        _, quat = self.get_robot_pose()
        return relative_quat_wxyz(self._startup_orientation_wxyz, quat.tolist())

    def get_pose_payload(self) -> dict[str, Any]:
        """Return a JSON-safe snapshot of robot world pose and control state."""
        pos, quat = self.get_robot_pose()
        yaw, pitch, roll = quat_wxyz_to_euler(quat.tolist())
        policy_quat = self.get_policy_orientation_quat()
        policy_yaw, policy_pitch, policy_roll = quat_wxyz_to_euler(policy_quat.tolist())
        vel = self._cached_linear_velocity.copy()

        now = time.time()
        cmd_age_ms = None if self._last_cmd_time <= 0.0 else int((now - self._last_cmd_time) * 1000.0)
        joint_cmd_age_ms = (
            None if self._last_joint_cmd_time <= 0.0 else int((now - self._last_joint_cmd_time) * 1000.0)
        )

        return {
            "ok": True,
            "position": [float(v) for v in pos.tolist()],
            "orientation": [float(v) for v in quat.tolist()],
            "orientation_order": self._quaternion_order,
            "euler": {
                "yaw": float(yaw),
                "pitch": float(pitch),
                "roll": float(roll),
            },
            "policy_orientation": [float(v) for v in policy_quat.tolist()],
            "policy_euler": {
                "yaw": float(policy_yaw),
                "pitch": float(policy_pitch),
                "roll": float(policy_roll),
            },
            "configured_robot_prim_path": self._configured_robot_prim_path,
            "articulation_prim_path": self._articulation_prim_path,
            "linear_velocity": [float(v) for v in vel.tolist()],
            "target_linear": float(self._target_linear),
            "target_angular": float(self._target_angular),
            "current_linear": float(self._current_linear),
            "current_angular": float(self._current_angular),
            "startup_pose_hold_active": bool(self._startup_hold_active),
            "joint_targets_active": bool(self._target_joint_positions),
            "cmd_age_ms": cmd_age_ms,
            "joint_command_age_ms": joint_cmd_age_ms,
            "stand_error": self.get_stand_error_payload(),
        }

    def get_feedback_payload(self) -> dict[str, Any]:
        """Return the combined joint-state and IMU snapshot used by HTTP feedback endpoints."""
        names = list(self._joint_names)
        positions = [self._joint_positions.get(n, 0.0) for n in names]
        velocities = [self._joint_velocities.get(n, 0.0) for n in names]
        yaw, pitch, roll = quat_wxyz_to_euler(self._imu_quat)
        policy_quat = self.get_policy_orientation_quat()
        policy_yaw, policy_pitch, policy_roll = quat_wxyz_to_euler(policy_quat.tolist())
        return {
            "joint_states": {
                "name": names,
                "position": positions,
                "velocity": velocities,
                "effort": [0.0] * len(names),
            },
            "imu": {
                "orientation": self._imu_quat,
                "orientation_order": self._quaternion_order,
                "euler": {"yaw": yaw, "pitch": pitch, "roll": roll},
                "policy_orientation": [float(v) for v in policy_quat.tolist()],
                "policy_euler": {
                    "yaw": policy_yaw,
                    "pitch": policy_pitch,
                    "roll": policy_roll,
                },
                "angular_velocity": self._imu_omega,
                "linear_acceleration": self._imu_accel,
            },
        }

    def get_joint_debug_payload(self) -> dict[str, Any]:
        """Return both logical(controller) and raw(Isaac articulation) joint views."""
        names = list(self._joint_names)
        joint_index = self._get_joint_index_map()
        now = time.time()
        joint_cmd_age_ms = (
            None if self._last_joint_cmd_time <= 0.0 else int((now - self._last_joint_cmd_time) * 1000.0)
        )

        logical_positions = {name: float(self._joint_positions.get(name, 0.0)) for name in names}
        logical_velocities = {name: float(self._joint_velocities.get(name, 0.0)) for name in names}
        raw_positions = {name: float(self._joint_positions_raw.get(name, 0.0)) for name in names}
        raw_velocities = {name: float(self._joint_velocities_raw.get(name, 0.0)) for name in names}

        ankle_focus: dict[str, Any] = {}
        for name in names:
            if "ankle" not in name:
                continue
            ankle_focus[name] = {
                "index": int(joint_index.get(name, -1)),
                "feedback_position_logical": logical_positions.get(name, 0.0),
                "feedback_position_raw": raw_positions.get(name, 0.0),
                "feedback_velocity_logical": logical_velocities.get(name, 0.0),
                "feedback_velocity_raw": raw_velocities.get(name, 0.0),
                "target_position_logical": (
                    None if name not in self._target_joint_positions else float(self._target_joint_positions[name])
                ),
                "last_applied_target_position_logical": (
                    None
                    if name not in self._last_target_positions_logical
                    else float(self._last_target_positions_logical[name])
                ),
                "last_applied_target_position_raw": (
                    None
                    if name not in self._last_target_positions_physical
                    else float(self._last_target_positions_physical[name])
                ),
            }

        return {
            "ok": True,
            "joint_names": names,
            "joint_name_to_index": {name: int(idx) for name, idx in joint_index.items()},
            "joint_command_age_ms": joint_cmd_age_ms,
            "joint_target_sign_overrides": dict(self._joint_target_sign_overrides),
            "joint_feedback_sign_overrides": dict(self._joint_feedback_sign_overrides),
            "joint_positions_logical": logical_positions,
            "joint_positions_raw": raw_positions,
            "joint_velocities_logical": logical_velocities,
            "joint_velocities_raw": raw_velocities,
            "cached_joint_positions_raw": _to_float_list(self._cached_joint_pos),
            "cached_joint_velocities_raw": _to_float_list(self._cached_joint_vel),
            "target_joint_positions_logical": {
                str(name): float(value) for name, value in self._target_joint_positions.items()
            },
            "last_target_positions_logical": dict(self._last_target_positions_logical),
            "last_target_positions_raw": dict(self._last_target_positions_physical),
            "last_target_array_logical": list(self._last_target_array_logical),
            "last_target_array_raw": list(self._last_target_array_physical),
            "last_target_apply_method": self._last_joint_target_apply_method,
            "last_target_apply_error": self._last_joint_target_apply_error,
            "ankle_focus": ankle_focus,
        }

    def apply_joint_command_payload(self, payload: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        """Apply a joint command payload from the HTTP control surface."""
        names = list(payload.get("name", []) or [])
        positions = list(payload.get("position", []) or [])
        if not names or len(names) != len(positions):
            return False, {"success": False, "error": "name/position mismatch"}

        self._target_joint_positions = {
            str(name): float(position)
            for name, position in zip(names, positions)
        }
        self._last_joint_cmd_time = time.time()
        return True, {"success": True, "joints": len(names)}

    def reset_to_standing_pose(self) -> tuple[bool, dict[str, Any]]:
        """Reapply the nominal standing pose so repeated live diagnostics can restart cleanly."""
        if self._articulation is None:
            return False, {"success": False, "error": "articulation_unavailable"}
        if not self._prepare_articulation_access("reset_to_standing_pose"):
            detail = self._articulation_setup_error or "articulation_not_ready"
            return False, {"success": False, "error": detail}

        self._target_linear = 0.0
        self._target_angular = 0.0
        self._current_linear = 0.0
        self._current_angular = 0.0
        self._last_cmd_time = 0.0
        self._apply_velocity(0.0, 0.0)
        self._prime_standing_pose()
        self.refresh_joint_state_cache(0.02)
        return True, {
            "success": True,
            "startup_pose_hold_active": bool(self._startup_hold_active),
            "pose": self.get_pose_payload(),
            "stand_error": self.get_stand_error_payload(),
        }

    def stop(self) -> None:
        """Stop the robot and clear active command targets."""
        self._target_linear = 0.0
        self._target_angular = 0.0
        self._target_joint_positions = {}
        self._last_joint_cmd_time = 0.0
        self._apply_velocity(0.0, 0.0)

    def close(self) -> None:
        """Cleanup ROS2 node resources."""
        if self._node:
            self._node.destroy_node()


def create_robot_controller(
    robot_prim_path: str = "/World/robot",
    cmd_vel_topic: str = "/cmd_vel",
    joint_command_topic: str = "/joint_command",
    **kwargs
) -> IsaacSimRobotController:
    """
    创建机器人控制器的便捷函数
    
    Args:
        robot_prim_path: 机器人在 USD 场景中的路径
        cmd_vel_topic: ROS2 速度命令话题
        **kwargs: 其他配置参数
    
    Returns:
        IsaacSimRobotController 实例
    """
    config = RobotControlConfig(
        robot_prim_path=robot_prim_path,
        cmd_vel_topic=cmd_vel_topic,
        joint_command_topic=joint_command_topic,
        **kwargs
    )
    return IsaacSimRobotController(config)


# ==================== Isaac Sim 集成 ====================

class IsaacSimControlExtension:
    """
    Isaac Sim 扩展，用于在仿真循环中集成 ROS2 控制
    """
    
    def __init__(self, controller: IsaacSimRobotController):
        self.controller = controller
        self._physics_step: Optional[Callable] = None
    
    def on_startup(self) -> None:
        """扩展启动"""
        print("[Extension] ROS2 Control Bridge starting...")
        
        # 获取 World 和 Robot
        self._setup_isaac_sim()
        
        # 注册物理步进回调
        self._register_physics_callback()
    
    def _setup_isaac_sim(self) -> None:
        """设置 Isaac Sim 环境"""
        try:
            from isaacsim import SimulationApp
            
            # 获取 simulation app
            sim_app = SimulationApp.instance()
            if sim_app:
                world = sim_app.world
                self.controller.set_world(world)
                
                # 获取机器人
                if world:
                    robot = world.scene.get_object(self.controller.config.robot_prim_path)
                    if robot:
                        self.controller.set_robot(robot)
                        
        except Exception as e:
            print(f"[Extension] Isaac Sim setup error: {e}")
    
    def _register_physics_callback(self) -> None:
        """注册物理步进回调"""
        try:
            import omni.physx
            from omni.physx import get_physx_interface
            
            physx_interface = get_physx_interface()
            if physx_interface:
                self._physics_step = self._on_physics_step
                physx_interface.add_physics_step_callback(self._physics_step)
                print("[Extension] Physics callback registered")
                
        except Exception as e:
            print(f"[Extension] Failed to register physics callback: {e}")
    
    def _on_physics_step(self, dt: float) -> None:
        """物理步进回调"""
        self.controller.update(dt)
    
    def on_shutdown(self) -> None:
        """扩展关闭"""
        print("[Extension] ROS2 Control Bridge shutting down...")
        self.controller.stop()
        self.controller.close()


def run_standalone_control(
    robot_prim_path: str = "/World/robot",
    cmd_vel_topic: str = "/cmd_vel",
    joint_command_topic: str = "/joint_command",
    joint_stiffness: float = 180.0,
    joint_damping: float = 8.0,
    ground_static_friction: float = 1.2,
    ground_dynamic_friction: float = 1.0,
    ground_restitution: float = 0.0,
    articulation_solver_position_iterations: int = 16,
    articulation_solver_velocity_iterations: int = 4,
    urdf_path: Optional[str] = None,
    usd_path: Optional[str] = None,
    headless: bool = False,
    joint_kp: Optional[list[float]] = None,
    joint_kd: Optional[list[float]] = None,
    actuator_gain_profile: str = "",
    actuator_limit_profile: str = "",
    joint_target_sign_overrides: Optional[dict[str, float]] = None,
    joint_feedback_sign_overrides: Optional[dict[str, float]] = None,
    startup_nominal_hold_tolerance_rad: Optional[float] = None,
    physics_dt: float = 1.0 / 60.0,
) -> None:
    """
    独立运行 ROS2 控制桥接
    
    Args:
        robot_prim_path: 机器人路径
        urdf_path: URDF 文件路径（可选，用于自动导入）
        headless: 是否无头模式
    """
    from isaacsim import SimulationApp
    
    # 创建仿真应用
    config = {"headless": headless}
    sim_app = SimulationApp(config)
    
    # 创建控制器
    controller = create_robot_controller(
        robot_prim_path=robot_prim_path,
        cmd_vel_topic=cmd_vel_topic,
        joint_command_topic=joint_command_topic,
        joint_stiffness=joint_stiffness,
        joint_damping=joint_damping,
        ground_static_friction=ground_static_friction,
        ground_dynamic_friction=ground_dynamic_friction,
        ground_restitution=ground_restitution,
        articulation_solver_position_iterations=articulation_solver_position_iterations,
        articulation_solver_velocity_iterations=articulation_solver_velocity_iterations,
        joint_kp=joint_kp,
        joint_kd=joint_kd,
        actuator_gain_profile=actuator_gain_profile,
        actuator_limit_profile=actuator_limit_profile,
        joint_target_sign_overrides=joint_target_sign_overrides,
        joint_feedback_sign_overrides=joint_feedback_sign_overrides,
        startup_nominal_hold_tolerance_rad=startup_nominal_hold_tolerance_rad,
    )
    
    # 设置场景
    try:
        from isaacsim.core.api import World

        # 优先使用 SingleArticulation（Isaac Sim 5.1+）
        try:
            from isaacsim.core.prims import SingleArticulation as ArticulationClass
        except ImportError:
            from isaacsim.core.prims import Articulation as ArticulationClass

        world = World(
            stage_units_in_meters=1.0,
            physics_dt=float(physics_dt),
        )
        world.scene.add_default_ground_plane()
        success = False
        prim_path = str(robot_prim_path)

        if usd_path:
            stage = _resolve_stage_from_world(world)
            success, prim_path = _reference_usd_robot(stage, usd_path, robot_prim_path)
            if success:
                print(f"[Standalone] USD referenced at: {prim_path}")
                print(f"[Standalone] USD asset: {usd_path}")
                controller.config.robot_prim_path = str(prim_path)
                controller._configured_robot_prim_path = str(prim_path)
            else:
                print(f"[Standalone] Failed to load USD: {usd_path}")
                print(f"[Standalone] USD error: {prim_path}")

        # 如果提供了 URDF，导入机器人
        elif urdf_path:
            try:
                from TGrobot4s.isaac_sim.import_tienkung_urdf import import_tienkung
            except ImportError:
                from import_tienkung_urdf import import_tienkung
            try:
                success, prim_path = import_tienkung(
                    urdf_path,
                    fix_base=False,
                    self_collision=False,
                )
            except Exception as e:
                print(f"[Standalone] URDF import error: {e}")
                import traceback
                traceback.print_exc()
                success, prim_path = False, str(e)
            if success:
                print(f"[Standalone] URDF imported at: {prim_path}")
                controller.config.robot_prim_path = str(prim_path)
                controller._configured_robot_prim_path = str(prim_path)
            else:
                print(f"[Standalone] Failed to load URDF: {urdf_path}")

        # 先 reset world 初始化物理仿真视图
        robot = None
        articulation_prim_path = controller._articulation_prim_path
        if success:
            articulation_prim_path = _resolve_articulation_root_prim_path(str(prim_path))
            controller._articulation_prim_path = str(articulation_prim_path)
        controller.set_world(world)
        world.reset()

        if success:
            # Warm the referenced stage before creating the articulation handle.
            # Adding a freshly referenced USD articulation into the scene before
            # physics is ready can trip Isaac Sim 5.1 tensor internals on
            # headless Linux.
            for _ in range(3):
                world.step(render=False)
            try:
                robot = ArticulationClass(prim_path=articulation_prim_path, name="robot")
                print(f"[Standalone] Articulation created at prim: {articulation_prim_path}")
            except Exception as e:
                print(f"[Standalone] Articulation failed: {e}")
                import traceback
                traceback.print_exc()
                robot = None

        # 然后创建 Articulation（需要物理视图已就绪）
        if robot is not None:
            handle_ready, handle_error = _warm_up_articulation_handle(
                robot,
                world,
                render=not headless,
            )
            if not handle_ready:
                print(f"[Standalone] Articulation handle warmup warning: {handle_error}")
            controller.set_robot(robot)
            print(f"[Standalone] Articulation created, {len(controller._joint_names)} joints")
            print(f"[Standalone] Physics config: {controller._physics_config_info}")
        elif not success:
            print("[Standalone] No robot loaded, HTTP API only")
        
        print("[Standalone] Running control bridge...")
        print(f"[Standalone] physics_dt={float(physics_dt):.6f}s")
        print("[Standalone] HTTP control: http://0.0.0.0:9200/move")
        print("[Standalone] Press Ctrl+C to stop")

        # 主循环：在 world.step() 之后刷新关节状态并推进控制器
        # 这样 /move 与 /joint_command 会走同一套仲裁逻辑，避免启动站立目标长期屏蔽速度命令。
        while sim_app.is_running():
            world.step(render=not headless)
            controller.refresh_joint_state_cache(float(physics_dt))
            controller.update(float(physics_dt))
            
    except KeyboardInterrupt:
        print("\n[Standalone] Stopping...")
    except Exception as e:
        import traceback
        print(f"[Standalone] Error: {e}")
        traceback.print_exc()
    finally:
        controller.close()
        sim_app.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Isaac Sim ROS2 Control Bridge")
    parser.add_argument("--robot-prim", default="/World/robot", help="Robot prim path")
    parser.add_argument("--cmd-vel-topic", default="/cmd_vel", help="cmd_vel topic name")
    parser.add_argument("--joint-command-topic", default="/joint_command", help="joint command topic name")
    parser.add_argument("--joint-stiffness", type=float, default=180.0, help="joint drive stiffness")
    parser.add_argument("--joint-damping", type=float, default=8.0, help="joint drive damping")
    parser.add_argument("--ground-static-friction", type=float, default=1.2,
                        help="ground/foot static friction override")
    parser.add_argument("--ground-dynamic-friction", type=float, default=1.0,
                        help="ground/foot dynamic friction override")
    parser.add_argument("--ground-restitution", type=float, default=0.0,
                        help="ground/foot restitution override")
    parser.add_argument("--solver-position-iterations", type=int, default=16,
                        help="articulation solver position iteration count")
    parser.add_argument("--solver-velocity-iterations", type=int, default=4,
                        help="articulation solver velocity iteration count")
    parser.add_argument("--odom-topic", default="/odom", help="odom topic name")
    parser.add_argument("--urdf", default=None, help="URDF file path")
    parser.add_argument("--usd", default=None, help="USD asset path")
    parser.add_argument("--official-lite-usd", action="store_true",
                        help="use the bundled official TienKung-Lab Lite USD asset")
    parser.add_argument("--headless", action="store_true", help="Run headless")
    parser.add_argument("--physics-dt", type=float, default=1.0 / 60.0,
                        help="Isaac physics step in seconds")
    parser.add_argument("--policy-config", default=None,
                        help="Path to tg22_config.yaml for per-joint PD gains")
    parser.add_argument(
        "--actuator-gain-profile",
        default="",
        help="Optional per-joint gain profile override, e.g. official_lite",
    )
    parser.add_argument(
        "--actuator-limit-profile",
        default="",
        help="Optional effort/velocity limit profile override, e.g. official_lite",
    )
    parser.add_argument(
        "--joint-target-sign-overrides",
        default=os.getenv(ENV_JOINT_TARGET_SIGN_OVERRIDES, ""),
        help=(
            "Optional logical->Isaac sign overrides, e.g. "
            "'ankle_pitch_l_joint=-1,ankle_pitch_r_joint=-1'"
        ),
    )
    parser.add_argument(
        "--joint-feedback-sign-overrides",
        default=os.getenv(ENV_JOINT_FEEDBACK_SIGN_OVERRIDES, ""),
        help=(
            "Optional Isaac->logical sign overrides, e.g. "
            "'ankle_pitch_l_joint=-1,ankle_pitch_r_joint=-1'"
        ),
    )
    parser.add_argument(
        "--startup-nominal-hold-tolerance-rad",
        type=float,
        default=None,
        help="Keep startup hold active while stand targets stay within this nominal joint tolerance",
    )
    args = parser.parse_args()

    joint_kp = None
    joint_kd = None
    if args.policy_config:
        try:
            import yaml
            with open(args.policy_config, encoding="utf-8") as f:
                cfg_data = yaml.safe_load(f)
            joint_kp = list(cfg_data.get("joint_kp_p", []))[:20]
            joint_kd = list(cfg_data.get("joint_kd_p", []))[:20]
            print(f"[Config] Loaded per-joint KP/KD from {args.policy_config}")
        except Exception as e:
            print(f"[Config] Failed to load policy config: {e}")

    usd_path = args.usd
    if args.official_lite_usd and not usd_path:
        usd_path = get_default_official_lite_usd_path()
        print(f"[Config] Using official Lite USD: {usd_path}")

    try:
        joint_target_sign_overrides = parse_joint_sign_overrides(args.joint_target_sign_overrides)
    except ValueError as exc:
        parser.error(f"--joint-target-sign-overrides: {exc}")
        raise AssertionError("unreachable")

    try:
        joint_feedback_sign_overrides = parse_joint_sign_overrides(args.joint_feedback_sign_overrides)
    except ValueError as exc:
        parser.error(f"--joint-feedback-sign-overrides: {exc}")
        raise AssertionError("unreachable")

    if joint_target_sign_overrides:
        print(f"[Config] Joint target sign overrides: {joint_target_sign_overrides}")
    if joint_feedback_sign_overrides:
        print(f"[Config] Joint feedback sign overrides: {joint_feedback_sign_overrides}")

    run_standalone_control(
        robot_prim_path=args.robot_prim,
        cmd_vel_topic=args.cmd_vel_topic,
        joint_command_topic=args.joint_command_topic,
        joint_stiffness=args.joint_stiffness,
        joint_damping=args.joint_damping,
        ground_static_friction=args.ground_static_friction,
        ground_dynamic_friction=args.ground_dynamic_friction,
        ground_restitution=args.ground_restitution,
        articulation_solver_position_iterations=args.solver_position_iterations,
        articulation_solver_velocity_iterations=args.solver_velocity_iterations,
        urdf_path=args.urdf,
        usd_path=usd_path,
        headless=args.headless,
        joint_kp=joint_kp,
        joint_kd=joint_kd,
        actuator_gain_profile=args.actuator_gain_profile,
        actuator_limit_profile=args.actuator_limit_profile,
        joint_target_sign_overrides=joint_target_sign_overrides,
        joint_feedback_sign_overrides=joint_feedback_sign_overrides,
        startup_nominal_hold_tolerance_rad=args.startup_nominal_hold_tolerance_rad,
        physics_dt=max(1e-4, float(args.physics_dt)),
    )
    return 0


if __name__ == "__main__":
    exit(main())
