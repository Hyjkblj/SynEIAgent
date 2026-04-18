package com.tgrobot.mobile.domain.usecase

import android.os.SystemClock
import com.tgrobot.mobile.core.model.TeleopCommand
import com.tgrobot.mobile.data.RobotClient
import com.tgrobot.mobile.domain.control.ControlEngine

/**
 * 发送控制命令用例
 * 
 * 封装发送控制命令的业务逻辑。
 * 
 * 职责：
 * - 协调 ControlEngine 和 RobotClient
 * - 处理语音独占窗口
 * - 更新控制引擎状态
 */
class SendControlCommandUseCase(
    private val robotClient: RobotClient,
    private val controlEngine: ControlEngine,
) {
    /**
     * 发送摇杆输入
     * 
     * @param x X 轴输入 [-1, 1]
     * @param y Y 轴输入 [-1, 1]
     */
    fun updateJoystickInput(x: Float, y: Float) {
        val now = SystemClock.elapsedRealtime()
        controlEngine.updateInput(x, y)
    }

    /**
     * 释放摇杆
     * 
     * @return 停止命令
     */
    suspend fun releaseJoystick(): Boolean {
        val now = SystemClock.elapsedRealtime()
        val command = controlEngine.release(now)
        return sendCommand(command, now)
    }

    /**
     * 紧急停止
     * 
     * @return 是否发送成功
     */
    suspend fun emergencyStop(): Boolean {
        val now = SystemClock.elapsedRealtime()
        val command = controlEngine.emergencyStop(now)
        return sendCommand(command, now)
    }

    /**
     * 发送命令
     * 
     * @param command 控制命令
     * @param nowMs 当前时间戳
     * @return 是否发送成功
     */
    suspend fun sendCommand(command: TeleopCommand, nowMs: Long): Boolean {
        val sent = robotClient.sendControl(command, clientTsMs = nowMs)
        if (sent) {
            controlEngine.onCommandSent(nowMs)
        }
        return sent
    }

    /**
     * 重置控制状态
     */
    fun reset() {
        controlEngine.reset()
    }
}
