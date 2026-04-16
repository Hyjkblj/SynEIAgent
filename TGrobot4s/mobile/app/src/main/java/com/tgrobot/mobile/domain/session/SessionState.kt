package com.tgrobot.mobile.domain.session

import com.tgrobot.mobile.core.model.RobotSession

/**
 * 会话状态
 * 
 * @param session 当前会话
 * @param isActive 是否活跃
 * @param connectedAt 连接时间戳
 */
data class SessionState(
    val session: RobotSession? = null,
    val isActive: Boolean = false,
    val connectedAt: Long? = null,
) {
    /**
     * 会话持续时间（毫秒）
     */
    val durationMs: Long?
        get() = connectedAt?.let { System.currentTimeMillis() - it }

    /**
     * 会话 ID（前8位）
     */
    val shortSessionId: String?
        get() = session?.chatId?.take(8)
}
