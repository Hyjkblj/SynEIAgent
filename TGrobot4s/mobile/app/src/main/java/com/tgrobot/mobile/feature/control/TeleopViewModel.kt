package com.tgrobot.mobile.feature.control

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.tgrobot.mobile.core.model.RobotConnectionState
import com.tgrobot.mobile.core.realtime.NetworkMonitor
import com.tgrobot.mobile.domain.control.ControlEngine
import com.tgrobot.mobile.domain.usecase.ConnectRobotUseCase
import com.tgrobot.mobile.domain.usecase.SendControlCommandUseCase
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.launch

/**
 * Teleop ViewModel
 *
 * Keeps UI bindings and delegates domain work to coordinator/use cases.
 */
class TeleopViewModel(
    private val coordinator: TeleopCoordinator,
    private val connectUseCase: ConnectRobotUseCase,
    private val networkMonitor: NetworkMonitor,
    private val controlEngine: ControlEngine,
    private val sendControlUseCase: SendControlCommandUseCase,
) : ViewModel() {

    val uiState = coordinator.uiState
    private val cleanupScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

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

    fun switchPrimaryCamera(cameraId: String) {
        connectUseCase.robotClient.setPrimaryCamera(cameraId)
        coordinator.switchPrimaryCamera(cameraId)
    }

    private fun observeRepository() {
        viewModelScope.launch {
            connectUseCase.robotClient.connectionState.collect { state ->
                coordinator.updateConnectionState(state)
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
            combine(
                connectUseCase.robotClient.videoTracks,
                connectUseCase.robotClient.primaryCameraId,
            ) { tracks, primaryCameraId ->
                tracks to primaryCameraId
            }.collect { (tracks, primaryCameraId) ->
                coordinator.updateVideoTracks(
                    tracks = tracks,
                    preferredPrimaryCameraId = primaryCameraId,
                )
            }
        }

        viewModelScope.launch {
            connectUseCase.robotClient.events.collect { event ->
                coordinator.handleRobotEvent(event)
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
        cleanupScope.launch {
            runCatching { connectUseCase.robotClient.disconnect() }
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
    private val sendControlUseCase: SendControlCommandUseCase,
) : ViewModelProvider.Factory {
    @Suppress("UNCHECKED_CAST")
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return TeleopViewModel(
            coordinator = coordinator,
            connectUseCase = connectUseCase,
            networkMonitor = networkMonitor,
            controlEngine = controlEngine,
            sendControlUseCase = sendControlUseCase,
        ) as T
    }
}

