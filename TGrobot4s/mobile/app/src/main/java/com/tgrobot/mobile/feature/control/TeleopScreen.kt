package com.tgrobot.mobile.feature.control

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import com.tgrobot.mobile.core.model.RobotConnectionState
import kotlin.math.hypot
import kotlin.math.min
import org.webrtc.EglBase
import org.webrtc.SurfaceViewRenderer
import org.webrtc.VideoTrack

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

@Composable
fun TeleopScreen(
    state: TeleopUiState,
    onHostChange: (String) -> Unit,
    onPortChange: (String) -> Unit,
    onConnectClick: () -> Unit,
    onDisconnectClick: () -> Unit,
    onEmergencyStop: () -> Unit,
    onVoiceControlClick: () -> Unit,
    onJoystickInput: (Float, Float) -> Unit,
    onJoystickRelease: () -> Unit,
    onDraftTextChange: (String) -> Unit,
    onSendText: () -> Unit,
) {
    if (!state.isConnected) {
        ConnectScreen(
            state = state,
            onHostChange = onHostChange,
            onPortChange = onPortChange,
            onConnectClick = onConnectClick,
        )
    } else {
        DriveScreen(
            state = state,
            onDisconnectClick = onDisconnectClick,
            onEmergencyStop = onEmergencyStop,
            onVoiceControlClick = onVoiceControlClick,
            onJoystickInput = onJoystickInput,
            onJoystickRelease = onJoystickRelease,
            onDraftTextChange = onDraftTextChange,
            onSendText = onSendText,
        )
    }
}

// ---------------------------------------------------------------------------
// Connect screen 闂?shown before DataChannel is open
// ---------------------------------------------------------------------------

