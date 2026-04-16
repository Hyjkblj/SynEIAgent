package com.tgrobot.mobile

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.ui.platform.LocalContext
import androidx.compose.runtime.getValue
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.tgrobot.mobile.core.realtime.AndroidNetworkMonitor
import com.tgrobot.mobile.data.RobotClient
import com.tgrobot.mobile.data.WebRtcRobotClient
import com.tgrobot.mobile.data.local.LocalRobotInfoService
import com.tgrobot.mobile.domain.control.ControlEngine
import com.tgrobot.mobile.domain.message.MessageStore
import com.tgrobot.mobile.domain.session.RobotSessionManager
import com.tgrobot.mobile.domain.usecase.ConnectRobotUseCase
import com.tgrobot.mobile.domain.usecase.DisconnectRobotUseCase
import com.tgrobot.mobile.domain.usecase.ProcessVoiceIntentUseCase
import com.tgrobot.mobile.domain.usecase.SendControlCommandUseCase
import com.tgrobot.mobile.domain.voice.VoiceIntentParser
import com.tgrobot.mobile.feature.control.TeleopCoordinator
import com.tgrobot.mobile.feature.control.TeleopScreen
import com.tgrobot.mobile.feature.control.TeleopViewModel
import com.tgrobot.mobile.feature.control.TeleopViewModelFactory
import com.tgrobot.mobile.feature.voice.VoiceModule
import com.tgrobot.mobile.ui.theme.RobotAppTheme

class MainActivity : ComponentActivity() {
    private val robotClient: RobotClient by lazy { WebRtcRobotClient(applicationContext) }
    private val networkMonitor by lazy { AndroidNetworkMonitor(applicationContext) }
    private val controlEngine by lazy { ControlEngine() }
    private val voiceIntentParser by lazy { VoiceIntentParser() }
    private val localRobotInfoService by lazy { LocalRobotInfoService() }
    private val messageStore by lazy { MessageStore() }
    private val sessionManager by lazy { RobotSessionManager() }

    // UseCase instances
    private val connectUseCase by lazy { ConnectRobotUseCase(robotClient, sessionManager) }
    private val sendControlUseCase by lazy {
        SendControlCommandUseCase(robotClient, controlEngine)
    }
    private val processVoiceUseCase by lazy {
        ProcessVoiceIntentUseCase(robotClient, voiceIntentParser)
    }

    // VoiceModule
    private val voiceModule by lazy { VoiceModule(this, processVoiceUseCase) }

    // DisconnectRobotUseCase
    private val disconnectUseCase by lazy {
        DisconnectRobotUseCase(robotClient, controlEngine, voiceModule, sessionManager)
    }

    // Coordinator
    private val coordinator by lazy {
        TeleopCoordinator(
            connectUseCase = connectUseCase,
            disconnectUseCase = disconnectUseCase,
            sendControlUseCase = sendControlUseCase,
            controlEngine = controlEngine,
            voiceModule = voiceModule,
            localRobotInfoService = localRobotInfoService,
            messageStore = messageStore,
        )
    }

    private val viewModelFactory by lazy {
        TeleopViewModelFactory(
            coordinator = coordinator,
            connectUseCase = connectUseCase,
            networkMonitor = networkMonitor,
            controlEngine = controlEngine,
        )
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        setContent {
            RobotAppTheme {
                val viewModel: TeleopViewModel = viewModel(factory = viewModelFactory)
                val state by viewModel.uiState.collectAsStateWithLifecycle()
                val context = LocalContext.current
                val audioPermissionLauncher = rememberLauncherForActivityResult(
                    contract = ActivityResultContracts.RequestPermission(),
                ) { granted ->
                    if (granted) {
                        viewModel.toggleVoiceListening()
                    } else {
                        viewModel.onVoicePermissionDenied()
                    }
                }

                TeleopScreen(
                    state = state,
                    onHostChange = viewModel::updateHost,
                    onPortChange = viewModel::updatePort,
                    onConnectClick = viewModel::connect,
                    onDisconnectClick = viewModel::disconnect,
                    onEmergencyStop = viewModel::emergencyStop,
                    onVoiceControlClick = {
                        val granted = ContextCompat.checkSelfPermission(
                            context,
                            Manifest.permission.RECORD_AUDIO,
                        ) == PackageManager.PERMISSION_GRANTED
                        if (granted) {
                            viewModel.toggleVoiceListening()
                        } else {
                            audioPermissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
                        }
                    },
                    onJoystickInput = viewModel::onJoystickInput,
                    onJoystickRelease = viewModel::onJoystickRelease,
                    onDraftTextChange = viewModel::updateDraftText,
                    onSendText = viewModel::sendText,
                )
            }
        }
    }
}
