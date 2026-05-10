"""PyBullet 实时可视化 — 从 Isaac Sim HTTP 拉取关节数据并显示。

用法：
  conda activate SE3nv
  python scripts/pybullet_viewer.py

依赖：pybullet, requests
"""
from __future__ import annotations

import argparse
import math
import time

import pybullet as p
import pybullet_data
import requests

ISAAC_SIM_URL = "http://localhost:9200"
URDF_PATH = r"D:\Develop\Project\SynEIAgent\TGrobot4s\lite_urdf_publish\x_humanoid_0430_newfeet_newbody_publish\urdf\humanoid_publish.urdf"

# URDF joint name → PyBullet joint index (built on first frame)
_NAME_TO_IDX: dict[str, int] = {}


def _build_joint_map(robot_id: int) -> None:
    global _NAME_TO_IDX
    for i in range(p.getNumJoints(robot_id)):
        info = p.getJointInfo(robot_id, i)
        name = info[1].decode("utf-8")
        _NAME_TO_IDX[name] = i


def fetch_joint_states() -> dict[str, float] | None:
    try:
        resp = requests.get(f"{ISAAC_SIM_URL}/joint_states", timeout=0.1)
        if resp.status_code != 200:
            return None
        data = resp.json()
        return dict(zip(data["name"], data["position"]))
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="PyBullet URDF viewer with Isaac Sim feedback")
    parser.add_argument("--urdf", default=URDF_PATH, help="URDF file path")
    parser.add_argument("--url", default=ISAAC_SIM_URL, help="Isaac Sim HTTP URL")
    parser.add_argument("--hz", type=float, default=30, help="Refresh rate")
    args = parser.parse_args()

    global ISAAC_SIM_URL
    ISAAC_SIM_URL = args.url

    # Connect to PyBullet GUI
    cid = p.connect(p.GUI)
    p.setAdditionalSearchPath(pybullet_data.getDataPath(), physicsClientId=cid)
    p.setGravity(0, 0, -9.81, physicsClientId=cid)
    p.setRealTimeSimulation(0, physicsClientId=cid)

    # Load ground plane
    p.loadURDF("plane.urdf", physicsClientId=cid)

    # Load robot
    robot = p.loadURDF(
        args.urdf,
        basePosition=[0, 0, 1.0],
        useFixedBase=True,
        physicsClientId=cid,
    )
    _build_joint_map(robot)

    print(f"[Viewer] Loaded {args.urdf}")
    print(f"[Viewer] {len(_NAME_TO_IDX)} joints mapped")
    print(f"[Viewer] Polling {args.url}/joint_states at {args.hz} Hz")
    print(f"[Viewer] Close the window to exit")

    # Camera setup
    p.resetDebugVisualizerCamera(
        cameraDistance=2.5,
        cameraYaw=45,
        cameraPitch=-20,
        cameraTargetPosition=[0, 0, 0.8],
        physicsClientId=cid,
    )

    dt = 1.0 / args.hz
    frame_count = 0
    last_print = time.time()

    while p.isConnected(physicsClientId=cid):
        states = fetch_joint_states()
        if states:
            for name, pos in states.items():
                idx = _NAME_TO_IDX.get(name)
                if idx is not None:
                    p.resetJointState(robot, idx, pos, physicsClientId=cid)

        p.stepSimulation(physicsClientId=cid)
        time.sleep(dt)

        frame_count += 1
        now = time.time()
        if now - last_print >= 2.0:
            actual_hz = frame_count / (now - last_print)
            print(f"[Viewer] {actual_hz:.0f} Hz, {len(states or {})} joints updated")
            frame_count = 0
            last_print = now

    p.disconnect(physicsClientId=cid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
