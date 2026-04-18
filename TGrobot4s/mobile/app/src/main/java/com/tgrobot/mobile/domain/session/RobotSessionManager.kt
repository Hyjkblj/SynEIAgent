package com.tgrobot.mobile.domain.session

import com.tgrobot.mobile.core.model.RobotSession
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update

/**
 * 机器人会话管理器
 * 
 * 统一管理连接会话的生命周期。
 * 
 * 职责：
 * - 创建会话
 * - 管理会话状态
 * - 跟踪连接时间
 */
class RobotSessionManager {
    private val _state = MutableStateFlow(SessionState())
    val state: StateFlow<SessionState> = _state.asStateFlow()

    /**
     * 当前会话
     */
    val currentSession: RobotSession?
        get() = _state.value.session

    /**
     * 是否有活跃会话
     */
    val hasActiveSession: Boolean
        get() = _state.value.isActive

    /**
     * 创建新会话
     * 
     * @return 新创建的会话
     */
    fun createSession(): RobotSession {
        val session = RobotSession.create()
        _state.update {
            SessionState(
                session = session,
                isActive = true,
                connectedAt = System.currentTimeMillis(),
            )
        }
        return session
    }

    /**
     * 激活会话
     */
    fun activate() {
        _state.update { it.copy(isActive = true) }
    }

    /**
     * 停用会话
     */
    fun deactivate() {
        _state.update { it.copy(isActive = false) }
    }

    /**
     * 清除会话
     */
    fun clear() {
        _state.value = SessionState()
    }

    /**
     * 更新会话
     */
    fun updateSession(session: RobotSession) {
        _state.update { it.copy(session = session) }
    }
}
