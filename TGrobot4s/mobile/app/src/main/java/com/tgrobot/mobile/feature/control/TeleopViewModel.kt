package com.tgrobot.mobile.feature.control

import android.os.SystemClock
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.tgrobot.mobile.core.model.RobotConnectionState
import com.tgrobot.mobile.core.model.RobotEvent
import com.tgrobot.mobile.core.model.RobotSession
import com.tgrobot.mobile.core.realtime.NetworkMonitor
import com.tgrobot.mobile.data.local.LocalRobotInfoService
import com.tgrobot.mobile.domain.control.ControlEngine
import com.tgrobot.mobile.domain.message.MessageStore
import com.tgrobot.mobile.domain.message.UiMessageRole
import com.tgrobot.mobile.domain.usecase.ConnectRobotUseCase
import com.tgrobot.mobile.domain.usecase.DisconnectRobotUseCase
import com.tgrobot.mobile.domain.usecase.SendControlCommandUseCase
import com.tgrobot.mobile.domain.usecase.VoiceIntentResult
import com.tgrobot.mobile.feature.voice.VoiceModule
import com.tgrobot.mobile.feature.voice.VoiceModuleEvent
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking

class TeleopViewModel(
    private val connectUseCase: ConnectRobotUseCase,
    private val disconnectUseCase: DisconnectRobotUseCase,
    private val sendControlUseCase: SendControlCommandUseCase,
    private val networkMonitor: NetworkMonitor,
    private val controlEngine: ControlEngine,
    private val voiceModule: VoiceModule,
    private val localRobotInfoService: LocalRobotInfoService,
    private val messageStore: MessageStore = MessageStore(),
) : ViewModel() {
    private val _uiState = MutableStateFlow(TeleopUiState())
    val uiState = _uiState.asStateFlow()

    private var session: RobotSession = RobotSession.create()
    private var streamDeltaBuffer = StringBuilder()
    private var voiceExclusiveUntilMs: Long = 0L

    init {
        observeRepository()
        observeNetwork()
        observeVoiceModule()
        observeMessages()
        observeControlEngine()
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
        viewModelScope.launch {
            val result = connectUseCase(_uiState.value.host, _uiState.value.port)
            result.fold(
                onSuccess = { newSession ->
                    session = newSession
                    messageStore.addSystemMessage("Session ${session.chatId.take(8)} connected.")
                },
                onFailure = { error ->
                    messageStore.addSystemMessage(error.message ?: "Connection failed.")
                },
            )
        }
    }

    fun disconnect() {
        viewModelScope.launch {
            disconnectUseCase()
        }
    }

    fun emergencyStop() {
        viewModelScope.launch {
            val success = sendControlUseCase.emergencyStop()
            if (success) {
                messageStore.addSystemMessage("Emergency stop triggered.")
            }
        }
    }

    fun onJoystickInput(x: Float, y: Float) {
        val now = SystemClock.elapsedRealtime()
        if (_uiState.value.isVoiceListening || now < voiceExclusiveUntilMs) {
            return
        }
        sendControlUseCase.updateJoystickInput(x = x, y = y)
    }

    fun onJoystickRelease() {
        viewModelScope.launch {
            sendControlUseCase.releaseJoystick()
        }
    }

    fun toggleVoiceListening() {
        _uiState.update { it.copy(voiceError = null) }
        if (_uiState.value.isVoiceListening) {
            voiceModule.stopListening()
            return
        }
        if (!voiceModule.startListening()) {
            messageStore.addSystemMessage("Voice start failed.")
        }
    }

    fun onVoicePermissionDenied() {
        _uiState.update { it.copy(voiceError = "Microphone permission denied") }
        messageStore.addSystemMessage("Microphone permission denied.")
    }

    fun sendText() {
        val text = uiState.value.draftText.trim()
        if (text.isBlank()) return

        _uiState.update { it.copy(draftText = "") }
        messageStore.addUserMessage(text)
        // 文本发送通过 VoiceModule 的 commandResults 处理
    }

    private fun observeRepository() {
        viewModelScope.launch {
            connectUseCase.robotClient.connectionState.collect { state ->
                _uiState.update { it.copy(connectionState = state) }
                if (state == RobotConnectionState.DATA_CHANNEL_OPEN) {
                    controlEngine.startControlLoop(tickMs = CONTROL_TICK_MS) { command, now ->
                        sendControlUseCase.sendCommand(command, now)
                    }
                } else {
                    controlEngine.stopControlLoop()
                }
            }
        }

        viewModelScope.launch {
            connectUseCase.robotClient.remoteVideoTrack.collect { track ->
                _uiState.update { it.copy(remoteVideoTrack = track) }
            }
        }

        viewModelScope.launch {
            connectUseCase.robotClient.events.collect(::handleRobotEvent)
        }
    }

    private fun observeNetwork() {
        viewModelScope.launch {
            networkMonitor.isOnline.collect { online ->
                _uiState.update { it.copy(isNetworkAvailable = online) }
            }
        }
    }

    private fun observeVoiceModule() {
        viewModelScope.launch {
            voiceModule.state.collect { state ->
                _uiState.update {
                    it.copy(
                        voiceAvailable = state.isAvailable,
                        isVoiceListening = state.isListening,
                        voicePartialText = state.partialText,
                        lastVoiceText = state.lastText,
                        voiceError = state.error,
                    )
                }
            }
        }

        viewModelScope.launch {
            voiceModule.events.collect(::handleVoiceModuleEvent)
        }

        viewModelScope.launch {
            voiceModule.commandResults.collect(::handleVoiceCommandResult)
        }
    }

    private fun observeMessages() {
        viewModelScope.launch {
            messageStore.messages.collect { messages ->
                _uiState.update { it.copy(messages = messages) }
            }
        }
    }

    private fun observeControlEngine() {
        viewModelScope.launch {
            controlEngine.lastCommand.collect { command ->
                _uiState.update { it.copy(lastCommand = command) }
            }
        }
    }

    private fun handleVoiceModuleEvent(event: VoiceModuleEvent) {
        when (event) {
            is VoiceModuleEvent.RecognitionComplete -> {
                messageStore.addUserMessage("Voice: ${event.text}")
            }
            is VoiceModuleEvent.RecognitionError -> {
                if (event.isRecoverable) {
                    messageStore.addSystemMessage("Voice notice(${event.code}): ${event.message}")
                } else {
                    messageStore.addSystemMessage("Voice error(${event.code}): ${event.message}")
                }
            }
            is VoiceModuleEvent.PermissionDenied -> {
                messageStore.addSystemMessage("Microphone permission denied.")
            }
        }
    }

    private suspend fun handleVoiceCommandResult(result: VoiceIntentResult) {
        // 设置语音独占窗口
        val windowMs = voiceModule.getVoiceExclusiveWindowMs(result)
        if (windowMs > 0) {
            preemptJoystickForVoice(windowMs)
        }

        // 处理结果
        when (result) {
            is VoiceIntentResult.Move -> {
                messageStore.addSystemMessage(
                    "Voice command sent: move linear=${result.linear}, angular=${result.angular}, ${result.durationMs}ms"
                )
            }
            is VoiceIntentResult.Action -> {
                messageStore.addSystemMessage(
                    "Voice command sent: action ${result.actionId} (motion=${result.motionNumber})"
                )
            }
            is VoiceIntentResult.Stop -> {
                messageStore.addSystemMessage("Voice command sent: stop")
            }
            is VoiceIntentResult.ResetEmergency -> {
                messageStore.addSystemMessage("Voice command sent: reset emergency")
            }
            is VoiceIntentResult.QueryBattery -> {
                replyLocalRobotInfo(query = "battery")
            }
            is VoiceIntentResult.QueryConfig -> {
                replyLocalRobotInfo(query = "config")
            }
            is VoiceIntentResult.QueryStatus -> {
                replyLocalRobotInfo(query = "status")
            }
            is VoiceIntentResult.Unknown -> {
                messageStore.addSystemMessage("Voice text forwarded as raw text.")
            }
            is VoiceIntentResult.Failed -> {
                messageStore.addSystemMessage(result.message)
            }
        }
    }

    private suspend fun preemptJoystickForVoice(windowMs: Long) {
        val now = SystemClock.elapsedRealtime()
        voiceExclusiveUntilMs = maxOf(voiceExclusiveUntilMs, now + windowMs)
        sendControlUseCase.releaseJoystick()
    }

    private suspend fun replyLocalRobotInfo(query: String) {
        val endpoint = connectUseCase.buildEndpoint(_uiState.value.host, _uiState.value.port)
        if (endpoint == null) {
            messageStore.addSystemMessage("Cannot query robot info: invalid host or port.")
            return
        }

        val snapshot = localRobotInfoService.fetchSnapshot(endpoint)
        if (snapshot == null) {
            messageStore.addSystemMessage(
                "Local query failed: cannot reach http://${endpoint.host}:${endpoint.port}/health or /status"
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
                messageStore.addSystemMessage("Robot battery: $batteryText")
            }

            "config" -> {
                val deadman = snapshot.deadmanTimeoutMs?.toString() ?: "n/a"
                val hz = snapshot.joystickMaxHz?.toString() ?: "n/a"
                val voiceDuration = snapshot.voiceMaxDurationMs?.toString() ?: "n/a"
                val videoEnabled = snapshot.videoEnabled?.toString() ?: "n/a"
                messageStore.addSystemMessage(
                    "Robot config: deadman=${deadman}ms, joystick_max_hz=$hz, voice_max_duration_ms=$voiceDuration, video_enabled=$videoEnabled"
                )
            }

            else -> {
                val sessions = snapshot.sessions?.toString() ?: "n/a"
                val pushed = snapshot.framesPushed?.toString() ?: "n/a"
                val sent = snapshot.framesSent?.toString() ?: "n/a"
                val drop = snapshot.dropRatio?.toString() ?: "n/a"
                val ros = snapshot.rosEnabled?.toString() ?: "n/a"
                val rosError = snapshot.rosError?.takeIf { it.isNotBlank() } ?: "-"
                messageStore.addSystemMessage(
                    "Robot status: gateway_ok=${snapshot.gatewayOk}, sessions=$sessions, video_pushed=$pushed, video_sent=$sent, drop_ratio=$drop, ros_enabled=$ros, ros_error=$rosError"
                )
            }
        }
    }

    private fun handleRobotEvent(event: RobotEvent) {
        when (event) {
            is RobotEvent.Message -> {
                flushDeltaBufferIfNeeded()
                messageStore.addRobotMessage(event.content)
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
                messageStore.addSystemMessage("Transcription: ${event.content}")
            }

            is RobotEvent.Error -> {
                messageStore.addSystemMessage("Error: ${event.content}")
            }

            is RobotEvent.Alert -> {
                val codePart = event.errorCode?.let { " code=$it" } ?: ""
                messageStore.addSystemMessage("Alert[${event.level}]$codePart ${event.content}")
            }

            is RobotEvent.JoystickAck -> {
                updateLatencyFromAckTs(event.ts)
                if (event.reason.isNotBlank() && event.reason != "accepted") {
                    messageStore.addSystemMessage("Joystick rejected: ${event.reason}")
                }
            }

            is RobotEvent.ControlAck -> {
                updateLatencyFromAckTs(event.ts)
                if (event.reason.isNotBlank() && event.reason != "accepted") {
                    messageStore.addSystemMessage("Control rejected: ${event.reason}")
                }
            }

            is RobotEvent.GatewayEvent -> {
                when (event.name) {
                    "state_changed" -> {
                        val oldState = event.oldState ?: "unknown"
                        val newState = event.state ?: "unknown"
                        messageStore.addSystemMessage("Gateway state: $oldState -> $newState")
                    }

                    "command_applied" -> {
                        val kind = event.kind ?: "unknown"
                        val source = event.source ?: "unknown"
                        messageStore.addSystemMessage("Command applied: $kind from $source")
                    }

                    else -> {
                        messageStore.addSystemMessage("Gateway event: ${event.name}")
                    }
                }
            }
        }
    }

    private fun flushDeltaBufferIfNeeded() {
        if (streamDeltaBuffer.isEmpty()) return
        messageStore.addRobotMessage(streamDeltaBuffer.toString())
        streamDeltaBuffer = StringBuilder()
    }

    private fun updateLatencyFromAckTs(ackTs: Long?) {
        val baseline = ackTs ?: return
        val latency = (SystemClock.elapsedRealtime() - baseline).coerceAtLeast(0L)
        _uiState.update { it.copy(latencyMs = latency) }
    }

    override fun onCleared() {
        controlEngine.stopControlLoop()
        voiceModule.release()
        runBlocking {
            connectUseCase.robotClient.disconnect()
        }
        super.onCleared()
    }

    private companion object {
        const val CONTROL_TICK_MS = 50L
    }
}

class TeleopViewModelFactory(
    private val connectUseCase: ConnectRobotUseCase,
    private val disconnectUseCase: DisconnectRobotUseCase,
    private val sendControlUseCase: SendControlCommandUseCase,
    private val networkMonitor: NetworkMonitor,
    private val controlEngine: ControlEngine,
    private val voiceModule: VoiceModule,
    private val localRobotInfoService: LocalRobotInfoService,
) : ViewModelProvider.Factory {
    @Suppress("UNCHECKED_CAST")
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return TeleopViewModel(
            connectUseCase = connectUseCase,
            disconnectUseCase = disconnectUseCase,
            sendControlUseCase = sendControlUseCase,
            networkMonitor = networkMonitor,
            controlEngine = controlEngine,
            voiceModule = voiceModule,
            localRobotInfoService = localRobotInfoService,
        ) as T
    }
}
