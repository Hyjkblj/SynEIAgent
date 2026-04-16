package com.tgrobot.mobile.data

import com.tgrobot.mobile.core.model.RobotConnectionState
import com.tgrobot.mobile.core.model.RobotEndpoint
import com.tgrobot.mobile.core.model.RobotEvent
import com.tgrobot.mobile.core.model.RobotSession
import com.tgrobot.mobile.core.model.TeleopCommand
import com.tgrobot.mobile.core.model.VoiceIntentPayload
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.StateFlow
import org.webrtc.VideoTrack

/**
 * 统一的机器人客户端接口
 * 
 * 合并了原 [RobotRepository] 和 [RealtimeTransport] 的职责，
 * 提供与机器人通信的完整抽象。
 * 
 * 职责：
 * - 连接管理（信令 + WebRTC）
 * - 控制命令发送
 * - 文本消息发送
 * - 语音意图发送
 * - 视频流接收
 * - 事件流订阅
 */
interface RobotClient {
    /**
     * 连接状态
     */
    val connectionState: StateFlow<RobotConnectionState>

    /**
     * 来自机器人的事件流
     */
    val events: Flow<RobotEvent>

    /**
     * 远程视频轨道
     */
    val remoteVideoTrack: StateFlow<VideoTrack?>

    /**
     * 连接到机器人
     * 
     * @param endpoint 机器人端点配置
     * @param session 会话信息
     */
    suspend fun connect(endpoint: RobotEndpoint, session: RobotSession)

    /**
     * 断开连接
     */
    suspend fun disconnect()

    /**
     * 发送控制命令
     * 
     * @param command 控制命令
     * @param clientTsMs 客户端时间戳（毫秒）
     * @return 是否发送成功
     */
    suspend fun sendControl(command: TeleopCommand, clientTsMs: Long): Boolean

    /**
     * 发送文本消息
     * 
     * @param content 文本内容
     * @return 是否发送成功
     */
    suspend fun sendText(content: String): Boolean

    /**
     * 发送语音意图
     * 
     * @param intent 语音意图载荷
     * @return 是否发送成功
     */
    suspend fun sendVoiceIntent(intent: VoiceIntentPayload): Boolean
}
