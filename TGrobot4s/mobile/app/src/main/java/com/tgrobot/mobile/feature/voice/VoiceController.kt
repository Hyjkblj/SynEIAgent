package com.tgrobot.mobile.feature.voice

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognitionService
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.util.Log
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
    data class Error(
        val message: String,
        val code: Int,
        val isRecoverable: Boolean = false,
    ) : VoiceControllerEvent
}

class VoiceController(
    context: Context,
    private val locale: Locale = Locale.CHINA,
) {
    private val appContext = context.applicationContext
    private var speechRecognizer: SpeechRecognizer? = null

    private val _state = MutableStateFlow(
        VoiceControllerState(isAvailable = false),
    )
    val state: StateFlow<VoiceControllerState> = _state.asStateFlow()

    private val _events = MutableSharedFlow<VoiceControllerEvent>(extraBufferCapacity = 32)
    val events: SharedFlow<VoiceControllerEvent> = _events.asSharedFlow()

    private val recognitionListener = object : RecognitionListener {
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
            val recoverable = error == SpeechRecognizer.ERROR_NO_MATCH ||
                error == SpeechRecognizer.ERROR_SPEECH_TIMEOUT
            val message = mapError(error)
            Log.w(TAG, "SpeechRecognizer error code=$error message=$message recoverable=$recoverable")
            _events.tryEmit(
                VoiceControllerEvent.Error(
                    message = message,
                    code = error,
                    isRecoverable = recoverable,
                ),
            )
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
    }

    init {
        refreshRecognizer()
    }

    fun startListening(): Boolean {
        refreshRecognizer()
        val recognizer = speechRecognizer
        if (recognizer == null) {
            _events.tryEmit(
                VoiceControllerEvent.Error(
                    message = "SpeechRecognizer unavailable on this device",
                    code = -2,
                    isRecoverable = false,
                ),
            )
            return false
        }
        if (_state.value.isListening) {
            return true
        }
        return runCatching {
            recognizer.startListening(createRecognizerIntent())
            true
        }.getOrElse { error ->
            val message = "Start voice failed: ${error.message ?: "unknown"}"
            Log.e(TAG, message, error)
            _events.tryEmit(
                VoiceControllerEvent.Error(
                    message = message,
                    code = -1,
                    isRecoverable = false,
                ),
            )
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
        speechRecognizer = null
        _state.value = _state.value.copy(isAvailable = false, isListening = false, partialText = "")
    }

    private fun refreshRecognizer() {
        if (speechRecognizer != null) {
            _state.value = _state.value.copy(isAvailable = true)
            return
        }
        speechRecognizer = createRecognizer()
        speechRecognizer?.setRecognitionListener(recognitionListener)
        _state.value = _state.value.copy(isAvailable = speechRecognizer != null)
    }

    private fun createRecognizer(): SpeechRecognizer? {
        val recognizerService = findRecognitionServiceComponent()
        if (recognizerService == null && !SpeechRecognizer.isRecognitionAvailable(appContext)) {
            Log.w(TAG, "No recognition service available")
            return null
        }
        return runCatching {
            if (recognizerService != null) {
                Log.i(TAG, "Using recognizer service: ${recognizerService.flattenToShortString()}")
                SpeechRecognizer.createSpeechRecognizer(appContext, recognizerService)
            } else {
                SpeechRecognizer.createSpeechRecognizer(appContext)
            }
        }.onFailure { error ->
            Log.e(TAG, "Create SpeechRecognizer failed", error)
        }.getOrNull()
    }

    private fun findRecognitionServiceComponent(): ComponentName? {
        val intent = Intent(RecognitionService.SERVICE_INTERFACE)
        val services = runCatching {
            appContext.packageManager.queryIntentServices(intent, PackageManager.MATCH_DEFAULT_ONLY)
        }.getOrElse {
            emptyList()
        }

        val serviceInfo = services.firstOrNull()?.serviceInfo ?: return null
        return ComponentName(serviceInfo.packageName, serviceInfo.name)
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

    private companion object {
        const val TAG = "VoiceController"
    }
}
