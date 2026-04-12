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
import com.tgrobot.mobile.core.realtime.NetworkMonitor
import com.tgrobot.mobile.data.RobotRepository
import com.tgrobot.mobile.domain.control.ControlManager
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
) : ViewModel() {
    private val _uiState = MutableStateFlow(TeleopUiState())
    val uiState = _uiState.asStateFlow()

    private var session: RobotSession = RobotSession.create()
    private var controlLoopJob: Job? = null
    private var streamDeltaBuffer = StringBuilder()

    init {
        observeRepository()
        observeNetwork()
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
            repository.disconnect()
            controlManager.reset()
            stopControlLoop()
        }
    }

    fun emergencyStop() {
        viewModelScope.launch {
            val now = SystemClock.elapsedRealtime()
            val command = controlManager.emergencyStop(now)
            sendControlCommand(command, now)
            appendMessage(UiMessageRole.SYSTEM, "Emergency stop triggered.")
        }
    }

    fun onJoystickInput(x: Float, y: Float) {
        controlManager.updateInput(x = x, y = y)
    }

    fun onJoystickRelease() {
        viewModelScope.launch {
            val now = SystemClock.elapsedRealtime()
            val command = controlManager.release(now)
            sendControlCommand(command, now)
        }
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
            }

            is RobotEvent.ControlAck -> {
                updateLatencyFromAckTs(event.ts)
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
                    sendControlCommand(command, now)
                }
                delay(CONTROL_TICK_MS)
            }
        }
    }

    private fun stopControlLoop() {
        controlLoopJob?.cancel()
        controlLoopJob = null
    }

    private suspend fun sendControlCommand(command: TeleopCommand, nowMs: Long) {
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
        runBlocking {
            repository.disconnect()
        }
        super.onCleared()
    }

    private companion object {
        const val CONTROL_TICK_MS = 50L
    }
}

class TeleopViewModelFactory(
    private val repository: RobotRepository,
    private val networkMonitor: NetworkMonitor,
    private val controlManager: ControlManager,
) : ViewModelProvider.Factory {
    @Suppress("UNCHECKED_CAST")
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return TeleopViewModel(
            repository = repository,
            networkMonitor = networkMonitor,
            controlManager = controlManager,
        ) as T
    }
}
