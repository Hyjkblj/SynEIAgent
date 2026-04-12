package com.tgrobot.mobile.core.model

enum class RobotConnectionState {
    DISCONNECTED,
    CONNECTING_SIGNAL,
    SIGNAL_CONNECTED,
    PEER_CONNECTING,
    DATA_CHANNEL_OPEN,
    FAILED,
}
