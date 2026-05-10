#!/usr/bin/env python3
"""
Isaac Sim HTTP 控制脚本

用法：
1. 打开 Isaac Sim GUI
2. 导入你的 URDF 机器人
3. 在 Script Editor 中运行此脚本

或者从命令行运行：
    D:\isaaclab_env\python.exe scripts/start_isaac_http_control.py --prim-path /World/robot
"""

import argparse
import json
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional, Any

import numpy as np


class IsaacSimHTTPController:
    """
    Isaac Sim HTTP 控制器
    
    在 Isaac Sim 中运行，通过 HTTP 接口接收速度命令。
    """
    
    def __init__(
        self,
        prim_path: str = "/World/robot",
        max_linear: float = 1.0,
        max_angular: float = 1.5,
        cmd_timeout: float = 0.5,
        port: int = 9200
    ):
        self.prim_path = prim_path
        self.max_linear = max_linear
        self.max_angular = max_angular
        self.cmd_timeout = cmd_timeout
        self.port = port
        
        self._robot: Optional[Any] = None
        self._world: Optional[Any] = None
        self._target_linear = 0.0
        self._target_angular = 0.0
        self._current_linear = 0.0
        self._current_angular = 0.0
        self._last_cmd_time = time.time()
        
        self._server: Optional[HTTPServer] = None
        self._server_thread: Optional[threading.Thread] = None
        
    def set_robot(self, robot: Any) -> None:
        """设置机器人 Articulation 对象"""
        self._robot = robot
        print(f"[HTTP Control] Robot set: {self.prim_path}")
        
    def set_world(self, world: Any) -> None:
        """设置 World 对象"""
        self._world = world
        print(f"[HTTP Control] World set")
    
    def start(self) -> None:
        """启动 HTTP 服务器"""
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
                        "mode": "http_control",
                        "prim_path": controller.prim_path,
                        "robot_set": controller._robot is not None,
                        "target_linear": controller._target_linear,
                        "target_angular": controller._target_angular
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
                        
                        # 限幅
                        controller._target_linear = float(np.clip(
                            linear, -controller.max_linear, controller.max_linear
                        ))
                        controller._target_angular = float(np.clip(
                            angular, -controller.max_angular, controller.max_angular
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
            self._server = HTTPServer(("0.0.0.0", self.port), ControlHandler)
            self._server.serve_forever()
        
        self._server_thread = threading.Thread(target=run_server, daemon=True)
        self._server_thread.start()
        print(f"[HTTP Control] Server started on http://0.0.0.0:{self.port}")
        print(f"[HTTP Control] Endpoints:")
        print(f"  GET  /health - Check status")
        print(f"  POST /move   - Send velocity command {{\"linear\": 0.2, \"angular\": 0.0}}")
    
    def update(self, dt: float) -> None:
        """
        每帧更新 - 在物理回调中调用
        
        Args:
            dt: 时间步长（秒）
        """
        # 检查命令超时
        current_time = time.time()
        if current_time - self._last_cmd_time > self.cmd_timeout:
            self._target_linear = 0.0
            self._target_angular = 0.0
        
        # 平滑过渡
        alpha = 0.1
        self._current_linear = self._current_linear + (self._target_linear - self._current_linear) * alpha
        self._current_angular = self._current_angular + (self._target_angular - self._current_angular) * alpha
        
        # 应用到机器人
        self._apply_velocity(self._current_linear, self._current_angular)
    
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
        except Exception as e:
            pass  # 静默处理错误
    
    def stop(self) -> None:
        """停止控制器"""
        self._target_linear = 0.0
        self._target_angular = 0.0
        if self._server:
            self._server.shutdown()


# 全局控制器实例
_controller: Optional[IsaacSimHTTPController] = None


def get_controller() -> Optional[IsaacSimHTTPController]:
    """获取全局控制器实例"""
    return _controller


def start_http_control(
    prim_path: str = "/World/robot",
    max_linear: float = 1.0,
    max_angular: float = 1.5,
    port: int = 9200
) -> IsaacSimHTTPController:
    """
    启动 HTTP 控制器
    
    Args:
        prim_path: 机器人 Prim 路径
        max_linear: 最大线速度 (m/s)
        max_angular: 最大角速度 (rad/s)
        port: HTTP 端口
    
    Returns:
        控制器实例
    """
    global _controller
    
    _controller = IsaacSimHTTPController(
        prim_path=prim_path,
        max_linear=max_linear,
        max_angular=max_angular,
        port=port
    )
    _controller.start()
    
    return _controller


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(description="Isaac Sim HTTP Control")
    parser.add_argument("--prim-path", default="/World/robot", help="Robot prim path")
    parser.add_argument("--max-linear", type=float, default=1.0, help="Max linear velocity")
    parser.add_argument("--max-angular", type=float, default=1.5, help="Max angular velocity")
    parser.add_argument("--port", type=int, default=9200, help="HTTP port")
    args = parser.parse_args()
    
    print("=" * 60)
    print("Isaac Sim HTTP Control")
    print("=" * 60)
    print()
    print("This script should be run INSIDE Isaac Sim.")
    print()
    print("Usage:")
    print("  1. Open Isaac Sim GUI")
    print("  2. Import your URDF robot")
    print("  3. Open Script Editor (Window -> Script Editor)")
    print("  4. Run this script:")
    print()
    print(f'     exec(open("scripts/start_isaac_http_control.py").read())')
    print(f'     controller = start_http_control("{args.prim_path}")')
    print()
    print("  5. Test with curl:")
    print(f'     curl -X POST http://127.0.0.1:{args.port}/move -H "Content-Type: application/json" -d \'{{"linear": 0.2, "angular": 0.0}}\'')
    print()
    print("=" * 60)


if __name__ == "__main__":
    main()
