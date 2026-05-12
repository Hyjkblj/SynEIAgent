"""管道健康检查：验证 RL policy 全链路是否真正工作。

检查项：
1. Gateway (9100) — WebRTC 会话
2. ROS Bridge (8080) — control_mode=rl_policy, rl_fsm_state, publish_count
3. Isaac Sim (9200) — joints > 0, 关节位置变化

用法：
  python scripts/check_pipeline_health.py
  python scripts/check_pipeline_health.py --watch  # 持续监控
"""
from __future__ import annotations

import argparse
import time

import httpx


def check_gateway(url: str = "http://127.0.0.1:9100") -> dict:
    try:
        r = httpx.get(f"{url}/status", timeout=2)
        data = r.json()
        peers = data.get("peers", {}) if isinstance(data.get("peers"), dict) else {}
        open_datachannels = sum(
            1 for peer in peers.values()
            if isinstance(peer, dict) and str(peer.get("dc_state", "")).lower() == "open"
        )
        connected_peers = sum(
            1 for peer in peers.values()
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


def check_ros_bridge(url: str = "http://127.0.0.1:8080") -> dict:
    try:
        r = httpx.get(f"{url}/health", timeout=2)
        data = r.json()
        control_mode = data.get("control_mode", "unknown")
        fsm_state = data.get("rl_fsm_state", "N/A")
        jd = data.get("joint_command_debug", {})
        publish_count = jd.get("publish_count", 0)
        last_targets = jd.get("last_targets", {})
        non_zero = sum(1 for v in last_targets.values() if abs(v) > 0.001)
        return {
            "ok": True,
            "control_mode": control_mode,
            "fsm_state": fsm_state,
            "publish_count": publish_count,
            "non_zero_targets": non_zero,
            "total_targets": len(last_targets),
            "data": data,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def check_isaac_sim(url: str = "http://127.0.0.1:9200") -> dict:
    try:
        r_health = httpx.get(f"{url}/health", timeout=2)
        health = r_health.json()
        joints = health.get("joints", 0)

        r_js = httpx.get(f"{url}/joint_states", timeout=2)
        js = r_js.json()
        positions = js.get("position", [])
        non_zero = sum(1 for p in positions if abs(p) > 0.001)
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


def print_report(gw: dict, rb: dict, sim: dict) -> bool:
    """Print health report. Returns True if pipeline is healthy."""
    healthy = True

    # Gateway
    print("=== Gateway (9100) ===")
    if gw["ok"]:
        sessions_ok = gw["sessions"] > 0
        datachannel_ok = gw["open_datachannels"] > 0
        print(
            "  sessions: "
            f"{gw['sessions']} {'OK' if sessions_ok else 'FAIL (no active session)'}"
        )
        print(f"  connected peers: {gw['connected_peers']}")
        print(
            "  open datachannels: "
            f"{gw['open_datachannels']} {'OK' if datachannel_ok else 'FAIL (control channel not open)'}"
        )
        if not sessions_ok or not datachannel_ok:
            healthy = False
    else:
        print(f"  FAIL | {gw['error']}")
        healthy = False

    # ROS Bridge
    print("\n=== ROS Bridge (8080) ===")
    if rb["ok"]:
        mode_ok = rb["control_mode"] == "rl_policy"
        fsm_ok = rb["fsm_state"] == "MLP"
        publish_ok = rb["publish_count"] > 0
        targets_ok = rb["total_targets"] > 0 and rb["non_zero_targets"] > 0
        print(f"  control_mode: {rb['control_mode']} {'OK' if mode_ok else 'FAIL (not rl_policy)'}")
        print(f"  rl_fsm_state: {rb['fsm_state']} {'OK' if fsm_ok else 'FAIL (not MLP)'}")
        print(f"  publish_count: {rb['publish_count']} {'OK' if publish_ok else 'FAIL (no joint targets published)'}")
        print(
            "  non-zero targets: "
            f"{rb['non_zero_targets']}/{rb['total_targets']} "
            f"{'OK' if targets_ok else 'FAIL (targets missing or all zero)'}"
        )
        if not mode_ok or not fsm_ok or not publish_ok or not targets_ok:
            healthy = False
    else:
        print(f"  FAIL | {rb['error']}")
        healthy = False

    # Isaac Sim
    print("\n=== Isaac Sim (9200) ===")
    if sim["ok"]:
        joints_ok = sim["joints"] > 0
        positions_ok = sim["positions_count"] == sim["joints"] and sim["non_zero_positions"] > 0
        gain_ok = sim["gain_profile"] in {"policy_config", "official_lite"}
        limit_ok = sim["limit_profile"] == "official_lite"
        print(f"  joints: {sim['joints']} {'OK' if joints_ok else 'FAIL (0)'}")
        print(
            "  non-zero positions: "
            f"{sim['non_zero_positions']}/{sim['positions_count']} "
            f"{'OK' if positions_ok else 'FAIL (joint state cache is empty or all zero)'}"
        )
        print(
            "  gain_profile: "
            f"{sim['gain_profile']} {'OK' if gain_ok else 'FAIL (expected policy_config or official_lite)'}"
        )
        print(
            "  limit_profile: "
            f"{sim['limit_profile']} {'OK' if limit_ok else 'FAIL (expected official_lite)'}"
        )
        if sim["limit_apply_method"]:
            print(f"  limit_apply_method: {sim['limit_apply_method']}")
        if not joints_ok or not positions_ok or not gain_ok or not limit_ok:
            healthy = False
    else:
        print(f"  FAIL | {sim['error']}")
        healthy = False

    return healthy


def watch_loop(interval: float = 2.0) -> None:
    """Continuously monitor pipeline health."""
    print("Watching pipeline health (Ctrl+C to stop)...\n")
    prev_positions = None
    prev_publish_count = None

    try:
        while True:
            gw = check_gateway()
            rb = check_ros_bridge()
            sim = check_isaac_sim()

            # Check for changes
            position_changed = False
            if prev_positions and sim["ok"]:
                for a, b in zip(prev_positions, sim["positions"]):
                    if abs(a - b) > 0.001:
                        position_changed = True
                        break

            publish_growing = False
            if prev_publish_count is not None and rb["ok"]:
                publish_growing = rb["publish_count"] > prev_publish_count

            print_report(gw, rb, sim)
            if position_changed:
                print("\n  >>> JOINTS MOVING <<<")
            if publish_growing:
                print("  >>> PUBLISH COUNT GROWING <<<")
            print()

            prev_positions = sim.get("positions", [])
            prev_publish_count = rb.get("publish_count", 0)
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