@Composable
private fun ConnectScreen(
    state: TeleopUiState,
    onHostChange: (String) -> Unit,
    onPortChange: (String) -> Unit,
    onConnectClick: () -> Unit,
) {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background),
        contentAlignment = Alignment.Center,
    ) {
        Card(
            modifier = Modifier
                .fillMaxWidth(0.88f),
            shape = RoundedCornerShape(20.dp),
            elevation = CardDefaults.cardElevation(defaultElevation = 4.dp),
        ) {
            Column(
                modifier = Modifier.padding(24.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(
                    text = "Robot Control",
                    style = MaterialTheme.typography.headlineSmall,
                    fontWeight = FontWeight.Bold,
                )

                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(
                        modifier = Modifier.weight(1f),
                        value = state.host,
                        onValueChange = onHostChange,
                        label = { Text("Host / IP") },
                        singleLine = true,
                    )
                    OutlinedTextField(
                        modifier = Modifier.width(100.dp),
                        value = state.port,
                        onValueChange = onPortChange,
                        label = { Text("Port") },
                        singleLine = true,
                    )
                }

                // Connection status indicator
                val statusText = when (state.connectionState) {
                    RobotConnectionState.DISCONNECTED -> "Ready to connect"
                    RobotConnectionState.CONNECTING_SIGNAL -> "Connecting to signal server..."
                    RobotConnectionState.SIGNAL_CONNECTED -> "Signal connected, negotiating..."
                    RobotConnectionState.PEER_CONNECTING -> "Establishing peer connection..."
                    RobotConnectionState.DATA_CHANNEL_OPEN -> "Connected"
                    RobotConnectionState.FAILED -> "Connection failed - check host/port"
                }
                val statusColor = when (state.connectionState) {
                    RobotConnectionState.FAILED -> MaterialTheme.colorScheme.error
                    RobotConnectionState.DATA_CHANNEL_OPEN -> Color(0xFF4CAF50)
                    RobotConnectionState.DISCONNECTED -> MaterialTheme.colorScheme.onSurfaceVariant
                    else -> MaterialTheme.colorScheme.primary
                }
                Text(
                    text = statusText,
                    style = MaterialTheme.typography.bodySmall,
                    color = statusColor,
                    textAlign = TextAlign.Center,
                )

                Button(
                    onClick = onConnectClick,
                    modifier = Modifier.fillMaxWidth(),
                    enabled = state.connectionState == RobotConnectionState.DISCONNECTED ||
                        state.connectionState == RobotConnectionState.FAILED,
                ) {
                    Text("Connect")
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Drive screen 闂?full-screen immersive layout while connected
// ---------------------------------------------------------------------------

@Composable
private fun DriveScreen(
    state: TeleopUiState,
    onDisconnectClick: () -> Unit,
    onEmergencyStop: () -> Unit,
    onVoiceControlClick: () -> Unit,
    onJoystickInput: (Float, Float) -> Unit,
    onJoystickRelease: () -> Unit,
    onDraftTextChange: (String) -> Unit,
    onSendText: () -> Unit,
) {
    var showChat by remember { mutableStateOf(false) }

    Box(modifier = Modifier.fillMaxSize()) {

        // 闂備礁鍟块崢婊堝磻閹剧粯鐓冮柛蹇擃槸娴?Layer 0: video fills entire screen 闂備礁鍟块崢婊堝磻閹剧粯鐓冮柛蹇擃槸娴滈箖姊洪崘鎻掑辅闁稿鎹囬弻宥夊礂婢跺﹣澹曢梻浣稿暱閸樻粓宕戦幘缁樼厓闁稿繐顦禍楣冩⒑閸愭彃甯ㄩ柛瀣崌閺屽秹宕楁径濠佸闂備礁鍟块崢婊堝磻閹剧粯鐓冮柛蹇擃槸娴滈箖姊洪崘鎻掑辅闁稿鎹囬弻宥夊礂婢跺﹣澹曢梻浣稿暱閸樻粓宕戦幘缁樼厓闁稿繐顦禍楣冩⒑閸愭彃甯ㄩ柛瀣崌閺屽秹宕楁径濠佸闂備礁鍟块崢婊堝磻閹剧粯鐓冮柛蹇擃槸娴滈箖姊洪崘鎻掑辅闁稿鎹囬弻宥夊礂婢跺﹣澹曢梻浣稿暱閸樻粓宕戦幘缁樼厓闁稿繐顦禍楣冩⒑閸愭彃甯ㄩ柛瀣崌閺屽秹宕楁径濠佸闂備礁鍟块崢婊堝磻閹剧粯鐓冮柛蹇擃槸娴?
        VideoBackground(track = state.remoteVideoTrack)

        // 闂備礁鍟块崢婊堝磻閹剧粯鐓冮柛蹇擃槸娴?Layer 1: HUD overlays 闂備礁鍟块崢婊堝磻閹剧粯鐓冮柛蹇擃槸娴滈箖姊洪崘鎻掑辅闁稿鎹囬弻宥夊礂婢跺﹣澹曢梻浣稿暱閸樻粓宕戦幘缁樼厓闁稿繐顦禍楣冩⒑閸愭彃甯ㄩ柛瀣崌閺屽秹宕楁径濠佸闂備礁鍟块崢婊堝磻閹剧粯鐓冮柛蹇擃槸娴滈箖姊洪崘鎻掑辅闁稿鎹囬弻宥夊礂婢跺﹣澹曢梻浣稿暱閸樻粓宕戦幘缁樼厓闁稿繐顦禍楣冩⒑閸愭彃甯ㄩ柛瀣崌閺屽秹宕楁径濠佸闂備礁鍟块崢婊堝磻閹剧粯鐓冮柛蹇擃槸娴滈箖姊洪崘鎻掑辅闁稿鎹囬弻宥夊礂婢跺﹣澹曢梻浣稿暱閸樻粓宕戦幘缁樼厓闁稿繐顦禍楣冩⒑閸愭彃甯ㄩ柛瀣崌閺屽秹宕楁径濠佸闂備礁鍟块崢婊堝磻閹剧粯鐓冮柛蹇擃槸娴滈箖姊洪崘鎻掑辅闁稿鎹囬弻宥夊礂婢跺﹣澹曢梻浣稿暱閸樻粓宕戦幘缁樼厓闁稿繐顦禍楣冩⒑閸愭彃甯ㄩ柛瀣崌閺屽秹宕楁径濠佸闂備礁鍟块崢婊堝磻閹剧粯鐓冮柛蹇擃槸娴滈箖姊洪崘鎻掑辅闁稿鎹囬弻宥夊礂婢跺﹣澹曢梻浣稿暱閸樻粓宕戦幘缁樼厓闁稿繐顦禍楣冩⒑閸愭彃甯ㄩ柛瀣崌閺屽秹宕楁径濠佸

        // Top-left: connection badge + disconnect
        TopLeftHud(
            state = state,
            onDisconnectClick = onDisconnectClick,
            modifier = Modifier.align(Alignment.TopStart),
        )

        // Top-right: status readouts
        TopRightHud(
            state = state,
            modifier = Modifier.align(Alignment.TopEnd),
        )

        // Bottom-left: joystick
        Box(
            modifier = Modifier
                .align(Alignment.BottomStart)
                .padding(start = 24.dp, bottom = 24.dp),
        ) {
            JoystickView(
                modifier = Modifier.size(180.dp),
                onInput = onJoystickInput,
                onRelease = onJoystickRelease,
            )
        }

        // Bottom-right: E-Stop + chat toggle
        Column(
            modifier = Modifier
                .align(Alignment.BottomEnd)
                .padding(end = 24.dp, bottom = 24.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
            horizontalAlignment = Alignment.End,
        ) {
            FilledTonalButton(
                onClick = onVoiceControlClick,
                shape = RoundedCornerShape(12.dp),
            ) {
                Text(if (state.isVoiceListening) "Stop Voice" else "Voice")
            }

            // Chat toggle
            FilledTonalButton(
                onClick = { showChat = !showChat },
                shape = RoundedCornerShape(12.dp),
            ) {
                Text(if (showChat) "Hide Chat" else "Chat")
            }

            // E-Stop 闂?large, red, impossible to miss
            Button(
                onClick = onEmergencyStop,
                modifier = Modifier.size(width = 120.dp, height = 56.dp),
                colors = ButtonDefaults.buttonColors(
                    containerColor = Color(0xFFD32F2F),
                    contentColor = Color.White,
                ),
                shape = RoundedCornerShape(12.dp),
            ) {
                Text(
                    text = "E-STOP",
                    fontWeight = FontWeight.ExtraBold,
                    fontSize = 16.sp,
                )
            }

            if (state.voicePartialText.isNotBlank()) {
                Surface(
                    shape = RoundedCornerShape(10.dp),
                    color = Color.Black.copy(alpha = 0.6f),
                ) {
                    Text(
                        text = state.voicePartialText,
                        modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
                        color = Color.White,
                        fontSize = 12.sp,
                    )
                }
            }
        }

        // Bottom-center: speed readout
        SpeedReadout(
            state = state,
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .padding(bottom = 32.dp),
        )

        // Chat panel slides in from bottom
        AnimatedVisibility(
            visible = showChat,
            enter = fadeIn(),
            exit = fadeOut(),
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .fillMaxWidth(0.6f)
                .padding(bottom = 100.dp),
        ) {
            ChatOverlay(
                state = state,
                onDraftTextChange = onDraftTextChange,
                onSendText = onSendText,
            )
        }
    }
}

// ---------------------------------------------------------------------------
// Video background
// ---------------------------------------------------------------------------

@Composable
private fun VideoBackground(track: VideoTrack?) {
    Box(modifier = Modifier.fillMaxSize().background(Color.Black)) {
        RealtimeVideoView(
            track = track,
            modifier = Modifier.fillMaxSize(),
        )
        if (track == null) {
            Text(
                text = "No video signal",
                modifier = Modifier.align(Alignment.Center),
                color = Color.White.copy(alpha = 0.5f),
                style = MaterialTheme.typography.bodyLarge,
            )
        }
    }
}

@Composable
private fun RealtimeVideoView(track: VideoTrack?, modifier: Modifier = Modifier) {
    val context = LocalContext.current
    val eglBase = remember { EglBase.create() }
    val renderer = remember {
        SurfaceViewRenderer(context).apply {
            init(eglBase.eglBaseContext, null)
            setEnableHardwareScaler(true)
            setMirror(false)
        }
    }

    DisposableEffect(track) {
        track?.addSink(renderer)
        onDispose { track?.removeSink(renderer) }
    }

    DisposableEffect(Unit) {
        onDispose {
            renderer.release()
            eglBase.release()
        }
    }

    AndroidView(modifier = modifier, factory = { renderer })
}

// ---------------------------------------------------------------------------
// HUD components
// ---------------------------------------------------------------------------

@Composable
private fun TopLeftHud(
    state: TeleopUiState,
    onDisconnectClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier.padding(top = 12.dp, start = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        // Green dot
        Box(
            modifier = Modifier
                .size(10.dp)
                .background(Color(0xFF4CAF50), CircleShape),
        )
        Text(
            text = "LIVE",
            color = Color.White,
            fontWeight = FontWeight.Bold,
            fontSize = 12.sp,
        )
        Spacer(modifier = Modifier.width(4.dp))
        Surface(
            shape = RoundedCornerShape(8.dp),
            color = Color.Black.copy(alpha = 0.45f),
        ) {
            TextButton(onClick = onDisconnectClick) {
                Text("Disconnect", color = Color.White.copy(alpha = 0.8f), fontSize = 12.sp)
            }
        }
    }
}

@Composable
private fun TopRightHud(state: TeleopUiState, modifier: Modifier = Modifier) {
    Surface(
        modifier = modifier.padding(top = 12.dp, end = 12.dp),
        shape = RoundedCornerShape(10.dp),
        color = Color.Black.copy(alpha = 0.45f),
    ) {
        Column(
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(3.dp),
            horizontalAlignment = Alignment.End,
        ) {
            HudRow("Latency", state.latencyMs?.let { "${it}ms" } ?: "--")
            HudRow("Battery", state.batteryPercent?.let { "$it%" } ?: "--")
            if (state.isVoiceListening) {
                Text("VOICE LISTENING", color = Color(0xFF80CBC4), fontSize = 11.sp, fontWeight = FontWeight.Bold)
            }
            state.voiceError?.takeIf { it.isNotBlank() }?.let {
                Text("VOICE ERROR", color = Color(0xFFFFB74D), fontSize = 11.sp, fontWeight = FontWeight.Bold)
                Text(
                    text = it,
                    color = Color(0xFFFFCC80),
                    fontSize = 10.sp,
                    maxLines = 2,
                )
            }
            if (!state.isNetworkAvailable) {
                Text("NO NETWORK", color = Color(0xFFFF5252), fontSize = 11.sp, fontWeight = FontWeight.Bold)
            }
        }
    }
}

@Composable
private fun HudRow(label: String, value: String) {
    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(label, color = Color.White.copy(alpha = 0.6f), fontSize = 11.sp)
        Text(value, color = Color.White, fontSize = 11.sp, fontWeight = FontWeight.Medium)
    }
}

@Composable
private fun SpeedReadout(state: TeleopUiState, modifier: Modifier = Modifier) {
    val isMoving = !state.lastCommand.isZero()
    Surface(
        modifier = modifier,
        shape = RoundedCornerShape(8.dp),
        color = Color.Black.copy(alpha = if (isMoving) 0.6f else 0.3f),
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 14.dp, vertical = 6.dp),
            horizontalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Text(
                text = "L ${String.format("%.2f", state.lastCommand.linear)} m/s",
                color = Color.White,
                fontSize = 13.sp,
                fontWeight = if (isMoving) FontWeight.Bold else FontWeight.Normal,
            )
            Text(
                text = "A ${String.format("%.2f", state.lastCommand.angular)} r/s",
                color = Color.White,
                fontSize = 13.sp,
                fontWeight = if (isMoving) FontWeight.Bold else FontWeight.Normal,
            )
        }
    }
}

// ---------------------------------------------------------------------------
// Chat overlay
// ---------------------------------------------------------------------------

@Composable
private fun ChatOverlay(
    state: TeleopUiState,
    onDraftTextChange: (String) -> Unit,
    onSendText: () -> Unit,
) {
    val listState = rememberLazyListState()
    LaunchedEffect(state.messages.size) {
        if (state.messages.isNotEmpty()) {
            listState.animateScrollToItem(state.messages.lastIndex)
        }
    }

    Surface(
        shape = RoundedCornerShape(16.dp),
        color = Color.Black.copy(alpha = 0.75f),
    ) {
        Column(
            modifier = Modifier.padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            LazyColumn(
                state = listState,
                modifier = Modifier.height(160.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                items(state.messages, key = { it.id }) { message ->
                    val color = when (message.role) {
                        UiMessageRole.USER -> Color(0xFF90CAF9)
                        UiMessageRole.ROBOT -> Color(0xFFA5D6A7)
                        UiMessageRole.SYSTEM -> Color.White.copy(alpha = 0.5f)
                    }
                    Text(
                        text = message.content,
                        color = color,
                        fontSize = 12.sp,
                    )
                }
            }

            Row(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                OutlinedTextField(
                    modifier = Modifier.weight(1f),
                    value = state.draftText,
                    onValueChange = onDraftTextChange,
                    placeholder = {
                        Text("Send a command...", color = Color.White.copy(alpha = 0.4f), fontSize = 12.sp)
                    },
                    singleLine = true,
                )
                Button(onClick = onSendText) {
                    Text("Send")
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Joystick
// ---------------------------------------------------------------------------

@Composable
private fun JoystickView(
    modifier: Modifier = Modifier,
    onInput: (Float, Float) -> Unit,
    onRelease: () -> Unit,
) {
    var size by remember { mutableStateOf(IntSize.Zero) }
    var knobOffset by remember { mutableStateOf(Offset.Zero) }

    val baseColor = Color.White.copy(alpha = 0.12f)
    val ringColor = Color.White.copy(alpha = 0.55f)
    val knobColor = Color.White.copy(alpha = 0.90f)
    val highlightColor = Color.White.copy(alpha = 0.5f)

    fun updateKnob(pointer: Offset) {
        if (size == IntSize.Zero) return
        val center = Offset(size.width / 2f, size.height / 2f)
        val radius = min(size.width, size.height) * 0.42f
        var dx = pointer.x - center.x
        var dy = pointer.y - center.y
        val dist = hypot(dx.toDouble(), dy.toDouble()).toFloat()
        if (dist > radius && dist > 0f) {
            val r = radius / dist
            dx *= r; dy *= r
        }
        knobOffset = Offset(dx, dy)
        onInput(
            (dx / radius).coerceIn(-1f, 1f),
            (-dy / radius).coerceIn(-1f, 1f),
        )
    }

    fun resetKnob() {
        knobOffset = Offset.Zero
        onRelease()
    }

    Box(
        modifier = modifier
            .clip(CircleShape)
            .onSizeChanged { size = it }
            .pointerInput(Unit) {
                detectDragGestures(
                    onDragStart = { updateKnob(it) },
                    onDragEnd = { resetKnob() },
                    onDragCancel = { resetKnob() },
                    onDrag = { change, _ ->
                        updateKnob(change.position)
                        change.consume()
                    },
                )
            },
    ) {
        Canvas(modifier = Modifier.fillMaxSize()) {
            val center = Offset(size.width / 2f, size.height / 2f)
            val baseRadius = min(size.width, size.height) * 0.42f
            val knobRadius = min(size.width, size.height) * 0.14f

            drawCircle(color = baseColor, radius = baseRadius, center = center)
            drawCircle(color = ringColor, radius = baseRadius, center = center, style = Stroke(width = 2.5.dp.toPx()))
            drawCircle(color = knobColor, radius = knobRadius, center = center + knobOffset)
            drawCircle(color = highlightColor, radius = knobRadius * 0.35f, center = center + knobOffset)
        }
    }
}

