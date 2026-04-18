# 多视频流传输方案设计

## 一、需求概述

### 1.1 功能需求
- 支持多个视频流同时传输（头部相机、胸部相机、手部相机等）
- 区分主视频流和副视频流
- 主视频流全屏展示
- 副视频流在顶部下拉栏悬浮窗展示
- 支持主副视频流切换
- 默认头部相机为主视频流

### 1.2 技术约束
- 基于现有 WebRTC 架构
- 保持与后端 Gateway Lite 的兼容性
- 遵循现有 UseCase、Coordinator 架构模式
- 最小化对现有代码的侵入性

---

## 二、机器人端多相机支持分析

### 2.1 硬件与驱动支持

#### 2.1.1 Orbbec 相机驱动

机器人使用 **Orbbec Gemini 330 系列** 深度相机，ROS2 驱动已原生支持多相机模式：

```
TGrobot4s/robot/orbbec_camera_ros2/
├── install/orbbec_camera/share/orbbec_camera/launch/
│   ├── multi_camera.launch.py          # 双相机示例
│   ├── multi_camera_synced.launch.py   # 同步多相机
│   └── orbbec_multicamera.launch.py    # 四相机示例
```

#### 2.1.2 多相机 Launch 配置

```python
# orbbec_multicamera.launch.py (四相机配置示例)
G330_0 = IncludeLaunchDescription(
    PythonLaunchDescriptionSource(...),
    launch_arguments={
        'camera_name': 'G330_0',  # 相机名称 → 话题前缀
        'usb_port': '2-1',        # USB 端口
        'device_num': '4',        # 设备数量
    }.items()
)
# G330_1, G330_2, G330_3 类似配置...
```

#### 2.1.3 ROS2 话题命名规则

每个相机发布独立的话题：

```
/G330_0/color/image_raw        # 相机 0 彩色图像
/G330_0/depth/image_raw        # 相机 0 深度图像
/G330_0/color/camera_info      # 相机 0 相机信息

/G330_1/color/image_raw        # 相机 1 彩色图像
/G330_1/depth/image_raw        # 相机 1 深度图像
...

/G330_3/color/image_raw        # 相机 3 彩色图像
```

### 2.2 视频推送机制

#### 2.2.1 当前架构

```
ROS2 Camera Node                Video Bridge Script              Gateway Lite
      │                               │                              │
      │ /camera/color/image_raw       │                              │
      │ (sensor_msgs/CompressedImage) │                              │
      ├──────────────────────────────►│                              │
      │                               │  POST /push_frame             │
      │                               │  Body: JPEG bytes             │
      │                               ├─────────────────────────────►│
      │                               │                              │
      │                               │         WebRTC VideoTrack    │
      │                               │◄─────────────────────────────┤
      │                               │                              │
```

#### 2.2.2 当前限制

1. **单一视频轨道**: `local_video_bridge.py` 只推送单个视频源
2. **无相机标识**: `/push_frame` 接口没有 `camera_id` 参数
3. **无多路复用**: Gateway Lite 只维护一个 `SharedVideoTrack`

### 2.3 多视频流支持可行性

#### 2.3.1 硬件层面 ✅ 支持

- Orbbec 驱动已支持最多 4 个相机同时工作
- USB 带宽足够 (USB 3.0)
- 机器人有多个 USB 端口

#### 2.3.2 ROS2 层面 ✅ 支持

- 每个相机有独立的话题命名空间 (`/G330_0`, `/G330_1`, ...)
- 支持同步模式 (`sync_mode: primary/secondary_synced`)
- 支持独立配置 (分辨率、帧率)

#### 2.3.3 Gateway 层面 ⚠️ 需要改造

- 需要支持多个 `SharedVideoTrack` 实例
- 需要扩展 `/push_frame` 接口支持 `camera_id`
- 需要修改 WebRTC 协商支持多 transceiver

#### 2.3.4 移动端层面 ⚠️ 需要改造

- 需要支持多个 `VideoTrack` 接收
- 需要实现主副视频切换 UI
- 需要处理多视频流带宽

### 2.4 推荐的相机配置

| 相机 ID | 位置 | 用途 | 优先级 |
|---------|------|------|--------|
| `head` | 头部 | 主视角、导航 | 主视频 (默认) |
| `chest` | 胸部 | 操作视角、物体识别 | 副视频 |
| `left_hand` | 左手 | 精细操作、抓取 | 副视频 |
| `right_hand` | 右手 | 精细操作、抓取 | 副视频 |

---

## 三、当前架构分析

### 2.1 移动端视频流架构

