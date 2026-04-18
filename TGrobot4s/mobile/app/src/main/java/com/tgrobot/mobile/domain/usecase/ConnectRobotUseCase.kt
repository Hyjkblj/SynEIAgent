package com.tgrobot.mobile.domain.usecase

import com.tgrobot.mobile.core.model.RobotEndpoint
import com.tgrobot.mobile.core.model.RobotSession
import com.tgrobot.mobile.data.RobotClient
import com.tgrobot.mobile.domain.session.RobotSessionManager

/**
 * 连接机器人用例
 * 
 * 封装连接机器人的业务逻辑。
 * 
 * 职责：
 * - 验证端点配置
 * - 管理会话生命周期
 * - 发起连接
 */
class ConnectRobotUseCase(
    val robotClient: RobotClient,
    private val sessionManager: RobotSessionManager = RobotSessionManager(),
) {
    /**
     * 执行连接
     * 
     * @param host 主机地址
     * @param port 端口号
     * @return 连接结果
     */
    suspend operator fun invoke(host: String, port: String): Result<RobotSession> {
        val endpoint = buildEndpoint(host, port)
            ?: return Result.failure(IllegalArgumentException("Invalid host or port"))

        val session = sessionManager.createSession()
        return runCatching {
            robotClient.connect(endpoint, session)
            sessionManager.activate()
            session
        }.onFailure {
            sessionManager.clear()
        }
    }

    /**
     * 构建端点配置
     */
    fun buildEndpoint(host: String, port: String): RobotEndpoint? {
        val trimmedHost = host.trim()
        val portNumber = port.filter(Char::isDigit).toIntOrNull()
        if (trimmedHost.isBlank() || portNumber == null) return null
        return RobotEndpoint(host = trimmedHost, port = portNumber, signalPath = "/signal")
    }

    /**
     * 获取当前会话
     */
    val currentSession: RobotSession?
        get() = sessionManager.currentSession

    /**
     * 会话状态
     */
    val sessionState
        get() = sessionManager.state
}
