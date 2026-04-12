package com.tgrobot.mobile.feature.voice

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import java.util.Locale

data class VoiceControllerState(
    val isAvailable: Boolean = true,
    val isListening: Boolean = false,
    val partialText: String = "",
)

sealed interface VoiceControllerEvent {
    data class FinalText(val text: String) : VoiceControllerEvent
    data class Error(val message: String) : VoiceControllerEvent
}

class VoiceController(
    context: Context,
    private val locale: Locale = Locale.CHINA,
) {
    private val appContext = context.applicationContext
    private val speechRecognizer: SpeechRecognizer? = if (SpeechRecognizer.isRecognitionAvailable(appContext)) {
        SpeechRecognizer.createSpeechRecognizer(appContext)
    } else {
        null
    }

    private val _state = MutableStateFlow(
        VoiceControllerState(isAvailable = speechRecognizer != null),
    )
    val state: StateFlow<VoiceControllerState> = _state.asStateFlow()

    private val _events = MutableSharedFlow<VoiceControllerEvent>(extraBufferCapacity = 32)
    val events: SharedFlow<VoiceControllerEvent> = _events.asSharedFlow()

    init {
        speechRecognizer?.setRecognitionListener(
            object : RecognitionListener {
                override fun onReadyForSpeech(params: Bundle?) {
                    _state.value = _state.value.copy(isListening = true, partialText = "")
                }

                override fun onBeginningOfSpeech() = Unit

                override fun onRmsChanged(rmsdB: Float) = Unit

                override fun onBufferReceived(buffer: ByteArray?) = Unit

                override fun onEndOfSpeech() {
                    _state.value = _state.value.copy(isListening = false)
                }

                override fun onError(error: Int) {
                    _state.value = _state.value.copy(isListening = false, partialText = "")
                    _events.tryEmit(VoiceControllerEvent.Error(message = mapError(error)))
                }

                override fun onResults(results: Bundle?) {
                    _state.value = _state.value.copy(isListening = false, partialText = "")
                    val text = results
                        ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                        ?.firstOrNull()
                        ?.trim()
                    if (!text.isNullOrBlank()) {
                        _events.tryEmit(VoiceControllerEvent.FinalText(text))
                    }
                }

                override fun onPartialResults(partialResults: Bundle?) {
                    val partial = partialResults
                        ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                        ?.firstOrNull()
                        ?.trim()
                        .orEmpty()
                    _state.value = _state.value.copy(partialText = partial)
                }

                override fun onEvent(eventType: Int, params: Bundle?) = Unit
            },
        )
    }

    fun startListening(): Boolean {
        val recognizer = speechRecognizer
        if (recognizer == null) {
            _events.tryEmit(VoiceControllerEvent.Error("SpeechRecognizer unavailable on this device"))
            return false
        }
        if (_state.value.isListening) {
            return true
        }
        return runCatching {
            recognizer.startListening(createRecognizerIntent())
            true
        }.getOrElse { error ->
            _events.tryEmit(VoiceControllerEvent.Error("Start voice failed: ${error.message ?: "unknown"}"))
            false
        }
    }

    fun stopListening() {
        speechRecognizer?.stopListening()
        _state.value = _state.value.copy(isListening = false)
    }

    fun cancelListening() {
        speechRecognizer?.cancel()
        _state.value = _state.value.copy(isListening = false, partialText = "")
    }

    fun release() {
        speechRecognizer?.destroy()
    }

    private fun createRecognizerIntent(): Intent {
        return Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(
                RecognizerIntent.EXTRA_LANGUAGE_MODEL,
                RecognizerIntent.LANGUAGE_MODEL_FREE_FORM,
            )
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, locale.toLanguageTag())
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 3)
            // Prefer on-device recognition when speech packs are available.
            putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true)
        }
    }

    private fun mapError(errorCode: Int): String {
        return when (errorCode) {
            SpeechRecognizer.ERROR_AUDIO -> "Audio capture error"
            SpeechRecognizer.ERROR_CLIENT -> "Client error"
            SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "Microphone permission denied"
            SpeechRecognizer.ERROR_NETWORK -> "Network error (internet or offline speech pack required)"
            SpeechRecognizer.ERROR_NETWORK_TIMEOUT -> "Network timeout (check internet/offline speech pack)"
            SpeechRecognizer.ERROR_NO_MATCH -> "No matching speech recognized"
            SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> "Recognizer busy"
            SpeechRecognizer.ERROR_SERVER -> "Speech server error (try internet or offline speech pack)"
            SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> "Speech timeout"
            else -> "Unknown speech error: $errorCode"
        }
    }
}
