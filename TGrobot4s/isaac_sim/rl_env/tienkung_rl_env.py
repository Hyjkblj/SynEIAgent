"""
天工行者 RL 仿真环境

- 基于 Isaac Sim Articulation + 自定义 reward
- 可与 Isaac Lab 的 Humanoid 环境对齐接口（obs/action 空间），便于后续换 Isaac Lab 训练
"""
import os
import numpy as np
from typing import Dict, Any, Optional, Tuple

# 在 Isaac Sim 内可用
def get_articulation(prim_path: str):
    try:
        from isaacsim.core import World
        from isaacsim.core.prims import Articulation
        world = World.instance()
        if world:
            return world.scene.get_object(prim_path)
    except Exception:
        pass
    return None


class TienKungRLEnv:
    """
    简易 RL 环境包装：
    - observation: base 高度、姿态、角速度、关节位置/速度、接触（可选）
    - action: 关节位置目标或力矩（与 URDF 驱动类型一致）
    - reward: 见 reward_design.md
    """

    def __init__(
        self,
        robot_prim_path: str = "/World/tienkung",
        obs_dim: Optional[int] = None,
        action_dim: Optional[int] = None,
        reward_weights: Optional[Dict[str, float]] = None,
    ):
        self.robot_prim_path = robot_prim_path
        self.reward_weights = reward_weights or {
            "alive": 1.0,
            "height": 0.5,
            "upright": 0.3,
            "angular_vel": 0.01,
            "action_smooth": 0.001,
            "obstacle_penalty": -0.5,
        }
        self._articulation = None
        self._obs_dim = obs_dim
        self._action_dim = action_dim
        self._last_action = None
        self._step_count = 0

    def _get_robot(self):
        if self._articulation is None:
            self._articulation = get_articulation(self.robot_prim_path)
        return self._articulation

    def reset(self) -> np.ndarray:
        """重置并返回初始 obs"""
        self._articulation = None
        robot = self._get_robot()
        if robot is not None and hasattr(robot, "set_world_pose"):
            # 回到初始位姿
            robot.set_world_pose(position=np.array([0, 0, 1.0]), orientation=np.array([1, 0, 0, 0]))
        if robot is not None and hasattr(robot, "set_joint_positions"):
            # 初始关节姿态（需与 URDF 默认一致或从配置读）
            pass
        self._last_action = np.zeros(self._action_dim or 0)
        self._step_count = 0
        return self.get_observation()

    def get_observation(self) -> np.ndarray:
        """组装 observation 向量"""
        robot = self._get_robot()
        if robot is None:
            return np.zeros(self._obs_dim or 1)

        parts = []
        if hasattr(robot, "get_world_pose"):
            pos, quat = robot.get_world_pose()
            parts.append(pos)   # 3
            parts.append(quat)  # 4
        if hasattr(robot, "get_linear_velocity"):
            parts.append(robot.get_linear_velocity())  # 3
        if hasattr(robot, "get_angular_velocity"):
            parts.append(robot.get_angular_velocity())  # 3
        if hasattr(robot, "get_joint_positions"):
            parts.append(robot.get_joint_positions())  # n_joints
        if hasattr(robot, "get_joint_velocities"):
            parts.append(robot.get_joint_velocities())

        obs = np.concatenate([np.ravel(p) for p in parts if p is not None])
        if self._obs_dim is not None and len(obs) != self._obs_dim:
            obs = np.resize(obs, self._obs_dim)
        return obs.astype(np.float32)

    def step(self, action: np.ndarray) -> Tuple[np.ndarray, float, bool, Dict[str, Any]]:
        """执行一步，返回 obs, reward, done, info"""
        robot = self._get_robot()
        if robot is not None and hasattr(robot, "apply_action"):
            robot.apply_action(action)

        obs = self.get_observation()
        reward = self._compute_reward(obs, action)
        done = self._is_done(obs)
        self._last_action = action
        self._step_count += 1
        info = {"step": self._step_count}
        return obs, reward, done, info

    def _compute_reward(self, obs: np.ndarray, action: np.ndarray) -> float:
        """按 reward_design.md 计算标量 reward"""
        r = 0.0
        # 简化：obs 前几维假设为 [x,y,z, quat, v, omega, ...]
        if len(obs) >= 3:
            z = obs[2]
            r += self.reward_weights.get("alive", 0) * 1.0
            r += self.reward_weights.get("height", 0) * (-abs(z - 1.0))
        if len(obs) >= 10:
            omega = obs[7:10]
            r += self.reward_weights.get("angular_vel", 0) * (-np.dot(omega, omega))
        if self._last_action is not None and len(action) == len(self._last_action):
            r += self.reward_weights.get("action_smooth", 0) * (-np.sum((action - self._last_action) ** 2))
        return float(r)

    def _is_done(self, obs: np.ndarray) -> bool:
        """倒地或超时则 done"""
        if len(obs) >= 3:
            if obs[2] < 0.3:
                return True
        if self._step_count >= 1000:
            return True
        return False

    @property
    def observation_space(self):
        try:
            import gym
            dim = self._obs_dim or 64
            return gym.spaces.Box(low=-np.inf, high=np.inf, shape=(dim,), dtype=np.float32)
        except ImportError:
            return None

    @property
    def action_space(self):
        try:
            import gym
            dim = self._action_dim or 32
            return gym.spaces.Box(low=-1, high=1, shape=(dim,), dtype=np.float32)
        except ImportError:
            return None


def run_random_policy_steps(num_steps: int = 500):
    """用随机动作跑若干步，用于验证环境是否正常"""
    env = TienKungRLEnv()
    obs = env.reset()
    total_rew = 0.0
    for _ in range(num_steps):
        action = np.zeros(env.action_space.shape[0]) if env.action_space else np.zeros(32)
        action = np.random.uniform(-0.1, 0.1, size=action.shape)
        obs, rew, done, info = env.step(action)
        total_rew += rew
        if done:
            obs = env.reset()
    print("Total reward (random):", total_rew)
    return total_rew


if __name__ == "__main__":
    run_random_policy_steps(200)
