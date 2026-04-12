package com.tgrobot.mobile

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.getValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.tgrobot.mobile.core.realtime.AndroidNetworkMonitor
import com.tgrobot.mobile.core.realtime.WebRtcRealtimeTransport
import com.tgrobot.mobile.data.DefaultRobotRepository
import com.tgrobot.mobile.domain.control.ControlManager
import com.tgrobot.mobile.feature.control.TeleopScreen
import com.tgrobot.mobile.feature.control.TeleopViewModel
import com.tgrobot.mobile.feature.control.TeleopViewModelFactory
import com.tgrobot.mobile.ui.theme.RobotAppTheme

class MainActivity : ComponentActivity() {
    private val transport by lazy { WebRtcRealtimeTransport(applicationContext) }
    private val repository by lazy { DefaultRobotRepository(transport) }
    private val networkMonitor by lazy { AndroidNetworkMonitor(applicationContext) }
    private val controlManager by lazy { ControlManager() }
    private val viewModelFactory by lazy {
        TeleopViewModelFactory(
            repository = repository,
            networkMonitor = networkMonitor,
            controlManager = controlManager,
        )
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        setContent {
            RobotAppTheme {
                val viewModel: TeleopViewModel = viewModel(factory = viewModelFactory)
                val state by viewModel.uiState.collectAsStateWithLifecycle()

                TeleopScreen(
                    state = state,
                    onHostChange = viewModel::updateHost,
                    onPortChange = viewModel::updatePort,
                    onConnectClick = viewModel::connect,
                    onDisconnectClick = viewModel::disconnect,
                    onEmergencyStop = viewModel::emergencyStop,
                    onJoystickInput = viewModel::onJoystickInput,
                    onJoystickRelease = viewModel::onJoystickRelease,
                    onDraftTextChange = viewModel::updateDraftText,
                    onSendText = viewModel::sendText,
                )
            }
        }
    }
}
