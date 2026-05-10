"""
Isaac Sim ROS2 控制桥接节点

功能：
- 订阅 ROS2 /cmd_vel (geometry_msgs/Twist)
- 控制仿真机器人移动（支持差速底盘和人形机器人）
- 发布 /odom (nav_msgs/Odometry) 和 /joint_states (sensor_msgs/JointState)

运行方式：
  在 Isaac Sim 的 Python 环境中运行：
  <IsaacSim>/python.sh ros2_control_bridge.py --robot-prim /World/tienkung

依赖：
  - Isaac Sim 4.x/5.x
  - ROS2 Humble/Iron
  - geometry_msgs, nav_msgs, sensor_msgs
"""
from __future__ import annotations

import argparse
import asyncio
import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import numpy as np


@dataclass
class RobotControlConfig:
    """机器人控制配置"""
    robot_prim_path: str = "/World/robot"
    cmd_vel_topic: str = "/cmd_vel"
    joint_command_topic: str = "/joint_command"
    odom_topic: str = "/odom"
    joint_states_topic: str = "/joint_states"
    odom_frame: str = "odom"
    base_frame: str = "base_link"
    
    # 运动学参数
    max_linear_velocity: float = 1.0  # m/s
    max_angular_velocity: float = 1.5  # rad/s
    wheel_base: float = 0.4  # 轮距（差速底盘）
    
    # 发布频率
    odom_publish_hz: float = 50.0
    joint_states_publish_hz: float = 50.0
    
    # 速度衰减（模拟）
    linear_decay: float = 0.95
    angular_decay: float = 0.95
    joint_command_timeout_s: float = 0.4
    joint_stiffness: float = 180.0
    joint_damping: float = 8.0
    # 逐关节 PD 增益（来自 tg22_config.yaml），优先级高于 joint_stiffness/damping
    joint_kp: Optional[list[float]] = None
    joint_kd: Optional[list[float]] = None


