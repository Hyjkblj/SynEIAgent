package com.tgrobot.mobile.domain.message

/**
 * UI 消息角色
 */
enum class UiMessageRole {
    USER,
    ROBOT,
    SYSTEM,
}

/**
 * UI 消息
 * 
 * @param id 唯一标识符
 * @param role 消息角色
 * @param content 消息内容
 */
data class UiMessage(
    val id: Long = System.nanoTime(),
    val role: UiMessageRole,
    val content: String,
)
