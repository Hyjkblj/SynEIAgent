"""
Isaac Sim 视频流桥接

功能：
- 获取 Isaac Sim 摄像头图像
- 编码为 JPEG
- POST 到 Gateway Lite /push_frame 接口
- 支持多摄像头

运行方式：
  在 Isaac Sim 的 Python 环境中运行：
  <IsaacSim>/python.sh video_bridge.py --gateway-url http://localhost:8088

依赖：
  - Isaac Sim 4.x/5.x
  - httpx / aiohttp
  - numpy, Pillow
"""
from __future__ import annotations

import argparse
import asyncio
import io
import time
from dataclasses import dataclass, field
from typing import Any, Optional
import threading
import queue

import numpy as np


@dataclass
class VideoBridgeConfig:
    """视频桥接配置"""
    gateway_url: str = "http://localhost:8088"
    push_frame_endpoint: str = "/push_frame"
    push_token: Optional[str] = None
    
    # 摄像头配置
    camera_prim_path: str = "/World/robot/camera"
    camera_id: str = "main"
    
    # 图像配置
    width: int = 640
    height: int = 480
    fps: float = 30.0
    jpeg_quality: int = 85
    
    # 网络配置
    timeout_s: float = 1.0
    max_retries: int = 3
    retry_delay_s: float = 0.1
    
    # 性能配置
    frame_queue_size: int = 2
    drop_frames_on_overflow: bool = True


class IsaacSimCameraCapture:
    """
    Isaac Sim 摄像头捕获
    
    支持多种方式获取图像：
    1. Isaac Sim Camera Sensor API
    2. Viewport 渲染
    3. ROS2 Camera Topic（如果已配置）
    """
    
    def __init__(self, config: VideoBridgeConfig):
        self.config = config
        self.enabled = False
        self.error = ""
        
        # Isaac Sim 相关
        self._camera: Any = None
        self._viewport: Any = None
        self._render_product: Any = None
        
        # 图像数据
        self._latest_frame: Optional[np.ndarray] = None
        self._frame_lock = threading.Lock()
        
        self._init_camera()
    
    def _init_camera(self) -> None:
        """初始化摄像头"""
        try:
            # 方式1：使用 Isaac Sim Camera Sensor
            try:
                from isaacsim.sensors.camera import Camera
                self._camera = Camera(
                    prim_path=self.config.camera_prim_path,
                    position=np.array([0.0, 0.0, 0.0]),
                    frequency=self.config.fps,
                    resolution=(self.config.width, self.config.height),
                    orientation=np.array([0.0, 0.0, 0.0, 1.0])
                )
                self._camera.initialize()
                print(f"[Camera] Initialized at {self.config.camera_prim_path}")
                self.enabled = True
                return
            except Exception as e:
                print(f"[Camera] Camera sensor init failed: {e}")
            
            # 方式2：使用 Viewport
            try:
                import omni.kit.viewport.utility
                from omni.kit.viewport.utility import get_active_viewport
                
                self._viewport = get_active_viewport()
                if self._viewport:
                    self._viewport.set_texture_resolution((self.config.width, self.config.height))
                    print(f"[Viewport] Using active viewport")
                    self.enabled = True
                    return
            except Exception as e:
                print(f"[Camera] Viewport init failed: {e}")
            
            # 方式3：创建新的 RenderProduct
            try:
                import omni.replicator.core as rep
                self._render_product = rep.create.render_product(
                    self.config.camera_prim_path,
                    resolution=(self.config.width, self.config.height)
                )
                print(f"[RenderProduct] Created for {self.config.camera_prim_path}")
                self.enabled = True
            except Exception as e:
                print(f"[Camera] RenderProduct init failed: {e}")
                
        except Exception as e:
            self.error = str(e)
            print(f"[Camera] Initialization failed: {e}")
    
    def capture_frame(self) -> Optional[np.ndarray]:
        """
        捕获一帧图像
        
        Returns:
            RGB 图像数组 (H, W, 3) 或 None
        """
        if not self.enabled:
            return None
        
        try:
            # 方式1：Camera Sensor
            if self._camera is not None:
                if hasattr(self._camera, 'get_rgb'):
                    data = self._camera.get_rgb()
                    if data is not None:
                        # 转换为 uint8
                        if data.dtype == np.float32 or data.dtype == np.float64:
                            data = (data * 255).astype(np.uint8)
                        return data
                
                if hasattr(self._camera, 'get_data'):
                    data = self._camera.get_data()
                    if data is not None:
                        return np.array(data)
            
            # 方式2：Viewport
            if self._viewport is not None:
                try:
                    import omni.ui
                    from omni.ui import ImageProvider
                    
                    # 获取 viewport 图像
                    image = self._viewport.get_texture()
                    if image is not None:
                        return np.array(image)
                except Exception:
                    pass
            
            # 方式3：RenderProduct
            if self._render_product is not None:
                try:
                    import omni.replicator.core as rep
                    data = rep.orchestrator.get_data(self._render_product)
                    if data is not None:
                        return np.array(data)
                except Exception:
                    pass
                    
        except Exception as e:
            print(f"[Camera] Capture error: {e}")
        
        return None
    
    def close(self) -> None:
        """清理资源"""
        if self._camera:
            try:
                self._camera = None
            except Exception:
                pass


