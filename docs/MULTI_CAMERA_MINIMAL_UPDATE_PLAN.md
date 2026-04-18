# 多相机支持最小改动方案

## 一、概述

### 1.1 目标
在最小改动前提下，实现机器人多相机视频流支持，允许移动端切换不同相机视角。

### 1.2 设计原则
- **最小侵入**: 保持现有接口兼容，通过扩展而非修改实现
- **渐进式**: 分阶段实施，每个阶段可独立测试验证
- **向后兼容**: 旧版本客户端仍可正常工作

### 1.3 相机配置

| 相机 ID | 位置 | ROS Topic | 优先级 |
|---------|------|-----------|--------|
| `head` | 头部 | `/G330_0/color/image_raw` | 主视频（默认） |
| `chest` | 胸部 | `/G330_1/color/image_raw` | 副视频 |
| `left_hand` | 左手 | `/G330_2/color/image_raw` | 副视频 |
| `right_hand` | 右手 | `/G330_3/color/image_raw` | 副视频 |

---

## 二、架构设计

### 2.1 当前架构（单视频流）

```
┌─────────────────┐     POST /push_frame      ┌─────────────────┐
│  Video Bridge   │ ────────────────────────► │  Gateway Lite   │
│  (单进程)        │     Body: JPEG bytes      │  SharedVideoTrack│
└─────────────────┘                           └─────────────────┘
                                                      │
                                                      ▼
                                              ┌─────────────────┐
                                              │   Mobile App    │
                                              │  VideoTrack x1  │
                                              └─────────────────┘
```

### 2.2 目标架构（多视频流 - 最小改动）

```
┌─────────────────┐     POST /push_frame?camera_id=head     ┌─────────────────┐
│  Video Bridge   │ ─────────────────────────────────────►  │  Gateway Lite   │
│  (多进程/多线程)  │     Body: JPEG bytes                   │  MultiCamera    │
│                 │     POST /push_frame?camera_id=chest    │  VideoManager   │
│                 │ ─────────────────────────────────────►  │                 │
└─────────────────┘                                        └─────────────────┘
                                                                  │
                                                                  ▼
                                                          ┌─────────────────┐
                                                          │   Mobile App    │
                                                          │  VideoTrack x N │
                                                          │  (可切换)        │
                                                          └─────────────────┘
```

### 2.3 关键改动点

| 层级 | 改动 | 影响范围 |
|------|------|----------|
| Gateway Lite | 新增 `MultiCameraVideoManager` | 新增文件，不修改现有逻辑 |
| Gateway Lite | `/push_frame` 支持 `camera_id` 参数 | 向后兼容，默认 `head` |
| Video Bridge | 支持多相机推送 | 新增启动参数 |
| Mobile App | 支持多 VideoTrack 接收 | 扩展接口，保持兼容 |

---

## 三、PR 任务规划

### PR-1: Gateway Lite 多相机支持

**目标**: 后端支持多相机视频轨道管理

**改动文件**:
```
gateway_lite/
├── video_track.py          # 扩展 SharedVideoTrack，新增 camera_id
├── multi_camera_manager.py # 新增：多相机视频管理器
└── server.py               # 修改：集成多相机管理器
```

**核心代码**:

