package com.tgrobot.mobile.domain.voice

sealed interface VoiceIntentCommand {
    data class Move(
        val linear: Float,
        val angular: Float,
        val durationMs: Int,
    ) : VoiceIntentCommand

    data class Action(
        val actionId: String,
        val motionNumber: Int,
    ) : VoiceIntentCommand

    data object Stop : VoiceIntentCommand

    data object ResetEmergency : VoiceIntentCommand

    data object Walk : VoiceIntentCommand

    data object Zero : VoiceIntentCommand

    data object GaitStop : VoiceIntentCommand

    data class FsmCmd(val cmd: String) : VoiceIntentCommand

    data object QueryBattery : VoiceIntentCommand

    data object QueryConfig : VoiceIntentCommand

    data object QueryStatus : VoiceIntentCommand

    data class Unknown(val text: String) : VoiceIntentCommand
}