class VideoBridge:
    """
    视频流桥接
    
    负责将 Isaac Sim 的摄像头图像编码并推送到 Gateway
    """
    
    def __init__(self, config: VideoBridgeConfig):
        self.config = config
        self.enabled = False
        
        # 组件
        self._camera: Optional[IsaacSimCameraCapture] = None
        self._http_client: Any = None
        
        # 状态
        self._running = False
        self._frame_queue: queue.Queue = queue.Queue(maxsize=config.frame_queue_size)
        self._capture_thread: Optional[threading.Thread] = None
        self._send_task: Optional[asyncio.Task] = None
        
        # 统计
        self._frames_captured = 0
        self._frames_sent = 0
        self._frames_dropped = 0
        self._last_fps_time = time.time()
        self._actual_fps = 0.0
        
        self._init_components()
    
    def _init_components(self) -> None:
        """初始化组件"""
        # 初始化摄像头
        self._camera = IsaacSimCameraCapture(self.config)
        self.enabled = self._camera.enabled
        
        if not self.enabled:
            print(f"[Bridge] Camera not available: {self._camera.error}")
            return
        
        # 初始化 HTTP 客户端
        try:
            import httpx
            self._http_client = httpx.AsyncClient(timeout=self.config.timeout_s)
            print(f"[Bridge] HTTP client initialized")
        except ImportError:
            print("[Bridge] httpx not available, using fallback")
            self._http_client = None
        
        print(f"[Bridge] Video bridge initialized")
        print(f"[Bridge] Gateway URL: {self.config.gateway_url}")
        print(f"[Bridge] Camera: {self.config.camera_prim_path}")
    
    def start(self) -> None:
        """启动视频流"""
        if not self.enabled:
            print("[Bridge] Cannot start: camera not available")
            return
        
        self._running = True
        
        # 启动捕获线程
        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._capture_thread.start()
        
        print(f"[Bridge] Started at {self.config.fps} FPS")
    
    def stop(self) -> None:
        """停止视频流"""
        self._running = False
        
        if self._capture_thread:
            self._capture_thread.join(timeout=2.0)
            self._capture_thread = None
        
        print(f"[Bridge] Stopped. Stats: captured={self._frames_captured}, sent={self._frames_sent}, dropped={self._frames_dropped}")
    
    def _capture_loop(self) -> None:
        """捕获循环（在独立线程中运行）"""
        frame_interval = 1.0 / self.config.fps
        
        while self._running:
            start_time = time.time()
            
            # 捕获帧
            frame = self._camera.capture_frame()
            if frame is not None:
                self._frames_captured += 1
                
                # 放入队列
                try:
                    if self.config.drop_frames_on_overflow and self._frame_queue.full():
                        # 丢弃旧帧
                        try:
                            self._frame_queue.get_nowait()
                            self._frames_dropped += 1
                        except queue.Empty:
                            pass
                    
                    self._frame_queue.put(frame, block=False)
                except queue.Full:
                    self._frames_dropped += 1
            
            # 控制帧率
            elapsed = time.time() - start_time
            sleep_time = frame_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
    
    async def send_loop(self) -> None:
        """发送循环（在 asyncio 中运行）"""
        import httpx
        
        gateway_url = self.config.gateway_url.rstrip('/')
        endpoint = f"{gateway_url}{self.config.push_frame_endpoint}"
        
        headers = {}
        if self.config.push_token:
            headers['X-Push-Token'] = self.config.push_token
        
        while self._running:
            try:
                # 从队列获取帧
                try:
                    frame = self._frame_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                
                # 编码为 JPEG
                jpeg_data = self._encode_jpeg(frame)
                if jpeg_data is None:
                    continue
                
                # 发送到 Gateway
                try:
                    if self._http_client:
                        response = await self._http_client.post(
                            endpoint,
                            content=jpeg_data,
                            headers=headers,
                            params={'camera_id': self.config.camera_id}
                        )
                    else:
                        async with httpx.AsyncClient(timeout=self.config.timeout_s) as client:
                            response = await client.post(
                                endpoint,
                                content=jpeg_data,
                                headers=headers,
                                params={'camera_id': self.config.camera_id}
                            )
                    
                    if response.status_code == 200:
                        self._frames_sent += 1
                    else:
                        print(f"[Bridge] Send failed: HTTP {response.status_code}")
                        
                except httpx.TimeoutException:
                    print("[Bridge] Send timeout")
                except Exception as e:
                    print(f"[Bridge] Send error: {e}")
                
                # 更新 FPS 统计
                self._update_fps_stats()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[Bridge] Send loop error: {e}")
                await asyncio.sleep(0.1)
    
    def _encode_jpeg(self, frame: np.ndarray) -> Optional[bytes]:
        """编码为 JPEG"""
        try:
            from PIL import Image
            
            # 确保是 RGB 格式
            if len(frame.shape) == 2:
                # 灰度图转 RGB
                frame = np.stack([frame] * 3, axis=-1)
            elif frame.shape[2] == 4:
                # RGBA 转 RGB
                frame = frame[:, :, :3]
            
            # 确保数据类型正确
            if frame.dtype != np.uint8:
                frame = frame.astype(np.uint8)
            
            # 编码
            img = Image.fromarray(frame)
            buffer = io.BytesIO()
            img.save(buffer, format='JPEG', quality=self.config.jpeg_quality)
            return buffer.getvalue()
            
        except ImportError:
            # 如果没有 Pillow，使用 OpenCV
            try:
                import cv2
                _, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, self.config.jpeg_quality])
                return encoded.tobytes()
            except ImportError:
                print("[Bridge] Neither Pillow nor OpenCV available for JPEG encoding")
                return None
        except Exception as e:
            print(f"[Bridge] JPEG encoding error: {e}")
            return None
    
    def _update_fps_stats(self) -> None:
        """更新 FPS 统计"""
        current_time = time.time()
        elapsed = current_time - self._last_fps_time
        
        if elapsed >= 1.0:
            self._actual_fps = self._frames_sent / elapsed
            self._last_fps_time = current_time
            
            # 重置计数器（可选）
            # self._frames_sent = 0
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            "enabled": self.enabled,
            "running": self._running,
            "frames_captured": self._frames_captured,
            "frames_sent": self._frames_sent,
            "frames_dropped": self._frames_dropped,
            "actual_fps": self._actual_fps,
            "queue_size": self._frame_queue.qsize(),
        }
    
    def close(self) -> None:
        """清理资源"""
        self.stop()
        
        if self._camera:
            self._camera.close()
        
        if self._http_client:
            try:
                asyncio.create_task(self._http_client.aclose())
            except Exception:
                pass