```python
# gateway_lite/multi_camera_manager.py (新增)
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Dict, Optional, List

from .video_track import SharedVideoTrack


@dataclass
class CameraConfig:
    """相机配置"""
    camera_id: str
    display_name: str
    ros_topic: str = ""


class MultiCameraVideoManager:
    """多相机视频管理器
    
    支持从多个相机接收视频帧，并通过 WebRTC 推送到移动端。
    """
    
    DEFAULT_CAMERAS = {
        "head": CameraConfig("head", "头部相机", "/G330_0/color/image_raw"),
        "chest": CameraConfig("chest", "胸部相机", "/G330_1/color/image_raw"),
        "left_hand": CameraConfig("left_hand", "左手相机", "/G330_2/color/image_raw"),
        "right_hand": CameraConfig("right_hand", "右手相机", "/G330_3/color/image_raw"),
    }
    
    def __init__(self, camera_ids: List[str] | None = None):
        self._tracks: Dict[str, SharedVideoTrack] = {}
        self._primary_camera_id: str = "head"
        
        # 初始化相机轨道
        ids = camera_ids or list(self.DEFAULT_CAMERAS.keys())
        for camera_id in ids:
            self._tracks[camera_id] = SharedVideoTrack(camera_id=camera_id)
    
    def get_track(self, camera_id: str) -> Optional[SharedVideoTrack]:
        return self._tracks.get(camera_id)
    
    def get_all_tracks(self) -> Dict[str, SharedVideoTrack]:
        return self._tracks.copy()
    
    def push_frame(self, camera_id: str, jpeg: bytes) -> bool:
        """推送视频帧到指定相机轨道"""
        if camera_id not in self._tracks:
            # 动态创建新相机轨道
            self._tracks[camera_id] = SharedVideoTrack(camera_id=camera_id)
        
        track = self._tracks.get(camera_id)
        if track is None:
            return False
        return track.push_jpeg(jpeg)
    
    def get_available_cameras(self) -> List[str]:
        """获取有视频流的相机列表"""
        return [
            camera_id for camera_id, track in self._tracks.items()
            if track.metrics.pushed > 0
        ]
    
    def get_metrics(self) -> Dict[str, dict]:
        return {
            camera_id: track.get_metrics()
            for camera_id, track in self._tracks.items()
        }
```

**server.py 改动**:

```python
# gateway_lite/server.py 改动点

# 1. 导入
from .multi_camera_manager import MultiCameraVideoManager

# 2. __init__ 中替换单一视频轨道
class GatewayServer:
    def __init__(self, config: GatewayConfig) -> None:
        # ... 现有代码 ...
        
        # 替换: self._video_track = SharedVideoTrack() if ...
        self._video_manager: MultiCameraVideoManager | None = (
            MultiCameraVideoManager() if self.cfg.video_enabled else None
        )

# 3. _push_frame_handler 改动
async def _push_frame_handler(self, request: web.Request) -> web.Response:
    if self._video_manager is None:
        return web.json_response({"ok": False, "error": "video_disabled"}, status=404)
    
    # 验证 token (保持不变)
    token = self.cfg.video_push_token
    if token:
        got = request.headers.get("X-Push-Token", "")
        if got != token:
            return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
    
    # 获取相机 ID (新增，向后兼容)
    camera_id = (
        request.query.get("camera_id") or 
        request.headers.get("X-Camera-Id", "head")
    )
    
    body = await request.read()
    accepted = self._video_manager.push_frame(camera_id, body)
    
    return web.json_response({
        "ok": accepted,
        "camera_id": camera_id,
        "available_cameras": self._video_manager.get_available_cameras(),
        "video": self._video_manager.get_metrics(),
    })

# 4. _setup_peer 改动
def _setup_peer(self, session: PeerSession, ws: web.WebSocketResponse) -> None:
    pc = session.pc
    
    # 替换: pc.addTrack(self._video_track)
    if self._video_manager is not None:
        for camera_id, track in self._video_manager.get_all_tracks().items():
            # 使用 stream_id 标识相机
            pc.addTrack(track, stream_id=f"camera_{camera_id}")
    
    # ... 其他代码保持不变 ...
```

**video_track.py 改动**:

```python
# gateway_lite/video_track.py 改动点

class SharedVideoTrack(VideoStreamTrack):
    kind = "video"

    def __init__(self, camera_id: str = "default") -> None:  # 新增 camera_id 参数
        super().__init__()
        self.camera_id = camera_id  # 新增
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=4)
        self.metrics = VideoMetrics()
    
    # ... 其他方法保持不变 ...
```

**验收标准**:
- [ ] `/push_frame?camera_id=head` 正常工作
- [ ] `/push_frame` 无 camera_id 参数时默认使用 `head`
- [ ] `/status` 返回所有相机的 metrics
- [ ] WebRTC 协商成功，SDP 包含多个 video m-line

---

### PR-2: Video Bridge 多相机支持

**目标**: 视频桥接脚本支持推送多个相机

**改动文件**:
```
scripts/
└── local_video_bridge.py   # 修改：支持多相机参数
```

**核心改动**:

