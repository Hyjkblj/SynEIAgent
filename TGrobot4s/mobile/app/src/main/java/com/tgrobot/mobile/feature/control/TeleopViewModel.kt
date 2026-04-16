package com.tgrobot.mobile.feature.control

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.tgrobot.mobile.core.model.RobotConnectionState
import com.tgrobot.mobile.core.model.RobotEvent
import com.tgrobot.mobile.core.realtime.NetworkMonitor
import com.tgrobot.mobile.domain.control.ControlEngine
import com.tgrobot.mobile.domain.message.MessageStore
import com.tgrobot.mobile.domain.message.UiMessageRole
import com.tgrobot.mobile.domain.usecase.ConnectRobotUseCase
import com.tgrobot.mobile.domain.usecase.DisconnectRobotUseCase
import com.tgrobot.mobile.domain.usecase.SendControlCommandUseCase
import com.tgrobot.mobile.feature.voice.VoiceModule
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking

/**
 * Teleop ViewModel
 * 
 * 精简后的 ViewModel，仅负责：
 * - 暴露 UI 状态
 * - 委托业务逻辑给 Coordinator
 * - 观察数据源更新状态
 */
class TeleopViewModel(
    private val coordinator: TeleopCoordinator,
    private val connectUseCase: ConnectRobotUseCase,
    private val networkMonitor: NetworkMonitor,
    private val controlEngine: ControlEngine,
) : ViewModel() {

    val uiState = coordinator.uiState

    init {
        observeRepository()
        observeNetwork()
    }

    fun updateHost(value: String) = coordinator.updateHost(value)

    fun updatePort(value: String) = coordinator.updatePort(value)

    fun updateDraftText(value: String) = coordinator.updateDraftText(value)

    fun connect() = coordinator.connect()

    fun disconnect() = coordinator.disconnect()

    fun emergencyStop() = coordinator.emergencyStop()

    fun onJoystickInput(x: Float, y: Float) = coordinator.onJoystickInput(x, y)

    fun onJoystickRelease() = coordinator.onJoystickRelease()

    fun toggleVoiceListening() = coordinator.toggleVoiceListening()

    fun onVoicePermissionDenied() = coordinator.onVoicePermissionDenied()

    fun sendText() = coordinator.sendText()

    private fun observeRepository() {
        viewModelScope.launch {
            connectUseCase.robotClient.connectionState.collect { state ->
                coordinator.updateConnectionState(state)
                if (state == RobotConnectionState.DATA_CHANNEL_OPEN) {
                    controlEngine.startControlLoop(tickMs = CONTROL_TICK_MS) { command, now ->
                        // 控制命令发送由 UseCase 处理
                    }
                } else {
                    controlEngine.stopControlLoop()
                }
            }
        }

        viewModelScope.launch {
            connectUseCase.robotClient.remoteVideoTrack.collect { track ->
                coordinator.updateVideoTrack(track)
            }
        }

        viewModelScope.launch {
            connectUseCase.robotClient.events.collect { event ->
                coordinator.handleRobotEvent(event)
                // 处理消息类型事件
                when (event) {
                    is RobotEvent.Message -> {
                        coordinator.messageStore.addRobotMessage(event.content)
                    }
                    is RobotEvent.Error -> {
                        coordinator.messageStore.addSystemMessage("Error: ${event.content}")
                    }
                    is RobotEvent.Alert -> {
                        val codePart = event.errorCode?.let { " code=$it" } ?: ""
                        coordinator.messageStore.addSystemMessage("Alert[${event.level}]$codePart ${event.content}")
                    }
                    is RobotEvent.Transcription -> {
                        coordinator.messageStore.addSystemMessage("Transcription: ${event.content}")
                    }
                    is RobotEvent.GatewayEvent -> {
                        handleGatewayEvent(event)
                    }
                    else -> Unit
                }
            }
        }
    }

    private fun handleGatewayEvent(event: RobotEvent.GatewayEvent) {
        when (event.name) {
            "state_changed" -> {
                val oldState = event.oldState ?: "unknown"
                val newState = event.state ?: "unknown"
                coordinator.messageStore.addSystemMessage("Gateway state: $oldState -> $newState")
            }
            "command_applied" -> {
                val kind = event.kind ?: "unknown"
                val source = event.source ?: "unknown"
                coordinator.messageStore.addSystemMessage("Command applied: $kind from $source")
            }
            else -> {
                coordinator.messageStore.addSystemMessage("Gateway event: ${event.name}")
            }
        }
    }

    private fun observeNetwork() {
        viewModelScope.launch {
            networkMonitor.isOnline.collect { online ->
                coordinator.updateNetworkAvailable(online)
            }
        }
    }

    override fun onCleared() {
        coordinator.release()
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
    private val coordinator: TeleopCoordinator,
    private val connectUseCase: ConnectRobotUseCase,
    private val networkMonitor: NetworkMonitor,
    private val controlEngine: ControlEngine,
) : ViewModelProvider.Factory {
    @Suppress("UNCHECKED_CAST")
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return TeleopViewModel(
            coordinator = coordinator,
            connectUseCase = connectUseCase,
            networkMonitor = networkMonitor,
            controlEngine = controlEngine,
        ) as T
    }
}
