package com.tgrobot.mobile.feature.voice.asr

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.util.Log
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.receiveAsFlow
import java.util.Locale
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap

/**
 * 系统 ASR 引擎
 *
 * 将 Android [SpeechRecognizer] 封装为 [AsrEngine]，适配 ASR 可插拔架构。
 * 适用于标准 AOSP 设备，兼容 Android 8.0+（API 26+）。
 *
 * 注意：[SpeechRecognizer] 要求在主线程创建和调用；本实现通过
 * [android.os.Handler] 将调用 Marshal 到主线程。
 *
 * 对于 VoicePipelineController 模式（PCM → ASR），系统引擎直接使用
 * SpeechRecognizer.startListening() 内置麦克风采集，因此 sendAudio() 为空实现。
 */
class SystemAsrEngine(
    private val context: Context,
    private val locale: Locale = Locale.CHINA,
) : AsrEngine {

    override val name: String = "SystemAsrEngine"

    private val sessionChannels = ConcurrentHashMap<String, Channel<AsrResult>>()
    private var activeSpeechRecognizer: SpeechRecognizer? = null
    private var activeSessionId: String? = null

    override fun isAvailable(): Boolean {
        return SpeechRecognizer.isRecognitionAvailable(context)
    }

    override fun startSession(): String {
        val sessionId = UUID.randomUUID().toString()
        val channel = Channel<AsrResult>(capacity = Channel.BUFFERED)
        sessionChannels[sessionId] = channel

        // 在主线程创建并启动 SpeechRecognizer
        android.os.Handler(android.os.Looper.getMainLooper()).post {
            startSpeechRecognizer(sessionId, channel)
        }

        Log.d(TAG, "Session started: $sessionId")
        return sessionId
    }

    /**
     * SystemAsrEngine 使用内置麦克风，PCM 投递为空实现。
     * FunAsrEngine / VoskEngine 会真正使用此方法。
     */
    override fun sendAudio(sessionId: String, audio: ByteArray) = Unit

    override fun observe(sessionId: String): Flow<AsrResult> {
        val channel = sessionChannels[sessionId]
            ?: Channel<AsrResult>(Channel.BUFFERED).also { sessionChannels[sessionId] = it }
        return channel.receiveAsFlow()
    }

    override fun endSession(sessionId: String) {
        if (activeSessionId == sessionId) {
            android.os.Handler(android.os.Looper.getMainLooper()).post {
                activeSpeechRecognizer?.destroy()
                activeSpeechRecognizer = null
                activeSessionId = null
            }
        }
        sessionChannels.remove(sessionId)?.close()
        Log.d(TAG, "Session ended: $sessionId")
    }

    // ── Internal ──────────────────────────────────────────────────────────

    private fun startSpeechRecognizer(sessionId: String, channel: Channel<AsrResult>) {
        activeSpeechRecognizer?.destroy()

        val recognizer = runCatching {
            SpeechRecognizer.createSpeechRecognizer(context)
        }.onFailure { e ->
            Log.e(TAG, "Create SpeechRecognizer failed", e)
            channel.trySend(AsrResult.Error(-1, "Create SpeechRecognizer failed: ${e.message}"))
            channel.close()
        }.getOrNull() ?: return

        activeSpeechRecognizer = recognizer
        activeSessionId = sessionId

        recognizer.setRecognitionListener(object : RecognitionListener {
            override fun onReadyForSpeech(params: Bundle?) = Unit
            override fun onBeginningOfSpeech() = Unit
            override fun onRmsChanged(rmsdB: Float) = Unit
            override fun onBufferReceived(buffer: ByteArray?) = Unit
            override fun onEndOfSpeech() = Unit

            override fun onPartialResults(partialResults: Bundle?) {
                val text = partialResults
                    ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                    ?.firstOrNull()
                    ?.trim()
                    .orEmpty()
                if (text.isNotBlank()) {
                    channel.trySend(AsrResult.Partial(text))
                }
            }

            override fun onResults(results: Bundle?) {
                val text = results
                    ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                    ?.firstOrNull()
                    ?.trim()
                if (!text.isNullOrBlank()) {
                    channel.trySend(AsrResult.Final(text))
                }
                channel.close()
                sessionChannels.remove(sessionId)
            }

            override fun onError(error: Int) {
                val recoverable = error == SpeechRecognizer.ERROR_NO_MATCH ||
                    error == SpeechRecognizer.ERROR_SPEECH_TIMEOUT
                val message = mapError(error)
                Log.w(TAG, "SpeechRecognizer error code=$error recoverable=$recoverable")
                channel.trySend(AsrResult.Error(error, message))
                if (!recoverable) {
                    channel.close()
                    sessionChannels.remove(sessionId)
                }
            }

            override fun onEvent(eventType: Int, params: Bundle?) = Unit
        })

        recognizer.startListening(buildIntent())
    }

    private fun buildIntent(): Intent {
        return Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, locale.toLanguageTag())
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 3)
            putExtra(RecognizerIntent.EXTRA_CALLING_PACKAGE, context.packageName)
            putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true)
        }
    }

    private fun mapError(code: Int): String = when (code) {
        SpeechRecognizer.ERROR_AUDIO -> "Audio capture error"
        SpeechRecognizer.ERROR_CLIENT -> "Client error"
        SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "Microphone permission denied"
        SpeechRecognizer.ERROR_NETWORK -> "Network error"
        SpeechRecognizer.ERROR_NETWORK_TIMEOUT -> "Network timeout"
        SpeechRecognizer.ERROR_NO_MATCH -> "No speech recognized"
        SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> "Recognizer busy"
        SpeechRecognizer.ERROR_SERVER -> "Speech server error"
        SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> "Speech timeout"
        else -> "Unknown error: $code"
    }

    private companion object {
        const val TAG = "SystemAsrEngine"
    }
}
