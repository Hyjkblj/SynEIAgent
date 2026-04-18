package com.tgrobot.mobile.feature.voice.asr

import android.os.Build
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.nio.charset.StandardCharsets
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit
import java.util.zip.GZIPInputStream
import java.util.zip.GZIPOutputStream

/**
 * 火山流式语音识别引擎（WebSocket + 二进制协议）。
 *
 * 已适配：
 * - 连接 Header 鉴权（app/access/resource/connect id）
 * - full client request + audio only request
 * - full server response + error response
 * - Gzip 压缩与 JSON 序列化
 */
class VolcAsrEngine(
    private val appKey: String,
    private val accessKey: String,
    private val resourceId: String,
    private val wsUrl: String = DEFAULT_WS_URL,
    private val modelName: String = "bigmodel",
    private val language: String = "zh-CN",
    private val enableItn: Boolean = true,
    private val enablePunc: Boolean = true,
    private val enableDdc: Boolean = false,
    private val enableNonstream: Boolean = false,
    private val resultType: String = "full",
    private val endWindowSizeMs: Int = 800,
    private val scope: CoroutineScope = CoroutineScope(Dispatchers.IO),
) : AsrEngine {

    override val name: String = "VolcAsrEngine"

    private val httpClient = OkHttpClient.Builder()
        .connectTimeout(8, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.SECONDS)
        .writeTimeout(15, TimeUnit.SECONDS)
        .build()

    private val sessionStates = ConcurrentHashMap<String, SessionState>()
    private val forceCloseJobs = ConcurrentHashMap<String, Job>()

    override fun isAvailable(): Boolean {
        return appKey.isNotBlank() && accessKey.isNotBlank() && resourceId.isNotBlank() && wsUrl.isNotBlank()
    }

    override fun startSession(): String {
        val sessionId = UUID.randomUUID().toString()
        val state = SessionState(
            sessionId = sessionId,
            connectId = UUID.randomUUID().toString(),
            channel = Channel(Channel.BUFFERED),
        )
        sessionStates[sessionId] = state
        connect(state)
        Log.d(TAG, "Session started: $sessionId connectId=${state.connectId}")
        return sessionId
    }

    override fun sendAudio(sessionId: String, audio: ByteArray) {
        if (audio.isEmpty()) return
        val state = sessionStates[sessionId] ?: return
        synchronized(state) {
            if (state.closed || state.clientClosing) return
            val frame = buildAudioOnlyRequestFrame(audio = audio, isFinal = false)
            if (state.isReady()) {
                state.webSocket?.send(ByteString.of(*frame))
            } else {
                if (state.pendingAudioFrames.size >= MAX_PENDING_FRAMES) {
                    state.pendingAudioFrames.removeFirst()
                }
                state.pendingAudioFrames.addLast(audio.copyOf())
            }
        }
    }

    override fun observe(sessionId: String): Flow<AsrResult> {
        val channel = sessionStates[sessionId]?.channel
            ?: Channel<AsrResult>(Channel.BUFFERED).also {
                sessionStates[sessionId] = SessionState(
                    sessionId = sessionId,
                    connectId = UUID.randomUUID().toString(),
                    channel = it,
                )
            }
        return channel.receiveAsFlow()
    }

    override fun endSession(sessionId: String) {
        val state = sessionStates[sessionId] ?: return
        synchronized(state) {
            if (state.closed) return
            state.clientClosing = true
            val finalFrame = buildAudioOnlyRequestFrame(audio = ByteArray(0), isFinal = true)
            val sent = state.webSocket?.send(ByteString.of(*finalFrame)) ?: false
            if (!sent) {
                closeSession(
                    sessionId = sessionId,
                    error = AsrResult.Error(
                        ERROR_SEND_FINAL_FAILED,
                        "Failed to send Volc final packet",
                    ),
                )
                return
            }
        }

        forceCloseJobs[sessionId]?.cancel()
        forceCloseJobs[sessionId] = scope.launch {
            delay(FORCE_CLOSE_DELAY_MS)
            closeSession(sessionId, closeReason = "force-close-timeout")
        }
    }

    // ── WebSocket ─────────────────────────────────────────────────────────

    private fun connect(state: SessionState) {
        val request = Request.Builder()
            .url(wsUrl)
            .addHeader(HEADER_APP_KEY, appKey)
            .addHeader(HEADER_ACCESS_KEY, accessKey)
            .addHeader(HEADER_RESOURCE_ID, resourceId)
            .addHeader(HEADER_CONNECT_ID, state.connectId)
            .build()

        httpClient.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                val fullRequestFrame = buildFullClientRequestFrame(state)
                synchronized(state) {
                    if (state.closed) return
                    state.webSocket = webSocket
                    state.opened = true
                    state.logId = response.header(HEADER_LOG_ID)
                    val ok = webSocket.send(ByteString.of(*fullRequestFrame))
                    if (!ok) {
                        closeSession(
                            sessionId = state.sessionId,
                            error = AsrResult.Error(ERROR_SEND_FULL_REQUEST_FAILED, "Failed to send full request"),
                        )
                        return
                    }
                    state.fullRequestSent = true
                    flushPendingAudioLocked(state)
                }
                Log.d(
                    TAG,
                    "Volc WS opened session=${state.sessionId} connectId=${state.connectId} logId=${state.logId}",
                )
            }

            override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                handleServerFrame(state, bytes.toByteArray())
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                Log.e(TAG, "Volc WS failure session=${state.sessionId}", t)
                closeSession(
                    sessionId = state.sessionId,
                    error = AsrResult.Error(ERROR_WEBSOCKET, "WebSocket failure: ${t.message}"),
                    closeReason = "ws-failure",
                )
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                Log.d(TAG, "Volc WS closed session=${state.sessionId} code=$code reason=$reason")
                closeSession(sessionId = state.sessionId, closeReason = "ws-closed")
            }
        })
    }

    // ── Protocol ──────────────────────────────────────────────────────────

    private fun buildFullClientRequestFrame(state: SessionState): ByteArray {
        val payloadJson = buildFullRequestPayload(state).toString()
        val payload = gzip(payloadJson.toByteArray(StandardCharsets.UTF_8))
        return buildFrame(
            messageType = MESSAGE_TYPE_FULL_CLIENT_REQUEST,
            messageFlags = FLAGS_NO_SEQUENCE,
            serialization = SERIALIZATION_JSON,
            compression = COMPRESSION_GZIP,
            payload = payload,
        )
    }

    private fun buildAudioOnlyRequestFrame(audio: ByteArray, isFinal: Boolean): ByteArray {
        val payload = gzip(audio)
        return buildFrame(
            messageType = MESSAGE_TYPE_AUDIO_ONLY_REQUEST,
            messageFlags = if (isFinal) FLAGS_LAST_PACKET else FLAGS_NO_SEQUENCE,
            serialization = SERIALIZATION_NONE,
            compression = COMPRESSION_GZIP,
            payload = payload,
        )
    }

    private fun buildFrame(
        messageType: Int,
        messageFlags: Int,
        serialization: Int,
        compression: Int,
        payload: ByteArray,
    ): ByteArray {
        val output = ByteArrayOutputStream()
        val byte0 = ((PROTOCOL_VERSION and 0x0F) shl 4) or (HEADER_SIZE_WORDS and 0x0F)
        val byte1 = ((messageType and 0x0F) shl 4) or (messageFlags and 0x0F)
        val byte2 = ((serialization and 0x0F) shl 4) or (compression and 0x0F)

        output.write(byte0)
        output.write(byte1)
        output.write(byte2)
        output.write(0x00) // reserved
        writeInt32(output, payload.size)
        output.write(payload)
        return output.toByteArray()
    }

    private fun buildFullRequestPayload(state: SessionState): JSONObject {
        val user = JSONObject().apply {
            put("uid", state.sessionId)
            put("did", Build.MODEL ?: "Android")
            put("platform", "Android-${Build.VERSION.SDK_INT}")
            put("sdk_version", "SynEI-Mobile")
            put("app_version", "0.1.0")
        }

        val audio = JSONObject().apply {
            put("format", "pcm")
            put("codec", "raw")
            put("rate", 16000)
            put("bits", 16)
            put("channel", 1)
            if (wsUrl.contains("nostream")) {
                put("language", language)
            }
        }

        val request = JSONObject().apply {
            put("model_name", modelName)
            put("enable_nonstream", enableNonstream)
            put("enable_itn", enableItn)
            put("enable_punc", enablePunc)
            put("enable_ddc", enableDdc)
            put("result_type", resultType)
            put("end_window_size", endWindowSizeMs)
        }

        return JSONObject().apply {
            put("user", user)
            put("audio", audio)
            put("request", request)
        }
    }

    private fun handleServerFrame(state: SessionState, frame: ByteArray) {
        runCatching {
            if (frame.size < MIN_FRAME_SIZE) {
                throw IllegalArgumentException("Invalid Volc frame size: ${frame.size}")
            }

            val byte0 = frame[0].toInt() and 0xFF
            val byte1 = frame[1].toInt() and 0xFF
            val byte2 = frame[2].toInt() and 0xFF
            val protocolVersion = (byte0 shr 4) and 0x0F
            val headerSize = (byte0 and 0x0F) * 4
            if (protocolVersion != PROTOCOL_VERSION) {
                throw IllegalArgumentException("Unsupported Volc protocol version=$protocolVersion")
            }
            if (frame.size < headerSize + 4) {
                throw IllegalArgumentException("Frame too short for header/payload")
            }

            val messageType = (byte1 shr 4) and 0x0F
            val flags = byte1 and 0x0F
            val compression = byte2 and 0x0F
            var offset = headerSize

            when (messageType) {
                MESSAGE_TYPE_FULL_SERVER_RESPONSE -> {
                    if (flags == FLAGS_SERVER_SEQ_POSITIVE || flags == FLAGS_SERVER_SEQ_NEGATIVE_FINAL) {
                        if (frame.size < offset + 4) {
                            throw IllegalArgumentException("Missing sequence field")
                        }
                        offset += 4 // sequence
                    }

                    val payloadSize = readInt32(frame, offset)
                    offset += 4
                    if (payloadSize < 0 || frame.size < offset + payloadSize) {
                        throw IllegalArgumentException("Invalid payload size=$payloadSize")
                    }
                    val payload = frame.copyOfRange(offset, offset + payloadSize)
                    val decoded = when (compression) {
                        COMPRESSION_GZIP -> ungzip(payload)
                        COMPRESSION_NONE -> payload
                        else -> throw IllegalArgumentException("Unsupported compression=$compression")
                    }
                    val json = decoded.toString(StandardCharsets.UTF_8)
                    parseRecognitionPayload(state, flags, json)
                }

                MESSAGE_TYPE_SERVER_ERROR -> {
                    if (frame.size < offset + 8) {
                        throw IllegalArgumentException("Error frame too short")
                    }
                    val errorCode = readInt32(frame, offset)
                    offset += 4
                    val errorMsgSize = readInt32(frame, offset)
                    offset += 4
                    val errorMsg = if (errorMsgSize > 0 && frame.size >= offset + errorMsgSize) {
                        frame.copyOfRange(offset, offset + errorMsgSize).toString(StandardCharsets.UTF_8)
                    } else {
                        "Unknown Volc protocol error"
                    }

                    closeSession(
                        sessionId = state.sessionId,
                        error = AsrResult.Error(errorCode, errorMsg),
                        closeReason = "server-error-frame",
                    )
                }

                else -> {
                    Log.w(TAG, "Ignore unsupported Volc messageType=$messageType session=${state.sessionId}")
                }
            }
        }.onFailure { error ->
            Log.e(TAG, "Failed to parse Volc frame session=${state.sessionId}", error)
            closeSession(
                sessionId = state.sessionId,
                error = AsrResult.Error(ERROR_PROTOCOL_PARSE, "Protocol parse error: ${error.message}"),
                closeReason = "parse-error",
            )
        }
    }

    private fun parseRecognitionPayload(state: SessionState, flags: Int, json: String) {
        runCatching {
            val root = JSONObject(json)
            val resultNode = root.opt("result")

            val resultObject = when (resultNode) {
                is JSONObject -> resultNode
                is JSONArray -> resultNode.optJSONObject(0)
                else -> null
            }

            val text = extractText(root, resultObject)
            val payloadIsFinal = root.optBoolean("is_final", false) ||
                (resultObject?.optBoolean("is_final", false) ?: false)
            val hasDefinite = hasDefiniteUtterance(resultObject)
            val isFinalPacket = flags == FLAGS_SERVER_SEQ_NEGATIVE_FINAL

            if (text.isNotBlank() && text != state.lastText) {
                state.lastText = text
                if (isFinalPacket || payloadIsFinal || hasDefinite) {
                    state.channel.trySend(AsrResult.Final(text))
                } else {
                    state.channel.trySend(AsrResult.Partial(text))
                }
            } else if (isFinalPacket && state.lastText.isNotBlank()) {
                state.channel.trySend(AsrResult.Final(state.lastText))
            }
            Unit
        }.onFailure { error ->
            Log.w(TAG, "Failed to parse Volc payload session=${state.sessionId}: $json", error)
        }
    }

    private fun extractText(root: JSONObject, resultObject: JSONObject?): String {
        val fromResult = resultObject?.optString("text", "").orEmpty().trim()
        if (fromResult.isNotBlank()) return fromResult

        val rootText = root.optString("text", "").trim()
        if (rootText.isNotBlank()) return rootText

        val resultArray = root.optJSONArray("result")
        if (resultArray != null && resultArray.length() > 0) {
            val firstObj = resultArray.optJSONObject(0)
            val firstText = firstObj?.optString("text", "").orEmpty().trim()
            if (firstText.isNotBlank()) return firstText
        }
        return ""
    }

    private fun hasDefiniteUtterance(resultObject: JSONObject?): Boolean {
        val utterances = resultObject?.optJSONArray("utterances") ?: return false
        for (i in 0 until utterances.length()) {
            val utt = utterances.optJSONObject(i) ?: continue
            if (utt.optBoolean("definite", false)) return true
        }
        return false
    }

    // ── Session lifecycle ─────────────────────────────────────────────────

    private fun flushPendingAudioLocked(state: SessionState) {
        if (!state.isReady()) return
        while (state.pendingAudioFrames.isNotEmpty()) {
            val audio = state.pendingAudioFrames.removeFirst()
            val frame = buildAudioOnlyRequestFrame(audio, isFinal = false)
            val ok = state.webSocket?.send(ByteString.of(*frame)) ?: false
            if (!ok) {
                closeSession(
                    sessionId = state.sessionId,
                    error = AsrResult.Error(ERROR_SEND_AUDIO_FAILED, "Failed to send audio frame"),
                    closeReason = "flush-audio-failed",
                )
                return
            }
        }
    }

    private fun closeSession(
        sessionId: String,
        error: AsrResult.Error? = null,
        closeReason: String = "normal",
    ) {
        val state = sessionStates.remove(sessionId) ?: return
        forceCloseJobs.remove(sessionId)?.cancel()

        synchronized(state) {
            if (state.closed) return
            state.closed = true
            if (error != null) {
                state.channel.trySend(error)
            }
            state.webSocket?.close(NORMAL_CLOSE_CODE, closeReason)
            state.webSocket = null
            state.pendingAudioFrames.clear()
            state.channel.close()
        }
        Log.d(TAG, "Session closed: $sessionId reason=$closeReason")
    }

    // ── Utils ─────────────────────────────────────────────────────────────

    private fun gzip(data: ByteArray): ByteArray {
        val output = ByteArrayOutputStream()
        GZIPOutputStream(output).use { gzip ->
            gzip.write(data)
        }
        return output.toByteArray()
    }

    private fun ungzip(data: ByteArray): ByteArray {
        GZIPInputStream(ByteArrayInputStream(data)).use { gzip ->
            return gzip.readBytes()
        }
    }

    private fun writeInt32(output: ByteArrayOutputStream, value: Int) {
        output.write((value shr 24) and 0xFF)
        output.write((value shr 16) and 0xFF)
        output.write((value shr 8) and 0xFF)
        output.write(value and 0xFF)
    }

    private fun readInt32(data: ByteArray, offset: Int): Int {
        return ((data[offset].toInt() and 0xFF) shl 24) or
            ((data[offset + 1].toInt() and 0xFF) shl 16) or
            ((data[offset + 2].toInt() and 0xFF) shl 8) or
            (data[offset + 3].toInt() and 0xFF)
    }

    private data class SessionState(
        val sessionId: String,
        val connectId: String,
        val channel: Channel<AsrResult>,
        var webSocket: WebSocket? = null,
        var opened: Boolean = false,
        var fullRequestSent: Boolean = false,
        var clientClosing: Boolean = false,
        var closed: Boolean = false,
        var lastText: String = "",
        var logId: String? = null,
        val pendingAudioFrames: ArrayDeque<ByteArray> = ArrayDeque(),
    ) {
        fun isReady(): Boolean = opened && fullRequestSent && webSocket != null
    }

    companion object {
        const val TAG = "VolcAsrEngine"

        const val DEFAULT_WS_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"

        const val HEADER_APP_KEY = "X-Api-App-Key"
        const val HEADER_ACCESS_KEY = "X-Api-Access-Key"
        const val HEADER_RESOURCE_ID = "X-Api-Resource-Id"
        const val HEADER_CONNECT_ID = "X-Api-Connect-Id"
        const val HEADER_LOG_ID = "X-Tt-Logid"

        const val PROTOCOL_VERSION = 0x1
        const val HEADER_SIZE_WORDS = 0x1
        const val MIN_FRAME_SIZE = 8

        const val MESSAGE_TYPE_FULL_CLIENT_REQUEST = 0x1
        const val MESSAGE_TYPE_AUDIO_ONLY_REQUEST = 0x2
        const val MESSAGE_TYPE_FULL_SERVER_RESPONSE = 0x9
        const val MESSAGE_TYPE_SERVER_ERROR = 0xF

        const val FLAGS_NO_SEQUENCE = 0x0
        const val FLAGS_LAST_PACKET = 0x2
        const val FLAGS_SERVER_SEQ_POSITIVE = 0x1
        const val FLAGS_SERVER_SEQ_NEGATIVE_FINAL = 0x3

        const val SERIALIZATION_NONE = 0x0
        const val SERIALIZATION_JSON = 0x1

        const val COMPRESSION_NONE = 0x0
        const val COMPRESSION_GZIP = 0x1

        const val NORMAL_CLOSE_CODE = 1000
        const val FORCE_CLOSE_DELAY_MS = 1500L
        const val MAX_PENDING_FRAMES = 200

        const val ERROR_WEBSOCKET = -400
        const val ERROR_PROTOCOL_PARSE = -401
        const val ERROR_SEND_FULL_REQUEST_FAILED = -402
        const val ERROR_SEND_AUDIO_FAILED = -403
        const val ERROR_SEND_FINAL_FAILED = -404
    }
}
