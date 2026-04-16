package com.tgrobot.mobile.domain.message

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update

/**
 * 消息存储
 * 
 * 负责管理 UI 消息列表，从 ViewModel 中剥离消息管理职责。
 * 
 * 职责：
 * - 存储消息列表
 * - 提供消息添加接口
 * - 限制消息数量防止内存溢出
 */
class MessageStore(
    private val maxMessages: Int = 120,
) {
    private val _messages = MutableStateFlow<List<UiMessage>>(emptyList())
    val messages: StateFlow<List<UiMessage>> = _messages.asStateFlow()

    /**
     * 添加消息
     * 
     * @param role 消息角色
     * @param content 消息内容
     */
    fun addMessage(role: UiMessageRole, content: String) {
        val normalized = content.trim()
        if (normalized.isBlank()) return

        _messages.update { current ->
            (current + UiMessage(role = role, content = normalized))
                .takeLast(maxMessages)
        }
    }

    /**
     * 添加用户消息
     */
    fun addUserMessage(content: String) {
        addMessage(UiMessageRole.USER, content)
    }

    /**
     * 添加机器人消息
     */
    fun addRobotMessage(content: String) {
        addMessage(UiMessageRole.ROBOT, content)
    }

    /**
     * 添加系统消息
     */
    fun addSystemMessage(content: String) {
        addMessage(UiMessageRole.SYSTEM, content)
    }

    /**
     * 清空消息
     */
    fun clear() {
        _messages.value = emptyList()
    }

    /**
     * 获取当前消息数量
     */
    val size: Int
        get() = _messages.value.size
}
