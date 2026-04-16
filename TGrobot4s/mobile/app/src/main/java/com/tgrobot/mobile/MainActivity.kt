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
import com.tgrobot.mobile.domain.control.ControlManager
import com.tgrobot.mobile.domain.voice.VoiceIntentParser
import com.tgrobot.mobile.feature.control.TeleopScreen
import com.tgrobot.mobile.feature.control.TeleopViewModel
import com.tgrobot.mobile.feature.control.TeleopViewModelFactory
import com.tgrobot.mobile.feature.voice.VoiceController
import com.tgrobot.mobile.ui.theme.RobotAppTheme

class MainActivity : ComponentActivity() {
    private val robotClient: RobotClient by lazy { WebRtcRobotClient(applicationContext) }
    private val networkMonitor by lazy { AndroidNetworkMonitor(applicationContext) }
    private val controlManager by lazy { ControlManager() }
    private val voiceController by lazy { VoiceController(this) }
    private val voiceIntentParser by lazy { VoiceIntentParser() }
    private val localRobotInfoService by lazy { LocalRobotInfoService() }
    private val viewModelFactory by lazy {
        TeleopViewModelFactory(
            repository = robotClient,
            networkMonitor = networkMonitor,
            controlManager = controlManager,
            voiceController = voiceController,
            voiceIntentParser = voiceIntentParser,
            localRobotInfoService = localRobotInfoService,
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
