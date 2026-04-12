package com.tgrobot.mobile.feature.control

import android.os.SystemClock
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.tgrobot.mobile.core.model.RobotConnectionState
import com.tgrobot.mobile.core.model.RobotEndpoint
import com.tgrobot.mobile.core.model.RobotEvent
import com.tgrobot.mobile.core.model.RobotSession
import com.tgrobot.mobile.core.model.TeleopCommand
import com.tgrobot.mobile.core.model.VoiceIntentPayload
import com.tgrobot.mobile.core.realtime.NetworkMonitor
import com.tgrobot.mobile.data.RobotRepository
import com.tgrobot.mobile.data.local.LocalRobotInfoService
import com.tgrobot.mobile.domain.control.ControlManager
import com.tgrobot.mobile.domain.voice.VoiceIntentCommand
import com.tgrobot.mobile.domain.voice.VoiceIntentParser
import com.tgrobot.mobile.feature.voice.VoiceController
import com.tgrobot.mobile.feature.voice.VoiceControllerEvent
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking

class TeleopViewModel(
    private val repository: RobotRepository,
    private val networkMonitor: NetworkMonitor,
    private val controlManager: ControlManager,
    private val voiceController: VoiceController,
    private val voiceIntentParser: VoiceIntentParser,
    private val localRobotInfoService: LocalRobotInfoService,
) : ViewModel() {
    private val _uiState = MutableStateFlow(TeleopUiState())
    val uiState = _uiState.asStateFlow()

    private var session: RobotSession = RobotSession.create()
    private var controlLoopJob: Job? = null
    private var streamDeltaBuffer = StringBuilder()
    private var voiceExclusiveUntilMs: Long = 0L

    init {
        observeRepository()
        observeNetwork()
        observeVoice()
    }

    fun updateHost(value: String) {
        _uiState.update { it.copy(host = value) }
    }

    fun updatePort(value: String) {
        _uiState.update { it.copy(port = value.filter(Char::isDigit).take(5)) }
    }

    fun updateDraftText(value: String) {
        _uiState.update { it.copy(draftText = value) }
    }

    fun connect() {
        val endpoint = buildEndpoint() ?: run {
            appendMessage(UiMessageRole.SYSTEM, "Invalid host or port.")
            return
        }

        session = RobotSession.create()
        viewModelScope.launch {
            repository.connect(endpoint, session)
            appendMessage(UiMessageRole.SYSTEM, "Session ${session.chatId.take(8)} connected.")
        }
    }

    fun disconnect() {
        viewModelScope.launch {
            voiceController.cancelListening()
            repository.disconnect()
            controlManager.reset()
            stopControlLoop()
        }
    }

    fun emergencyStop() {
        viewModelScope.launch {
            val now = SystemClock.elapsedRealtime()
            val command = controlManager.emergencyStop(now)
            sendControlCommand(command, now, allowDuringVoiceWindow = true)
            appendMessage(UiMessageRole.SYSTEM, "Emergency stop triggered.")
        }
    }

    fun onJoystickInput(x: Float, y: Float) {
        val now = SystemClock.elapsedRealtime()
        if (_uiState.value.isVoiceListening || now < voiceExclusiveUntilMs) {
            return
        }
        controlManager.updateInput(x = x, y = y)
    }

    fun onJoystickRelease() {
        viewModelScope.launch {
            val now = SystemClock.elapsedRealtime()
            val command = controlManager.release(now)
            sendControlCommand(command, now, allowDuringVoiceWindow = true)
        }
    }

    fun toggleVoiceListening() {
        _uiState.update { it.copy(voiceError = null) }
        if (_uiState.value.isVoiceListening) {
            voiceController.stopListening()
            return
        }
        if (!voiceController.startListening()) {
            appendMessage(UiMessageRole.SYSTEM, "Voice start failed.")
        }
    }

    fun onVoicePermissionDenied() {
        _uiState.update { it.copy(voiceError = "Microphone permission denied") }
        appendMessage(UiMessageRole.SYSTEM, "Microphone permission denied.")
    }

    fun sendText() {
        val text = uiState.value.draftText.trim()
        if (text.isBlank()) return

        _uiState.update { it.copy(draftText = "") }
        appendMessage(UiMessageRole.USER, text)

        viewModelScope.launch {
            if (!repository.sendText(text)) {
                appendMessage(UiMessageRole.SYSTEM, "Text send failed: DataChannel is not open.")
            }
        }
    }

    private fun observeRepository() {
        viewModelScope.launch {
            repository.connectionState.collect { state ->
                _uiState.update { it.copy(connectionState = state) }
                if (state == RobotConnectionState.DATA_CHANNEL_OPEN) {
                    startControlLoop()
                } else {
                    stopControlLoop()
                }
            }
        }

        viewModelScope.launch {
            repository.remoteVideoTrack.collect { track ->
                _uiState.update { it.copy(remoteVideoTrack = track) }
            }
        }

        viewModelScope.launch {
            repository.events.collect(::handleRobotEvent)
        }
    }

    private fun observeNetwork() {
        viewModelScope.launch {
            networkMonitor.isOnline.collect { online ->
                _uiState.update { it.copy(isNetworkAvailable = online) }
            }
        }
    }

    private fun observeVoice() {
        viewModelScope.launch {
            voiceController.state.collect { state ->
                _uiState.update {
                    it.copy(
                        isVoiceListening = state.isListening,
                        voicePartialText = state.partialText,
                    )
                }
            }
        }

        viewModelScope.launch {
            voiceController.events.collect(::handleVoiceEvent)
        }
    }

    private suspend fun handleVoiceEvent(event: VoiceControllerEvent) {
        when (event) {
            is VoiceControllerEvent.FinalText -> {
                val text = event.text.trim()
                if (text.isBlank()) return
                _uiState.update {
                    it.copy(
                        lastVoiceText = text,
                        voiceError = null,
                    )
                }
                appendMessage(UiMessageRole.USER, "Voice: $text")
                dispatchVoiceText(text)
            }

            is VoiceControllerEvent.Error -> {
                _uiState.update { it.copy(voiceError = event.message) }
                appendMessage(UiMessageRole.SYSTEM, "Voice error: ${event.message}")
            }
        }
    }

    private suspend fun dispatchVoiceText(text: String) {
        when (val intent = voiceIntentParser.parse(text)) {
            is VoiceIntentCommand.Move -> {
                preemptJoystickForVoice(windowMs = intent.durationMs.toLong() + VOICE_WINDOW_PADDING_MS)
                sendVoiceIntent(
                    payload = VoiceIntentPayload(
                        intent = "move",
                        linear = intent.linear,
                        angular = intent.angular,
                        durationMs = intent.durationMs,
                    ),
                    describe = "move linear=${intent.linear}, angular=${intent.angular}, ${intent.durationMs}ms",
                )
            }

            is VoiceIntentCommand.Action -> {
                preemptJoystickForVoice(windowMs = VOICE_ACTION_WINDOW_MS)
                sendVoiceIntent(
                    payload = VoiceIntentPayload(
                        intent = "action",
                        actionId = intent.actionId,
                        motionNumber = intent.motionNumber,
                    ),
                    describe = "action ${intent.actionId} (motion=${intent.motionNumber})",
                )
            }

            VoiceIntentCommand.Stop -> {
                preemptJoystickForVoice(windowMs = VOICE_STOP_WINDOW_MS)
                sendVoiceIntent(
                    payload = VoiceIntentPayload(intent = "stop"),
                    describe = "stop",
                )
            }

            VoiceIntentCommand.ResetEmergency -> {
                sendVoiceIntent(
                    payload = VoiceIntentPayload(intent = "reset_emergency"),
                    describe = "reset emergency",
                )
            }

            VoiceIntentCommand.QueryBattery -> {
                replyLocalRobotInfo(query = "battery")
            }

            VoiceIntentCommand.QueryConfig -> {
                replyLocalRobotInfo(query = "config")
            }

            VoiceIntentCommand.QueryStatus -> {
                replyLocalRobotInfo(query = "status")
            }

            is VoiceIntentCommand.Unknown -> {
                if (!repository.sendText(intent.text)) {
                    appendMessage(UiMessageRole.SYSTEM, "Voice text fallback send failed.")
                } else {
                    appendMessage(UiMessageRole.SYSTEM, "Voice text forwarded as raw text.")
                }
            }
        }
    }

    private suspend fun preemptJoystickForVoice(windowMs: Long) {
        val now = SystemClock.elapsedRealtime()
        voiceExclusiveUntilMs = maxOf(voiceExclusiveUntilMs, now + windowMs)
        val stopCommand = controlManager.release(now)
        sendControlCommand(stopCommand, now, allowDuringVoiceWindow = true)
    }

    private suspend fun sendVoiceIntent(payload: VoiceIntentPayload, describe: String) {
        val sent = repository.sendVoiceIntent(payload)
        if (!sent) {
            appendMessage(UiMessageRole.SYSTEM, "Voice command send failed: $describe")
            return
        }
        appendMessage(UiMessageRole.SYSTEM, "Voice command sent: $describe")
    }

    private suspend fun replyLocalRobotInfo(query: String) {
        val endpoint = buildEndpoint()
        if (endpoint == null) {
            appendMessage(UiMessageRole.SYSTEM, "Cannot query robot info: invalid host or port.")
            return
        }

        val snapshot = localRobotInfoService.fetchSnapshot(endpoint)
        if (snapshot == null) {
            appendMessage(
                UiMessageRole.SYSTEM,
                "Local query failed: cannot reach http://${endpoint.host}:${endpoint.port}/health or /status",
            )
            return
        }
        _uiState.update { current ->
            current.copy(
                batteryPercent = snapshot.batteryPercent ?: current.batteryPercent,
            )
        }

        when (query) {
            "battery" -> {
                val batteryText = snapshot.batteryPercent?.let { "$it%" }
                    ?: "unknown (battery field not provided by current gateway/bridge)"
                appendMessage(UiMessageRole.SYSTEM, "Robot battery: $batteryText")
            }

            "config" -> {
                val deadman = snapshot.deadmanTimeoutMs?.toString() ?: "n/a"
                val hz = snapshot.joystickMaxHz?.toString() ?: "n/a"
                val voiceDuration = snapshot.voiceMaxDurationMs?.toString() ?: "n/a"
                val videoEnabled = snapshot.videoEnabled?.toString() ?: "n/a"
                appendMessage(
                    UiMessageRole.SYSTEM,
                    "Robot config: deadman=${deadman}ms, joystick_max_hz=$hz, voice_max_duration_ms=$voiceDuration, video_enabled=$videoEnabled",
                )
            }

            else -> {
                val sessions = snapshot.sessions?.toString() ?: "n/a"
                val pushed = snapshot.framesPushed?.toString() ?: "n/a"
                val sent = snapshot.framesSent?.toString() ?: "n/a"
                val drop = snapshot.dropRatio?.toString() ?: "n/a"
                val ros = snapshot.rosEnabled?.toString() ?: "n/a"
                val rosError = snapshot.rosError?.takeIf { it.isNotBlank() } ?: "-"
                appendMessage(
                    UiMessageRole.SYSTEM,
                    "Robot status: gateway_ok=${snapshot.gatewayOk}, sessions=$sessions, video_pushed=$pushed, video_sent=$sent, drop_ratio=$drop, ros_enabled=$ros, ros_error=$rosError",
                )
            }
        }
    }

    private fun handleRobotEvent(event: RobotEvent) {
        when (event) {
            is RobotEvent.Message -> {
                flushDeltaBufferIfNeeded()
                appendMessage(UiMessageRole.ROBOT, event.content)
            }

            is RobotEvent.MessageDelta -> {
                if (event.content.isNotBlank()) {
                    streamDeltaBuffer.append(event.content)
                }
                if (event.end) {
                    flushDeltaBufferIfNeeded()
                }
            }

            is RobotEvent.Transcription -> {
                appendMessage(UiMessageRole.SYSTEM, "Transcription: ${event.content}")
            }

            is RobotEvent.Error -> {
                appendMessage(UiMessageRole.SYSTEM, "Error: ${event.content}")
            }

            is RobotEvent.Alert -> {
                val codePart = event.errorCode?.let { " code=$it" } ?: ""
                appendMessage(UiMessageRole.SYSTEM, "Alert[${event.level}]$codePart ${event.content}")
            }

            is RobotEvent.JoystickAck -> {
                updateLatencyFromAckTs(event.ts)
                if (event.reason.isNotBlank() && event.reason != "accepted") {
                    appendMessage(UiMessageRole.SYSTEM, "Joystick rejected: ${event.reason}")
                }
            }

            is RobotEvent.ControlAck -> {
                updateLatencyFromAckTs(event.ts)
                if (event.reason.isNotBlank() && event.reason != "accepted") {
                    appendMessage(UiMessageRole.SYSTEM, "Control rejected: ${event.reason}")
                }
            }

            is RobotEvent.GatewayEvent -> {
                when (event.name) {
                    "state_changed" -> {
                        val oldState = event.oldState ?: "unknown"
                        val newState = event.state ?: "unknown"
                        appendMessage(UiMessageRole.SYSTEM, "Gateway state: $oldState -> $newState")
                    }

                    "command_applied" -> {
                        val kind = event.kind ?: "unknown"
                        val source = event.source ?: "unknown"
                        appendMessage(UiMessageRole.SYSTEM, "Command applied: $kind from $source")
                    }

                    else -> {
                        appendMessage(UiMessageRole.SYSTEM, "Gateway event: ${event.name}")
                    }
                }
            }
        }
    }

    private fun flushDeltaBufferIfNeeded() {
        if (streamDeltaBuffer.isEmpty()) return
        appendMessage(UiMessageRole.ROBOT, streamDeltaBuffer.toString())
        streamDeltaBuffer = StringBuilder()
    }

    private fun appendMessage(role: UiMessageRole, content: String) {
        val normalized = content.trim()
        if (normalized.isBlank()) return

        _uiState.update { current ->
            val next = (current.messages + UiMessage(role = role, content = normalized)).takeLast(120)
            current.copy(messages = next)
        }
    }

    private fun buildEndpoint(): RobotEndpoint? {
        val host = uiState.value.host.trim()
        val port = uiState.value.port.toIntOrNull()
        if (host.isBlank() || port == null) return null
        return RobotEndpoint(host = host, port = port, signalPath = "/signal")
    }

    private fun startControlLoop() {
        if (controlLoopJob?.isActive == true) return

        controlLoopJob = viewModelScope.launch {
            while (isActive) {
                val now = SystemClock.elapsedRealtime()
                val command = controlManager.nextCommand(now)
                if (command != null) {
                    sendControlCommand(command, now, allowDuringVoiceWindow = false)
                }
                delay(CONTROL_TICK_MS)
            }
        }
    }

    private fun stopControlLoop() {
        controlLoopJob?.cancel()
        controlLoopJob = null
    }

    private suspend fun sendControlCommand(
        command: TeleopCommand,
        nowMs: Long,
        allowDuringVoiceWindow: Boolean,
    ) {
        if (!allowDuringVoiceWindow && nowMs < voiceExclusiveUntilMs) {
            return
        }
        val sent = repository.sendControl(command, clientTsMs = nowMs)
        if (sent) {
            controlManager.onCommandSent(nowMs)
            _uiState.update { it.copy(lastCommand = command) }
        }
    }

    private fun updateLatencyFromAckTs(ackTs: Long?) {
        val baseline = ackTs ?: return
        val latency = (SystemClock.elapsedRealtime() - baseline).coerceAtLeast(0L)
        _uiState.update { it.copy(latencyMs = latency) }
    }

    override fun onCleared() {
        stopControlLoop()
        voiceController.release()
        runBlocking {
            repository.disconnect()
        }
        super.onCleared()
    }

    private companion object {
        const val CONTROL_TICK_MS = 50L
        const val VOICE_WINDOW_PADDING_MS = 120L
        const val VOICE_ACTION_WINDOW_MS = 1400L
        const val VOICE_STOP_WINDOW_MS = 600L
    }
}

class TeleopViewModelFactory(
    private val repository: RobotRepository,
    private val networkMonitor: NetworkMonitor,
    private val controlManager: ControlManager,
    private val voiceController: VoiceController,
    private val voiceIntentParser: VoiceIntentParser,
    private val localRobotInfoService: LocalRobotInfoService,
) : ViewModelProvider.Factory {
    @Suppress("UNCHECKED_CAST")
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return TeleopViewModel(
            repository = repository,
            networkMonitor = networkMonitor,
            controlManager = controlManager,
            voiceController = voiceController,
            voiceIntentParser = voiceIntentParser,
            localRobotInfoService = localRobotInfoService,
        ) as T
    }
}
