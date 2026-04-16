package com.tgrobot.mobile.domain.usecase

import com.tgrobot.mobile.core.model.RobotEndpoint
import com.tgrobot.mobile.core.model.RobotSession
import com.tgrobot.mobile.data.RobotClient

/**
 * 连接机器人用例
 * 
 * 封装连接机器人的业务逻辑。
 * 
 * 职责：
 * - 验证端点配置
 * - 创建会话
 * - 发起连接
 */
class ConnectRobotUseCase(
    val robotClient: RobotClient,
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

        val session = RobotSession.create()
        return runCatching {
            robotClient.connect(endpoint, session)
            session
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
}
