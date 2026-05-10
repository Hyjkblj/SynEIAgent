# Isaac Sim 仿真脚本包
# 需在 Isaac Sim 的 Python 环境中运行，或通过 Isaac Sim 的 standalone 启动器执行

"""
Isaac Sim 仿真模块

包含：
- import_tienkung_urdf: 天工机器人 URDF 导入
- ros2_control_bridge: ROS2 控制桥接
- video_bridge: 视频流桥接
- simulation_launcher: 一键启动脚本
- scene_obstacles: 场景障碍物配置
- rl_env: RL 训练环境

使用方式：
    from isaac_sim.ros2_control_bridge import create_robot_controller
    from isaac_sim.video_bridge import VideoBridge
    from isaac_sim.simulation_launcher import IsaacSimSimulation
"""

__all__ = [
    "import_tienkung_urdf",
    "ros2_control_bridge", 
    "video_bridge",
    "simulation_launcher",
    "scene_obstacles",
]

__version__ = "0.1.0"
