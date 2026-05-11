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
        r = httpx.get(f"{url}/health", timeout=2)
        data = r.json()
        return {"ok": True, "sessions": data.get("sessions", 0), "data": data}
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
        print(f"  OK | sessions={gw['sessions']}")
    else:
        print(f"  FAIL | {gw['error']}")
        healthy = False

    # ROS Bridge
    print("\n=== ROS Bridge (8080) ===")
    if rb["ok"]:
        mode_ok = rb["control_mode"] == "rl_policy"
        fsm_ok = rb["fsm_state"] == "MLP"
        print(f"  control_mode: {rb['control_mode']} {'OK' if mode_ok else 'WARN (not rl_policy)'}")
        print(f"  rl_fsm_state: {rb['fsm_state']} {'OK' if fsm_ok else 'WAIT (not MLP)'}")
        print(f"  publish_count: {rb['publish_count']}")
        print(f"  non-zero targets: {rb['non_zero_targets']}/{rb['total_targets']}")
        if not mode_ok:
            healthy = False
    else:
        print(f"  FAIL | {rb['error']}")
        healthy = False

    # Isaac Sim
    print("\n=== Isaac Sim (9200) ===")
    if sim["ok"]:
        joints_ok = sim["joints"] > 0
        print(f"  joints: {sim['joints']} {'OK' if joints_ok else 'WARN (0)'}")
        print(f"  non-zero positions: {sim['non_zero_positions']}/{sim['positions_count']}")
        if not joints_ok:
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