```python
# scripts/local_video_bridge.py 改动点

import argparse
import asyncio
import sys

# 新增命令行参数
parser = argparse.ArgumentParser()
parser.add_argument("--nanobot", required=True, help="Gateway URL")
parser.add_argument("--topic", default="/camera/color/image_raw", help="ROS topic")
parser.add_argument("--camera-id", default="head", help="Camera ID for multi-camera")  # 新增
parser.add_argument("--fps", type=int, default=15)
# ... 其他参数 ...

async def push_frame(url: str, camera_id: str, jpeg: bytes, token: str | None):
    headers = {"Content-Type": "image/jpeg"}
    if token:
        headers["X-Push-Token"] = token
    
    # 新增 camera_id 参数
    full_url = f"{url}/push_frame?camera_id={camera_id}"
    
    async with aiohttp.ClientSession() as session:
        async with session.post(full_url, data=jpeg, headers=headers) as resp:
            return resp.status == 200

# 启动命令示例:
# python local_video_bridge.py --nanobot http://192.168.1.100:9100 --topic /G330_0/color/image_raw --camera-id head
# python local_video_bridge.py --nanobot http://192.168.1.100:9100 --topic /G330_1/color/image_raw --camera-id chest
```

**验收标准**:
- [ ] `--camera-id` 参数正确传递到 Gateway
- [ ] 可同时启动多个 bridge 进程推送不同相机
- [ ] Gateway `/status` 显示多个相机的 metrics

---

### PR-3: Mobile App 多视频轨道接收

**目标**: 移动端支持接收多个视频轨道

**改动文件**:
```
TGrobot4s/mobile/app/src/main/java/com/tgrobot/mobile/
├── data/
│   ├── RobotClient.kt           # 扩展接口
│   └── WebRtcRobotClient.kt     # 实现多轨道接收
├── feature/control/
│   ├── TeleopCoordinator.kt     # 支持相机切换
│   └── TeleopUiState.kt         # 新增多视频状态
└── core/model/
    └── VideoStream.kt           # 新增：视频流数据模型
```

**核心代码**:

```kotlin
// core/model/VideoStream.kt (新增)
package com.tgrobot.mobile.core.model

import org.webrtc.VideoTrack

data class VideoStream(
    val cameraId: String,
    val displayName: String,
    val track: VideoTrack?,
    val isPrimary: Boolean = false,
    val order: Int = 0,
) {
    val isAvailable: Boolean
        get() = track != null
}

enum class CameraType(val id: String, val displayName: String, val defaultOrder: Int) {
    HEAD("head", "头部相机", 0),
    CHEST("chest", "胸部相机", 1),
    LEFT_HAND("left_hand", "左手相机", 2),
    RIGHT_HAND("right_hand", "右手相机", 3);
    
    companion object {
        fun fromId(id: String): CameraType? = values().find { it.id == id }
    }
}
```

```kotlin
// data/RobotClient.kt 扩展
interface RobotClient {
    // ... 现有接口保持不变 ...
    
    /**
     * 所有远程视频轨道 (新增)
     */
    val videoTracks: StateFlow<Map<String, VideoTrack>>
    
    /**
     * 当前主相机 ID (新增)
     */
    val primaryCameraId: StateFlow<String>
    
    /**
     * 远程视频轨道 (保持兼容)
     */
    val remoteVideoTrack: StateFlow<VideoTrack?>
        get() = videoTracks.map { it.values.firstOrNull() }
            .stateIn(CoroutineScope(Dispatchers.IO), SharingStarted.Eagerly, null)
}
```

```kotlin
// data/WebRtcRobotClient.kt 改动
class WebRtcRobotClient(...) : RobotClient {
    // ... 现有代码 ...
    
    // 新增
    private val _videoTracks = MutableStateFlow<Map<String, VideoTrack>>(emptyMap())
    override val videoTracks: StateFlow<Map<String, VideoTrack>> = _videoTracks.asStateFlow()
    
    private val _primaryCameraId = MutableStateFlow("head")
    override val primaryCameraId: StateFlow<String> = _primaryCameraId.asStateFlow()
    
    // 保持兼容
    override val remoteVideoTrack: StateFlow<VideoTrack?> = _videoTracks
        .map { it[_primaryCameraId.value] }
        .stateIn(scope, SharingStarted.Eagerly, null)
    
    // 改动: onAddTrack
    override fun onAddTrack(receiver: RtpReceiver, mediaStreams: Array<MediaStream>) {
        val track = receiver.track() as? VideoTrack ?: return
        
        // 从 stream_id 提取相机 ID
        val cameraId = extractCameraId(mediaStreams, receiver)
        
        _videoTracks.update { current ->
            current + (cameraId to track)
        }
    }
    
    private fun extractCameraId(mediaStreams: Array<MediaStream>, receiver: RtpReceiver): String {
        // 从 MediaStream ID 提取 (格式: "camera_head", "camera_chest")
        for (stream in mediaStreams) {
            val streamId = stream.id
            if (streamId.startsWith("camera_")) {
                return streamId.removePrefix("camera_")
            }
        }
        return "head" // 默认
    }
    
    // 改动: cleanupPeer
    private suspend fun cleanupPeer() {
        // ... 现有代码 ...
        _videoTracks.value = emptyMap()
    }
}
```