```
┌─────────────────────────────────────────────────────────────┐
│                      TeleopScreen                           │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              VideoBackground                         │   │
│  │  ┌─────────────────────────────────────────────┐    │   │
│  │  │         RealtimeVideoView                    │    │   │
│  │  │         (SurfaceViewRenderer)                │    │   │
│  │  └─────────────────────────────────────────────┘    │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                            ▲
                            │ VideoTrack?
                            │
┌─────────────────────────────────────────────────────────────┐
│                    TeleopCoordinator                        │
│  - updateVideoTrack(track: VideoTrack?)                    │
│  - uiState.remoteVideoTrack: VideoTrack?                   │
└─────────────────────────────────────────────────────────────┘
                            ▲
                            │ StateFlow<VideoTrack?>
                            │
┌─────────────────────────────────────────────────────────────┐
│                   WebRtcRobotClient                         │
│  - remoteVideoTrack: StateFlow<VideoTrack?>                │
│  - onAddTrack() → _remoteVideoTrack.value = track          │
└─────────────────────────────────────────────────────────────┘
                            ▲
                            │ WebRTC PeerConnection
                            │
┌─────────────────────────────────────────────────────────────┐
│                    Gateway Lite                             │
│  - SharedVideoTrack (单一视频轨道)                          │
│  - pc.addTrack(self._video_track)                          │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 当前限制
1. **单一视频轨道**: `RobotClient` 接口只支持单个 `remoteVideoTrack`
2. **无相机标识**: 后端推送视频帧时没有相机 ID 标识
3. **无切换机制**: UI 层没有主副视频切换逻辑
4. **信令协议**: 信令协议未定义多视频流协商

---

## 三、目标架构设计

### 3.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                      TeleopScreen                           │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  CameraSelectorDropdown (顶部下拉栏)                 │   │
│  │  - 显示所有可用相机列表                              │   │
│  │  - 点击切换主视频                                    │   │
│  └─────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              PrimaryVideoView (全屏)                 │   │
│  │  - 显示当前主视频流                                  │   │
│  └─────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │         SecondaryCameraBar (底部缩略图栏)            │   │
│  │  - 显示副视频流缩略图                                │   │
│  │  - 点击切换为主视频                                  │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    TeleopCoordinator                        │
│  - videoStreams: StateFlow<Map<String, VideoStream>>        │
│  - primaryCameraId: StateFlow<String>                       │
│  - switchPrimaryCamera(cameraId: String)                    │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                   WebRtcRobotClient                         │
│  - videoTracks: StateFlow<Map<String, VideoTrack>>          │
│  - 多 transceiver 支持                                      │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    Gateway Lite                             │
│  - video_tracks: Dict[str, SharedVideoTrack]               │
│  - 多视频轨道支持                                          │
│  - /push_frame?camera_id=xxx                               │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 数据模型设计

#### 3.2.1 VideoStream 数据类

```kotlin
// core/model/VideoStream.kt
package com.tgrobot.mobile.core.model

import org.webrtc.VideoTrack

/**
 * 视频流数据模型
 * 
 * @property cameraId 相机唯一标识 (如 "head", "chest", "left_hand", "right_hand")
 * @property displayName 显示名称 (如 "头部相机", "胸部相机")
 * @property track WebRTC 视频轨道
 * @property isPrimary 是否为主视频流
 * @property order 排序权重 (用于 UI 展示顺序)
 */
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

/**
 * 相机类型枚举
 */
enum class CameraType(val id: String, val displayName: String, val defaultOrder: Int) {
    HEAD("head", "头部相机", 0),
    CHEST("chest", "胸部相机", 1),
    LEFT_HAND("left_hand", "左手相机", 2),
    RIGHT_HAND("right_hand", "右手相机", 3),
    ;

    companion object {
        fun fromId(id: String): CameraType? {
            return values().find { it.id == id }
        }
    }
}
```

#### 3.2.2 VideoStreamState 状态类

```kotlin
// feature/control/VideoStreamState.kt
package com.tgrobot.mobile.feature.control

import com.tgrobot.mobile.core.model.VideoStream

/**
 * 视频流状态
 */
data class VideoStreamState(
    val streams: Map<String, VideoStream> = emptyMap(),
    val primaryCameraId: String = "head",
    val isLoading: Boolean = false,
    val error: String? = null,
) {
    val primaryStream: VideoStream?
        get() = streams[primaryCameraId]

    val secondaryStreams: List<VideoStream>
        get() = streams.values
            .filter { it.cameraId != primaryCameraId }
            .sortedBy { it.order }

    val availableCameras: List<String>
        get() = streams.values
            .filter { it.isAvailable }
            .sortedBy { it.order }
            .map { it.cameraId }
}
```

### 3.3 接口层改造

#### 3.3.1 RobotClient 接口扩展

```kotlin
// data/RobotClient.kt
interface RobotClient {
    // ... 现有接口保持不变 ...

    /**
     * 远程视频轨道 (已废弃，使用 videoTracks)
     */
    @Deprecated("Use videoTracks instead", ReplaceWith("videoTracks"))
    val remoteVideoTrack: StateFlow<VideoTrack?>
        get() = videoTracks.map { it.values.firstOrNull()?.track }
            .stateIn(CoroutineScope(Dispatchers.IO), SharingStarted.Eagerly, null)

    /**
     * 所有远程视频轨道
     */
    val videoTracks: StateFlow<Map<String, VideoTrack>>

