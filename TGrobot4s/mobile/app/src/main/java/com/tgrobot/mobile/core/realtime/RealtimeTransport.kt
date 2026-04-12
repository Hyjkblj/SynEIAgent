package com.tgrobot.mobile.core.realtime

import com.tgrobot.mobile.core.model.RobotConnectionState
import com.tgrobot.mobile.core.model.RobotEndpoint
import com.tgrobot.mobile.core.model.RobotEvent
import com.tgrobot.mobile.core.model.RobotSession
import com.tgrobot.mobile.core.model.TeleopCommand
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.StateFlow
import org.webrtc.VideoTrack

interface RealtimeTransport {
    val connectionState: StateFlow<RobotConnectionState>
    val events: Flow<RobotEvent>
    val remoteVideoTrack: StateFlow<VideoTrack?>

    suspend fun connect(endpoint: RobotEndpoint, session: RobotSession)
    suspend fun disconnect()
    suspend fun sendControl(command: TeleopCommand, clientTsMs: Long): Boolean
    suspend fun sendText(content: String): Boolean
}
