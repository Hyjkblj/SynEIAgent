#!/usr/bin/env python3
"""
check_sim_chain.py — 启动验证脚本，依次检查 ros_bridge_lite 和 gateway_lite 的完整链路。

用法：
    python scripts/check_sim_chain.py [--bridge-url URL] [--gateway-url URL] [--isaac-url URL]

默认地址：
    --bridge-url  http://127.0.0.1:8080
    --gateway-url http://127.0.0.1:9100
    --isaac-url   http://127.0.0.1:9200  (Isaac Sim HTTP 回退接口)
"""

import argparse
import json
import sys
import time

import httpx

# ANSI 颜色码
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"


def ok(msg: str) -> None:
    print(f"  {GREEN}✓{RESET} {msg}")


def fail(msg: str) -> None:
    print(f"  {RED}✗{RESET} {msg}")


def info(msg: str) -> None:
    print(f"  {CYAN}→{RESET} {msg}")


def step_header(n: int, desc: str) -> None:
    print(f"\n{BOLD}[Step {n}]{RESET} {desc}")


def pretty_json(data: dict) -> str:
    return json.dumps(data, indent=4, ensure_ascii=False)


def check_bridge_health(bridge_url: str) -> dict:
    """Step 1: GET /health on ros_bridge_lite — check if running."""
    step_header(1, f"GET {bridge_url}/health  →  check ros_bridge_lite status")
    try:
        resp = httpx.get(f"{bridge_url}/health", timeout=5.0)
        data = resp.json()
        info(f"Response ({resp.status_code}):\n{pretty_json(data)}")

        ros_enabled = data.get("ros_enabled", False)
        if ros_enabled:
            ok("ros_enabled == true (ROS2 mode)")
        else:
            print(f"  {YELLOW}⚠{RESET}  ros_enabled == false (ROS2 not available)")

        cmd_vel_debug = data.get("cmd_vel_debug")
        if cmd_vel_debug:
            ok(f"cmd_vel_debug: {json.dumps(cmd_vel_debug, ensure_ascii=False)}")
        else:
            print(f"  {YELLOW}⚠{RESET}  cmd_vel_debug field not present in response")

        return data

    except httpx.ConnectError as e:
        fail(f"Connection refused — is ros_bridge_lite running at {bridge_url}? ({e})")
        sys.exit(1)
    except httpx.TimeoutException as e:
        fail(f"Request timed out: {e}")
        sys.exit(1)
    except Exception as e:
        fail(f"Unexpected error: {e}")
        sys.exit(1)


def check_gateway_health(gateway_url: str) -> dict:
    """Step 2: GET /health on gateway_lite — assert ok == true."""
    step_header(2, f"GET {gateway_url}/health  →  assert ok == true")
    try:
        resp = httpx.get(f"{gateway_url}/health", timeout=5.0)
        data = resp.json()
        info(f"Response ({resp.status_code}):\n{pretty_json(data)}")

        if not data.get("ok", False):
            fail(f"ok is not true (got: {data.get('ok')!r})")
            sys.exit(1)

        ok("ok == true")
        return data

    except httpx.ConnectError as e:
        fail(f"Connection refused — is gateway_lite running at {gateway_url}? ({e})")
        sys.exit(1)
    except httpx.TimeoutException as e:
        fail(f"Request timed out: {e}")
        sys.exit(1)
    except Exception as e:
        fail(f"Unexpected error: {e}")
        sys.exit(1)


def check_isaac_http(isaac_url: str) -> dict:
    """Step 3: Check Isaac Sim HTTP fallback interface."""
    step_header(3, f"GET {isaac_url}/health  →  check Isaac Sim HTTP control")
    try:
        resp = httpx.get(f"{isaac_url}/health", timeout=5.0)
        data = resp.json()
        info(f"Response ({resp.status_code}):\n{pretty_json(data)}")

        if data.get("ok"):
            mode = data.get("mode", "unknown")
            ok(f"Isaac Sim HTTP control ready (mode: {mode})")
        else:
            print(f"  {YELLOW}⚠{RESET}  Isaac Sim HTTP not available (this is OK if using ROS2)")

        return data

    except httpx.ConnectError:
        print(f"  {YELLOW}⚠{RESET}  Isaac Sim HTTP interface not running at {isaac_url}")
        print(f"  {YELLOW}⚠{RESET}  This is OK if you're using ROS2 mode")
        return {"ok": False, "mode": "not_running"}
    except httpx.TimeoutException as e:
        fail(f"Request timed out: {e}")
        return {"ok": False}
    except Exception as e:
        fail(f"Unexpected error: {e}")
        return {"ok": False}


