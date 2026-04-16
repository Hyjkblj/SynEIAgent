package com.tgrobot.mobile.domain.usecase

import com.tgrobot.mobile.core.model.VoiceIntentPayload
import com.tgrobot.mobile.data.RobotClient
import com.tgrobot.mobile.domain.voice.VoiceIntentCommand
import com.tgrobot.mobile.domain.voice.VoiceIntentParser

/**
 * 语音意图处理结果
 */
sealed interface VoiceIntentResult {
    /**
     * 移动命令
     */
    data class Move(
        val linear: Float,
        val angular: Float,
        val durationMs: Int,
    ) : VoiceIntentResult

    /**
     * 动作命令
     */
    data class Action(
        val actionId: String,
        val motionNumber: Int,
    ) : VoiceIntentResult

    /**
     * 停止命令
     */
    data object Stop : VoiceIntentResult

    /**
     * 重置紧急停止
     */
    data object ResetEmergency : VoiceIntentResult

    /**
     * 查询电池
     */
    data object QueryBattery : VoiceIntentResult

    /**
     * 查询配置
     */
    data object QueryConfig : VoiceIntentResult

    /**
     * 查询状态
     */
    data object QueryStatus : VoiceIntentResult

    /**
     * 未知命令（作为文本发送）
     */
    data class Unknown(val text: String) : VoiceIntentResult

    /**
     * 发送失败
     */
    data class Failed(val message: String) : VoiceIntentResult
}

/**
 * 处理语音意图用例
 * 
 * 封装语音意图解析和发送的业务逻辑。
 * 
 * 职责：
 * - 解析语音文本为意图
 * - 构建并发送意图载荷
 * - 返回处理结果
 */
class ProcessVoiceIntentUseCase(
    private val robotClient: RobotClient,
    private val voiceIntentParser: VoiceIntentParser,
) {
    /**
     * 处理语音文本
     * 
     * @param text 语音文本
     * @return 处理结果
     */
    suspend operator fun invoke(text: String): VoiceIntentResult {
        val intent = voiceIntentParser.parse(text)

        return when (intent) {
            is VoiceIntentCommand.Move -> {
                val payload = VoiceIntentPayload(
                    intent = "move",
                    linear = intent.linear,
                    angular = intent.angular,
                    durationMs = intent.durationMs,
                )
                if (robotClient.sendVoiceIntent(payload)) {
                    VoiceIntentResult.Move(
                        linear = intent.linear,
                        angular = intent.angular,
                        durationMs = intent.durationMs,
                    )
                } else {
                    VoiceIntentResult.Failed("Voice command send failed: move")
                }
            }

            is VoiceIntentCommand.Action -> {
                val payload = VoiceIntentPayload(
                    intent = "action",
                    actionId = intent.actionId,
                    motionNumber = intent.motionNumber,
                )
                if (robotClient.sendVoiceIntent(payload)) {
                    VoiceIntentResult.Action(
                        actionId = intent.actionId,
                        motionNumber = intent.motionNumber,
                    )
                } else {
                    VoiceIntentResult.Failed("Voice command send failed: action")
                }
            }

            VoiceIntentCommand.Stop -> {
                val payload = VoiceIntentPayload(intent = "stop")
                if (robotClient.sendVoiceIntent(payload)) {
                    VoiceIntentResult.Stop
                } else {
                    VoiceIntentResult.Failed("Voice command send failed: stop")
                }
            }

            VoiceIntentCommand.ResetEmergency -> {
                val payload = VoiceIntentPayload(intent = "reset_emergency")
                if (robotClient.sendVoiceIntent(payload)) {
                    VoiceIntentResult.ResetEmergency
                } else {
                    VoiceIntentResult.Failed("Voice command send failed: reset emergency")
                }
            }

            VoiceIntentCommand.QueryBattery -> VoiceIntentResult.QueryBattery

            VoiceIntentCommand.QueryConfig -> VoiceIntentResult.QueryConfig

            VoiceIntentCommand.QueryStatus -> VoiceIntentResult.QueryStatus

            is VoiceIntentCommand.Unknown -> {
                if (robotClient.sendText(intent.text)) {
                    VoiceIntentResult.Unknown(intent.text)
                } else {
                    VoiceIntentResult.Failed("Voice text fallback send failed")
                }
            }
        }
    }

    /**
     * 获取语音独占窗口时长
     * 
     * @param result 语音意图结果
     * @return 独占窗口时长（毫秒）
     */
    fun getVoiceExclusiveWindowMs(result: VoiceIntentResult): Long {
        return when (result) {
            is VoiceIntentResult.Move -> result.durationMs.toLong() + VOICE_WINDOW_PADDING_MS
            is VoiceIntentResult.Action -> VOICE_ACTION_WINDOW_MS
            is VoiceIntentResult.Stop -> VOICE_STOP_WINDOW_MS
            else -> 0L
        }
    }

    private companion object {
        const val VOICE_WINDOW_PADDING_MS = 120L
        const val VOICE_ACTION_WINDOW_MS = 1400L
        const val VOICE_STOP_WINDOW_MS = 600L
    }
}
