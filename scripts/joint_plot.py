"""关节实时 2D 可视化 — 用 matplotlib 从 Isaac Sim HTTP 拉取并显示关节位置。

用法：
  conda activate SE3nv
  python scripts/joint_plot.py
"""
from __future__ import annotations

import argparse
import time

import matplotlib.pyplot as plt
import numpy as np
import requests

ISAAC_SIM_URL = "http://localhost:9200"
LEG_JOINTS = [
    "hip_roll_l", "hip_pitch_l", "hip_yaw_l", "knee_pitch_l", "ankle_pitch_l", "ankle_roll_l",
    "hip_roll_r", "hip_pitch_r", "hip_yaw_r", "knee_pitch_r", "ankle_pitch_r", "ankle_roll_r",
]
URDF_LEG_NAMES = [
    "hip_roll_l_joint", "hip_pitch_l_joint", "hip_yaw_l_joint",
    "knee_pitch_l_joint", "ankle_pitch_l_joint", "ankle_roll_l_joint",
    "hip_roll_r_joint", "hip_pitch_r_joint", "hip_yaw_r_joint",
    "knee_pitch_r_joint", "ankle_pitch_r_joint", "ankle_roll_r_joint",
]


def fetch(url: str) -> dict[str, float] | None:
    try:
        r = requests.get(f"{url}/joint_states", timeout=0.1)
        if r.status_code != 200:
            return None
        d = r.json()
        return dict(zip(d["name"], d["position"]))
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=ISAAC_SIM_URL)
    parser.add_argument("--window", type=float, default=30, help="History window in seconds")
    args = parser.parse_args()

    plt.ion()
    fig, axes = plt.subplots(4, 3, figsize=(14, 8), sharex=True)
    fig.suptitle("Leg Joint Positions (Isaac Sim)", fontsize=14)

    for i, ax in enumerate(axes.flat):
        ax.set_title(LEG_JOINTS[i], fontsize=9)
        ax.set_ylabel("rad", fontsize=8)
        ax.grid(True, alpha=0.3)
    for ax in axes[3]:
        ax.set_xlabel("time (s)", fontsize=8)

    fig.tight_layout(rect=[0, 0, 1, 0.95])

    history: dict[str, list[tuple[float, float]]] = {name: [] for name in URDF_LEG_NAMES}
    t0 = time.time()

    print(f"[Plot] Polling {args.url}/joint_states, window={args.window}s")
    print("[Plot] Close the window to exit")

    try:
        while plt.fignum_exists(fig.number):
            states = fetch(args.url)
            now = time.time() - t0

            if states:
                for urdf_name in URDF_LEG_NAMES:
                    pos = states.get(urdf_name, 0.0)
                    history[urdf_name].append((now, pos))

                # Trim old data
                cutoff = now - args.window
                for name in URDF_LEG_NAMES:
                    history[name] = [(t, p) for t, p in history[name] if t >= cutoff]

                # Update plots
                for i, (label, urdf_name) in enumerate(zip(LEG_JOINTS, URDF_LEG_NAMES)):
                    ax = axes.flat[i]
                    ax.cla()
                    ax.set_title(label, fontsize=9)
                    ax.set_ylabel("rad", fontsize=8)
                    ax.grid(True, alpha=0.3)
                    if i >= 9:
                        ax.set_xlabel("time (s)", fontsize=8)

                    data = history[urdf_name]
                    if data:
                        ts, ps = zip(*data)
                        ax.plot(ts, ps, linewidth=1.2, color="tab:blue")
                        # Show current value
                        ax.annotate(f"{ps[-1]:.3f}", xy=(ts[-1], ps[-1]),
                                    fontsize=8, color="red", fontweight="bold")

                fig.tight_layout(rect=[0, 0, 1, 0.95])
                fig.canvas.draw_idle()

            fig.canvas.start_event_loop(0.05)

    except KeyboardInterrupt:
        print("\n[Plot] Stopped")
    except Exception as e:
        print(f"\n[Plot] Error: {e}")

    plt.close(fig)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
