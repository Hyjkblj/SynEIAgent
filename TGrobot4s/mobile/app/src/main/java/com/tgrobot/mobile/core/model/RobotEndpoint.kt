package com.tgrobot.mobile.core.model

data class RobotEndpoint(
    val host: String,
    val port: Int = 9100,
    val secure: Boolean = false,
    val signalPath: String = "/signal",
    val stunServer: String = "stun:stun.l.google.com:19302",
) {
    val signalUrl: String
        get() {
            val scheme = if (secure) "wss" else "ws"
            val normalizedPath = if (signalPath.startsWith("/")) signalPath else "/$signalPath"
            return "$scheme://$host:$port$normalizedPath"
        }
}