    /**
     * 切换主视频流
     */
    suspend fun setPrimaryCamera(cameraId: String): Boolean
}
```

#### 3.3.2 WebRtcRobotClient 实现

```kotlin
// data/WebRtcRobotClient.kt
class WebRtcRobotClient(...) : RobotClient {
    // ... 现有代码 ...

    private val _videoTracks = MutableStateFlow<Map<String, VideoTrack>>(emptyMap())
    override val videoTracks: StateFlow<Map<String, VideoTrack>> = _videoTracks.asStateFlow()

    // 兼容旧接口
    override val remoteVideoTrack: StateFlow<VideoTrack?> = _videoTracks
        .map { it.values.firstOrNull() }
        .stateIn(scope, SharingStarted.Eagerly, null)

    override suspend fun setPrimaryCamera(cameraId: String): Boolean {
        // 发送信令通知后端切换主视频
        val payload = JSONObject()
            .put("type", "camera_switch")
            .put("camera_id", cameraId)
        return sendData(payload.toString())
    }

    private fun createPeerConnection(endpoint: RobotEndpoint): PeerConnection? {
        // ... 现有代码 ...

        val pc = peerConnectionFactory.createPeerConnection(
            rtcConfig,
            object : PeerConnection.Observer {
                // ... 现有回调 ...

                override fun onAddTrack(receiver: RtpReceiver, mediaStreams: Array<MediaStream>) {
                    val track = receiver.track() as? VideoTrack ?: return
                    
                    // 从 MediaStream 或 SDP 中提取相机 ID
                    val cameraId = extractCameraId(mediaStreams, receiver)
                    
                    _videoTracks.update { current ->
                        current + (cameraId to track)
                    }
                }

                override fun onRemoveTrack(receiver: RtpReceiver) {
                    val track = receiver.track() ?: return
                    _videoTracks.update { current ->
                        current.filterValues { it != track }
                    }
                }
            },
        )

        // ... 现有代码 ...
    }

    private fun extractCameraId(mediaStreams: Array<MediaStream>, receiver: RtpReceiver): String {
        // 尝试从 MediaStream ID 中提取相机 ID
        // 格式: "camera_head", "camera_chest", etc.
        for (stream in mediaStreams) {
            val streamId = stream.id
            if (streamId.startsWith("camera_")) {
                return streamId.removePrefix("camera_")
            }
        }
        
        // 从 SDP mid 中提取 (如 "video_head", "video_chest")
        val mid = receiver.track()?.id() ?: "0"
        return when {
            mid.contains("head") -> "head"
            mid.contains("chest") -> "chest"
            mid.contains("left") -> "left_hand"
            mid.contains("right") -> "right_hand"
            else -> "head" // 默认
        }
    }

    private suspend fun cleanupPeer() {
        // ... 现有代码 ...
        _videoTracks.value = emptyMap()
    }
}
```

### 3.4 UI 组件设计

#### 3.4.1 CameraSelectorDropdown 组件

```kotlin
// feature/control/CameraSelectorDropdown.kt
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

/**
 * 相机选择下拉栏
 * 
 * 显示在屏幕顶部，用于切换主视频流
 */
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
        // 触发按钮
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

        // 下拉菜单
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

#### 3.4.2 SecondaryCameraBar 组件

```kotlin
// feature/control/SecondaryCameraBar.kt
package com.tgrobot.mobile.feature.control

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.tgrobot.mobile.core.model.VideoStream
import org.webrtc.VideoTrack

/**
 * 副相机缩略图栏
 * 
 * 显示在屏幕底部，展示副视频流缩略图
 */
@Composable
fun SecondaryCameraBar(
    streams: List<VideoStream>,
    onCameraSelected: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    if (streams.isEmpty()) return

    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        streams.forEach { stream ->
            SecondaryCameraThumbnail(
                stream = stream,
                onClick = { onCameraSelected(stream.cameraId) },
                modifier = Modifier
                    .weight(1f)
                    .aspectRatio(16f / 9f),
            )
        }
    }
}

@Composable
private fun SecondaryCameraThumbnail(
    stream: VideoStream,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Box(
        modifier = modifier
            .clip(RoundedCornerShape(8.dp))
            .background(Color.Black)
            .border(1.dp, Color.White.copy(alpha = 0.3f), RoundedCornerShape(8.dp))
            .clickable(onClick = onClick),
    ) {
        // 视频缩略图
        if (stream.track != null) {
            RealtimeVideoView(
                track = stream.track,
                modifier = Modifier.fillMaxSize(),
            )
        }

        // 相机名称标签
        Text(
            text = stream.displayName,
            modifier = Modifier
                .align(Alignment.BottomStart)
                .padding(4.dp),
            color = Color.White,
            style = androidx.compose.material.MaterialTheme.typography.caption,
        )
    }
}
```

#### 3.4.3 TeleopScreen 改造