```kotlin
// feature/control/TeleopUiState.kt 扩展
data class TeleopUiState(
    // ... 现有字段 ...
    
    // 新增
    val videoStreams: Map<String, VideoStream> = emptyMap(),
    val primaryCameraId: String = "head",
) {
    // 保持兼容
    val remoteVideoTrack: VideoTrack?
        get() = videoStreams[primaryCameraId]?.track
    
    // 新增
    val primaryVideoTrack: VideoTrack?
        get() = videoStreams[primaryCameraId]?.track
    
    val secondaryVideoStreams: List<VideoStream>
        get() = videoStreams.values
            .filter { it.cameraId != primaryCameraId }
            .sortedBy { it.order }
    
    val availableCameraCount: Int
        get() = videoStreams.values.count { it.isAvailable }
}
```

```kotlin
// feature/control/TeleopCoordinator.kt 扩展
class TeleopCoordinator(...) {
    // ... 现有代码 ...
    
    /**
     * 更新视频轨道 (扩展)
     */
    fun updateVideoTracks(tracks: Map<String, VideoTrack>) {
        val currentStreams = _uiState.value.videoStreams
        val updatedStreams = tracks.mapValues { (cameraId, track) ->
            val existing = currentStreams[cameraId]
            VideoStream(
                cameraId = cameraId,
                displayName = existing?.displayName 
                    ?: CameraType.fromId(cameraId)?.displayName 
                    ?: cameraId,
                track = track,
                isPrimary = cameraId == _uiState.value.primaryCameraId,
                order = existing?.order 
                    ?: CameraType.fromId(cameraId)?.defaultOrder 
                    ?: 99,
            )
        }
        _uiState.update { it.copy(videoStreams = updatedStreams) }
    }
    
    /**
     * 切换主相机 (新增)
     */
    fun switchPrimaryCamera(cameraId: String) {
        if (!_uiState.value.videoStreams.containsKey(cameraId)) {
            messageStore.addSystemMessage("Camera $cameraId not available.")
            return
        }
        _uiState.update { it.copy(primaryCameraId = cameraId) }
        messageStore.addSystemMessage("Switched to ${_uiState.value.videoStreams[cameraId]?.displayName}")
    }
    
    // 保持兼容
    fun updateVideoTrack(track: VideoTrack?) {
        if (track == null) {
            updateVideoTracks(emptyMap())
        } else {
            updateVideoTracks(mapOf("head" to track))
        }
    }
}
```

**验收标准**:
- [ ] `videoTracks` 正确接收多个视频轨道
- [ ] `remoteVideoTrack` 保持向后兼容
- [ ] `switchPrimaryCamera()` 可切换主视频
- [ ] UI 显示当前相机名称

---

### PR-4: Mobile App 相机切换 UI

**目标**: 添加相机切换下拉菜单

**改动文件**:
```
TGrobot4s/mobile/app/src/main/java/com/tgrobot/mobile/
└── feature/control/
    ├── CameraSelectorDropdown.kt  # 新增：相机选择组件
    └── TeleopScreen.kt            # 修改：集成相机选择器
```

**核心代码**:

