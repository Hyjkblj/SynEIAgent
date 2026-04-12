package com.tgrobot.mobile.core.realtime

import android.content.Context
import com.tgrobot.mobile.core.model.RobotConnectionState
import com.tgrobot.mobile.core.model.RobotEndpoint
import com.tgrobot.mobile.core.model.RobotEvent
import com.tgrobot.mobile.core.model.RobotSession
import com.tgrobot.mobile.core.model.TeleopCommand
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import org.json.JSONObject
import org.webrtc.DataChannel
import org.webrtc.DefaultVideoDecoderFactory
import org.webrtc.DefaultVideoEncoderFactory
import org.webrtc.EglBase
import org.webrtc.IceCandidate
import org.webrtc.MediaConstraints
import org.webrtc.MediaStream
import org.webrtc.MediaStreamTrack
import org.webrtc.PeerConnection
import org.webrtc.PeerConnectionFactory
import org.webrtc.RtpReceiver
import org.webrtc.RtpTransceiver
import org.webrtc.SdpObserver
import org.webrtc.SessionDescription
import org.webrtc.VideoTrack
import java.nio.ByteBuffer
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlinx.coroutines.suspendCancellableCoroutine

class WebRtcRealtimeTransport(
    context: Context,
    private val signalingClient: SignalingClient = SignalingClient(),
    externalScope: CoroutineScope? = null,
) : RealtimeTransport {
    private val appContext = context.applicationContext
    private val scope = externalScope ?: CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val eglBase: EglBase = EglBase.create()

    private val _connectionState = MutableStateFlow(RobotConnectionState.DISCONNECTED)
    override val connectionState: StateFlow<RobotConnectionState> = _connectionState.asStateFlow()

    private val _events = MutableSharedFlow<RobotEvent>(extraBufferCapacity = 64)
    override val events: Flow<RobotEvent> = _events.asSharedFlow()

    private val _remoteVideoTrack = MutableStateFlow<VideoTrack?>(null)
    override val remoteVideoTrack: StateFlow<VideoTrack?> = _remoteVideoTrack.asStateFlow()

    private val peerConnectionFactory: PeerConnectionFactory by lazy {
        createPeerConnectionFactory()
    }

    @Volatile
    private var endpoint: RobotEndpoint? = null

    @Volatile
    private var session: RobotSession? = null

    @Volatile
    private var peerConnection: PeerConnection? = null

    @Volatile
    private var dataChannel: DataChannel? = null

    @Volatile
    private var manualDisconnect: Boolean = false

    @Volatile
    private var signalingGeneration: Long = 0L

    override suspend fun connect(endpoint: RobotEndpoint, session: RobotSession) {
        val generation = nextSignalingGeneration()
        manualDisconnect = true
        disconnectInternal(updateState = false)
        manualDisconnect = false

        this.endpoint = endpoint
        this.session = session
        _connectionState.value = RobotConnectionState.CONNECTING_SIGNAL

        signalingClient.connect(
            endpoint.signalUrl,
            object : SignalingClient.Listener {
                override fun onOpen() {
                    if (!isCurrentGeneration(generation)) return
                    _connectionState.value = RobotConnectionState.SIGNAL_CONNECTED
                    scope.launch {
                        startPeerNegotiation()
                    }
                }

                override fun onMessage(text: String) {
                    if (!isCurrentGeneration(generation)) return
                    scope.launch {
                        handleSignalingMessage(text)
                    }
                }

                override fun onClosed(code: Int, reason: String) {
                    if (!isCurrentGeneration(generation)) return
                    if (!manualDisconnect) {
                        scope.launch {
                            cleanupPeer()
                            _connectionState.value = RobotConnectionState.DISCONNECTED
                        }
                    }
                }

                override fun onFailure(error: Throwable) {
                    if (!isCurrentGeneration(generation)) return
                    emitError("Signaling failed", error)
                    _connectionState.value = RobotConnectionState.FAILED
                    scope.launch {
                        cleanupPeer()
                    }
                }
            },
        )
    }

    override suspend fun disconnect() {
        nextSignalingGeneration()
        manualDisconnect = true
        disconnectInternal(updateState = true)
        manualDisconnect = false
    }

    override suspend fun sendControl(command: TeleopCommand, clientTsMs: Long): Boolean {
        val payload = JSONObject()
            .put("type", "joystick")
            .put("x", command.x)
            .put("y", command.y)
            .put("linear", command.linear)
            .put("angular", command.angular)
            .put("ts", clientTsMs)
        return sendData(payload.toString())
    }

    override suspend fun sendText(content: String): Boolean {
        val payload = JSONObject()
            .put("type", "text")
            .put("content", content)
        return sendData(payload.toString())
    }

    private suspend fun disconnectInternal(updateState: Boolean) {
        signalingClient.close()
        cleanupPeer()
        if (updateState) {
            _connectionState.value = RobotConnectionState.DISCONNECTED
        }
    }

    private suspend fun startPeerNegotiation() {
        val activeEndpoint = endpoint ?: return
        val activeSession = session ?: return

        val pc = createPeerConnection(activeEndpoint)
            ?: run {
                _connectionState.value = RobotConnectionState.FAILED
                emitError("PeerConnection create failed")
                return
            }

        _connectionState.value = RobotConnectionState.PEER_CONNECTING

        try {
            ensureRecvOnlyVideoTransceiver(pc)
            var offer = pc.createOfferSuspend(createOfferConstraints())
            if (!hasVideoMLine(offer.description)) {
                emitError("Offer missing m=video, retrying transceiver setup once")
                ensureRecvOnlyVideoTransceiver(pc)
                offer = pc.createOfferSuspend(createOfferConstraints())
                if (!hasVideoMLine(offer.description)) {
                    throw IllegalStateException("Offer still missing m=video after retry")
                }
            }
            pc.setLocalDescriptionSuspend(offer)
            val localSdp = pc.localDescription?.description ?: offer.description
            if (!hasVideoMLine(localSdp)) {
                throw IllegalStateException("LocalDescription missing m=video")
            }

            val payload = JSONObject()
                .put("type", "offer")
                .put("sdp", localSdp)
                .put("chat_id", activeSession.chatId)
                .put("sender_id", activeSession.senderId)

            if (!signalingClient.send(payload.toString())) {
                throw IllegalStateException("offer send failed")
            }
        } catch (error: Throwable) {
            emitError("Failed to create/send offer", error)
            _connectionState.value = RobotConnectionState.FAILED
        }
    }

    private fun ensureRecvOnlyVideoTransceiver(pc: PeerConnection) {
        runCatching {
            val init = RtpTransceiver.RtpTransceiverInit(
                RtpTransceiver.RtpTransceiverDirection.RECV_ONLY,
            )
            pc.addTransceiver(MediaStreamTrack.MediaType.MEDIA_TYPE_VIDEO, init)
        }.onFailure { error ->
            throw IllegalStateException("addTransceiver(video recvonly) failed", error)
        }
    }

    private fun createOfferConstraints(): MediaConstraints {
        return MediaConstraints().apply {
            // Request remote camera track from server.
            mandatory.add(MediaConstraints.KeyValuePair("OfferToReceiveVideo", "true"))
            // App currently does not send local mic track.
            mandatory.add(MediaConstraints.KeyValuePair("OfferToReceiveAudio", "false"))
        }
    }

    private fun createPeerConnection(endpoint: RobotEndpoint): PeerConnection? {
        if (peerConnection != null) {
            return peerConnection
        }

        val iceServers = buildList {
            if (endpoint.stunServer.isNotBlank()) {
                add(PeerConnection.IceServer.builder(endpoint.stunServer).createIceServer())
            }
        }

        val rtcConfig = PeerConnection.RTCConfiguration(iceServers).apply {
            // Required for addTransceiver(RECV_ONLY); Plan-B will crash in native layer.
            sdpSemantics = PeerConnection.SdpSemantics.UNIFIED_PLAN
        }

        val pc = peerConnectionFactory.createPeerConnection(
            rtcConfig,
            object : PeerConnection.Observer {
                override fun onSignalingChange(newState: PeerConnection.SignalingState) = Unit

                override fun onIceConnectionChange(newState: PeerConnection.IceConnectionState) {
                    when (newState) {
                        PeerConnection.IceConnectionState.FAILED -> {
                            _connectionState.value = RobotConnectionState.FAILED
                            emitError("ICE connection failed")
                        }

                        PeerConnection.IceConnectionState.DISCONNECTED -> {
                            if (_connectionState.value == RobotConnectionState.DATA_CHANNEL_OPEN) {
                                _connectionState.value = RobotConnectionState.PEER_CONNECTING
                            }
                        }

                        PeerConnection.IceConnectionState.CLOSED -> {
                            if (!manualDisconnect) {
                                _connectionState.value = RobotConnectionState.DISCONNECTED
                            }
                        }

                        else -> Unit
                    }
                }

                override fun onIceConnectionReceivingChange(receiving: Boolean) = Unit

                override fun onIceGatheringChange(newState: PeerConnection.IceGatheringState) = Unit

                override fun onIceCandidate(candidate: IceCandidate) {
                    sendLocalIceCandidate(candidate)
                }

                override fun onIceCandidatesRemoved(candidates: Array<IceCandidate>) = Unit

                override fun onAddStream(stream: MediaStream) {
                    val track = stream.videoTracks.firstOrNull() ?: return
                    _remoteVideoTrack.value = track
                }

                override fun onRemoveStream(stream: MediaStream) {
                    _remoteVideoTrack.value = null
                }

                override fun onDataChannel(channel: DataChannel) {
                    if (channel.label() == DATA_CHANNEL_LABEL) {
                        observeDataChannel(channel)
                        dataChannel = channel
                    }
                }

                override fun onRenegotiationNeeded() = Unit

                override fun onAddTrack(receiver: RtpReceiver, mediaStreams: Array<MediaStream>) {
                    val track = receiver.track() as? VideoTrack ?: return
                    _remoteVideoTrack.value = track
                }
            },
        )

        if (pc == null) {
            return null
        }

        val channel = pc.createDataChannel(
            DATA_CHANNEL_LABEL,
            DataChannel.Init().apply {
                ordered = true
            },
        )
        observeDataChannel(channel)

        peerConnection = pc
        dataChannel = channel
        return pc
    }

    private fun observeDataChannel(channel: DataChannel) {
        channel.registerObserver(
            object : DataChannel.Observer {
                override fun onBufferedAmountChange(previousAmount: Long) = Unit

                override fun onStateChange() {
                    if (channel.state() == DataChannel.State.OPEN) {
                        _connectionState.value = RobotConnectionState.DATA_CHANNEL_OPEN
                    }
                }

                override fun onMessage(buffer: DataChannel.Buffer) {
                    val payload = decodeTextBuffer(buffer)
                    scope.launch {
                        handleDataChannelMessage(payload)
                    }
                }
            },
        )
    }

    private suspend fun handleSignalingMessage(raw: String) {
        val message = runCatching { JSONObject(raw) }.getOrNull() ?: return
        when (message.optString("type")) {
            "answer" -> {
                val sdp = message.optString("sdp")
                if (sdp.isBlank()) {
                    return
                }
                val pc = peerConnection ?: return
                runCatching {
                    pc.setRemoteDescriptionSuspend(
                        SessionDescription(SessionDescription.Type.ANSWER, sdp),
                    )
                }.onFailure { error ->
                    emitError("Set remote answer failed", error)
                    _connectionState.value = RobotConnectionState.FAILED
                }
            }

            "ice" -> {
                addRemoteIceCandidate(message.optJSONObject("candidate"))
            }

            "error" -> {
                emitError(message.optString("content", "signal error"))
            }
        }
    }

    private fun sendLocalIceCandidate(candidate: IceCandidate) {
        val payload = JSONObject()
            .put("type", "ice")
            .put("candidate", toServerIceCandidate(candidate))
        signalingClient.send(payload.toString())
    }

    private fun toServerIceCandidate(candidate: IceCandidate): JSONObject {
        val parsed = parseIceSdp(candidate.sdp)
        return JSONObject()
            .put("component", parsed.component)
            .put("foundation", parsed.foundation)
            .put("ip", parsed.ip)
            .put("port", parsed.port)
            .put("priority", parsed.priority)
            .put("protocol", parsed.protocol)
            .put("type", parsed.type)
            .put("sdpMid", candidate.sdpMid)
            .put("sdpMLineIndex", candidate.sdpMLineIndex)
            .put("candidate", candidate.sdp)
    }

    private fun parseIceSdp(sdp: String): ParsedIce {
        val tokens = sdp.trim().split(Regex("\\s+"))
        if (tokens.size < 8) {
            return ParsedIce(
                foundation = "0",
                component = 1,
                protocol = "udp",
                priority = 0L,
                ip = "0.0.0.0",
                port = 0,
                type = "host",
            )
        }

        val foundation = tokens[0].removePrefix("candidate:")
        val component = tokens[1].toIntOrNull() ?: 1
        val protocol = tokens[2].lowercase()
        val priority = tokens[3].toLongOrNull() ?: 0L
        val ip = tokens[4]
        val port = tokens[5].toIntOrNull() ?: 0
        val typeIndex = tokens.indexOf("typ")
        val type = if (typeIndex >= 0 && typeIndex + 1 < tokens.size) {
            tokens[typeIndex + 1]
        } else {
            "host"
        }
        return ParsedIce(foundation, component, protocol, priority, ip, port, type)
    }

    private fun addRemoteIceCandidate(candidateObj: JSONObject?) {
        val pc = peerConnection ?: return
        val candidate = candidateObj ?: return

        val sdp = candidate.optString("candidate").takeIf { it.isNotBlank() } ?: buildCandidateSdp(candidate)
        val sdpMid = candidate.optString("sdpMid").ifBlank { null }
        val mLineIndex = candidate.optInt("sdpMLineIndex", 0)

        if (sdp.isBlank()) {
            return
        }

        pc.addIceCandidate(IceCandidate(sdpMid, mLineIndex, sdp))
    }

    private fun buildCandidateSdp(candidate: JSONObject): String {
        val foundation = candidate.optString("foundation", "0")
        val component = candidate.optInt("component", 1)
        val protocol = candidate.optString("protocol", "udp")
        val priority = candidate.optLong("priority", 0L)
        val ip = candidate.optString("ip", "0.0.0.0")
        val port = candidate.optInt("port", 0)
        val type = candidate.optString("type", "host")

        if (ip.isBlank() || port <= 0) {
            return ""
        }
        return "candidate:$foundation $component $protocol $priority $ip $port typ $type"
    }

    private suspend fun handleDataChannelMessage(raw: String) {
        val json = runCatching { JSONObject(raw) }.getOrNull() ?: return
        when (json.optString("type")) {
            "message" -> _events.emit(RobotEvent.Message(json.optString("content")))
            "message_delta" -> _events.emit(
                RobotEvent.MessageDelta(
                    content = json.optString("content"),
                    end = json.optBoolean("end", false),
                ),
            )

            "transcription" -> _events.emit(RobotEvent.Transcription(json.optString("content")))
            "error" -> _events.emit(RobotEvent.Error(json.optString("content")))
            "alert" -> _events.emit(
                RobotEvent.Alert(
                    level = json.optString("level", "warn"),
                    errorCode = json.optInt("error_code").takeIf { it != 0 || json.has("error_code") },
                    content = json.optString("content"),
                ),
            )

            "joystick_ack" -> _events.emit(
                RobotEvent.JoystickAck(
                    x = json.optDouble("x", 0.0).toFloat(),
                    y = json.optDouble("y", 0.0).toFloat(),
                    ts = json.optLong("ts").takeIf { json.has("ts") && !json.isNull("ts") },
                ),
            )

            "ack" -> _events.emit(
                RobotEvent.ControlAck(
                    ts = json.optLong("ts").takeIf { json.has("ts") && !json.isNull("ts") },
                ),
            )
        }
    }

    private fun sendData(message: String): Boolean {
        val channel = dataChannel ?: return false
        if (channel.state() != DataChannel.State.OPEN) {
            return false
        }
        val bytes = message.toByteArray(Charsets.UTF_8)
        val buffer = DataChannel.Buffer(ByteBuffer.wrap(bytes), false)
        return channel.send(buffer)
    }

    private suspend fun cleanupPeer() {
        dataChannel?.unregisterObserver()
        dataChannel?.close()
        dataChannel = null

        peerConnection?.close()
        peerConnection = null
        _remoteVideoTrack.value = null
    }

    @Synchronized
    private fun nextSignalingGeneration(): Long {
        signalingGeneration += 1L
        return signalingGeneration
    }

    private fun isCurrentGeneration(generation: Long): Boolean {
        return signalingGeneration == generation
    }

    private fun hasVideoMLine(sdp: String): Boolean {
        return sdp.lineSequence().any { it.startsWith("m=video") }
    }

    private fun emitError(message: String, throwable: Throwable? = null) {
        val full = if (throwable?.message.isNullOrBlank()) {
            message
        } else {
            "$message: ${throwable?.message}"
        }
        _events.tryEmit(RobotEvent.Error(full))
    }

    private fun decodeTextBuffer(buffer: DataChannel.Buffer): String {
        val data = buffer.data
        data.rewind()
        val bytes = ByteArray(data.remaining())
        data.get(bytes)
        return String(bytes, Charsets.UTF_8)
    }

    private fun createPeerConnectionFactory(): PeerConnectionFactory {
        PeerConnectionFactory.initialize(
            PeerConnectionFactory.InitializationOptions.builder(appContext)
                .createInitializationOptions(),
        )

        val encoderFactory = DefaultVideoEncoderFactory(eglBase.eglBaseContext, true, true)
        val decoderFactory = DefaultVideoDecoderFactory(eglBase.eglBaseContext)

        return PeerConnectionFactory.builder()
            .setVideoEncoderFactory(encoderFactory)
            .setVideoDecoderFactory(decoderFactory)
            .createPeerConnectionFactory()
    }

    private data class ParsedIce(
        val foundation: String,
        val component: Int,
        val protocol: String,
        val priority: Long,
        val ip: String,
        val port: Int,
        val type: String,
    )

    private companion object {
        private const val DATA_CHANNEL_LABEL = "control"
    }
}