```kotlin
// feature/control/TeleopScreen.kt
@Composable
private fun DriveScreen(
    state: TeleopUiState,
    onDisconnectClick: () -> Unit,
    onEmergencyStop: () -> Unit,
    onVoiceControlClick: () -> Unit,
    onJoystickInput: (Float, Float) -> Unit,
    onJoystickRelease: () -> Unit,
    onDraftTextChange: (String) -> Unit,
    onSendText: () -> Unit,
    onCameraSelected: (String) -> Unit, // 新增
) {
    var showChat by remember { mutableStateOf(false) }

    Box(modifier = Modifier.fillMaxSize()) {
        // Layer 0: 主视频全屏
        VideoBackground(
            track = state.primaryVideoTrack, // 改为使用主视频轨道
        )

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

        // Top-left: 连接状态
        TopLeftHud(
            state = state,
            onDisconnectClick = onDisconnectClick,
            modifier = Modifier.align(Alignment.TopStart),
        )

        // Top-right: 状态信息
        TopRightHud(
            state = state,
            modifier = Modifier.align(Alignment.TopEnd),
        )

        // Bottom: 副相机缩略图栏 (新增)
        SecondaryCameraBar(
            streams = state.secondaryVideoStreams,
            onCameraSelected = onCameraSelected,
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .padding(bottom = 180.dp),
        )

        // Bottom-left: 摇杆
        Box(
            modifier = Modifier
                .align(Alignment.BottomStart)
                .padding(start = 24.dp, bottom = 24.dp),
        ) {
            JoystickView(
                modifier = Modifier.size(180.dp),
                onInput = onJoystickInput,
                onRelease = onJoystickRelease,
            )
        }

        // Bottom-right: E-Stop + 语音 + 聊天
        // ... 现有代码 ...
    }
}
```

### 3.5 TeleopUiState 扩展

```kotlin
// feature/control/TeleopUiState.kt
data class TeleopUiState(
    // ... 现有字段 ...

    // 多视频流支持
    val videoStreams: Map<String, VideoStream> = emptyMap(),
    val primaryCameraId: String = "head",

    // 兼容旧接口
    override val remoteVideoTrack: VideoTrack?
        get() = videoStreams[primaryCameraId]?.track,
) {
    // ... 现有计算属性 ...

    /**
     * 主视频轨道
     */
    val primaryVideoTrack: VideoTrack?
        get() = videoStreams[primaryCameraId]?.track

    /**
     * 副视频流列表
     */
    val secondaryVideoStreams: List<VideoStream>
        get() = videoStreams.values
            .filter { it.cameraId != primaryCameraId }
            .sortedBy { it.order }

    /**
     * 可用相机数量
     */
    val availableCameraCount: Int
        get() = videoStreams.values.count { it.isAvailable }
}
```

### 3.6 TeleopCoordinator 扩展

```kotlin
// feature/control/TeleopCoordinator.kt
class TeleopCoordinator(
    // ... 现有依赖 ...
) {
    // ... 现有代码 ...

    /**
     * 切换主视频流
     */
    fun switchPrimaryCamera(cameraId: String) {
        if (!_uiState.value.videoStreams.containsKey(cameraId)) {
            messageStore.addSystemMessage("Camera $cameraId not available.")
            return
        }

        _uiState.update { it.copy(primaryCameraId = cameraId) }
        messageStore.addSystemMessage("Switched to ${_uiState.value.videoStreams[cameraId]?.displayName}")

        scope.launch {
            val success = sendControlUseCase.setPrimaryCamera(cameraId)
            if (!success) {
                messageStore.addSystemMessage("Failed to notify robot about camera switch.")
            }
        }
    }

    /**
     * 更新视频轨道
     */
    fun updateVideoTracks(tracks: Map<String, VideoTrack>) {
        val currentStreams = _uiState.value.videoStreams
        val updatedStreams = tracks.mapValues { (cameraId, track) ->
            val existing = currentStreams[cameraId]
            VideoStream(
                cameraId = cameraId,
                displayName = existing?.displayName ?: CameraType.fromId(cameraId)?.displayName ?: cameraId,
                track = track,
                isPrimary = cameraId == _uiState.value.primaryCameraId,
                order = existing?.order ?: CameraType.fromId(cameraId)?.defaultOrder ?: 99,
            )
        }

        _uiState.update { it.copy(videoStreams = updatedStreams) }
    }

    // 兼容旧接口
    fun updateVideoTrack(track: VideoTrack?) {
        if (track == null) {
            updateVideoTracks(emptyMap())
        } else {
            updateVideoTracks(mapOf("head" to track))
        }
    }
}
```

---

## 四、后端改造设计

### 4.1 Gateway Lite 改造

#### 4.1.1 多视频轨道支持