class IsaacSimRobotController:
    """
    Isaac Sim 机器人控制器
    
    支持两种模式：
    1. 差速底盘模式：直接控制 base 的线速度和角速度
    2. 人形机器人模式：通过关节控制实现行走
    """
    
    def __init__(self, config: RobotControlConfig):
        self.config = config
        self.enabled = False
        self.error = ""
        
        # ROS2 相关
        self._rclpy: Any = None
        self._node: Any = None
        self._cmd_vel_sub: Any = None
        self._joint_command_sub: Any = None
        self._odom_pub: Any = None
        self._joint_states_pub: Any = None
        self._twist_type: Any = None
        self._odom_type: Any = None
        self._joint_state_type: Any = None
        
        # Isaac Sim 相关
        self._world: Any = None
        self._robot: Any = None
        self._articulation: Any = None
        
        # 状态
        self._current_linear: float = 0.0
        self._current_angular: float = 0.0
        self._target_linear: float = 0.0
        self._target_angular: float = 0.0
        self._last_cmd_time: float = 0.0
        self._cmd_timeout: float = 0.5  # 秒
        
        # 里程计
        self._odom_x: float = 0.0
        self._odom_y: float = 0.0
        self._odom_theta: float = 0.0
        self._last_odom_time: float = 0.0
        
        # 关节状态
        self._joint_names: list[str] = []
        self._joint_positions: dict[str, float] = {}
        self._target_joint_positions: dict[str, float] = {}
        self._last_joint_cmd_time: float = 0.0
        self._cached_joint_pos: np.ndarray = np.zeros(0, dtype=np.float64)

        # IMU 状态缓存（从物理引擎实时读取）
        self._imu_quat: list[float] = [1.0, 0.0, 0.0, 0.0]  # [x, y, z, w]
        self._imu_omega: list[float] = [0.0, 0.0, 0.0]  # rad/s
        self._imu_accel: list[float] = [0.0, 0.0, 9.81]  # m/s^2
        self._prev_linear_vel: np.ndarray = np.zeros(3)

        self._init_ros2()
        # Always start HTTP server for external access (main.py feedback polling)
        if not hasattr(self, '_http_thread') or self._http_thread is None:
            self._start_http_server()

    def _start_http_server(self, port: int = 9200) -> None:
        """Start HTTP server providing /health, /joint_states, /imu, /joint_command, /move."""
        import threading
        import json
        from http.server import HTTPServer, BaseHTTPRequestHandler

        controller = self

        class ControlHandler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                pass

            def _json_response(self, code: int, data: dict) -> None:
                try:
                    self.send_response(code)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(json.dumps(data).encode())
                except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, OSError):
                    pass  # 客户端已断开，忽略

            def do_GET(self):
                if self.path == "/health":
                    self._json_response(200, {
                        "ok": True,
                        "ros_enabled": controller.enabled,
                        "error": controller.error,
                        "joints": len(controller._joint_names),
                    })
                elif self.path == "/joint_states":
                    names = list(controller._joint_names)
                    # 使用缓存数据，避免物理步进期间调用 get_joint_positions()
                    positions = [controller._joint_positions.get(n, 0.0) for n in names]
                    self._json_response(200, {
                        "name": names,
                        "position": positions,
                        "velocity": [],
                    })
                elif self.path == "/imu":
                    from math import asin, atan2
                    qx, qy, qz, qw = controller._imu_quat
                    sinr_cosp = 2.0 * (qw * qx + qy * qz)
                    cosr_cosp = 1.0 - 2.0 * (qx * qx + qy * qy)
                    roll = atan2(sinr_cosp, cosr_cosp)
                    sinp = 2.0 * (qw * qy - qz * qx)
                    pitch = asin(max(-1.0, min(1.0, sinp)))
                    siny_cosp = 2.0 * (qw * qz + qx * qy)
                    cosy_cosp = 1.0 - 2.0 * (qy * qy + qz * qz)
                    yaw = atan2(siny_cosp, cosy_cosp)
                    self._json_response(200, {
                        "orientation": controller._imu_quat,
                        "euler": {"yaw": yaw, "pitch": pitch, "roll": roll},
                        "angular_velocity": controller._imu_omega,
                        "linear_acceleration": controller._imu_accel,
                    })
                else:
                    self._json_response(404, {"error": "not found"})

            def do_POST(self):
                if self.path == "/move":
                    try:
                        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                        linear = float(body.get("linear", 0.0))
                        angular = float(body.get("angular", 0.0))
                        controller._target_linear = float(np.clip(linear,
                            -controller.config.max_linear_velocity, controller.config.max_linear_velocity))
                        controller._target_angular = float(np.clip(angular,
                            -controller.config.max_angular_velocity, controller.config.max_angular_velocity))
                        controller._last_cmd_time = time.time()
                        self._json_response(200, {"success": True, "linear": controller._target_linear, "angular": controller._target_angular})
                    except Exception as ex:
                        self._json_response(400, {"success": False, "error": str(ex)})
                elif self.path == "/joint_command":
                    try:
                        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                        names = body.get("name", [])
                        positions = body.get("position", [])
                        if names and positions and len(names) == len(positions):
                            controller._target_joint_positions = {str(n): float(p) for n, p in zip(names, positions)}
                            controller._last_joint_cmd_time = time.time()
                            self._json_response(200, {"success": True, "joints": len(names)})
                        else:
                            self._json_response(400, {"success": False, "error": "name/position mismatch"})
                    except Exception as ex:
                        self._json_response(400, {"success": False, "error": str(ex)})
                elif self.path == "/stop":
                    controller.stop()
                    self._json_response(200, {"success": True})
                else:
                    self._json_response(404, {"error": "not found"})

        def run_server():
            server = HTTPServer(("0.0.0.0", port), ControlHandler)
            server.serve_forever()

        self._http_thread = threading.Thread(target=run_server, daemon=True)
        self._http_thread.start()
        print(f"[HTTP] API ready on http://0.0.0.0:{port}  (/health /joint_states /imu /joint_command /move /stop)")

    def _init_ros2(self) -> None:
        """初始化 ROS2 节点和话题"""
        try:
            import rclpy
            from rclpy.node import Node
            from geometry_msgs.msg import Twist
            from nav_msgs.msg import Odometry
            from sensor_msgs.msg import JointState
            
            self._rclpy = rclpy
            self._twist_type = Twist
            self._odom_type = Odometry
            self._joint_state_type = JointState
            
            if not rclpy.ok():
                rclpy.init(args=None)
            
            self._node = rclpy.create_node("isaac_sim_control_bridge")
            
            # 订阅 /cmd_vel
            self._cmd_vel_sub = self._node.create_subscription(
                Twist,
                self.config.cmd_vel_topic,
                self._cmd_vel_callback,
                10
            )

            self._joint_command_sub = self._node.create_subscription(
                JointState,
                self.config.joint_command_topic,
                self._joint_command_callback,
                10
            )
            
            # 发布 /odom
            self._odom_pub = self._node.create_publisher(
                Odometry,
                self.config.odom_topic,
                10
            )
            
            # 发布 /joint_states
            self._joint_states_pub = self._node.create_publisher(
                JointState,
                self.config.joint_states_topic,
                10
            )
            
            self.enabled = True
            print(f"[ROS2] Control bridge initialized")
            print(f"[ROS2] Subscribed to: {self.config.cmd_vel_topic}, {self.config.joint_command_topic}")
            print(f"[ROS2] Publishing: {self.config.odom_topic}, {self.config.joint_states_topic}")
            
        except Exception as e:
            self.error = str(e)
            print(f"[ROS2] Initialization failed: {e}")
            print(f"[HTTP] Using HTTP control interface (already running)")
            self.enabled = True
    
    def _init_http_fallback(self) -> None:
        """初始化 HTTP 回退接口（当 ROS2 不可用时）"""
        import threading
        import json
        from http.server import HTTPServer, BaseHTTPRequestHandler
        
        controller = self  # 闭包捕获
        
        class ControlHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass  # 静默日志
            
            def do_GET(self):
                if self.path == "/health":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "ok": True,
                        "mode": "http_fallback",
                        "ros_enabled": False,
                        "error": controller.error
                    }).encode())
                else:
                    self.send_response(404)
                    self.end_headers()
            
            def do_POST(self):
                if self.path == "/move":
                    content_length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(content_length)
                    try:
                        data = json.loads(body)
                        linear = float(data.get("linear", 0.0))
                        angular = float(data.get("angular", 0.0))
                        
                        # 直接设置目标速度
                        controller._target_linear = float(np.clip(
                            linear,
                            -controller.config.max_linear_velocity,
                            controller.config.max_linear_velocity
                        ))
                        controller._target_angular = float(np.clip(
                            angular,
                            -controller.config.max_angular_velocity,
                            controller.config.max_angular_velocity
                        ))
                        controller._last_cmd_time = time.time()
                        
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps({
                            "success": True,
                            "linear": controller._target_linear,
                            "angular": controller._target_angular
                        }).encode())
                    except Exception as ex:
                        self.send_response(400)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps({
                            "success": False,
                            "error": str(ex)
                        }).encode())
                else:
                    self.send_response(404)
                    self.end_headers()
        
        def run_server():
            server = HTTPServer(("0.0.0.0", 9200), ControlHandler)
            server.serve_forever()
        
        self._http_thread = threading.Thread(target=run_server, daemon=True)
        self._http_thread.start()
        self.enabled = True  # 启用控制器
        print(f"[HTTP] Control interface ready on http://0.0.0.0:9200/move")

    def _cmd_vel_callback(self, msg: Any) -> None:
        """Handle /cmd_vel velocity command."""
        self._target_linear = float(msg.linear.x)
        self._target_angular = float(msg.angular.z)
        self._last_cmd_time = time.time()

        self._target_linear = np.clip(
            self._target_linear,
            -self.config.max_linear_velocity,
            self.config.max_linear_velocity,
        )
        self._target_linear = np.clip(
            self._target_linear,
            -self.config.max_linear_velocity,
            self.config.max_linear_velocity,
        )
        self._target_angular = np.clip(
            self._target_angular,
            -self.config.max_angular_velocity,
            self.config.max_angular_velocity,
        )

    def _joint_command_callback(self, msg: Any) -> None:
        """Handle /joint_command (sensor_msgs/JointState) messages."""
        names = list(getattr(msg, "name", []) or [])
        positions = list(getattr(msg, "position", []) or [])
        if not positions:
            return

        if names and len(names) == len(positions):
            self._target_joint_positions = {str(n): float(p) for n, p in zip(names, positions)}
        elif self._joint_names and len(self._joint_names) == len(positions):
            self._target_joint_positions = {
                str(n): float(p) for n, p in zip(self._joint_names, positions)
            }
        else:
            return

        self._last_joint_cmd_time = time.time()

    def set_robot(self, robot: Any) -> None:

        """设置机器人 Articulation 对象"""
        self._robot = robot
        self._articulation = robot

        # 获取关节名称（兼容不同 Isaac Sim 版本）
        if hasattr(robot, 'dof_names'):
            names = robot.dof_names
            self._joint_names = list(names) if not callable(names) else list(names())
        elif hasattr(robot, 'get_joint_names'):
            self._joint_names = list(robot.get_joint_names())
        elif hasattr(robot, 'joint_names'):
            names = robot.joint_names
            self._joint_names = list(names) if not callable(names) else list(names())

        print(f"[Control] Robot set with {len(self._joint_names)} joints")
        self._cached_joint_pos = np.zeros(len(self._joint_names), dtype=np.float64)
        self._configure_joint_drive()
    
    def set_world(self, world: Any) -> None:
        """设置 Isaac Sim World 对象"""
        self._world = world


    def _configure_joint_drive(self) -> None:
        """
        Try to increase joint stiffness/damping for position commands.
        Safe no-op when API is unavailable.
        """
        if self._articulation is None:
            return
        if not self._joint_names:
            return

        n = len(self._joint_names)
        if self.config.joint_kp and self.config.joint_kd and len(self.config.joint_kp) >= n:
            kps = np.array(self.config.joint_kp[:n], dtype=np.float64)
            kds = np.array(self.config.joint_kd[:n], dtype=np.float64)
            print(f"[Control] Per-joint gains from policy config ({n} joints)")
        else:
            kps = np.full(n, float(self.config.joint_stiffness))
            kds = np.full(n, float(self.config.joint_damping))
            print(
                f"[Control] Uniform gains: stiffness={self.config.joint_stiffness}, "
                f"damping={self.config.joint_damping}"
            )

        # 尝试设置增益（不同 Isaac Sim 版本 API 不同）
        if hasattr(self._articulation, "set_gains"):
            try:
                self._articulation.set_gains(kps, kds)
                print("[Control] Joint gains applied via set_gains()")
            except Exception as e:
                print(f"[Control] set_gains() failed: {e}")
        elif hasattr(self._articulation, "get_articulation_controller"):
            try:
                ctrl = self._articulation.get_articulation_controller()
                if ctrl and hasattr(ctrl, "set_gains"):
                    ctrl.set_gains(kps, kds)
                    print("[Control] Joint gains applied via controller.set_gains()")
            except Exception as e:
                print(f"[Control] controller.set_gains() failed: {e}")
        else:
            print("[Control] set_gains not available, using URDF defaults")
    
    def update(self, dt: float) -> None:
        """
        每帧更新
        
        Args:
            dt: 时间步长（秒）
        """
        if not self.enabled:
            return
        
        # 检查命令超时
        current_time = time.time()
        if current_time - self._last_cmd_time > self._cmd_timeout:
            self._target_linear = 0.0
            self._target_angular = 0.0
        
        # 平滑过渡
        self._current_linear = self._lerp(
            self._current_linear, 
            self._target_linear, 
            0.1
        )
        self._current_angular = self._lerp(
            self._current_angular, 
            self._target_angular, 
            0.1
        )
        
        # 应用到机器人
        if self._target_joint_positions:
            self._apply_joint_targets()
        elif self._has_recent_joint_command(current_time):
            self._apply_joint_targets()
        else:
            self._apply_velocity(self._current_linear, self._current_angular)

        # 从物理引擎读取 IMU 数据
        self._update_imu(dt)

        # 更新里程计
        self._update_odometry(dt)
        
        # ROS2 spin (仅在 ROS2 可用时)
        if self._rclpy and self._node:
            self._rclpy.spin_once(self._node, timeout_sec=0.0)

    def _lerp(self, current: float, target: float, alpha: float) -> float:
        """Linear interpolation helper."""
        return current + (target - current) * alpha

    def _has_recent_joint_command(self, now: float) -> bool:
        if not self._target_joint_positions:
            return False
        return (now - self._last_joint_cmd_time) <= float(self.config.joint_command_timeout_s)

    def _apply_joint_targets(self) -> None:
        """Apply joint position targets via ArticulationController (physics-step safe write-only)."""
        if self._articulation is None:
            return
        if not self._target_joint_positions:
            return

        try:
            ctrl = None
            if hasattr(self._articulation, "get_articulation_controller"):
                ctrl = self._articulation.get_articulation_controller()

            if ctrl is None or not hasattr(ctrl, "set_joint_position_targets"):
                return

            if len(self._cached_joint_pos) == len(self._joint_names):
                targets = self._cached_joint_pos.copy()
            else:
                targets = np.zeros(len(self._joint_names), dtype=np.float64)
            has_any = False
            for joint_name, target in self._target_joint_positions.items():
                if joint_name in self._joint_names:
                    idx = self._joint_names.index(joint_name)
                    targets[idx] = float(target)
                    has_any = True
            if has_any:
                ctrl.set_joint_position_targets(targets)
        except Exception as e:
            print(f"[Control] Error applying joint targets: {e}")

    def _apply_velocity(self, linear: float, angular: float) -> None:

        """应用速度到机器人"""
        if self._robot is None:
            return
        
        try:
            # 方式1：直接设置速度（适用于差速底盘）
            if hasattr(self._robot, 'set_linear_velocity'):
                self._robot.set_linear_velocity([linear, 0.0, 0.0])
            if hasattr(self._robot, 'set_angular_velocity'):
                self._robot.set_angular_velocity([0.0, 0.0, angular])
            
            # 方式2：通过关节控制（适用于人形机器人）
            # 这里可以添加步态控制逻辑
            # self._apply_walking_gait(linear, angular)
            
        except Exception as e:
            print(f"[Control] Error applying velocity: {e}")
    
    def _apply_walking_gait(self, linear: float, angular: float) -> None:
        """
        应用行走步态（人形机器人）
        
        这是一个简化的步态控制器，实际应用中需要更复杂的实现
        """
        if not self._joint_names or self._articulation is None:
            return
        
        # 简化：根据速度调整关节目标
        # 实际实现需要完整的步态规划
        pass
    
    def _update_imu(self, dt: float) -> None:
        """从物理引擎读取真实 IMU 数据"""
        if self._robot is None:
            return
        try:
            # 方向四元数（兼容 get_world_pose / get_world_poses）
            if hasattr(self._robot, 'get_world_pose'):
                _, quat = self._robot.get_world_pose()
                self._imu_quat = [float(q) for q in quat]
            elif hasattr(self._robot, 'get_world_poses'):
                _, quats = self._robot.get_world_poses()
                if len(quats) > 0:
                    self._imu_quat = [float(q) for q in quats[0]]
            # 角速度
            if hasattr(self._robot, 'get_angular_velocity'):
                omega = self._robot.get_angular_velocity()
                self._imu_omega = [float(v) for v in omega]
            # 线加速度（数值微分 + 重力补偿）
            if hasattr(self._robot, 'get_linear_velocity') and dt > 0:
                vel = np.array(self._robot.get_linear_velocity(), dtype=np.float64)
                accel = (vel - self._prev_linear_vel) / dt
                self._imu_accel = [float(accel[0]), float(accel[1]), float(accel[2] + 9.81)]
                self._prev_linear_vel = vel
        except Exception:
            pass

    def _update_odometry(self, dt: float) -> None:
        """更新里程计"""
        # 积分更新位置
        self._odom_x += self._current_linear * math.cos(self._odom_theta) * dt
        self._odom_y += self._current_linear * math.sin(self._odom_theta) * dt
        self._odom_theta += self._current_angular * dt
        
        # 归一化角度
        self._odom_theta = math.atan2(
            math.sin(self._odom_theta), 
            math.cos(self._odom_theta)
        )
        
        # 发布里程计消息
        self._publish_odometry()
        
        # 发布关节状态
        self._publish_joint_states()
    
    def _publish_odometry(self) -> None:
        """发布里程计消息"""
        if not self._odom_pub:
            return
        
        msg = self._odom_type()
        msg.header.stamp = self._node.get_clock().now().to_msg()
        msg.header.frame_id = self.config.odom_frame
        msg.child_frame_id = self.config.base_frame
        
        # 位置
        msg.pose.pose.position.x = self._odom_x
        msg.pose.pose.position.y = self._odom_y
        msg.pose.pose.position.z = 0.0
        
        # 姿态（四元数）
        half_theta = self._odom_theta / 2.0
        msg.pose.pose.orientation.x = 0.0
        msg.pose.pose.orientation.y = 0.0
        msg.pose.pose.orientation.z = math.sin(half_theta)
        msg.pose.pose.orientation.w = math.cos(half_theta)
        
        # 速度
        msg.twist.twist.linear.x = self._current_linear
        msg.twist.twist.angular.z = self._current_angular
        
        self._odom_pub.publish(msg)
    
    def _publish_joint_states(self) -> None:
        """发布关节状态消息（使用缓存数据）"""
        if not self._joint_states_pub or not self._joint_names:
            return

        msg = self._joint_state_type()
        msg.header.stamp = self._node.get_clock().now().to_msg()
        msg.name = self._joint_names
        msg.position = [self._joint_positions.get(n, 0.0) for n in self._joint_names]
        msg.velocity = [0.0] * len(self._joint_names)
        msg.effort = [0.0] * len(self._joint_names)

        self._joint_states_pub.publish(msg)
    
    def get_robot_pose(self) -> tuple[np.ndarray, np.ndarray]:
        """获取机器人位姿"""
        if self._robot and hasattr(self._robot, 'get_world_pose'):
            pos, quat = self._robot.get_world_pose()
            return np.array(pos), np.array(quat)
        return np.zeros(3), np.array([0, 0, 0, 1])

    def stop(self) -> None:
        """Stop the robot and clear active command targets."""
        self._target_linear = 0.0
        self._target_angular = 0.0
        self._target_joint_positions = {}
        self._last_joint_cmd_time = 0.0
        self._apply_velocity(0.0, 0.0)

    def close(self) -> None:
        """Cleanup ROS2 node resources."""
        if self._node:
            self._node.destroy_node()