private suspend fun PeerConnection.createOfferSuspend(
    offerConstraints: MediaConstraints = MediaConstraints(),
): SessionDescription =
    suspendCancellableCoroutine { continuation ->
        createOffer(
            object : SdpObserver {
                override fun onCreateSuccess(description: SessionDescription?) {
                    if (description == null) {
                        continuation.resumeWithException(IllegalStateException("offer is null"))
                    } else {
                        continuation.resume(description)
                    }
                }

                override fun onCreateFailure(error: String?) {
                    continuation.resumeWithException(
                        IllegalStateException(error ?: "createOffer failure"),
                    )
                }

                override fun onSetSuccess() = Unit
                override fun onSetFailure(error: String?) = Unit
            },
            offerConstraints,
        )
    }

private suspend fun PeerConnection.setLocalDescriptionSuspend(description: SessionDescription) {
    suspendCancellableCoroutine<Unit> { continuation ->
        setLocalDescription(
            object : SdpObserver {
                override fun onSetSuccess() {
                    continuation.resume(Unit)
                }

                override fun onSetFailure(error: String?) {
                    continuation.resumeWithException(
                        IllegalStateException(error ?: "setLocalDescription failure"),
                    )
                }

                override fun onCreateSuccess(description: SessionDescription?) = Unit
                override fun onCreateFailure(error: String?) = Unit
            },
            description,
        )
    }
}

private suspend fun PeerConnection.setRemoteDescriptionSuspend(description: SessionDescription) {
    suspendCancellableCoroutine<Unit> { continuation ->
        setRemoteDescription(
            object : SdpObserver {
                override fun onSetSuccess() {
                    continuation.resume(Unit)
                }

                override fun onSetFailure(error: String?) {
                    continuation.resumeWithException(
                        IllegalStateException(error ?: "setRemoteDescription failure"),
                    )
                }

                override fun onCreateSuccess(description: SessionDescription?) = Unit
                override fun onCreateFailure(error: String?) = Unit
            },
            description,
        )
    }
}