```python
# gateway_lite/video_track.py
from __future__ import annotations

import asyncio
import io
from dataclasses import dataclass, field
from typing import Dict, Optional

import av
from aiortc import VideoStreamTrack

try:
    import numpy as np
    from PIL import Image
except Exception:
    np = None
    Image = None


@dataclass(slots=True)
class VideoMetrics:
    pushed: int = 0
    dropped: int = 0
    sent: int = 0


class SharedVideoTrack(VideoStreamTrack):
    """单个视频轨道"""
    kind = "video"

    def __init__(self, camera_id: str = "default") -> None:
        super().__init__()
        self.camera_id = camera_id
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=4)
        self.metrics = VideoMetrics()

    def push_jpeg(self, jpeg: bytes) -> bool:
        # ... 现有实现 ...
        pass

    async def recv(self) -> av.VideoFrame:
        # ... 现有实现 ...
        pass


class MultiCameraVideoManager:
    """多相机视频管理器
    
    支持从多个 ROS2 相机话题接收视频帧，并通过 WebRTC 推送到移动端。
    
    相机 ID 映射:
    - "head" → 头部相机 (主视频)
    - "chest" → 胸部相机
    - "left_hand" → 左手相机
    - "right_hand" → 右手相机
    """
    
    # 默认相机配置 (与机器人 ROS2 launch 配置对应)
    DEFAULT_CAMERAS = {
        "head": {"ros_topic": "/G330_0/color/image_raw/compressed"},
        "chest": {"ros_topic": "/G330_1/color/image_raw/compressed"},
        "left_hand": {"ros_topic": "/G330_2/color/image_raw/compressed"},
        "right_hand": {"ros_topic": "/G330_3/color/image_raw/compressed"},
    }
    
    def __init__(self, camera_ids: list[str] = None):
        self._tracks: Dict[str, SharedVideoTrack] = {}
        self._primary_camera_id: str = "head"
        
        # 初始化默认相机
        default_cameras = camera_ids or list(self.DEFAULT_CAMERAS.keys())
        for camera_id in default_cameras:
            self._tracks[camera_id] = SharedVideoTrack(camera_id=camera_id)

    def get_track(self, camera_id: str) -> Optional[SharedVideoTrack]:
        return self._tracks.get(camera_id)

    def get_all_tracks(self) -> Dict[str, SharedVideoTrack]:
        return self._tracks.copy()

    def push_frame(self, camera_id: str, jpeg: bytes) -> bool:
        """推送视频帧到指定相机轨道
        
        Args:
            camera_id: 相机 ID (如 "head", "chest")
            jpeg: JPEG 编码的视频帧
            
        Returns:
            是否成功推送
        """
        track = self._tracks.get(camera_id)
        if track is None:
            # 动态创建新相机轨道
            track = SharedVideoTrack(camera_id=camera_id)
            self._tracks[camera_id] = track
        return track.push_jpeg(jpeg)

    def set_primary_camera(self, camera_id: str) -> bool:
        if camera_id not in self._tracks:
            return False
        self._primary_camera_id = camera_id
        return True

    def get_primary_camera_id(self) -> str:
        return self._primary_camera_id

    def get_metrics(self) -> Dict[str, dict]:
        return {
            camera_id: track.get_metrics()
            for camera_id, track in self._tracks.items()
        }
    
    def get_available_cameras(self) -> list[str]:
        """获取有视频流的相机列表"""
        return [
            camera_id for camera_id, track in self._tracks.items()
            if track.metrics.pushed > 0
        ]
```

#### 4.1.2 Server 改造

```python
# gateway_lite/server.py
class GatewayServer:
    def __init__(self, config: GatewayConfig) -> None:
        # ... 现有代码 ...
        
        # 替换单一视频轨道为多相机管理器
        self._video_manager: MultiCameraVideoManager | None = (
            MultiCameraVideoManager() if self.cfg.video_enabled else None
        )

    async def _push_frame_handler(self, request: web.Request) -> web.Response:
        if self._video_manager is None:
            return web.json_response({"ok": False, "error": "video_disabled"}, status=404)

        # 验证 token
        token = self.cfg.video_push_token
        if token:
            got = request.headers.get("X-Push-Token", "")
            if got != token:
                return web.json_response({"ok": False, "error": "unauthorized"}, status=401)

        # 获取相机 ID (支持 query 参数和 header)
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

    def _setup_peer(self, session: PeerSession, ws: web.WebSocketResponse) -> None:
        pc = session.pc

        # 添加所有视频轨道 (使用 stream_id 标识相机)
        if self._video_manager is not None:
            for camera_id, track in self._video_manager.get_all_tracks().items():
                # stream_id 格式: "camera_{camera_id}"
                # 移动端通过 stream_id 识别相机
                pc.addTrack(track, stream_id=f"camera_{camera_id}")

        # ... 其他代码保持不变 ...

    async def _on_dc_message(self, session: PeerSession, raw: str) -> None:
        # ... 现有代码 ...

        # 处理相机切换
        if msg_type == "camera_switch":
            camera_id = data.get("camera_id")
            if camera_id and self._video_manager:
                success = self._video_manager.set_primary_camera(camera_id)
                session.dc_send({
                    "type": "camera_switch_ack",
                    "camera_id": camera_id,
                    "success": success,
                    "available_cameras": self._video_manager.get_available_cameras(),
                })
            return

        # ... 其他消息处理 ...
```

### 4.2 视频推送脚本改造

#### 4.2.1 多相机视频桥接脚本

