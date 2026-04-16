package com.tgrobot.mobile.feature.control

import android.os.SystemClock
import com.tgrobot.mobile.core.model.RobotEndpoint
import com.tgrobot.mobile.core.model.RobotSession
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
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * Teleop 协调器
 * 
 * 协调各子模块，管理 UI 状态。
 * 从 TeleopViewModel 中剥离协调逻辑。
 * 
 * 职责：
 * - 协调 UseCase、VoiceModule、ControlEngine
 * - 管理 UI 状态
 * - 处理业务流程
 */
class TeleopCoordinator(
    private val connectUseCase: ConnectRobotUseCase,
    private val disconnectUseCase: DisconnectRobotUseCase,
    private val sendControlUseCase: SendControlCommandUseCase,
    private val controlEngine: ControlEngine,
    private val voiceModule: VoiceModule,
    private val localRobotInfoService: LocalRobotInfoService,
    val messageStore: MessageStore,
    private val scope: CoroutineScope = CoroutineScope(Dispatchers.Default),
) {
    private val _uiState = MutableStateFlow(TeleopUiState())
    val uiState: StateFlow<TeleopUiState> = _uiState.asStateFlow()

    private var session: RobotSession = RobotSession.create()
    private var voiceExclusiveUntilMs: Long = 0L

    init {
        observeVoiceModule()
        observeControlEngine()
        observeMessages()
    }

    /**
     * 更新主机地址
     */
    fun updateHost(value: String) {
        _uiState.update { it.copy(host = value) }
    }

    /**
     * 更新端口
     */
    fun updatePort(value: String) {
        _uiState.update { it.copy(port = value.filter(Char::isDigit).take(5)) }
    }

    /**
     * 更新草稿文本
     */
    fun updateDraftText(value: String) {
        _uiState.update { it.copy(draftText = value) }
    }

    /**
     * 连接机器人
     */
    fun connect() {
        scope.launch {
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

    /**
     * 断开连接
     */
    fun disconnect() {
        scope.launch {
            disconnectUseCase()
        }
    }

    /**
     * 紧急停止
     */
    fun emergencyStop() {
        scope.launch {
            val success = sendControlUseCase.emergencyStop()
            if (success) {
                messageStore.addSystemMessage("Emergency stop triggered.")
            }
        }
    }

    /**
     * 更新摇杆输入
     */
    fun onJoystickInput(x: Float, y: Float) {
        val now = SystemClock.elapsedRealtime()
        if (_uiState.value.isVoiceListening || now < voiceExclusiveUntilMs) {
            return
        }
        sendControlUseCase.updateJoystickInput(x, y)
    }

    /**
     * 释放摇杆
     */
    fun onJoystickRelease() {
        scope.launch {
            sendControlUseCase.releaseJoystick()
        }
    }

    /**
     * 切换语音监听
     */
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

    /**
     * 语音权限被拒绝
     */
    fun onVoicePermissionDenied() {
        _uiState.update { it.copy(voiceError = "Microphone permission denied") }
        messageStore.addSystemMessage("Microphone permission denied.")
    }

    /**
     * 发送文本
     */
    fun sendText() {
        val text = _uiState.value.draftText.trim()
        if (text.isBlank()) return

        _uiState.update { it.copy(draftText = "") }
        messageStore.addUserMessage(text)
    }

    /**
     * 更新连接状态
     */
    fun updateConnectionState(state: com.tgrobot.mobile.core.model.RobotConnectionState) {
        _uiState.update { it.copy(connectionState = state) }
    }

    /**
     * 更新网络状态
     */
    fun updateNetworkAvailable(available: Boolean) {
        _uiState.update { it.copy(isNetworkAvailable = available) }
    }

    /**
     * 更新视频轨道
     */
    fun updateVideoTrack(track: org.webrtc.VideoTrack?) {
        _uiState.update { it.copy(remoteVideoTrack = track) }
    }

    /**
     * 更新延迟
     */
    fun updateLatency(latencyMs: Long?) {
        _uiState.update { it.copy(latencyMs = latencyMs) }
    }

    /**
     * 更新电池百分比
     */
    fun updateBatteryPercent(percent: Int?) {
        _uiState.update { it.copy(batteryPercent = percent) }
    }

    /**
     * 处理机器人事件
     */
    fun handleRobotEvent(event: com.tgrobot.mobile.core.model.RobotEvent) {
        when (event) {
            is com.tgrobot.mobile.core.model.RobotEvent.JoystickAck -> {
                updateLatency(event.ts?.let { ts ->
                    (SystemClock.elapsedRealtime() - ts).coerceAtLeast(0L)
                })
                if (event.reason.isNotBlank() && event.reason != "accepted") {
                    messageStore.addSystemMessage("Joystick rejected: ${event.reason}")
                }
            }
            is com.tgrobot.mobile.core.model.RobotEvent.ControlAck -> {
                updateLatency(event.ts?.let { ts ->
                    (SystemClock.elapsedRealtime() - ts).coerceAtLeast(0L)
                })
                if (event.reason.isNotBlank() && event.reason != "accepted") {
                    messageStore.addSystemMessage("Control rejected: ${event.reason}")
                }
            }
            else -> Unit
        }
    }

    private fun observeVoiceModule() {
        scope.launch {
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

        scope.launch {
            voiceModule.events.collect { event ->
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
        }

        scope.launch {
            voiceModule.commandResults.collect { result ->
                handleVoiceCommandResult(result)
            }
        }
    }

    private fun observeControlEngine() {
        scope.launch {
            controlEngine.lastCommand.collect { command ->
                _uiState.update { it.copy(lastCommand = command) }
            }
        }
    }

    private fun observeMessages() {
        scope.launch {
            messageStore.messages.collect { messages ->
                _uiState.update { it.copy(messages = messages) }
            }
        }
    }

    private suspend fun handleVoiceCommandResult(result: VoiceIntentResult) {
        val windowMs = voiceModule.getVoiceExclusiveWindowMs(result)
        if (windowMs > 0) {
            preemptJoystickForVoice(windowMs)
        }

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

        updateBatteryPercent(snapshot.batteryPercent ?: _uiState.value.batteryPercent)

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

    /**
     * 释放资源
     */
    fun release() {
        controlEngine.stopControlLoop()
        voiceModule.release()
    }
}
