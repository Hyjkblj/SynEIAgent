package com.tgrobot.mobile.feature.voice.asr

import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import java.util.concurrent.TimeUnit

/**
 * FunASR 引擎
 *
 * 通过 WebSocket 对接自建 FunASR 流式语音识别服务（ali-speech/FunASR）。
 *
 * 协议说明：
 * - 建立 WebSocket 连接后发送 JSON 配置帧
 * - 持续发送 PCM ByteArray 音频帧
 * - 接收 JSON 识别结果（mode = "2pass-online"）
 * - 发送 {"is_speaking": false} 表示说话结束
 *
 * @param wsUrl  FunASR 服务地址，例如 "ws://192.168.1.100:10095"
 */
class FunAsrEngine(
    private val wsUrl: String,
) : AsrEngine {

    override val name: String = "FunAsrEngine"

    private val scope = CoroutineScope(Dispatchers.IO)
    private val sessionChannels = ConcurrentHashMap<String, Channel<AsrResult>>()
    private val sessionSockets = ConcurrentHashMap<String, WebSocket>()
    private var reconnectJob: Job? = null

    private val httpClient = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.SECONDS)   // WebSocket 长连接
        .writeTimeout(10, TimeUnit.SECONDS)
        .build()

    override fun isAvailable(): Boolean {
        // FunASR 只要 URL 配置非空即认为可用（实际连通性在 startSession 时验证）
        return wsUrl.isNotBlank()
    }

    override fun startSession(): String {
        val sessionId = UUID.randomUUID().toString()
        val channel = Channel<AsrResult>(capacity = Channel.BUFFERED)
        sessionChannels[sessionId] = channel

        connectWebSocket(sessionId, channel)
        Log.d(TAG, "Session started: $sessionId -> $wsUrl")
        return sessionId
    }

    override fun sendAudio(sessionId: String, audio: ByteArray) {
        val ws = sessionSockets[sessionId] ?: return
        ws.send(ByteString.of(*audio))
    }

    override fun observe(sessionId: String): Flow<AsrResult> {
        val channel = sessionChannels[sessionId]
            ?: Channel<AsrResult>(Channel.BUFFERED).also { sessionChannels[sessionId] = it }
        return channel.receiveAsFlow()
    }

    override fun endSession(sessionId: String) {
        // 告知服务端说话已结束
        sessionSockets[sessionId]?.send("""{"is_speaking":false}""")
        sessionSockets.remove(sessionId)?.close(1000, "Session ended")
        sessionChannels.remove(sessionId)?.close()
        Log.d(TAG, "Session ended: $sessionId")
    }

    // ── Private ───────────────────────────────────────────────────────────

    private fun connectWebSocket(sessionId: String, channel: Channel<AsrResult>) {
        val request = Request.Builder().url(wsUrl).build()

        httpClient.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                sessionSockets[sessionId] = webSocket
                // 发送初始化配置帧
                val config = JSONObject().apply {
                    put("mode", "2pass")
                    put("chunk_size", JSONObject().apply {
                        put("0", 5); put("1", 10); put("2", 5)
                    })
                    put("chunk_interval", 10)
                    put("encoder_chunk_look_back", 4)
                    put("decoder_chunk_look_back", 0)
                    put("hotwords", "")
                    put("itn", false)
                }
                webSocket.send(config.toString())
                Log.d(TAG, "WebSocket opened for session=$sessionId")
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                parseResult(text, channel)
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                Log.e(TAG, "WebSocket failure session=$sessionId", t)
                channel.trySend(AsrResult.Error(-100, "WebSocket error: ${t.message}"))
                sessionSockets.remove(sessionId)
                scheduleReconnect(sessionId, channel)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                Log.d(TAG, "WebSocket closed session=$sessionId code=$code")
                sessionSockets.remove(sessionId)
                channel.close()
                sessionChannels.remove(sessionId)
            }
        })
    }

    private fun parseResult(json: String, channel: Channel<AsrResult>) {
        runCatching {
            val obj = JSONObject(json)
            val text = obj.optString("text", "").trim()
            val isFinal = obj.optBoolean("is_final", false)

            if (isFinal && text.isNotBlank()) {
                channel.trySend(AsrResult.Final(text))
            } else if (text.isNotBlank()) {
                channel.trySend(AsrResult.Partial(text))
            }
            Unit
        }.onFailure { e ->
            Log.w(TAG, "Failed to parse FunASR result: $json", e)
        }
    }

    private fun scheduleReconnect(sessionId: String, channel: Channel<AsrResult>) {
        reconnectJob?.cancel()
        reconnectJob = scope.launch {
            var attempt = 0
            while (isActive && sessionChannels.containsKey(sessionId)) {
                attempt++
                val delayMs = minOf(1_000L * attempt, MAX_RECONNECT_DELAY_MS)
                Log.d(TAG, "Reconnect attempt $attempt in ${delayMs}ms (session=$sessionId)")
                delay(delayMs)
                if (sessionChannels.containsKey(sessionId)) {
                    connectWebSocket(sessionId, channel)
                    break
                }
            }
        }
    }

    private companion object {
        const val TAG = "FunAsrEngine"
        const val MAX_RECONNECT_DELAY_MS = 8_000L
    }
}