```python
# scripts/multi_camera_bridge.py
"""
多相机视频桥接脚本

从多个 ROS2 相机话题订阅视频帧，推送到 Gateway Lite。

使用方式:
    # 启动所有相机
    python multi_camera_bridge.py --gateway http://127.0.0.1:9100

    # 只启动指定相机
    python multi_camera_bridge.py --cameras head,chest

    # 使用 ROS2 话题
    python multi_camera_bridge.py --ros-topics /G330_0/color/image_raw/compressed,/G330_1/color/image_raw/compressed
"""
from __future__ import annotations

import argparse
import asyncio
import time
from typing import Dict, List, Optional

import cv2
import httpx
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage


class MultiCameraBridge(Node):
    """ROS2 节点: 订阅多个相机话题并推送到 Gateway"""

    CAMERA_TOPICS = {
        "head": "/G330_0/color/image_raw/compressed",
        "chest": "/G330_1/color/image_raw/compressed",
        "left_hand": "/G330_2/color/image_raw/compressed",
        "right_hand": "/G330_3/color/image_raw/compressed",
    }

    def __init__(
        self,
        gateway_url: str,
        camera_ids: List[str],
        push_token: str = "",
        fps: float = 15.0,
        jpeg_quality: int = 80,
    ):
        super().__init__("multi_camera_bridge")
        self._gateway_url = gateway_url.rstrip("/")
        self._push_token = push_token
        self._fps = fps
        self._jpeg_quality = jpeg_quality

        self._client = httpx.AsyncClient(timeout=1.2)
        self._metrics: Dict[str, Dict[str, int]] = {}
        self._last_push: Dict[str, float] = {}

        # 订阅相机话题
        self._subscriptions = {}
        for camera_id in camera_ids:
            topic = self.CAMERA_TOPICS.get(camera_id)
            if topic:
                self._subscriptions[camera_id] = self.create_subscription(
                    CompressedImage,
                    topic,
                    lambda msg, cid=camera_id: self._on_frame(cid, msg),
                    10,
                )
                self._metrics[camera_id] = {"sent": 0, "failed": 0}
                self._last_push[camera_id] = 0.0
                self.get_logger().info(f"Subscribed to {topic} as {camera_id}")

    def _on_frame(self, camera_id: str, msg: CompressedImage):
        """处理相机帧"""
        now = time.time()
        interval = 1.0 / self._fps

        # 帧率控制
        if now - self._last_push.get(camera_id, 0) < interval:
            return
        self._last_push[camera_id] = now

        # 异步推送
        asyncio.create_task(self._push_frame(camera_id, msg.data))

    async def _push_frame(self, camera_id: str, jpeg_data: bytes):
        """推送帧到 Gateway"""
        url = f"{self._gateway_url}/push_frame?camera_id={camera_id}"
        headers = {"X-Push-Token": self._push_token} if self._push_token else {}

        try:
            resp = await self._client.post(url, content=jpeg_data, headers=headers)
            if resp.status_code < 400:
                self._metrics[camera_id]["sent"] += 1
            else:
                self._metrics[camera_id]["failed"] += 1
        except Exception:
            self._metrics[camera_id]["failed"] += 1

    def get_metrics(self) -> Dict[str, Dict[str, int]]:
        return self._metrics.copy()


def main():
    parser = argparse.ArgumentParser(description="Multi-camera video bridge")
    parser.add_argument("--gateway", default="http://127.0.0.1:9100")
    parser.add_argument("--cameras", default="head,chest,left_hand,right_hand")
    parser.add_argument("--push-token", default="")
    parser.add_argument("--fps", type=float, default=15.0)
    parser.add_argument("--jpeg-quality", type=int, default=80)
    args = parser.parse_args()

    camera_ids = [c.strip() for c in args.cameras.split(",") if c.strip()]

    rclpy.init()
    node = MultiCameraBridge(
        gateway_url=args.gateway,
        camera_ids=camera_ids,
        push_token=args.push_token,
        fps=args.fps,
        jpeg_quality=args.jpeg_quality,
    )

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
```

### 4.3 信令协议扩展

#### 4.2.1 Offer/Answer 扩展

```json
// Offer SDP 扩展 (客户端发送)
{
  "type": "offer",
  "sdp": "...",
  "chat_id": "xxx",
  "sender_id": "xxx",
  "cameras": ["head", "chest", "left_hand", "right_hand"]  // 新增：请求的相机列表
}

// Answer SDP 扩展 (服务端响应)
{
  "type": "answer",
  "sdp": "...",
  "chat_id": "xxx",
  "cameras": {
    "head": {"available": true, "stream_id": "camera_head"},
    "chest": {"available": true, "stream_id": "camera_chest"},
    "left_hand": {"available": false, "reason": "not_connected"},
    "right_hand": {"available": false, "reason": "not_connected"}
  }
}
```

#### 4.2.2 相机切换消息

```json
// 客户端 → 服务端
{
  "type": "camera_switch",
  "camera_id": "chest"
}

// 服务端 → 客户端
{
  "type": "camera_switch_ack",
  "camera_id": "chest",
  "success": true
}
```

#### 4.2.3 相机状态通知

```json
// 服务端 → 客户端 (相机上线/下线)
{
  "type": "camera_status",
  "camera_id": "left_hand",
  "status": "online",  // or "offline"
  "stream_id": "camera_left_hand"
}
```

