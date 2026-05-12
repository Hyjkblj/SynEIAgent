from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "diagnose_rl_run.py"
SPEC = importlib.util.spec_from_file_location("diagnose_rl_run", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_extract_rl_debug_focus_reports_direction_mismatch_and_obs_consistency() -> None:
    payload = {
        "controller_debug": {
            "policy_command": {"x_vel": 0.1},
            "post_controller_targets": {
                "l_ankle_pitch": 0.2,
                "r_ankle_pitch": -0.8,
            },
            "fsm_debug": {
                "inference_count": 12,
                "last_infer_state_timer_s": 0.9,
                "imu": {
                    "feedback_euler_zyx": {"yaw": 0.0, "pitch": 0.0, "roll": 0.0},
                    "processed_ang_vel": [0.0, 0.0, 0.0],
                    "gravity_dir": [0.0, 0.0, -1.0],
                },
                    "obs": {
                        "joint_pos_terms": {
                            "l_ankle_pitch": -0.3,
                            "r_ankle_pitch": -0.2,
                        },
                    "joint_vel_terms": {
                        "l_ankle_pitch": 1.5,
                        "r_ankle_pitch": -2.0,
                    },
                    "action_last_terms": {
                        "l_ankle_pitch": 0.1,
                        "r_ankle_pitch": -0.2,
                    },
                },
                "policy": {
                    "raw_output_mujoco_order": {
                        "l_ankle_pitch": 2.8,
                        "r_ankle_pitch": -1.2,
                    },
                    "pre_entry_targets": {
                        "l_ankle_pitch": 0.2,
                        "r_ankle_pitch": -0.8,
                    },
                    "post_entry_targets": {
                        "l_ankle_pitch": 0.2,
                        "r_ankle_pitch": -0.8,
                    },
                },
                "feedback_joint_pos": {
                    "l_ankle_pitch": -0.8,
                    "r_ankle_pitch": -0.7,
                },
                "feedback_joint_vel": {
                    "l_ankle_pitch": 1.5,
                    "r_ankle_pitch": -2.0,
                },
            },
        },
    }

    focus = MODULE._extract_rl_debug_focus(payload)
    assert focus is not None

    left = focus["ankles"]["ankle_pitch_l_joint"]
    right = focus["ankles"]["ankle_pitch_r_joint"]

    assert left["obs_pos_term_expected_from_feedback"] == pytest.approx(-0.3)
    assert left["obs_pos_term_error"] == pytest.approx(0.0)
    assert left["target_from_raw_output_before_entry"] == pytest.approx(0.2)
    assert left["target_from_raw_output_error"] == pytest.approx(0.0)
    assert left["target_direction_sign"] == 1
    assert left["actual_direction_sign"] == -1
    assert left["target_actual_direction_match"] is False

    assert right["target_direction_sign"] == -1
    assert right["actual_direction_sign"] == -1
    assert right["target_actual_direction_match"] is True