```kotlin
// feature/control/CameraSelectorDropdown.kt (新增)
package com.tgrobot.mobile.feature.control

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.Videocam
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.tgrobot.mobile.core.model.VideoStream

@Composable
fun CameraSelectorDropdown(
    streams: List<VideoStream>,
    primaryCameraId: String,
    onCameraSelected: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    var expanded by remember { mutableStateOf(false) }
    val primaryStream = streams.find { it.cameraId == primaryCameraId }

    Box(modifier = modifier) {
        Surface(
            modifier = Modifier
                .clip(RoundedCornerShape(8.dp))
                .clickable { expanded = true },
            color = Color.Black.copy(alpha = 0.6f),
        ) {
            Row(
                modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Icon(
                    imageVector = Icons.Default.Videocam,
                    contentDescription = null,
                    tint = Color.White,
                    modifier = Modifier.size(18.dp),
                )
                Text(
                    text = primaryStream?.displayName ?: "选择相机",
                    color = Color.White,
                    style = MaterialTheme.typography.bodyMedium,
                )
                Icon(
                    imageVector = Icons.Default.ArrowDropDown,
                    contentDescription = null,
                    tint = Color.White,
                    modifier = Modifier.size(18.dp),
                )
            }
        }

        DropdownMenu(
            expanded = expanded,
            onDismissRequest = { expanded = false },
            modifier = Modifier
                .background(Color.Black.copy(alpha = 0.9f))
                .width(200.dp),
        ) {
            streams.forEach { stream ->
                DropdownMenuItem(
                    text = {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            if (stream.cameraId == primaryCameraId) {
                                Icon(
                                    imageVector = Icons.Default.Videocam,
                                    contentDescription = null,
                                    tint = Color(0xFF4CAF50),
                                    modifier = Modifier.size(16.dp),
                                )
                            }
                            Text(
                                text = stream.displayName,
                                color = if (stream.cameraId == primaryCameraId) {
                                    Color(0xFF4CAF50)
                                } else {
                                    Color.White
                                },
                            )
                        }
                    },
                    onClick = {
                        onCameraSelected(stream.cameraId)
                        expanded = false
                    },
                    enabled = stream.isAvailable,
                )
            }
        }
    }
}
```

**TeleopScreen.kt 改动**:

```kotlin
// 在 DriveScreen 中添加相机选择器
@Composable
private fun DriveScreen(
    state: TeleopUiState,
    // ... 现有参数 ...
    onCameraSelected: (String) -> Unit, // 新增
) {
    Box(modifier = Modifier.fillMaxSize()) {
        // Layer 0: 主视频全屏
        VideoBackground(track = state.remoteVideoTrack)

        // Layer 1: HUD overlays

        // Top-center: 相机选择下拉栏 (新增)
        CameraSelectorDropdown(
            streams = state.videoStreams.values.toList(),
            primaryCameraId = state.primaryCameraId,
            onCameraSelected = onCameraSelected,
            modifier = Modifier
                .align(Alignment.TopCenter)
                .padding(top = 48.dp),
        )

        // ... 其他 HUD 组件保持不变 ...
    }
}
```

**验收标准**:
- [ ] 下拉菜单显示所有可用相机
- [ ] 点击可切换主视频
- [ ] 当前相机有绿色图标标识
- [ ] 不可用相机置灰

---

### PR-5: 机器人端多相机启动配置

**目标**: 提供多相机启动脚本和配置

**改动文件**:
```
TGrobot4s/robot/orbbec_camera_ros2/orbbec_camera_ros2/
└── install/orbbec_camera/share/orbbec_camera/launch/
    └── robot_multi_camera.launch.py  # 新增：机器人专用多相机启动
```

**核心代码**:

```python
# robot_multi_camera.launch.py (新增)
"""
机器人多相机启动配置

启动 4 个相机:
- head: 头部相机 (G330_0)
- chest: 胸部相机 (G330_1)
- left_hand: 左手相机 (G330_2)
- right_hand: 右手相机 (G330_3)
"""
import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, GroupAction, TimerAction
from launch.launch_description_sources import PythonLaunchDescriptionSource


def generate_launch_description():
    package_dir = get_package_share_directory("orbbec_camera")
    launch_file_dir = os.path.join(package_dir, "launch")

    cameras = [
        {"name": "G330_0", "camera_id": "head", "usb_port": "2-1"},
        {"name": "G330_1", "camera_id": "chest", "usb_port": "2-2"},
        {"name": "G330_2", "camera_id": "left_hand", "usb_port": "2-3"},
        {"name": "G330_3", "camera_id": "right_hand", "usb_port": "2-4"},
    ]

    launch_includes = []
    for i, cam in enumerate(cameras):
        include = IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(launch_file_dir, "gemini_330_series.launch.py")
            ),
            launch_arguments={
                "camera_name": cam["name"],
                "usb_port": cam["usb_port"],
                "device_num": str(len(cameras)),
                "enable_color": "true",
                "enable_depth": "false",
                "enable_left_ir": "false",
                "enable_right_ir": "false",
            }.items(),
        )
        # 错开启动时间，避免 USB 带宽冲突
        launch_includes.append(
            TimerAction(period=i * 2.0, actions=[GroupAction([include])])
        )

    return LaunchDescription(launch_includes)
```