# ==================== 多摄像头支持 ====================

class MultiCameraVideoBridge:
    """
    多摄像头视频桥接
    
    支持同时管理多个摄像头
    """
    
    def __init__(self, gateway_url: str = "http://localhost:8088"):
        self.gateway_url = gateway_url
        self._bridges: dict[str, VideoBridge] = {}
    
    def add_camera(
        self,
        camera_id: str,
        camera_prim_path: str,
        width: int = 640,
        height: int = 480,
        fps: float = 30.0,
        **kwargs
    ) -> bool:
        """添加摄像头"""
        if camera_id in self._bridges:
            print(f"[MultiBridge] Camera {camera_id} already exists")
            return False
        
        config = VideoBridgeConfig(
            gateway_url=self.gateway_url,
            camera_prim_path=camera_prim_path,
            camera_id=camera_id,
            width=width,
            height=height,
            fps=fps,
            **kwargs
        )
        
        bridge = VideoBridge(config)
        if bridge.enabled:
            self._bridges[camera_id] = bridge
            print(f"[MultiBridge] Added camera: {camera_id}")
            return True
        else:
            print(f"[MultiBridge] Failed to add camera: {camera_id}")
            return False
    
    def start_all(self) -> None:
        """启动所有摄像头"""
        for bridge in self._bridges.values():
            bridge.start()
    
    def stop_all(self) -> None:
        """停止所有摄像头"""
        for bridge in self._bridges.values():
            bridge.stop()
    
    def get_all_stats(self) -> dict[str, dict]:
        """获取所有摄像头统计"""
        return {cam_id: bridge.get_stats() for cam_id, bridge in self._bridges.items()}
    
    def close(self) -> None:
        """清理所有资源"""
        for bridge in self._bridges.values():
            bridge.close()
        self._bridges.clear()


