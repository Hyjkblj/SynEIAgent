package com.tgrobot.mobile.feature.voice.asr

import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.io.File
import java.util.Collections
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap

/**
 * Vosk ASR engine.
 *
 * This implementation does not require a compile-time Vosk dependency.
 * It uses reflection to call Vosk classes when the SDK is available in runtime.
 */
class VoskEngine(
    private val modelPath: String?,
    private val sampleRateHz: Float = 16_000f,
    private val scope: CoroutineScope = CoroutineScope(Dispatchers.IO),
) : AsrEngine {

    override val name: String = "VoskEngine"

    private val sessionChannels = ConcurrentHashMap<String, Channel<AsrResult>>()
    private val sessionBuffers = ConcurrentHashMap<String, MutableList<ByteArray>>()
    private val sessionJobs = ConcurrentHashMap<String, Job>()

    override fun isAvailable(): Boolean {
        val path = modelPath?.trim().orEmpty()
        return path.isNotBlank() && File(path).exists() && hasVoskSdk()
    }

    override fun startSession(): String {
        val sessionId = UUID.randomUUID().toString()
        sessionChannels[sessionId] = Channel(Channel.BUFFERED)
        sessionBuffers[sessionId] = Collections.synchronizedList(mutableListOf())
        Log.d(TAG, "Session started: $sessionId")
        return sessionId
    }

    override fun sendAudio(sessionId: String, audio: ByteArray) {
        val bufferList = sessionBuffers[sessionId] ?: return
        bufferList.add(audio.copyOf())
    }

    override fun observe(sessionId: String): Flow<AsrResult> {
        val channel = sessionChannels[sessionId]
            ?: Channel<AsrResult>(Channel.BUFFERED).also { sessionChannels[sessionId] = it }
        return channel.receiveAsFlow()
    }

    override fun endSession(sessionId: String) {
        val channel = sessionChannels[sessionId] ?: return
        val audioFrames: List<ByteArray> = sessionBuffers.remove(sessionId)?.toList() ?: emptyList()

        sessionJobs.remove(sessionId)?.cancel()

        if (!isAvailable()) {
            channel.trySend(
                AsrResult.Error(
                    code = ERROR_NOT_AVAILABLE,
                    message = "Vosk SDK unavailable or model path missing",
                ),
            )
            channel.close()
            sessionChannels.remove(sessionId)
            return
        }

        if (audioFrames.isEmpty()) {
            channel.close()
            sessionChannels.remove(sessionId)
            return
        }

        sessionJobs[sessionId] = scope.launch {
            runCatching {
                transcribe(audioFrames, channel)
            }.onFailure { error ->
                Log.e(TAG, "Vosk transcription failed (session=$sessionId)", error)
                channel.trySend(
                    AsrResult.Error(
                        code = ERROR_TRANSCRIBE_FAILED,
                        message = "Vosk transcription failed: ${error.message}",
                    ),
                )
            }

            channel.close()
            sessionChannels.remove(sessionId)
            sessionJobs.remove(sessionId)
            Log.d(TAG, "Session ended: $sessionId")
        }
    }

    private fun transcribe(frames: List<ByteArray>, channel: Channel<AsrResult>) {
        val model = createModel()
        val recognizer = createRecognizer(model)

        try {
            var lastText = ""

            for (frame in frames) {
                val accepted = invokeAcceptWaveForm(recognizer, frame)
                val json = if (accepted) invokeResult(recognizer) else invokePartialResult(recognizer)
                val text = extractText(json)
                if (text.isNotBlank()) {
                    lastText = text
                    channel.trySend(AsrResult.Partial(text))
                }
            }

            val finalText = extractText(invokeFinalResult(recognizer)).ifBlank { lastText }
            if (finalText.isNotBlank()) {
                channel.trySend(AsrResult.Final(finalText))
            } else {
                channel.trySend(
                    AsrResult.Error(
                        code = ERROR_EMPTY_RESULT,
                        message = "No speech recognized by Vosk",
                    ),
                )
            }
        } finally {
            closeQuietly(recognizer)
            closeQuietly(model)
        }
    }

    private fun hasVoskSdk(): Boolean = runCatching {
        Class.forName(VOSK_MODEL_CLASS)
        Class.forName(VOSK_RECOGNIZER_CLASS)
        true
    }.getOrDefault(false)

    private fun createModel(): Any {
        val path = modelPath?.trim().orEmpty()
        require(path.isNotBlank()) { "Vosk model path is blank" }
        val modelClass = Class.forName(VOSK_MODEL_CLASS)
        return modelClass.getConstructor(String::class.java).newInstance(path)
    }

    private fun createRecognizer(model: Any): Any {
        val recognizerClass = Class.forName(VOSK_RECOGNIZER_CLASS)
        return recognizerClass
            .getConstructor(model.javaClass, java.lang.Float.TYPE)
            .newInstance(model, sampleRateHz)
    }

    private fun invokeAcceptWaveForm(recognizer: Any, audio: ByteArray): Boolean {
        val method = recognizer.javaClass.getMethod(
            "acceptWaveForm",
            ByteArray::class.java,
            Int::class.javaPrimitiveType,
        )
        return method.invoke(recognizer, audio, audio.size) as? Boolean ?: false
    }

    private fun invokeResult(recognizer: Any): String {
        return recognizer.javaClass.getMethod("result").invoke(recognizer)?.toString().orEmpty()
    }

    private fun invokePartialResult(recognizer: Any): String {
        return recognizer.javaClass.getMethod("partialResult").invoke(recognizer)?.toString().orEmpty()
    }

    private fun invokeFinalResult(recognizer: Any): String {
        return recognizer.javaClass.getMethod("finalResult").invoke(recognizer)?.toString().orEmpty()
    }

    private fun extractText(json: String): String {
        return runCatching {
            val obj = JSONObject(json)
            obj.optString("text", "").ifBlank {
                obj.optString("partial", "")
            }.trim()
        }.getOrDefault("")
    }

    private fun closeQuietly(target: Any?) {
        if (target == null) return
        runCatching {
            target.javaClass.getMethod("close").invoke(target)
        }.onFailure {
            // no-op
        }
    }

    private companion object {
        private const val TAG = "VoskEngine"
        private const val VOSK_MODEL_CLASS = "org.vosk.Model"
        private const val VOSK_RECOGNIZER_CLASS = "org.vosk.Recognizer"

        private const val ERROR_NOT_AVAILABLE = -210
        private const val ERROR_TRANSCRIBE_FAILED = -211
        private const val ERROR_EMPTY_RESULT = -212
    }
}
