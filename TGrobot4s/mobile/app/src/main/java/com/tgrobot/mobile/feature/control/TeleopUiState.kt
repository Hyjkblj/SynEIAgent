package com.tgrobot.mobile.feature.control

import com.tgrobot.mobile.core.model.RobotConnectionState
import com.tgrobot.mobile.core.model.TeleopCommand
import com.tgrobot.mobile.domain.message.UiMessage
import com.tgrobot.mobile.domain.message.UiMessageRole
import org.webrtc.VideoTrack

data class TeleopUiState(
    val host: String = "192.168.41.1",
    val port: String = "9100",
    val connectionState: RobotConnectionState = RobotConnectionState.DISCONNECTED,
    val isNetworkAvailable: Boolean = true,
    val latencyMs: Long? = null,
    val batteryPercent: Int? = null,
    val remoteVideoTrack: VideoTrack? = null,
    val draftText: String = "",
    val messages: List<UiMessage> = emptyList(),
    val lastCommand: TeleopCommand = TeleopCommand.Zero,
    val voiceAvailable: Boolean = true,
    val isVoiceListening: Boolean = false,
    val voicePartialText: String = "",
    val lastVoiceText: String = "",
    val voiceError: String? = null,
) {
    val isConnected: Boolean
        get() = connectionState == RobotConnectionState.DATA_CHANNEL_OPEN

    val signalUrlPreview: String
        get() = "ws://$host:$port/signal"
}