---

## 五、实施计划

### 5.1 Phase 1: 数据模型与接口定义 (PR-1)

**目标**: 定义多视频流核心数据模型和接口

**任务**:
1. 创建 `VideoStream` 数据类
2. 创建 `CameraType` 枚举
3. 创建 `VideoStreamState` 状态类
4. 扩展 `RobotClient` 接口
5. 更新 `TeleopUiState`

**文件**:
- `core/model/VideoStream.kt` (新建)
- `data/RobotClient.kt` (修改)
- `feature/control/TeleopUiState.kt` (修改)

**风险**: 低 - 仅添加新接口，不修改现有逻辑

---

### 5.2 Phase 2: WebRTC 客户端改造 (PR-2)

**目标**: 实现多视频轨道接收和解析

**任务**:
1. 修改 `WebRtcRobotClient` 支持多 transceiver
2. 实现 `extractCameraId()` 从 SDP/MediaStream 提取相机 ID
3. 实现 `videoTracks` StateFlow
4. 实现 `setPrimaryCamera()` 方法
5. 保持 `remoteVideoTrack` 向后兼容

**文件**:
- `data/WebRtcRobotClient.kt` (修改)

**风险**: 中 - 需要修改核心 WebRTC 逻辑，需要充分测试

---

### 5.3 Phase 3: UI 组件开发 (PR-3)

**目标**: 开发相机选择和切换 UI 组件

**任务**:
1. 创建 `CameraSelectorDropdown` 组件
2. 创建 `SecondaryCameraBar` 组件
3. 创建 `SecondaryCameraThumbnail` 组件
4. 修改 `TeleopScreen` 集成新组件

**文件**:
- `feature/control/CameraSelectorDropdown.kt` (新建)
- `feature/control/SecondaryCameraBar.kt` (新建)
- `feature/control/TeleopScreen.kt` (修改)

**风险**: 低 - 纯 UI 组件，不影响业务逻辑

---

### 5.4 Phase 4: Coordinator 集成 (PR-4)

**目标**: 集成多视频流到业务流程

**任务**:
1. 扩展 `TeleopCoordinator` 支持多视频流
2. 实现 `switchPrimaryCamera()` 方法
3. 实现 `updateVideoTracks()` 方法
4. 保持 `updateVideoTrack()` 向后兼容
5. 更新 `TeleopViewModel` (如果存在)

**文件**:
- `feature/control/TeleopCoordinator.kt` (修改)

**风险**: 中 - 需要修改业务协调逻辑

---

### 5.5 Phase 5: 后端多视频轨道支持 (PR-5)

**目标**: 后端支持多相机视频流

**任务**:
1. 创建 `MultiCameraVideoManager` 类
2. 修改 `GatewayServer` 支持多轨道
3. 扩展 `/push_frame` API 支持 `camera_id` 参数
4. 扩展信令协议支持相机列表协商
5. 实现相机切换消息处理
6. 创建多相机视频桥接脚本 `multi_camera_bridge.py`

**文件**:
- `gateway_lite/video_track.py` (修改)
- `gateway_lite/server.py` (修改)
- `scripts/multi_camera_bridge.py` (新建)

**风险**: 高 - 需要修改后端核心逻辑，需要充分测试

---

### 5.6 Phase 6: 机器人端 ROS2 配置 (PR-5.5)

**目标**: 配置机器人端多相机 ROS2 节点

**任务**:
1. 修改 `orbbec_multicamera.launch.py` 配置相机位置映射
2. 配置相机话题命名规则 (`/G330_0` → `head`, etc.)
3. 启动多相机 ROS2 节点
4. 验证视频话题发布正常
5. 配置 systemd 自启动服务

**文件**:
- `TGrobot4s/robot/orbbec_camera_ros2/orbbec_camera_ros2/install/orbbec_camera/share/orbbec_camera/launch/orbbec_multicamera.launch.py` (修改)
- `TGrobot4s/robot/ros2ws/ros2ws/scripts/` (新增启动脚本)

**ROS2 话题映射**:
```yaml
# 相机 ID → ROS2 话题
head: /G330_0/color/image_raw/compressed
chest: /G330_1/color/image_raw/compressed
left_hand: /G330_2/color/image_raw/compressed
right_hand: /G330_3/color/image_raw/compressed
```

**风险**: 中 - 需要修改机器人端配置，需要现场调试

---

### 5.7 Phase 7: 集成测试与优化 (PR-6)

**目标**: 端到端测试和性能优化

**任务**:
1. 编写端到端测试用例
2. 测试多视频流同时传输
3. 测试主副视频切换
4. 性能测试和优化
5. 文档更新

**风险**: 中 - 需要真实设备测试

---

## 六、风险与缓解措施

### 6.1 技术风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| WebRTC 多轨道协商失败 | 高 | 中 | 充分测试 SDP 协商，添加 fallback 逻辑 |
| 视频帧推送延迟增加 | 中 | 中 | 优化队列大小，添加丢帧策略 |
| 内存占用增加 | 中 | 高 | 限制最大相机数量，优化视频缓冲区 |
| UI 渲染性能下降 | 低 | 低 | 使用硬件加速，优化缩略图分辨率 |

