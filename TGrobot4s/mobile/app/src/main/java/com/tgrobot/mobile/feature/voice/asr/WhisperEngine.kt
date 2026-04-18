package com.tgrobot.mobile.feature.voice.asr

import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit

/**
 * Whisper ASR 引擎
 *
 * 通过 HTTP POST 调用 Whisper 转录服务（兼容 OpenAI /v1/audio/transcriptions 格式）。
 * 适合服务端部署场景（高精度、支持中文、延迟约 1-3s）。
 *
 * 工作方式：
 * - 音频帧在内存中累积，直到 endSession 触发上传
 * - 上传完整 PCM 数据后返回一次 Final 结果
 *
 * @param httpUrl  Whisper 服务地址，例如 "http://192.168.1.100:9000/v1/audio/transcriptions"
 * @param model    模型名称，默认 "whisper-1"
 * @param language 语言代码，默认 "zh"
 */
class WhisperEngine(
    private val httpUrl: String,
    private val model: String = "whisper-1",
    private val language: String = "zh",
) : AsrEngine {

    override val name: String = "WhisperEngine"

    private val scope = CoroutineScope(Dispatchers.IO)
    private val sessionChannels = ConcurrentHashMap<String, Channel<AsrResult>>()
    private val sessionBuffers = ConcurrentHashMap<String, MutableList<ByteArray>>()

    private val httpClient = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .writeTimeout(60, TimeUnit.SECONDS)
        .build()

    override fun isAvailable(): Boolean = httpUrl.isNotBlank()

    override fun startSession(): String {
        val sessionId = UUID.randomUUID().toString()
        sessionChannels[sessionId] = Channel(Channel.BUFFERED)
        sessionBuffers[sessionId] = mutableListOf()
        Log.d(TAG, "Session started: $sessionId")
        return sessionId
    }

    /** 将 PCM 帧追加到缓冲区，endSession 时批量上传 */
    override fun sendAudio(sessionId: String, audio: ByteArray) {
        sessionBuffers[sessionId]?.add(audio)
    }

    override fun observe(sessionId: String): Flow<AsrResult> {
        val channel = sessionChannels[sessionId]
            ?: Channel<AsrResult>(Channel.BUFFERED).also { sessionChannels[sessionId] = it }
        return channel.receiveAsFlow()
    }

    override fun endSession(sessionId: String) {
        val channel = sessionChannels[sessionId] ?: return
        val buffers = sessionBuffers.remove(sessionId) ?: emptyList<ByteArray>()

        if (buffers.isEmpty()) {
            channel.close()
            sessionChannels.remove(sessionId)
            return
        }

        // 合并所有 PCM 帧后上传
        scope.launch {
            val pcm = merge(buffers)
            transcribe(sessionId, pcm, channel)
            channel.close()
            sessionChannels.remove(sessionId)
        }
        Log.d(TAG, "Session ended: $sessionId (${buffers.size} frames queued for upload)")
    }

    // ── Private ───────────────────────────────────────────────────────────

    private fun merge(buffers: List<ByteArray>): ByteArray {
        val total = buffers.sumOf { it.size }
        val out = ByteArray(total)
        var offset = 0
        for (buf in buffers) {
            buf.copyInto(out, offset)
            offset += buf.size
        }
        return out
    }

    private fun transcribe(sessionId: String, pcm: ByteArray, channel: Channel<AsrResult>) {
        // Whisper 接受 WAV 格式；这里构造最小 WAV header 包裹 PCM
        val wav = buildWavBytes(pcm)

        val body = wav.toRequestBody("audio/wav".toMediaType())
        val request = Request.Builder()
            .url(httpUrl)
            .post(body)
            .header("Content-Type", "audio/wav")
            .build()

        runCatching {
            httpClient.newCall(request).execute().use { response ->
                if (!response.isSuccessful) {
                    channel.trySend(AsrResult.Error(response.code, "Whisper HTTP ${response.code}"))
                    return
                }
                val json = response.body?.string() ?: ""
                val text = JSONObject(json).optString("text", "").trim()
                if (text.isNotBlank()) {
                    channel.trySend(AsrResult.Final(text))
                    Log.d(TAG, "Transcription: $text")
                }
            }
        }.onFailure { e ->
            Log.e(TAG, "Whisper request failed session=$sessionId", e)
            channel.trySend(AsrResult.Error(-1, "Whisper request failed: ${e.message}"))
        }
    }

    /**
     * 构造 PCM → WAV 字节流（16kHz, 16-bit, mono）
     */
    private fun buildWavBytes(pcm: ByteArray): ByteArray {
        val channels = 1
        val sampleRate = 16_000
        val bitsPerSample = 16
        val byteRate = sampleRate * channels * bitsPerSample / 8
        val blockAlign = channels * bitsPerSample / 8
        val dataSize = pcm.size
        val headerSize = 44
        val totalSize = headerSize + dataSize

        return ByteArray(totalSize).also { wav ->
            fun Int.le4(offset: Int) {
                wav[offset] = (this and 0xff).toByte()
                wav[offset + 1] = (this shr 8 and 0xff).toByte()
                wav[offset + 2] = (this shr 16 and 0xff).toByte()
                wav[offset + 3] = (this shr 24 and 0xff).toByte()
            }
            fun Int.le2(offset: Int) {
                wav[offset] = (this and 0xff).toByte()
                wav[offset + 1] = (this shr 8 and 0xff).toByte()
            }
            "RIFF".toByteArray().copyInto(wav, 0)
            (totalSize - 8).le4(4)
            "WAVE".toByteArray().copyInto(wav, 8)
            "fmt ".toByteArray().copyInto(wav, 12)
            16.le4(16)               // subchunk1 size
            1.le2(20)                // PCM format
            channels.le2(22)
            sampleRate.le4(24)
            byteRate.le4(28)
            blockAlign.le2(32)
            bitsPerSample.le2(34)
            "data".toByteArray().copyInto(wav, 36)
            dataSize.le4(40)
            pcm.copyInto(wav, 44)
        }
    }

    private companion object {
        const val TAG = "WhisperEngine"
    }
}
