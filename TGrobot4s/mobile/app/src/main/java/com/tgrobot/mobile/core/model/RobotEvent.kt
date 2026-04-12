package com.tgrobot.mobile.core.model

sealed interface RobotEvent {
    data class Message(val content: String) : RobotEvent
    data class MessageDelta(val content: String, val end: Boolean) : RobotEvent
    data class Transcription(val content: String) : RobotEvent
    data class Error(val content: String) : RobotEvent
    data class Alert(
        val level: String,
        val errorCode: Int?,
        val content: String,
    ) : RobotEvent

    data class JoystickAck(
        val x: Float,
        val y: Float,
        val ts: Long?,
    ) : RobotEvent

    data class ControlAck(
        val ts: Long?,
    ) : RobotEvent
}
