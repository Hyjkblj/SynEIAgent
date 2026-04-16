package com.tgrobot.mobile.domain.usecase

import com.tgrobot.mobile.data.RobotClient
import com.tgrobot.mobile.domain.control.ControlEngine
import com.tgrobot.mobile.feature.voice.VoiceModule

/**
 * 断开机器人连接用例
 * 
 * 封装断开连接的业务逻辑。
 * 
 * 职责：
 * - 取消语音监听
 * - 停止控制循环
 * - 重置控制状态
 * - 断开连接
 */
class DisconnectRobotUseCase(
    private val robotClient: RobotClient,
    private val controlEngine: ControlEngine,
    private val voiceModule: VoiceModule,
) {
    /**
     * 执行断开连接
     */
    suspend operator fun invoke() {
        voiceModule.cancelListening()
        controlEngine.stopControlLoop()
        controlEngine.reset()
        robotClient.disconnect()
    }
}
