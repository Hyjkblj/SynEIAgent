from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_pipeline_health.py"
SPEC = importlib.util.spec_from_file_location("check_pipeline_health", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def make_gateway(*, sessions: int = 1, connected_peers: int = 1, open_datachannels: int = 1) -> dict:
    return {
        "ok": True,
        "sessions": sessions,
        "connected_peers": connected_peers,
        "open_datachannels": open_datachannels,
    }


def make_bridge(
    *,
    control_mode: str = "rl_policy",
    fsm_state: str = "MLP",
    publish_count: int = 10,
    non_zero_targets: int = 8,
    total_targets: int = 20,
    joy_publish_count: int = 0,
    non_zero_axes: int = 0,
    total_axes: int = 0,
    active_topic: str = "/sbus_data",
    last_fsm_command: str = "",
) -> dict:
    return {
        "ok": True,
        "control_mode": control_mode,
        "fsm_state": fsm_state,
        "publish_count": publish_count,
        "non_zero_targets": non_zero_targets,
        "total_targets": total_targets,
        "joy_publish_count": joy_publish_count,
        "non_zero_axes": non_zero_axes,
        "total_axes": total_axes,
        "active_topic": active_topic,
        "last_fsm_command": last_fsm_command,
    }


def make_sim(
    *,
    joints: int = 20,
    positions_count: int = 20,
    non_zero_positions: int = 8,
    gain_profile: str = "policy_config",
    limit_profile: str = "official_lite",
    limit_apply_method: str = "articulation_view.set_max_efforts+set_max_joint_velocities",
) -> dict:
    return {
        "ok": True,
        "joints": joints,
        "positions_count": positions_count,
        "non_zero_positions": non_zero_positions,
        "gain_profile": gain_profile,
        "limit_profile": limit_profile,
        "limit_apply_method": limit_apply_method,
    }


def test_print_report_requires_open_gateway_session() -> None:
    healthy = MODULE.print_report(
        make_gateway(sessions=0, open_datachannels=0),
        make_bridge(),
        make_sim(),
    )
    assert healthy is False


def test_print_report_requires_bridge_in_mlp() -> None:
    healthy = MODULE.print_report(
        make_gateway(),
        make_bridge(fsm_state="ZERO"),
        make_sim(),
    )
    assert healthy is False


def test_print_report_requires_non_zero_joint_positions() -> None:
    healthy = MODULE.print_report(
        make_gateway(),
        make_bridge(),
        make_sim(non_zero_positions=0),
    )
    assert healthy is False


def test_print_report_requires_official_lite_limit_profile() -> None:
    healthy = MODULE.print_report(
        make_gateway(),
        make_bridge(),
        make_sim(limit_profile="not_configured", limit_apply_method="not_configured"),
    )
    assert healthy is False


def test_print_report_accepts_strictly_healthy_pipeline() -> None:
    healthy = MODULE.print_report(
        make_gateway(),
        make_bridge(),
        make_sim(),
    )
    assert healthy is True


def test_print_report_accepts_healthy_remote_joy_pipeline() -> None:
    healthy = MODULE.print_report(
        make_gateway(),
        make_bridge(
            control_mode="tienkung_remote_joy",
            joy_publish_count=12,
            non_zero_axes=2,
            total_axes=12,
            last_fsm_command="gotoMLP",
        ),
        make_sim(),
    )
    assert healthy is True


def test_print_report_rejects_remote_joy_without_traffic() -> None:
    healthy = MODULE.print_report(
        make_gateway(),
        make_bridge(
            control_mode="tienkung_remote_joy",
            joy_publish_count=0,
            non_zero_axes=0,
            total_axes=12,
            last_fsm_command="",
        ),
        make_sim(),
    )
    assert healthy is False
