package com.tgrobot.mobile.core.model

import java.util.UUID

data class RobotSession(
    val chatId: String,
    val senderId: String = chatId,
) {
    companion object {
        fun create(senderId: String? = null): RobotSession {
            val chatId = UUID.randomUUID().toString()
            return RobotSession(chatId = chatId, senderId = senderId ?: chatId)
        }
    }
}
