#!/usr/bin/env python3
"""Run a short RL locomotion diagnostic and summarize tracking stability.

This tool is intentionally lightweight: it drives the existing ros_bridge HTTP
surface and samples bridge + Isaac feedback at a modest rate so we can compare
pose stability against joint target tracking without overwhelming the sim.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any

import httpx

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from ros_bridge_lite.motor_id_map import NAME_TO_INDEX
from ros_bridge_lite.policy_config import PolicyConfig
from ros_bridge_lite.sim_feedback_adapter import BODYIDMAP_TO_URDF

LIMIT_CFG = PolicyConfig()


@dataclass(slots=True)
class Sample:
    t: float
    x: float
    y: float
    z: float
    max_joint_error: float | None
    max_joint_joint: str | None
    max_joint_target: float | None
    max_joint_actual: float | None
    max_joint_signed_error: float | None
    max_limit_joint: str | None
    max_limit_target: float | None
    max_limit_excess: float | None
    fsm_state: str
    rl_debug_focus: dict[str, Any] | None = None


FOCUS_BODY_JOINTS = ("l_ankle_pitch", "r_ankle_pitch")
FOCUS_URDF_JOINTS = tuple(BODYIDMAP_TO_URDF.get(name, name) for name in FOCUS_BODY_JOINTS)


def _direction_sign(value: float, *, eps: float = 1.0e-4) -> int:
    value_f = float(value)
    if value_f > eps:
        return 1
    if value_f < -eps:
        return -1
    return 0


def _json_get(client: httpx.Client, url: str, *, retries: int = 3) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict):
                raise ValueError(f"{url} did not return a JSON object")
            return data
        except Exception as exc:  # pragma: no cover - live diagnostic path
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(0.05)
    assert last_error is not None
    raise last_error


def _json_post(client: httpx.Client, url: str, payload: dict[str, Any], *, retries: int = 3) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict):
                raise ValueError(f"{url} did not return a JSON object")
            return data
        except Exception as exc:  # pragma: no cover - live diagnostic path
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(0.05)
    assert last_error is not None
    raise last_error


def _compute_joint_errors(
    body_targets: dict[str, float],
    feedback: dict[str, Any],
) -> tuple[float | None, str | None, float | None, float | None, float | None, dict[str, float]]:
    js = feedback.get("joint_states", {})
    names = list(js.get("name", []) or [])
    positions = list(js.get("position", []) or [])
    actual_by_name = {
        str(name): float(positions[i])
        for i, name in enumerate(names)
        if i < len(positions)
    }

    errors: dict[str, float] = {}
    for body_name, target in body_targets.items():
        urdf_name = BODYIDMAP_TO_URDF.get(body_name)
        if urdf_name is None:
            continue
        actual = actual_by_name.get(urdf_name)
        if actual is None:
            continue
        errors[urdf_name] = abs(float(target) - actual)

    if not errors:
        return None, None, None, None, None, {}

    max_joint, max_error = max(errors.items(), key=lambda item: item[1])
    actual = actual_by_name.get(max_joint)
    target = None
    for body_name, body_target in body_targets.items():
        if BODYIDMAP_TO_URDF.get(body_name) == max_joint:
            target = float(body_target)
            break
    signed_error = None if target is None or actual is None else float(target - actual)
    return float(max_error), str(max_joint), target, actual, signed_error, errors


def _compute_joint_target_limit_metrics(
    body_targets: dict[str, float],
) -> tuple[float | None, str | None, float | None, dict[str, float], dict[str, float]]:
    peak_excess_by_joint: dict[str, float] = {}
    abs_offset_from_default_by_joint: dict[str, float] = {}
    worst_joint: str | None = None
    worst_target: float | None = None
    worst_excess: float | None = None

    for body_name, target in body_targets.items():
        idx = NAME_TO_INDEX.get(body_name, -1)
        if idx < 0:
            continue
        urdf_name = BODYIDMAP_TO_URDF.get(body_name)
        if urdf_name is None:
            continue
        lower = float(LIMIT_CFG.joint_pos_lower[idx])
        upper = float(LIMIT_CFG.joint_pos_upper[idx])
        default = float(LIMIT_CFG.default_dof_pos[idx])
        target_f = float(target)
        excess = max(lower - target_f, target_f - upper, 0.0)
        peak_excess_by_joint[urdf_name] = excess
        abs_offset_from_default_by_joint[urdf_name] = abs(target_f - default)
        if worst_excess is None or excess > worst_excess:
            worst_joint = urdf_name
            worst_target = target_f
            worst_excess = excess

    return worst_excess, worst_joint, worst_target, peak_excess_by_joint, abs_offset_from_default_by_joint


def _extract_rl_debug_focus(debug_payload: dict[str, Any]) -> dict[str, Any] | None:
    controller_debug = debug_payload.get("controller_debug", {})
    if not isinstance(controller_debug, dict):
        return None
    fsm_debug = controller_debug.get("fsm_debug", {})
    if not isinstance(fsm_debug, dict):
        return None

    obs = fsm_debug.get("obs", {})
    policy = fsm_debug.get("policy", {})
    imu = fsm_debug.get("imu", {})
    feedback_joint_pos = fsm_debug.get("feedback_joint_pos", {})
    feedback_joint_vel = fsm_debug.get("feedback_joint_vel", {})
    post_controller_targets = controller_debug.get("post_controller_targets", {})
    if not all(
        isinstance(section, dict)
        for section in [obs, policy, imu, feedback_joint_pos, feedback_joint_vel, post_controller_targets]
    ):
        return None

    joint_pos_terms = obs.get("joint_pos_terms", {})
    joint_vel_terms = obs.get("joint_vel_terms", {})
    action_last_terms = obs.get("action_last_terms", {})
    raw_output_mujoco = policy.get("raw_output_mujoco_order", {})
    pre_entry_targets = policy.get("pre_entry_targets", {})
    post_entry_targets = policy.get("post_entry_targets", {})
    if not all(
        isinstance(section, dict)
        for section in [
            joint_pos_terms,
            joint_vel_terms,
            action_last_terms,
            raw_output_mujoco,
            pre_entry_targets,
            post_entry_targets,
        ]
    ):
        return None

    ankles: dict[str, Any] = {}
    for body_name in FOCUS_BODY_JOINTS:
        idx = NAME_TO_INDEX.get(body_name, -1)
        if idx < 0:
            continue
        urdf_name = BODYIDMAP_TO_URDF.get(body_name, body_name)
        default = float(LIMIT_CFG.default_dof_pos[idx])
        lower = float(LIMIT_CFG.joint_pos_lower[idx])
        upper = float(LIMIT_CFG.joint_pos_upper[idx])
        feedback_pos = float(feedback_joint_pos.get(body_name, 0.0))
        feedback_vel = float(feedback_joint_vel.get(body_name, 0.0))
        obs_pos_term = float(joint_pos_terms.get(body_name, 0.0))
        obs_vel_term = float(joint_vel_terms.get(body_name, 0.0))
        obs_action_last_term = float(action_last_terms.get(body_name, 0.0))
        raw_output = float(raw_output_mujoco.get(body_name, 0.0))
        pre_target = float(pre_entry_targets.get(body_name, 0.0))
        post_target = float(post_entry_targets.get(body_name, 0.0))
        post_controller = float(post_controller_targets.get(body_name, 0.0))
        expected_obs_pos_term = feedback_pos - default
        expected_target_from_raw = raw_output * float(LIMIT_CFG.action_scales) + default
        target_delta_from_default = post_controller - default
        actual_delta_from_default = feedback_pos - default
        target_direction = _direction_sign(target_delta_from_default)
        actual_direction = _direction_sign(actual_delta_from_default)
        ankles[urdf_name] = {
            "body_name": body_name,
            "default_joint_pos": default,
            "obs_pos_term": obs_pos_term,
            "obs_pos_term_expected_from_feedback": expected_obs_pos_term,
            "obs_pos_term_error": obs_pos_term - expected_obs_pos_term,
            "obs_vel_term": obs_vel_term,
            "obs_vel_term_expected_from_feedback": feedback_vel,
            "obs_vel_term_error": obs_vel_term - feedback_vel,
            "obs_action_last_term": obs_action_last_term,
            "feedback_joint_pos": feedback_pos,
            "feedback_joint_vel": feedback_vel,
            "raw_output_mujoco": raw_output,
            "target_from_raw_output_before_entry": expected_target_from_raw,
            "pre_entry_target": pre_target,
            "post_entry_target": post_target,
            "post_controller_target": post_controller,
            "target_from_raw_output_error": post_target - expected_target_from_raw,
            "controller_target_minus_entry_target": post_controller - post_target,
            "target_delta_from_default": target_delta_from_default,
            "actual_delta_from_default": actual_delta_from_default,
            "target_direction_sign": target_direction,
            "actual_direction_sign": actual_direction,
            "target_actual_direction_match": (
                None
                if target_direction == 0 or actual_direction == 0
                else target_direction == actual_direction
            ),
            "target_actual_error": post_controller - feedback_pos,
            "joint_lower": lower,
            "joint_upper": upper,
            "pre_entry_limit_excess": max(lower - pre_target, pre_target - upper, 0.0),
            "post_entry_limit_excess": max(lower - post_target, post_target - upper, 0.0),
            "post_controller_limit_excess": max(lower - post_controller, post_controller - upper, 0.0),
        }

    return {
        "inference_count": int(fsm_debug.get("inference_count", 0)),
        "last_infer_state_timer_s": float(fsm_debug.get("last_infer_state_timer_s", 0.0)),
        "policy_command": controller_debug.get("policy_command", {}),
        "imu": {
            "feedback_euler_zyx": imu.get("feedback_euler_zyx", {}),
            "processed_ang_vel": imu.get("processed_ang_vel", []),
            "gravity_dir": imu.get("gravity_dir", []),
        },
        "ankles": ankles,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose RL gait tracking in Isaac Sim")
    parser.add_argument("--bridge-url", default="http://127.0.0.1:8080", help="ros_bridge_lite base URL")
    parser.add_argument("--isaac-url", default="http://127.0.0.1:9200", help="Isaac Sim control bridge base URL")
    parser.add_argument("--linear", type=float, default=0.08, help="Linear command sent to /move")
    parser.add_argument("--angular", type=float, default=0.0, help="Angular command sent to /move")
    parser.add_argument("--duration-s", type=float, default=5.0, help="Command duration in seconds")
    parser.add_argument("--cmd-hz", type=float, default=16.0, help="Command refresh rate in Hz")
    parser.add_argument("--sample-hz", type=float, default=5.0, help="Telemetry sample rate in Hz")
    parser.add_argument("--z-threshold", type=float, default=0.7, help="Fall threshold for pose.z")
    parser.add_argument("--settle-s", type=float, default=0.8, help="Post-stop settle duration in seconds")
    parser.add_argument("--reset-settle-s", type=float, default=0.5, help="Wait after /reset_pose before sampling")
    parser.add_argument("--no-reset-pose", action="store_true", help="Skip calling Isaac /reset_pose before the run")
    parser.add_argument("--timeout-s", type=float, default=2.0, help="Per-request timeout in seconds")
    parser.add_argument("--output", default="", help="Optional JSON output path")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    bridge_url = str(args.bridge_url).rstrip("/")
    isaac_url = str(args.isaac_url).rstrip("/")
    cmd_period = 1.0 / max(1.0, float(args.cmd_hz))
    sample_period = 1.0 / max(0.5, float(args.sample_hz))

    samples: list[Sample] = []
    peak_error_by_joint: dict[str, float] = {}
    max_joint_occurrences: Counter[str] = Counter()
    target_limit_excess_peak_by_joint: dict[str, float] = {}
    target_limit_violation_counts: Counter[str] = Counter()
    target_offset_peak_by_joint: dict[str, float] = {}
    warnings: list[str] = []
    reset_payload: dict[str, Any] | None = None
    rl_debug_supported = True

    with httpx.Client(timeout=float(args.timeout_s), trust_env=False) as client:
        if not bool(args.no_reset_pose):
            try:
                reset_payload = _json_post(client, f"{isaac_url}/reset_pose", {})
                time.sleep(max(0.0, float(args.reset_settle_s)))
            except Exception as exc:  # pragma: no cover - live diagnostic path
                warnings.append(f"reset_pose failed before run: {exc}")

        bridge_before = _json_get(client, f"{bridge_url}/health")
        dbg_before = bridge_before.get("joint_command_debug", {}).get("http_transport_debug", {})
        initial_pose = _json_get(client, f"{isaac_url}/pose")
        initial_position = list(initial_pose.get("position", [0.0, 0.0, 0.0]))
        if len(initial_position) < 3:
            raise ValueError("Isaac pose payload missing position")

        start = time.perf_counter()
        next_cmd_at = start
        next_sample_at = start
        while (time.perf_counter() - start) < float(args.duration_s):
            now = time.perf_counter()
            if now >= next_cmd_at:
                _json_post(
                    client,
                    f"{bridge_url}/move",
                    {"linear": float(args.linear), "angular": float(args.angular)},
                )
                next_cmd_at += cmd_period

            if now >= next_sample_at:
                bridge = _json_get(client, f"{bridge_url}/health")
                feedback = _json_get(client, f"{isaac_url}/feedback")
                pose = _json_get(client, f"{isaac_url}/pose")
                rl_debug_focus = None
                if rl_debug_supported:
                    try:
                        rl_debug_payload = _json_get(client, f"{bridge_url}/debug/rl", retries=1)
                        rl_debug_focus = _extract_rl_debug_focus(rl_debug_payload)
                    except Exception as exc:  # pragma: no cover - live diagnostic path
                        rl_debug_supported = False
                        warnings.append(f"rl_debug unavailable: {exc}")
                joint_debug = bridge.get("joint_command_debug", {})
                body_targets = dict(joint_debug.get("last_targets", {}) or {})
                max_error, max_joint, max_target, max_actual, max_signed_error, per_joint_errors = _compute_joint_errors(
                    body_targets,
                    feedback,
                )
                (
                    max_limit_excess,
                    max_limit_joint,
                    max_limit_target,
                    per_joint_limit_excess,
                    per_joint_target_offsets,
                ) = _compute_joint_target_limit_metrics(body_targets)
                if max_joint is not None:
                    max_joint_occurrences[max_joint] += 1
                for joint_name, error in per_joint_errors.items():
                    peak_error_by_joint[joint_name] = max(error, peak_error_by_joint.get(joint_name, 0.0))
                for joint_name, excess in per_joint_limit_excess.items():
                    target_limit_excess_peak_by_joint[joint_name] = max(
                        excess,
                        target_limit_excess_peak_by_joint.get(joint_name, 0.0),
                    )
                    if excess > 1e-6:
                        target_limit_violation_counts[joint_name] += 1
                for joint_name, offset in per_joint_target_offsets.items():
                    target_offset_peak_by_joint[joint_name] = max(
                        offset,
                        target_offset_peak_by_joint.get(joint_name, 0.0),
                    )
                position = list(pose.get("position", [0.0, 0.0, 0.0]))
                samples.append(
                    Sample(
                        t=float(time.perf_counter() - start),
                        x=float(position[0]),
                        y=float(position[1]),
                        z=float(position[2]),
                        max_joint_error=max_error,
                        max_joint_joint=max_joint,
                        max_joint_target=max_target,
                        max_joint_actual=max_actual,
                        max_joint_signed_error=max_signed_error,
                        max_limit_joint=max_limit_joint,
                        max_limit_target=max_limit_target,
                        max_limit_excess=max_limit_excess,
                        fsm_state=str(bridge.get("rl_fsm_state", "unknown")),
                        rl_debug_focus=rl_debug_focus,
                    )
                )
                next_sample_at += sample_period

            time.sleep(0.005)

        _json_post(client, f"{bridge_url}/move", {"linear": 0.0, "angular": 0.0})
        time.sleep(max(0.0, float(args.settle_s)))

        bridge_after = _json_get(client, f"{bridge_url}/health")
        final_pose = _json_get(client, f"{isaac_url}/pose")
        dbg_after = bridge_after.get("joint_command_debug", {}).get("http_transport_debug", {})

    valid_samples = samples
    final_position = list(final_pose.get("position", [0.0, 0.0, 0.0]))
    delta_x = float(final_position[0]) - float(initial_position[0])
    delta_y = float(final_position[1]) - float(initial_position[1])
    delta_planar = math.hypot(delta_x, delta_y)
    max_planar = max(
        (math.hypot(sample.x - float(initial_position[0]), sample.y - float(initial_position[1])) for sample in valid_samples),
        default=0.0,
    )
    min_z = min((sample.z for sample in valid_samples), default=float(initial_position[2]))

    first_below_threshold = next(
        (sample for sample in valid_samples if sample.z < float(args.z_threshold)),
        None,
    )
    max_joint_error_sample = max(
        valid_samples,
        key=lambda sample: -1.0 if sample.max_joint_error is None else sample.max_joint_error,
        default=None,
    )
    sorted_worst_samples = sorted(
        valid_samples,
        key=lambda sample: -1.0 if sample.max_joint_error is None else sample.max_joint_error,
        reverse=True,
    )
    fall_window_samples: list[dict[str, Any]] = []
    fall_window_focus: list[dict[str, Any]] = []
    if first_below_threshold is not None:
        fall_index = valid_samples.index(first_below_threshold)
        start_idx = max(0, fall_index - 2)
        end_idx = min(len(valid_samples), fall_index + 3)
        for sample in valid_samples[start_idx:end_idx]:
            fall_window_samples.append(
                {
                    "t": round(sample.t, 3),
                    "z": float(sample.z),
                    "max_joint_error": sample.max_joint_error,
                    "max_joint_joint": sample.max_joint_joint,
                    "max_joint_target": sample.max_joint_target,
                    "max_joint_actual": sample.max_joint_actual,
                    "max_joint_signed_error": sample.max_joint_signed_error,
                    "max_limit_joint": sample.max_limit_joint,
                    "max_limit_target": sample.max_limit_target,
                    "max_limit_excess": sample.max_limit_excess,
                    "fsm_state": sample.fsm_state,
                }
            )
            if sample.rl_debug_focus is not None:
                fall_window_focus.append(
                    {
                        "t": round(sample.t, 3),
                        "fsm_state": sample.fsm_state,
                        "focus": sample.rl_debug_focus,
                    }
                )

    focus_samples = [sample for sample in valid_samples if sample.rl_debug_focus is not None]
    ankle_raw_output_peaks: dict[str, float] = {}
    ankle_obs_pos_term_peaks: dict[str, float] = {}
    ankle_feedback_velocity_peaks: dict[str, float] = {}
    ankle_obs_pos_term_error_peaks: dict[str, float] = {}
    ankle_target_from_raw_error_peaks: dict[str, float] = {}
    ankle_direction_mismatch_counts: Counter[str] = Counter()
    ankle_direction_mismatch_peak_abs_target_delta: dict[str, float] = {}
    ankle_direction_mismatch_peak_abs_actual_delta: dict[str, float] = {}
    for sample in focus_samples:
        focus = sample.rl_debug_focus or {}
        for joint_name, joint_data in dict(focus.get("ankles", {})).items():
            if not isinstance(joint_data, dict):
                continue
            ankle_raw_output_peaks[joint_name] = max(
                abs(float(joint_data.get("raw_output_mujoco", 0.0))),
                ankle_raw_output_peaks.get(joint_name, 0.0),
            )
            ankle_obs_pos_term_peaks[joint_name] = max(
                abs(float(joint_data.get("obs_pos_term", 0.0))),
                ankle_obs_pos_term_peaks.get(joint_name, 0.0),
            )
            ankle_feedback_velocity_peaks[joint_name] = max(
                abs(float(joint_data.get("feedback_joint_vel", 0.0))),
                ankle_feedback_velocity_peaks.get(joint_name, 0.0),
            )
            ankle_obs_pos_term_error_peaks[joint_name] = max(
                abs(float(joint_data.get("obs_pos_term_error", 0.0))),
                ankle_obs_pos_term_error_peaks.get(joint_name, 0.0),
            )
            ankle_target_from_raw_error_peaks[joint_name] = max(
                abs(float(joint_data.get("target_from_raw_output_error", 0.0))),
                ankle_target_from_raw_error_peaks.get(joint_name, 0.0),
            )
            if joint_data.get("target_actual_direction_match") is False:
                ankle_direction_mismatch_counts[joint_name] += 1
                ankle_direction_mismatch_peak_abs_target_delta[joint_name] = max(
                    abs(float(joint_data.get("target_delta_from_default", 0.0))),
                    ankle_direction_mismatch_peak_abs_target_delta.get(joint_name, 0.0),
                )
                ankle_direction_mismatch_peak_abs_actual_delta[joint_name] = max(
                    abs(float(joint_data.get("actual_delta_from_default", 0.0))),
                    ankle_direction_mismatch_peak_abs_actual_delta.get(joint_name, 0.0),
                )

    def _focus_score(sample: Sample) -> float:
        focus = sample.rl_debug_focus or {}
        score = 0.0
        for joint_data in dict(focus.get("ankles", {})).values():
            if not isinstance(joint_data, dict):
                continue
            score = max(score, float(joint_data.get("post_controller_limit_excess", 0.0)))
            score = max(score, abs(float(joint_data.get("raw_output_mujoco", 0.0))) * 0.1)
        return score

    worst_focus_samples = sorted(focus_samples, key=_focus_score, reverse=True)

    summary: dict[str, Any] = {
        "command": {
            "linear": float(args.linear),
            "angular": float(args.angular),
            "duration_s": float(args.duration_s),
            "cmd_hz": float(args.cmd_hz),
            "sample_hz": float(args.sample_hz),
            "z_threshold": float(args.z_threshold),
        },
        "pose": {
            "initial": [float(v) for v in initial_position[:3]],
            "final": [float(v) for v in final_position[:3]],
            "delta_x": delta_x,
            "delta_y": delta_y,
            "delta_planar": delta_planar,
            "max_planar": max_planar,
            "min_z": min_z,
            "first_z_below_threshold_s": None if first_below_threshold is None else round(first_below_threshold.t, 3),
        },
        "tracking": {
            "max_joint_error": None if max_joint_error_sample is None else max_joint_error_sample.max_joint_error,
            "max_joint_error_joint": None if max_joint_error_sample is None else max_joint_error_sample.max_joint_joint,
            "max_joint_error_t_s": None if max_joint_error_sample is None else round(max_joint_error_sample.t, 3),
            "joint_peak_errors": [
                {"joint": joint_name, "error": float(error)}
                for joint_name, error in sorted(
                    peak_error_by_joint.items(),
                    key=lambda item: item[1],
                    reverse=True,
                )[:8]
            ],
            "joint_most_often_worst": [
                {"joint": joint_name, "count": int(count)}
                for joint_name, count in max_joint_occurrences.most_common(8)
            ],
        },
        "limits": {
            "joint_target_limit_violations": [
                {
                    "joint": joint_name,
                    "count": int(target_limit_violation_counts[joint_name]),
                    "max_excess": float(target_limit_excess_peak_by_joint.get(joint_name, 0.0)),
                }
                for joint_name, _count in target_limit_violation_counts.most_common(8)
            ],
            "joint_peak_target_offsets_from_default": [
                {"joint": joint_name, "abs_offset": float(offset)}
                for joint_name, offset in sorted(
                    target_offset_peak_by_joint.items(),
                    key=lambda item: item[1],
                    reverse=True,
                )[:8]
            ],
        },
        "bridge": {
            "rl_fsm_state": bridge_after.get("rl_fsm_state"),
            "feedback_attempt_delta": int(dbg_after.get("feedback_attempt_count", 0)) - int(dbg_before.get("feedback_attempt_count", 0)),
            "command_attempt_delta": int(dbg_after.get("command_attempt_count", 0)) - int(dbg_before.get("command_attempt_count", 0)),
            "feedback_success_delta": int(dbg_after.get("feedback_success_count", 0)) - int(dbg_before.get("feedback_success_count", 0)),
            "command_success_delta": int(dbg_after.get("command_success_count", 0)) - int(dbg_before.get("command_success_count", 0)),
            "last_command_ok": dbg_after.get("last_command_ok"),
        },
        "samples": {
            "count": len(valid_samples),
            "first_fall_sample": None if first_below_threshold is None else {
                "t": round(first_below_threshold.t, 3),
                "z": float(first_below_threshold.z),
                "max_joint_error": first_below_threshold.max_joint_error,
                "max_joint_joint": first_below_threshold.max_joint_joint,
                "max_joint_target": first_below_threshold.max_joint_target,
                "max_joint_actual": first_below_threshold.max_joint_actual,
                "max_joint_signed_error": first_below_threshold.max_joint_signed_error,
                "max_limit_joint": first_below_threshold.max_limit_joint,
                "max_limit_target": first_below_threshold.max_limit_target,
                "max_limit_excess": first_below_threshold.max_limit_excess,
                "fsm_state": first_below_threshold.fsm_state,
            },
            "worst_samples": [
                {
                    "t": round(sample.t, 3),
                    "z": float(sample.z),
                    "max_joint_error": sample.max_joint_error,
                    "max_joint_joint": sample.max_joint_joint,
                    "max_joint_target": sample.max_joint_target,
                    "max_joint_actual": sample.max_joint_actual,
                    "max_joint_signed_error": sample.max_joint_signed_error,
                    "max_limit_joint": sample.max_limit_joint,
                    "max_limit_target": sample.max_limit_target,
                    "max_limit_excess": sample.max_limit_excess,
                    "fsm_state": sample.fsm_state,
                }
                for sample in sorted_worst_samples[:8]
            ],
            "fall_window_samples": fall_window_samples,
        },
        "rl_debug": {
            "supported": rl_debug_supported or bool(focus_samples),
            "sample_count": len(focus_samples),
            "focus_joints": list(FOCUS_URDF_JOINTS),
            "ankle_peak_abs_raw_output_mujoco": [
                {"joint": joint_name, "abs_raw_output": float(value)}
                for joint_name, value in sorted(
                    ankle_raw_output_peaks.items(),
                    key=lambda item: item[1],
                    reverse=True,
                )
            ],
            "ankle_peak_abs_obs_pos_term": [
                {"joint": joint_name, "abs_obs_pos_term": float(value)}
                for joint_name, value in sorted(
                    ankle_obs_pos_term_peaks.items(),
                    key=lambda item: item[1],
                    reverse=True,
                )
            ],
            "ankle_peak_abs_feedback_joint_vel": [
                {"joint": joint_name, "abs_feedback_joint_vel": float(value)}
                for joint_name, value in sorted(
                    ankle_feedback_velocity_peaks.items(),
                    key=lambda item: item[1],
                    reverse=True,
                )
            ],
            "ankle_peak_abs_obs_pos_term_error": [
                {"joint": joint_name, "abs_obs_pos_term_error": float(value)}
                for joint_name, value in sorted(
                    ankle_obs_pos_term_error_peaks.items(),
                    key=lambda item: item[1],
                    reverse=True,
                )
            ],
            "ankle_peak_abs_target_from_raw_output_error": [
                {"joint": joint_name, "abs_target_from_raw_output_error": float(value)}
                for joint_name, value in sorted(
                    ankle_target_from_raw_error_peaks.items(),
                    key=lambda item: item[1],
                    reverse=True,
                )
            ],
            "ankle_target_actual_direction_mismatch": [
                {
                    "joint": joint_name,
                    "count": int(ankle_direction_mismatch_counts[joint_name]),
                    "peak_abs_target_delta_from_default": float(
                        ankle_direction_mismatch_peak_abs_target_delta.get(joint_name, 0.0)
                    ),
                    "peak_abs_actual_delta_from_default": float(
                        ankle_direction_mismatch_peak_abs_actual_delta.get(joint_name, 0.0)
                    ),
                }
                for joint_name, _count in ankle_direction_mismatch_counts.most_common()
            ],
            "worst_focus_samples": [
                {
                    "t": round(sample.t, 3),
                    "z": float(sample.z),
                    "fsm_state": sample.fsm_state,
                    "focus": sample.rl_debug_focus,
                }
                for sample in worst_focus_samples[:8]
            ],
            "fall_window_focus": fall_window_focus,
        },
        "reset_pose": reset_payload,
        "warnings": warnings,
    }

    if float(initial_position[2]) < float(args.z_threshold):
        summary["warnings"].append(
            f"initial pose.z {float(initial_position[2]):.3f} is already below z-threshold {float(args.z_threshold):.3f}"
        )

    rendered = json.dumps(summary, ensure_ascii=False, indent=2)
    print(rendered)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(rendered)
            fh.write("\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