### 6.2 兼容性风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| 旧版本客户端不兼容 | 高 | 低 | 保持 `remoteVideoTrack` 接口向后兼容 |
| 旧版本后端不兼容 | 高 | 低 | 后端支持单轨道和多轨道两种模式 |
| 不同 Android 版本表现不一致 | 中 | 中 | 添加版本适配代码，充分测试 |

### 6.3 业务风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| 用户不理解新功能 | 低 | 中 | 添加引导提示，优化 UI 设计 |
| 相机切换延迟影响体验 | 中 | 中 | 添加加载动画，优化切换速度 |

---

## 七、测试策略

### 7.1 单元测试

- `VideoStream` 数据类测试
- `VideoStreamState` 状态计算测试
- `WebRtcRobotClient` 多轨道解析测试
- `TeleopCoordinator` 切换逻辑测试

### 7.2 集成测试

- WebRTC 多轨道协商测试
- 视频帧推送和接收测试
- 相机切换端到端测试

### 7.3 性能测试

- 多视频流带宽占用测试
- UI 渲染帧率测试
- 内存占用测试

### 7.4 兼容性测试

- 不同 Android 版本测试 (Android 8.0+)
- 不同设备分辨率测试
- 与旧版本后端兼容性测试

---

## 八、后续优化方向

### 8.1 短期优化 (1-2 周)

- 添加视频质量自适应 (根据网络状况调整分辨率)
- 添加视频流录制功能
- 优化缩略图渲染性能

### 8.2 中期优化 (1-2 月)

- 支持视频流截图
- 支持视频流标注 (在视频上绘制标记)
- 支持画中画模式

### 8.3 长期优化 (3-6 月)

- 支持 AI 视频分析 (目标检测、跟踪)
- 支持 VR/AR 显示模式
- 支持多用户协同观看

---

## 九、机器人端支持总结

### 9.1 硬件与驱动支持 ✅

| 组件 | 支持情况 | 说明 |
|------|----------|------|
| Orbbec 相机 | ✅ 已支持 | Gemini 330 系列，最多 4 个相机 |
| ROS2 驱动 | ✅ 已支持 | `orbbec_camera` 包含多相机 launch 文件 |
| USB 带宽 | ✅ 足够 | USB 3.0 支持多路视频流 |
| 话题命名 | ✅ 已支持 | 每个相机独立命名空间 |

### 9.2 软件层面支持情况

| 层级 | 支持情况 | 需要改造 |
|------|----------|----------|
| ROS2 相机节点 | ✅ 已支持 | 无 |
| 视频推送脚本 | ⚠️ 单相机 | 需要创建多相机版本 |
| Gateway Lite | ⚠️ 单轨道 | 需要支持多轨道 |
| 移动端 | ⚠️ 单视频 | 需要支持多视频流 |

### 9.3 实施优先级

1. **Phase 1-4**: 移动端改造 (不影响机器人端)
2. **Phase 5**: 后端改造 (需要先完成移动端)
3. **Phase 6**: 机器人端配置 (可与 Phase 5 并行)
4. **Phase 7**: 集成测试

### 9.4 相机配置建议

```yaml
# 推荐的相机配置
cameras:
  - id: head
    position: 头部
    ros_topic: /G330_0/color/image_raw/compressed
    priority: primary
    resolution: 640x480
    fps: 15
    
  - id: chest
    position: 胸部
    ros_topic: /G330_1/color/image_raw/compressed
    priority: secondary
    resolution: 640x480
    fps: 15
    
  - id: left_hand
    position: 左手
    ros_topic: /G330_2/color/image_raw/compressed
    priority: secondary
    resolution: 320x240
    fps: 10
    
  - id: right_hand
    position: 右手
    ros_topic: /G330_3/color/image_raw/compressed
    priority: secondary
    resolution: 320x240
    fps: 10
```

### 9.5 带宽估算

```
主视频 (head): 640x480 @ 15fps, JPEG 80% ≈ 2 Mbps
副视频 (chest): 640x480 @ 15fps, JPEG 80% ≈ 2 Mbps
副视频 (left_hand): 320x240 @ 10fps, JPEG 70% ≈ 0.5 Mbps
副视频 (right_hand): 320x240 @ 10fps, JPEG 70% ≈ 0.5 Mbps
---------------------------------------------------
总计: ≈ 5 Mbps (WiFi 5 足够)
```

---

## 十、总结

本方案设计了一套完整的多视频流传输和切换系统，主要特点：

1. **架构清晰**: 遵循现有 UseCase、Coordinator 模式
2. **向后兼容**: 保持现有接口不变，渐进式升级
3. **可扩展**: 支持动态添加相机，不限制数量
4. **用户友好**: 直观的 UI 设计，流畅的切换体验
5. **风险可控**: 分阶段实施，每阶段独立可测试

通过 6 个 PR 的渐进式开发，可以在 2-3 周内完成核心功能，后续根据用户反馈持续优化。
