"""
Isaac Sim 仿真启动器

一键启动：
- Isaac Sim 仿真环境
- ROS2 控制桥接
- 视频流桥接
- 完整的移动端控制闭环

运行方式：
  <IsaacSim>/python.sh simulation_launcher.py --urdf /path/to/robot.urdf

或使用 Isaac Sim 内置 Python：
  Windows: <IsaacSim>\\python.bat simulation_launcher.py
  Linux: <IsaacSim>/python.sh simulation_launcher.py
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from dataclasses import dataclass
from typing import Any, Optional

# 添加项目路径
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


@dataclass
class SimulationConfig:
    """仿真配置"""
    # 机器人配置
    urdf_path: Optional[str] = None
    robot_prim_path: str = "/World/robot"
    robot_version: str = "lite"
    fix_base: bool = False
    
    # ROS2 配置
    cmd_vel_topic: str = "/cmd_vel"
    odom_topic: str = "/odom"
    joint_states_topic: str = "/joint_states"
    
    # 视频配置
    video_enabled: bool = True
    gateway_url: str = "http://localhost:8088"
    camera_id: str = "main"
    camera_fps: float = 30.0
    camera_width: int = 640
    camera_height: int = 480
    
    # 仿真配置
    headless: bool = False
    physics_dt: float = 1.0 / 60.0
    render_dt: float = 1.0 / 60.0
    
    # 场景配置
    scene_config: Optional[str] = None


class IsaacSimSimulation:
    """
    Isaac Sim 仿真管理器
    
    整合：
    - 机器人导入
    - ROS2 控制桥接
    - 视频流桥接
    - 场景管理
    """
    
    def __init__(self, config: SimulationConfig):
        self.config = config
        self.enabled = False
        
        # Isaac Sim 组件
        self._sim_app: Any = None
        self._world: Any = None
        self._robot: Any = None
        
        # 桥接组件
        self._control_bridge: Any = None
        self._video_bridge: Any = None
        
        # 状态
        self._running = False
        self._start_time = 0.0
    
    def initialize(self) -> bool:
        """初始化仿真环境"""
        try:
            # 导入 Isaac Sim
            from isaacsim import SimulationApp
            
            # 创建仿真应用
            app_config = {
                "headless": self.config.headless,
                "width": 1280,
                "height": 720,
            }
            self._sim_app = SimulationApp(app_config)
            
            print("[Simulation] Isaac Sim initialized")
            
            # 设置场景
            self._setup_world()
            
            # 导入机器人
            self._import_robot()
            
            # 初始化控制桥接
            self._init_control_bridge()
            
            # 初始化视频桥接
            if self.config.video_enabled:
                self._init_video_bridge()
            
            # 添加场景障碍物
            self._setup_scene()
            
            self.enabled = True
            return True
            
        except Exception as e:
            print(f"[Simulation] Initialization failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _setup_world(self) -> None:
        """设置仿真世界"""
        try:
            from isaacsim.core.api import World
            
            self._world = World(
                stage_units_in_meters=1.0,
                physics_dt=self.config.physics_dt,
                render_dt=self.config.render_dt,
            )
            
            # 添加地面
            self._world.scene.add_default_ground_plane()
            
            print("[Simulation] World created")
            
        except Exception as e:
            print(f"[Simulation] World setup failed: {e}")
    
    def _import_robot(self) -> None:
        """导入机器人"""
        if not self.config.urdf_path:
            print("[Simulation] No URDF path provided, skipping robot import")
            return
        
        if not os.path.isfile(self.config.urdf_path):
            print(f"[Simulation] URDF not found: {self.config.urdf_path}")
            return
        
        try:
            from isaac_sim.import_tienkung_urdf import import_tienkung
            
            success, prim_path = import_tienkung(
                self.config.urdf_path,
                fix_base=self.config.fix_base
            )
            
            if success:
                print(f"[Simulation] Robot imported at: {prim_path}")
                self.config.robot_prim_path = str(prim_path)
                
                # 创建 Articulation
                try:
                    try:
                        from isaacsim.core.prims import SingleArticulation as ArticulationClass
                    except ImportError:
                        from isaacsim.core.prims import Articulation as ArticulationClass

                    self._robot = ArticulationClass(
                        prim_path=prim_path,
                        name="robot"
                    )
                    self._robot.initialize()
                    
                except Exception as e:
                    print(f"[Simulation] Articulation creation failed: {e}")
            else:
                print(f"[Simulation] Robot import failed: {prim_path}")
                
        except ImportError:
            print("[Simulation] import_tienkung_urdf not available")
        except Exception as e:
            print(f"[Simulation] Robot import error: {e}")
    
    def _init_control_bridge(self) -> None:
        """初始化控制桥接"""
        try:
            from isaac_sim.ros2_control_bridge import create_robot_controller
            
            self._control_bridge = create_robot_controller(
                robot_prim_path=self.config.robot_prim_path,
                cmd_vel_topic=self.config.cmd_vel_topic,
                odom_topic=self.config.odom_topic,
                joint_states_topic=self.config.joint_states_topic,
            )
            
            if self._robot:
                self._control_bridge.set_robot(self._robot)
            
            if self._world:
                self._control_bridge.set_world(self._world)
            
            print("[Simulation] Control bridge initialized")
            
        except ImportError:
            print("[Simulation] ros2_control_bridge not available")
        except Exception as e:
            print(f"[Simulation] Control bridge init failed: {e}")
    
    def _init_video_bridge(self) -> None:
        """初始化视频桥接"""
        try:
            from isaac_sim.video_bridge import VideoBridge, VideoBridgeConfig
            
            config = VideoBridgeConfig(
                gateway_url=self.config.gateway_url,
                camera_prim_path=f"{self.config.robot_prim_path}/camera",
                camera_id=self.config.camera_id,
                fps=self.config.camera_fps,
                width=self.config.camera_width,
                height=self.config.camera_height,
            )
            
            self._video_bridge = VideoBridge(config)
            
            print("[Simulation] Video bridge initialized")
            
        except ImportError:
            print("[Simulation] video_bridge not available")
        except Exception as e:
            print(f"[Simulation] Video bridge init failed: {e}")
    
    def _setup_scene(self) -> None:
        """设置场景"""
        try:
            from isaac_sim.scene_obstacles import build_demo_obstacle_scene
            import omni.usd
            
            stage = omni.usd.get_context().get_stage()
            if stage:
                build_demo_obstacle_scene(stage)
                print("[Simulation] Scene obstacles added")
                
        except ImportError:
            print("[Simulation] scene_obstacles not available")
        except Exception as e:
            print(f"[Simulation] Scene setup failed: {e}")
    
    def run(self) -> None:
        """运行仿真"""
        if not self.enabled:
            print("[Simulation] Cannot run: not initialized")
            return
        
        print("\n" + "=" * 60)
        print("[Simulation] Starting...")
        print("=" * 60)
        print(f"  Robot: {self.config.robot_prim_path}")
        print(f"  ROS2: {self.config.cmd_vel_topic}")
        print(f"  Video: {self.config.gateway_url}")
        print("=" * 60)
        print("\nPress Ctrl+C to stop\n")
        
        # 重置世界
        self._world.reset()
        
        # 启动视频桥接
        if self._video_bridge:
            self._video_bridge.start()
        
        self._running = True
        self._start_time = time.time()
        
        # 主循环
        try:
            async def main_loop():
                # 启动视频发送任务
                video_task = None
                if self._video_bridge:
                    video_task = asyncio.create_task(self._video_bridge.send_loop())
                
                while self._sim_app.is_running() and self._running:
                    # 步进仿真
                    self._world.step(render=True)
                    
                    # 更新控制桥接
                    if self._control_bridge:
                        self._control_bridge.update(self.config.physics_dt)
                    
                    # 让出控制权
                    await asyncio.sleep(0.001)
                
                # 清理
                if video_task:
                    video_task.cancel()
            
            asyncio.run(main_loop())
            
        except KeyboardInterrupt:
            print("\n[Simulation] Interrupted by user")
        finally:
            self.shutdown()
    
    def shutdown(self) -> None:
        """关闭仿真"""
        print("[Simulation] Shutting down...")
        
        self._running = False
        
        # 停止视频桥接
        if self._video_bridge:
            self._video_bridge.stop()
            self._video_bridge.close()
        
        # 停止控制桥接
        if self._control_bridge:
            self._control_bridge.stop()
            self._control_bridge.close()
        
        # 关闭仿真应用
        if self._sim_app:
            self._sim_app.close()
        
        elapsed = time.time() - self._start_time
        print(f"[Simulation] Shutdown complete. Runtime: {elapsed:.1f}s")


def get_default_urdf_path(version: str = "lite") -> str:
    """获取默认 URDF 路径"""
    urdf_root = os.path.join(REPO_ROOT, "urdf")
    
    paths = {
        "lite": os.path.join(urdf_root, "lite", "urdf", "humanoid_publish.urdf"),
        "pro": os.path.join(urdf_root, "pro", "urdf", "humanoid_publish.urdf"),
        "tiangong2pro": os.path.join(urdf_root, "tiangong2pro-urdf", "urdf", "tiangong2.0_pro_urdf.urdf"),
    }
    
    return paths.get(version, paths["lite"])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Isaac Sim Simulation Launcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 使用默认配置启动
  python simulation_launcher.py
  
  # 指定 URDF 文件
  python simulation_launcher.py --urdf /path/to/robot.urdf
  
  # 无头模式
  python simulation_launcher.py --headless
  
  # 自定义 Gateway URL
  python simulation_launcher.py --gateway-url http://192.168.1.100:8088
"""
    )
    
    # 机器人配置
    parser.add_argument("--urdf", type=str, default=None, help="URDF file path")
    parser.add_argument("--robot-version", default="lite", choices=["lite", "pro", "tiangong2pro"])
    parser.add_argument("--robot-prim", default="/World/robot", help="Robot prim path")
    parser.add_argument("--fix-base", action="store_true", help="Fix robot base")
    
    # ROS2 配置
    parser.add_argument("--cmd-vel-topic", default="/cmd_vel")
    parser.add_argument("--odom-topic", default="/odom")
    parser.add_argument("--joint-states-topic", default="/joint_states")
    
    # 视频配置
    parser.add_argument("--gateway-url", default="http://localhost:8088", help="Gateway URL")
    parser.add_argument("--camera-id", default="main")
    parser.add_argument("--camera-fps", type=float, default=30.0)
    parser.add_argument("--no-video", action="store_true", help="Disable video streaming")
    
    # 仿真配置
    parser.add_argument("--headless", action="store_true", help="Run headless")
    parser.add_argument("--scene-config", type=str, default=None, help="Scene config JSON")
    
    args = parser.parse_args()
    
    # 确定 URDF 路径
    urdf_path = args.urdf
    if urdf_path is None:
        urdf_path = get_default_urdf_path(args.robot_version)
        if not os.path.isfile(urdf_path):
            print(f"[Warning] Default URDF not found: {urdf_path}")
            print("[Warning] Running without robot. Use --urdf to specify URDF file.")
            urdf_path = None
    
    # 创建配置
    config = SimulationConfig(
        urdf_path=urdf_path,
        robot_prim_path=args.robot_prim,
        robot_version=args.robot_version,
        fix_base=args.fix_base,
        cmd_vel_topic=args.cmd_vel_topic,
        odom_topic=args.odom_topic,
        joint_states_topic=args.joint_states_topic,
        video_enabled=not args.no_video,
        gateway_url=args.gateway_url,
        camera_id=args.camera_id,
        camera_fps=args.camera_fps,
        headless=args.headless,
        scene_config=args.scene_config,
    )
    
    # 创建并运行仿真
    sim = IsaacSimSimulation(config)
    
    if sim.initialize():
        sim.run()
        return 0
    else:
        print("[Error] Simulation initialization failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
