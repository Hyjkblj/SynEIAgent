package com.tgrobot.mobile.data

import com.tgrobot.mobile.core.model.RobotConnectionState
import com.tgrobot.mobile.core.model.RobotEndpoint
import com.tgrobot.mobile.core.model.RobotEvent
import com.tgrobot.mobile.core.model.RobotSession
import com.tgrobot.mobile.core.model.TeleopCommand
import com.tgrobot.mobile.core.model.VoiceIntentPayload
import com.tgrobot.mobile.core.realtime.RealtimeTransport
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.StateFlow
import org.webrtc.VideoTrack

class DefaultRobotRepository(
    private val transport: RealtimeTransport,
) : RobotRepository {
    override val connectionState: StateFlow<RobotConnectionState> = transport.connectionState
    override val events: Flow<RobotEvent> = transport.events
    override val remoteVideoTrack: StateFlow<VideoTrack?> = transport.remoteVideoTrack

    override suspend fun connect(endpoint: RobotEndpoint, session: RobotSession) {
        transport.connect(endpoint, session)
    }

    override suspend fun disconnect() {
        transport.disconnect()
    }

    override suspend fun sendControl(command: TeleopCommand, clientTsMs: Long): Boolean {
        return transport.sendControl(command, clientTsMs)
    }

    override suspend fun sendText(content: String): Boolean {
        return transport.sendText(content)
    }

    override suspend fun sendVoiceIntent(intent: VoiceIntentPayload): Boolean {
        return transport.sendVoiceIntent(intent)
    }
}