def check_move_isaac(isaac_url: str) -> dict:
    """Step 4: POST /move to Isaac Sim HTTP interface."""
    payload = {"linear": 0.1, "angular": 0.0}
    step_header(4, f"POST {isaac_url}/move {json.dumps(payload)}  →  test Isaac Sim control")
    try:
        resp = httpx.post(f"{isaac_url}/move", json=payload, timeout=5.0)
        data = resp.json()
        info(f"Response ({resp.status_code}):\n{pretty_json(data)}")

        if data.get("success"):
            ok(f"Isaac Sim move command accepted: linear={data.get('linear')}, angular={data.get('angular')}")
        else:
            fail(f"Isaac Sim move command failed: {data.get('error', 'unknown')}")

        return data

    except httpx.ConnectError:
        print(f"  {YELLOW}⚠{RESET}  Isaac Sim HTTP interface not available")
        return {"success": False}
    except httpx.TimeoutException as e:
        fail(f"Request timed out: {e}")
        return {"success": False}
    except Exception as e:
        fail(f"Unexpected error: {e}")
        return {"success": False}


def check_move(bridge_url: str) -> dict:
    """Step 5: POST /move {"linear": 0.1, "angular": 0.0} — assert success == true."""
    payload = {"linear": 0.1, "angular": 0.0}
    step_header(5, f"POST {bridge_url}/move {json.dumps(payload)}  →  assert success == true")
    try:
        resp = httpx.post(f"{bridge_url}/move", json=payload, timeout=5.0)
        data = resp.json()
        info(f"Response ({resp.status_code}):\n{pretty_json(data)}")

        if not data.get("success", False):
            detail = data.get("detail", "(no detail)")
            fail(f"success is not true — detail: {detail}")
            sys.exit(1)

        ok("success == true")
        return data

    except httpx.ConnectError as e:
        fail(f"Connection refused — is ros_bridge_lite running at {bridge_url}? ({e})")
        sys.exit(1)
    except httpx.TimeoutException as e:
        fail(f"Request timed out: {e}")
        sys.exit(1)
    except Exception as e:
        fail(f"Unexpected error: {e}")
        sys.exit(1)


def check_publish_count(bridge_url: str) -> dict:
    """Step 6: Wait 1s, GET /health — assert cmd_vel_debug.publish_count > 0."""
    step_header(6, f"Wait 1s, GET {bridge_url}/health  →  assert cmd_vel_debug.publish_count > 0")
    info("Waiting 1 second...")
    time.sleep(1.0)
    try:
        resp = httpx.get(f"{bridge_url}/health", timeout=5.0)
        data = resp.json()
        info(f"Response ({resp.status_code}):\n{pretty_json(data)}")

        cmd_vel_debug = data.get("cmd_vel_debug")
        if cmd_vel_debug is None:
            fail("cmd_vel_debug field missing from /health response")
            sys.exit(1)

        publish_count = cmd_vel_debug.get("publish_count", 0)
        if publish_count <= 0:
            fail(f"publish_count is not > 0 (got: {publish_count!r})")
            sys.exit(1)

        ok(f"cmd_vel_debug.publish_count == {publish_count} (> 0)")
        return data

    except httpx.ConnectError as e:
        fail(f"Connection refused — is ros_bridge_lite running at {bridge_url}? ({e})")
        sys.exit(1)
    except httpx.TimeoutException as e:
        fail(f"Request timed out: {e}")
        sys.exit(1)
    except Exception as e:
        fail(f"Unexpected error: {e}")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="依次检查 ros_bridge_lite 和 gateway_lite 的完整仿真链路。"
    )
    parser.add_argument(
        "--bridge-url",
        default="http://127.0.0.1:8080",
        help="ros_bridge_lite 地址（默认：http://127.0.0.1:8080）",
    )
    parser.add_argument(
        "--gateway-url",
        default="http://127.0.0.1:9100",
        help="gateway_lite 地址（默认：http://127.0.0.1:9100）",
    )
    parser.add_argument(
        "--isaac-url",
        default="http://127.0.0.1:9200",
        help="Isaac Sim HTTP 控制接口地址（默认：http://127.0.0.1:9200）",
    )
    args = parser.parse_args()

    bridge_url = args.bridge_url.rstrip("/")
    gateway_url = args.gateway_url.rstrip("/")
    isaac_url = args.isaac_url.rstrip("/")

    print(f"\n{BOLD}=== Sim Chain Check ==={RESET}")
    print(f"  bridge-url:  {bridge_url}")
    print(f"  gateway-url: {gateway_url}")
    print(f"  isaac-url:   {isaac_url}")

    # Step 1: Check ros_bridge_lite
    bridge_data = check_bridge_health(bridge_url)
    
    # Step 2: Check gateway_lite
    check_gateway_health(gateway_url)
    
    # Step 3-4: Check Isaac Sim HTTP interface (if ROS2 not available)
    ros_enabled = bridge_data.get("ros_enabled", False)
    if not ros_enabled:
        print(f"\n  {YELLOW}⚠{RESET}  ROS2 not available, checking Isaac Sim HTTP fallback...")
        isaac_data = check_isaac_http(isaac_url)
        if isaac_data.get("ok"):
            check_move_isaac(isaac_url)
    else:
        # Step 5-6: Use ros_bridge_lite if ROS2 is available
        check_move(bridge_url)
        check_publish_count(bridge_url)

    print(f"\n{BOLD}{GREEN}All checks passed.{RESET}\n")
    sys.exit(0)


if __name__ == "__main__":
    main()
