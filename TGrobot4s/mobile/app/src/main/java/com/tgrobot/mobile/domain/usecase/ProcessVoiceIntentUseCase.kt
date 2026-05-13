package com.tgrobot.mobile.domain.usecase

import com.tgrobot.mobile.core.model.VoiceIntentPayload
import com.tgrobot.mobile.data.RobotClient
import com.tgrobot.mobile.domain.voice.VoiceIntentCommand
import com.tgrobot.mobile.domain.voice.VoiceIntentParser

sealed interface VoiceIntentResult {
    data class Move(
        val linear: Float,
        val angular: Float,
        val durationMs: Int,
    ) : VoiceIntentResult

    data class Action(
        val actionId: String,
        val motionNumber: Int,
    ) : VoiceIntentResult

    data object Stop : VoiceIntentResult

    data object ResetEmergency : VoiceIntentResult

    data object Walk : VoiceIntentResult

    data object Zero : VoiceIntentResult

    data object GaitStop : VoiceIntentResult

    data class FsmCmd(val cmd: String) : VoiceIntentResult

    data object QueryBattery : VoiceIntentResult

    data object QueryConfig : VoiceIntentResult

    data object QueryStatus : VoiceIntentResult

    data class Unknown(val text: String) : VoiceIntentResult

    data class Failed(val message: String) : VoiceIntentResult
}

class ProcessVoiceIntentUseCase(
    private val robotClient: RobotClient,
    private val voiceIntentParser: VoiceIntentParser,
) {
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

            VoiceIntentCommand.Walk -> {
                val payload = VoiceIntentPayload(intent = "walk")
                if (robotClient.sendVoiceIntent(payload)) {
                    VoiceIntentResult.Walk
                } else {
                    VoiceIntentResult.Failed("Voice command send failed: walk")
                }
            }

            VoiceIntentCommand.Zero -> {
                val payload = VoiceIntentPayload(intent = "zero")
                if (robotClient.sendVoiceIntent(payload)) {
                    VoiceIntentResult.Zero
                } else {
                    VoiceIntentResult.Failed("Voice command send failed: zero")
                }
            }

            VoiceIntentCommand.GaitStop -> {
                val payload = VoiceIntentPayload(intent = "gait_stop")
                if (robotClient.sendVoiceIntent(payload)) {
                    VoiceIntentResult.GaitStop
                } else {
                    VoiceIntentResult.Failed("Voice command send failed: gait_stop")
                }
            }

            is VoiceIntentCommand.FsmCmd -> {
                val payload = VoiceIntentPayload(intent = "fsm_cmd", fsmCmd = intent.cmd)
                if (robotClient.sendVoiceIntent(payload)) {
                    VoiceIntentResult.FsmCmd(intent.cmd)
                } else {
                    VoiceIntentResult.Failed("Voice command send failed: fsm_cmd")
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

    fun getVoiceExclusiveWindowMs(result: VoiceIntentResult): Long {
        return when (result) {
            is VoiceIntentResult.Move -> result.durationMs.toLong() + VOICE_WINDOW_PADDING_MS
            is VoiceIntentResult.Action -> VOICE_ACTION_WINDOW_MS
            is VoiceIntentResult.Stop -> VOICE_STOP_WINDOW_MS
            is VoiceIntentResult.Walk -> VOICE_ACTION_WINDOW_MS
            is VoiceIntentResult.Zero -> VOICE_ACTION_WINDOW_MS
            is VoiceIntentResult.GaitStop -> VOICE_STOP_WINDOW_MS
            is VoiceIntentResult.FsmCmd -> VOICE_ACTION_WINDOW_MS
            else -> 0L
        }
    }

    private companion object {
        const val VOICE_WINDOW_PADDING_MS = 120L
        const val VOICE_ACTION_WINDOW_MS = 1400L
        const val VOICE_STOP_WINDOW_MS = 600L
    }
}