def create_robot_controller(
    robot_prim_path: str = "/World/robot",
    cmd_vel_topic: str = "/cmd_vel",
    joint_command_topic: str = "/joint_command",
    **kwargs
) -> IsaacSimRobotController:
    """
    创建机器人控制器的便捷函数
    
    Args:
        robot_prim_path: 机器人在 USD 场景中的路径
        cmd_vel_topic: ROS2 速度命令话题
        **kwargs: 其他配置参数
    
    Returns:
        IsaacSimRobotController 实例
    """
    config = RobotControlConfig(
        robot_prim_path=robot_prim_path,
        cmd_vel_topic=cmd_vel_topic,
        joint_command_topic=joint_command_topic,
        **kwargs
    )
    return IsaacSimRobotController(config)


# ==================== Isaac Sim 集成 ====================

class IsaacSimControlExtension:
    """
    Isaac Sim 扩展，用于在仿真循环中集成 ROS2 控制
    """
    
    def __init__(self, controller: IsaacSimRobotController):
        self.controller = controller
        self._physics_step: Optional[Callable] = None
    
    def on_startup(self) -> None:
        """扩展启动"""
        print("[Extension] ROS2 Control Bridge starting...")
        
        # 获取 World 和 Robot
        self._setup_isaac_sim()
        
        # 注册物理步进回调
        self._register_physics_callback()
    
    def _setup_isaac_sim(self) -> None:
        """设置 Isaac Sim 环境"""
        try:
            from isaacsim import SimulationApp
            
            # 获取 simulation app
            sim_app = SimulationApp.instance()
            if sim_app:
                world = sim_app.world
                self.controller.set_world(world)
                
                # 获取机器人
                if world:
                    robot = world.scene.get_object(self.controller.config.robot_prim_path)
                    if robot:
                        self.controller.set_robot(robot)
                        
        except Exception as e:
            print(f"[Extension] Isaac Sim setup error: {e}")
    
    def _register_physics_callback(self) -> None:
        """注册物理步进回调"""
        try:
            import omni.physx
            from omni.physx import get_physx_interface
            
            physx_interface = get_physx_interface()
            if physx_interface:
                self._physics_step = self._on_physics_step
                physx_interface.add_physics_step_callback(self._physics_step)
                print("[Extension] Physics callback registered")
                
        except Exception as e:
            print(f"[Extension] Failed to register physics callback: {e}")
    
    def _on_physics_step(self, dt: float) -> None:
        """物理步进回调"""
        self.controller.update(dt)
    
    def on_shutdown(self) -> None:
        """扩展关闭"""
        print("[Extension] ROS2 Control Bridge shutting down...")
        self.controller.stop()
        self.controller.close()


