"""Pipeline health check for both RL-policy and Tiangong remote-joy paths."""
from __future__ import annotations

import argparse
import time
from typing import Any

import httpx


def check_gateway(url: str = "http://127.0.0.1:9100") -> dict[str, Any]:
    try:
        r = httpx.get(f"{url}/status", timeout=2)
        data = r.json()
        peers = data.get("peers", {}) if isinstance(data.get("peers"), dict) else {}
        open_datachannels = sum(
            1
            for peer in peers.values()
            if isinstance(peer, dict) and str(peer.get("dc_state", "")).lower() == "open"
        )
        connected_peers = sum(
            1
            for peer in peers.values()
            if isinstance(peer, dict) and str(peer.get("connection_state", "")).lower() == "connected"
        )
        return {
            "ok": True,
            "sessions": int(data.get("sessions", 0)),
            "connected_peers": connected_peers,
            "open_datachannels": open_datachannels,
            "data": data,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def check_ros_bridge(url: str = "http://127.0.0.1:8080") -> dict[str, Any]:
    try:
        r = httpx.get(f"{url}/health", timeout=2)
        data = r.json()
        control_mode = str(data.get("control_mode", "unknown"))
        joint_debug = data.get("joint_command_debug", {}) if isinstance(data.get("joint_command_debug"), dict) else {}
        joy_debug = data.get("joy_debug", {}) if isinstance(data.get("joy_debug"), dict) else {}
        publish_count = int(joint_debug.get("publish_count", 0))
        last_targets = joint_debug.get("last_targets", {}) if isinstance(joint_debug.get("last_targets"), dict) else {}
        non_zero_targets = sum(1 for v in last_targets.values() if abs(float(v)) > 0.001)
        joy_publish_count = int(joy_debug.get("publish_count", 0))
        last_axes = joy_debug.get("last_axes", []) if isinstance(joy_debug.get("last_axes"), list) else []
        non_zero_axes = sum(1 for v in last_axes if abs(float(v)) > 0.001)
        return {
            "ok": True,
            "control_mode": control_mode,
            "fsm_state": str(data.get("rl_fsm_state", "N/A")),
            "publish_count": publish_count,
            "non_zero_targets": non_zero_targets,
            "total_targets": len(last_targets),
            "joy_publish_count": joy_publish_count,
            "non_zero_axes": non_zero_axes,
            "total_axes": len(last_axes),
            "active_topic": str(data.get("sbus_data_topic") or data.get("joint_command_topic") or ""),
            "last_fsm_command": str(joy_debug.get("last_fsm_command", "")),
            "data": data,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def check_isaac_sim(url: str = "http://127.0.0.1:9200") -> dict[str, Any]:
    try:
        r_health = httpx.get(f"{url}/health", timeout=2)
        health = r_health.json()
        joints = int(health.get("joints", 0))

        r_js = httpx.get(f"{url}/joint_states", timeout=2)
        js = r_js.json()
        positions = js.get("position", []) if isinstance(js.get("position"), list) else []
        non_zero = sum(1 for p in positions if abs(float(p)) > 0.001)
        return {
            "ok": True,
            "joints": joints,
            "positions_count": len(positions),
            "non_zero_positions": non_zero,
            "gain_profile": str(health.get("gain_profile", "")),
            "limit_profile": str(health.get("limit_profile", "")),
            "limit_apply_method": str(health.get("limit_apply_method", "")),
            "positions": positions,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _bridge_healthy(rb: dict[str, Any]) -> tuple[bool, list[str]]:
    issues: list[str] = []
    mode = rb["control_mode"]
    if mode == "rl_policy":
        if rb["fsm_state"] != "MLP":
            issues.append("rl_fsm_state is not MLP")
        if rb["publish_count"] <= 0:
            issues.append("no joint targets published")
        if rb["total_targets"] <= 0 or rb["non_zero_targets"] <= 0:
            issues.append("joint targets missing or all zero")
    elif mode == "tienkung_remote_joy":
        if rb["joy_publish_count"] <= 0:
            issues.append("no remote joy messages published")
        if rb["total_axes"] != 12:
            issues.append("joy axes layout is not 12-channel")
        if rb["last_fsm_command"] == "" and rb["non_zero_axes"] <= 0:
            issues.append("no fsm command or non-zero joystick axes observed")
    else:
        issues.append(f"unsupported control_mode: {mode}")
    return len(issues) == 0, issues


def print_report(gw: dict[str, Any], rb: dict[str, Any], sim: dict[str, Any]) -> bool:
    healthy = True

    print("=== Gateway (9100) ===")
    if gw["ok"]:
        sessions_ok = gw["sessions"] > 0
        datachannel_ok = gw["open_datachannels"] > 0
        print(f"  sessions: {gw['sessions']} {'OK' if sessions_ok else 'FAIL'}")
        print(f"  connected peers: {gw['connected_peers']}")
        print(f"  open datachannels: {gw['open_datachannels']} {'OK' if datachannel_ok else 'FAIL'}")
        if not sessions_ok or not datachannel_ok:
            healthy = False
    else:
        print(f"  FAIL | {gw['error']}")
        healthy = False

    print("\n=== ROS Bridge (8080) ===")
    if rb["ok"]:
        bridge_ok, issues = _bridge_healthy(rb)
        print(f"  control_mode: {rb['control_mode']}")
        if rb["control_mode"] == "rl_policy":
            print(f"  rl_fsm_state: {rb['fsm_state']}")
            print(f"  publish_count: {rb['publish_count']}")
            print(f"  non-zero targets: {rb['non_zero_targets']}/{rb['total_targets']}")
        elif rb["control_mode"] == "tienkung_remote_joy":
            print(f"  active_topic: {rb['active_topic']}")
            print(f"  joy_publish_count: {rb['joy_publish_count']}")
            print(f"  non-zero axes: {rb['non_zero_axes']}/{rb['total_axes']}")
            print(f"  last_fsm_command: {rb['last_fsm_command'] or '-'}")
        if not bridge_ok:
            healthy = False
            for issue in issues:
                print(f"  FAIL | {issue}")
    else:
        print(f"  FAIL | {rb['error']}")
        healthy = False

    print("\n=== Isaac Sim (9200) ===")
    if sim["ok"]:
        joints_ok = sim["joints"] > 0
        positions_ok = sim["positions_count"] == sim["joints"] and sim["non_zero_positions"] > 0
        gain_ok = sim["gain_profile"] in {"policy_config", "official_lite", ""}
        limit_ok = sim["limit_profile"] in {"official_lite", ""}
        print(f"  joints: {sim['joints']} {'OK' if joints_ok else 'FAIL'}")
        print(f"  non-zero positions: {sim['non_zero_positions']}/{sim['positions_count']} {'OK' if positions_ok else 'FAIL'}")
        print(f"  gain_profile: {sim['gain_profile'] or '-'} {'OK' if gain_ok else 'FAIL'}")
        print(f"  limit_profile: {sim['limit_profile'] or '-'} {'OK' if limit_ok else 'FAIL'}")
        if sim["limit_apply_method"]:
            print(f"  limit_apply_method: {sim['limit_apply_method']}")
        if not joints_ok or not positions_ok or not gain_ok or not limit_ok:
            healthy = False
    else:
        print(f"  FAIL | {sim['error']}")
        healthy = False

    return healthy


def watch_loop(interval: float = 2.0) -> None:
    print("Watching pipeline health (Ctrl+C to stop)...\n")
    prev_positions: list[float] | None = None
    prev_publish_count: int | None = None

    try:
        while True:
            gw = check_gateway()
            rb = check_ros_bridge()
            sim = check_isaac_sim()

            position_changed = False
            if prev_positions and sim["ok"]:
                for a, b in zip(prev_positions, sim["positions"]):
                    if abs(float(a) - float(b)) > 0.001:
                        position_changed = True
                        break

            publish_growing = False
            current_publish = rb.get("joy_publish_count", 0) if rb.get("control_mode") == "tienkung_remote_joy" else rb.get("publish_count", 0)
            if prev_publish_count is not None and rb["ok"]:
                publish_growing = int(current_publish) > prev_publish_count

            print_report(gw, rb, sim)
            if position_changed:
                print("\n  >>> JOINTS MOVING <<<")
            if publish_growing:
                print("  >>> COMMAND COUNT GROWING <<<")
            print()

            prev_positions = sim.get("positions", [])
            prev_publish_count = int(current_publish)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nStopped.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Pipeline health check")
    parser.add_argument("--watch", action="store_true", help="Continuous monitoring")
    parser.add_argument("--interval", type=float, default=2.0, help="Watch interval (seconds)")
    args = parser.parse_args()

    if args.watch:
        watch_loop(args.interval)
        return 0

    gw = check_gateway()
    rb = check_ros_bridge()
    sim = check_isaac_sim()
    healthy = print_report(gw, rb, sim)

    print("\n" + ("PIPELINE OK" if healthy else "PIPELINE ISSUES DETECTED"))
    return 0 if healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