**验收标准**:
- [ ] `ros2 launch orbbec_camera robot_multi_camera.launch.py` 启动成功
- [ ] `ros2 topic list` 显示 4 个相机的 topic
- [ ] 每个相机帧率稳定

---

## 四、实施顺序

```
Phase 1: 后端基础 (PR-1)
    │
    ▼
Phase 2: 视频桥接 (PR-2) ──► 可独立测试
    │
    ▼
Phase 3: 移动端接收 (PR-3) ──► 可独立测试
    │
    ▼
Phase 4: 移动端 UI (PR-4)
    │
    ▼
Phase 5: 机器人配置 (PR-5) ──► 完整验证
```

---

## 五、测试计划

### 5.1 单元测试

| PR | 测试项 |
|----|--------|
| PR-1 | `MultiCameraVideoManager.push_frame()` 多相机推送 |
| PR-1 | `MultiCameraVideoManager.get_available_cameras()` 动态相机列表 |
| PR-3 | `WebRtcRobotClient.videoTracks` 多轨道接收 |
| PR-3 | `TeleopCoordinator.switchPrimaryCamera()` 切换逻辑 |

### 5.2 集成测试

| 场景 | 步骤 | 预期结果 |
|------|------|----------|
| 单相机兼容 | 启动旧版 bridge，无 camera_id | 默认使用 head，视频正常 |
| 多相机推送 | 启动 2 个 bridge，不同 camera_id | Gateway 显示 2 个相机 |
| 移动端切换 | 连接后切换相机 | 视频切换，无黑屏 |
| 断线重连 | 断开一个相机 bridge | 该相机标记为不可用 |

### 5.3 性能测试

| 指标 | 目标 |
|------|------|
| 单相机帧率 | ≥ 15 FPS |
| 4 相机总帧率 | ≥ 60 FPS (每个 15 FPS) |
| 切换延迟 | < 500ms |
| CPU 占用 | < 50% (4 相机) |

---

## 六、回滚方案

每个 PR 可独立回滚：

| PR | 回滚影响 |
|----|----------|
| PR-1 | 回退到单一 `SharedVideoTrack`，移动端仍可工作 |
| PR-2 | 回退到单相机 bridge |
| PR-3 | 回退到单一 `remoteVideoTrack` |
| PR-4 | 移除相机选择 UI，使用默认相机 |
| PR-5 | 使用单相机启动配置 |

---

## 七、文档更新

| 文档 | 更新内容 |
|------|----------|
| `README.md` | 多相机使用说明 |
| `docs/robot_camera_connection_and_startup.txt` | 更新启动命令 |
| API 文档 | `/push_frame` 新增 `camera_id` 参数 |

---

## 八、时间估算

| PR | 开发 | 测试 | 总计 |
|----|------|------|------|
| PR-1 | 2h | 1h | 3h |
| PR-2 | 1h | 0.5h | 1.5h |
| PR-3 | 3h | 1.5h | 4.5h |
| PR-4 | 2h | 1h | 3h |
| PR-5 | 1h | 1h | 2h |
| **总计** | **9h** | **5h** | **14h** |

---

## 九、风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| USB 带宽不足 | 多相机帧率下降 | 使用 USB 3.0 端口，错开启动 |
| WebRTC 多轨道协商失败 | 移动端无视频 | 降级到单轨道模式 |
| 移动端性能不足 | 卡顿 | 限制同时显示的相机数量 |
| SDP m-line 顺序不一致 | 相机 ID 识别错误 | 使用 stream_id 标识 |

---

## 十、总结

本方案通过 **5 个渐进式 PR** 实现多相机支持：

1. **PR-1**: Gateway Lite 多相机管理器（核心）
2. **PR-2**: Video Bridge 多相机推送
3. **PR-3**: Mobile App 多轨道接收
4. **PR-4**: Mobile App 相机切换 UI
5. **PR-5**: 机器人多相机启动配置

**关键设计**:
- 向后兼容：旧版客户端仍可正常工作
- 最小侵入：通过扩展而非修改实现
- 渐进式：每个 PR 可独立测试和部署