def run_standalone_control(
    robot_prim_path: str = "/World/robot",
    cmd_vel_topic: str = "/cmd_vel",
    joint_command_topic: str = "/joint_command",
    joint_stiffness: float = 180.0,
    joint_damping: float = 8.0,
    urdf_path: Optional[str] = None,
    headless: bool = False,
    joint_kp: Optional[list[float]] = None,
    joint_kd: Optional[list[float]] = None,
) -> None:
    """
    独立运行 ROS2 控制桥接
    
    Args:
        robot_prim_path: 机器人路径
        urdf_path: URDF 文件路径（可选，用于自动导入）
        headless: 是否无头模式
    """
    from isaacsim import SimulationApp
    
    # 创建仿真应用
    config = {"headless": headless}
    sim_app = SimulationApp(config)
    
    # 创建控制器
    controller = create_robot_controller(
        robot_prim_path=robot_prim_path,
        cmd_vel_topic=cmd_vel_topic,
        joint_command_topic=joint_command_topic,
        joint_stiffness=joint_stiffness,
        joint_damping=joint_damping,
        joint_kp=joint_kp,
        joint_kd=joint_kd,
    )
    
    # 设置场景
    try:
        from isaacsim.core.api import World

        # 优先使用 SingleArticulation（Isaac Sim 5.1+）
        try:
            from isaacsim.core.prims import SingleArticulation as ArticulationClass
        except ImportError:
            from isaacsim.core.prims import Articulation as ArticulationClass

        world = World(stage_units_in_meters=1.0)
        world.scene.add_default_ground_plane()

        # 如果提供了 URDF，导入机器人
        if urdf_path:
            try:
                from TGrobot4s.isaac_sim.import_tienkung_urdf import import_tienkung
            except ImportError:
                from import_tienkung_urdf import import_tienkung
            try:
                success, prim_path = import_tienkung(urdf_path, fix_base=False)
            except Exception as e:
                print(f"[Standalone] URDF import error: {e}")
                import traceback
                traceback.print_exc()
                success, prim_path = False, str(e)
            if success:
                print(f"[Standalone] URDF imported at: {prim_path}")
            else:
                print(f"[Standalone] Failed to load URDF: {urdf_path}")

        # 先 reset world 初始化物理仿真视图
        world.reset()
        controller.set_world(world)

        # 然后创建 Articulation（需要物理视图已就绪）
        if urdf_path and success:
            try:
                robot = ArticulationClass(prim_path=prim_path, name="robot")
                robot.initialize()
                controller.set_robot(robot)
                print(f"[Standalone] Articulation created, {len(controller._joint_names)} joints")
            except Exception as e:
                print(f"[Standalone] Articulation failed: {e}")
                import traceback
                traceback.print_exc()
        else:
            print("[Standalone] No robot loaded, HTTP API only")
        
        print("[Standalone] Running control bridge...")
        print("[Standalone] HTTP control: http://0.0.0.0:9200/move")
        print("[Standalone] Press Ctrl+C to stop")

        # 注册预步进回调：仅写入关节目标（不读取状态！）
        # get_joint_positions() 触发 copyInternalStateToCache，物理步进期间禁止
        # set_joint_position_targets() 是纯写操作，物理步进期间安全
        def _pre_step(dt):
            controller._apply_joint_targets()

        world.add_physics_callback("rl_control", _pre_step)

        # 主循环：在 world.step() 之间读取关节位置（物理步进外安全）
        while sim_app.is_running():
            world.step(render=not headless)
            # 步进后缓存关节位置（此时物理引擎空闲，安全读取）
            if controller._articulation and hasattr(controller._articulation, 'get_joint_positions'):
                try:
                    pos = controller._articulation.get_joint_positions()
                    controller._cached_joint_pos = np.array(pos, dtype=np.float64)
                    for i, name in enumerate(controller._joint_names):
                        controller._joint_positions[name] = float(pos[i])
                except Exception:
                    pass
            # 更新 IMU（物理步进外安全）
            controller._update_imu(1.0 / 60.0)
            
    except KeyboardInterrupt:
        print("\n[Standalone] Stopping...")
    except Exception as e:
        import traceback
        print(f"[Standalone] Error: {e}")
        traceback.print_exc()
    finally:
        controller.close()
        sim_app.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Isaac Sim ROS2 Control Bridge")
    parser.add_argument("--robot-prim", default="/World/robot", help="Robot prim path")
    parser.add_argument("--cmd-vel-topic", default="/cmd_vel", help="cmd_vel topic name")
    parser.add_argument("--joint-command-topic", default="/joint_command", help="joint command topic name")
    parser.add_argument("--joint-stiffness", type=float, default=180.0, help="joint drive stiffness")
    parser.add_argument("--joint-damping", type=float, default=8.0, help="joint drive damping")
    parser.add_argument("--odom-topic", default="/odom", help="odom topic name")
    parser.add_argument("--urdf", default=None, help="URDF file path")
    parser.add_argument("--headless", action="store_true", help="Run headless")
    parser.add_argument("--policy-config", default=None,
                        help="Path to tg22_config.yaml for per-joint PD gains")
    args = parser.parse_args()

    joint_kp = None
    joint_kd = None
    if args.policy_config:
        try:
            import yaml
            with open(args.policy_config, encoding="utf-8") as f:
                cfg_data = yaml.safe_load(f)
            joint_kp = list(cfg_data.get("joint_kp_p", []))[:20]
            joint_kd = list(cfg_data.get("joint_kd_p", []))[:20]
            print(f"[Config] Loaded per-joint KP/KD from {args.policy_config}")
        except Exception as e:
            print(f"[Config] Failed to load policy config: {e}")

    run_standalone_control(
        robot_prim_path=args.robot_prim,
        cmd_vel_topic=args.cmd_vel_topic,
        joint_command_topic=args.joint_command_topic,
        joint_stiffness=args.joint_stiffness,
        joint_damping=args.joint_damping,
        urdf_path=args.urdf,
        headless=args.headless,
        joint_kp=joint_kp,
        joint_kd=joint_kd,
    )
    return 0


if __name__ == "__main__":
    exit(main())