# ==================== Isaac Sim 集成 ====================

def create_camera_at_robot_eye(
    robot_prim_path: str = "/World/robot",
    camera_name: str = "eye_camera",
    position_offset: tuple = (0.1, 0.0, 1.5),
    orientation: tuple = (0.0, 0.0, 0.0, 1.0)
) -> str:
    """
    在机器人头部位置创建摄像头
    
    Args:
        robot_prim_path: 机器人路径
        camera_name: 摄像头名称
        position_offset: 相对于机器人基座的位置偏移
        orientation: 摄像头朝向（四元数）
    
    Returns:
        摄像头 prim 路径
    """
    try:
        from isaacsim.sensors.camera import Camera
        import omni.usd
        from pxr import UsdGeom, Gf
        
        camera_prim_path = f"{robot_prim_path}/{camera_name}"
        
        # 创建摄像头
        camera = Camera(
            prim_path=camera_prim_path,
            position=np.array(position_offset),
            orientation=np.array(orientation),
            frequency=30.0,
            resolution=(640, 480)
        )
        camera.initialize()
        
        # 将摄像头附加到机器人
        stage = omni.usd.get_context().get_stage()
        camera_prim = stage.GetPrimAtPath(camera_prim_path)
        if camera_prim:
            # 设置为机器人的子节点
            pass
        
        print(f"[Camera] Created at {camera_prim_path}")
        return camera_prim_path
        
    except Exception as e:
        print(f"[Camera] Failed to create camera: {e}")
        return ""


def run_standalone_video_bridge(
    gateway_url: str = "http://localhost:8088",
    camera_prim_path: str = "/World/robot/camera",
    camera_id: str = "main",
    fps: float = 30.0,
    headless: bool = False
) -> None:
    """
    独立运行视频桥接
    
    Args:
        gateway_url: Gateway URL
        camera_prim_path: 摄像头路径
        camera_id: 摄像头 ID
        fps: 帧率
        headless: 是否无头模式
    """
    from isaacsim import SimulationApp
    
    # 创建仿真应用
    config = {"headless": headless}
    sim_app = SimulationApp(config)
    
    # 创建视频桥接
    bridge_config = VideoBridgeConfig(
        gateway_url=gateway_url,
        camera_prim_path=camera_prim_path,
        camera_id=camera_id,
        fps=fps
    )
    
    bridge = VideoBridge(bridge_config)
    
    if not bridge.enabled:
        print("[Standalone] Video bridge not available")
        sim_app.close()
        return
    
    # 设置场景
    try:
        from isaacsim.core import World
        
        world = World(stage_units_in_meters=1.0)
        world.scene.add_default_ground_plane()
        world.reset()
        
        # 启动视频桥接
        bridge.start()
        
        print("[Standalone] Running video bridge...")
        print("[Standalone] Press Ctrl+C to stop")
        
        # 主循环
        async def main_loop():
            send_task = asyncio.create_task(bridge.send_loop())
            
            while sim_app.is_running():
                world.step(render=True)
                await asyncio.sleep(0.001)
            
            send_task.cancel()
        
        asyncio.run(main_loop())
        
    except KeyboardInterrupt:
        print("\n[Standalone] Stopping...")
    finally:
        bridge.close()
        sim_app.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Isaac Sim Video Bridge")
    parser.add_argument("--gateway-url", default="http://localhost:8088", help="Gateway URL")
    parser.add_argument("--camera-prim", default="/World/robot/camera", help="Camera prim path")
    parser.add_argument("--camera-id", default="main", help="Camera ID")
    parser.add_argument("--fps", type=float, default=30.0, help="Frame rate")
    parser.add_argument("--push-token", default=None, help="Push token for authentication")
    parser.add_argument("--headless", action="store_true", help="Run headless")
    args = parser.parse_args()
    
    run_standalone_video_bridge(
        gateway_url=args.gateway_url,
        camera_prim_path=args.camera_prim,
        camera_id=args.camera_id,
        fps=args.fps,
        headless=args.headless
    )
    return 0


if __name__ == "__main__":
    exit(main())
