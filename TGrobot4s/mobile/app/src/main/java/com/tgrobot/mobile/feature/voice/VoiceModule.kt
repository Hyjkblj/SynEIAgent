package com.tgrobot.mobile.feature.voice

import android.content.Context
import com.tgrobot.mobile.domain.usecase.ProcessVoiceIntentUseCase
import com.tgrobot.mobile.domain.usecase.VoiceIntentResult
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.util.Locale

/**
 * 语音模块
 * 
 * 封装语音识别和意图处理的完整流程。
 * 将语音控制从 TeleopViewModel 中独立出来。
 * 
 * 职责：
 * - 管理语音识别生命周期
 * - 处理语音意图
 * - 发送语音命令结果
 */
class VoiceModule(
    context: Context,
    private val processVoiceIntentUseCase: ProcessVoiceIntentUseCase,
    private val locale: Locale = Locale.CHINA,
    private val scope: CoroutineScope = CoroutineScope(Dispatchers.Default),
) {
    private val voiceController = VoiceController(context, locale)

    private val _state = MutableStateFlow(VoiceModuleState())
    val state: StateFlow<VoiceModuleState> = _state.asStateFlow()

    private val _events = MutableSharedFlow<VoiceModuleEvent>(extraBufferCapacity = 32)
    val events: SharedFlow<VoiceModuleEvent> = _events.asSharedFlow()

    private val _commandResults = MutableSharedFlow<VoiceIntentResult>(extraBufferCapacity = 32)
    val commandResults: SharedFlow<VoiceIntentResult> = _commandResults.asSharedFlow()

    private var processJob: Job? = null

    init {
        observeVoiceController()
    }

    /**
     * 开始语音监听
     * 
     * @return 是否成功开始
     */
    fun startListening(): Boolean {
        _state.update { it.copy(error = null) }
        return voiceController.startListening()
    }

    /**
     * 停止语音监听
     */
    fun stopListening() {
        voiceController.stopListening()
    }

    /**
     * 取消语音监听
     */
    fun cancelListening() {
        voiceController.cancelListening()
        _state.update { it.copy(isListening = false, partialText = "") }
    }

    /**
     * 释放资源
     */
    fun release() {
        voiceController.release()
        processJob?.cancel()
    }

    private fun observeVoiceController() {
        scope.launch {
            voiceController.state.collect { controllerState ->
                _state.update {
                    it.copy(
                        isAvailable = controllerState.isAvailable,
                        isListening = controllerState.isListening,
                        partialText = controllerState.partialText,
                    )
                }
            }
        }

        scope.launch {
            voiceController.events.collect { event ->
                when (event) {
                    is VoiceControllerEvent.FinalText -> {
                        val text = event.text.trim()
                        if (text.isNotBlank()) {
                            _state.update { it.copy(lastText = text, error = null) }
                            _events.tryEmit(VoiceModuleEvent.RecognitionComplete(text))
                            processVoiceIntent(text)
                        }
                    }

                    is VoiceControllerEvent.Error -> {
                        _state.update { it.copy(isListening = false) }
                        if (event.isRecoverable) {
                            _state.update { it.copy(error = null) }
                        } else {
                            _state.update { it.copy(error = event.message) }
                        }
                        _events.tryEmit(
                            VoiceModuleEvent.RecognitionError(
                                message = event.message,
                                code = event.code,
                                isRecoverable = event.isRecoverable,
                            ),
                        )
                    }
                }
            }
        }
    }

    private fun processVoiceIntent(text: String) {
        processJob?.cancel()
        processJob = scope.launch {
            val result = processVoiceIntentUseCase(text)
            _commandResults.tryEmit(result)
        }
    }

    /**
     * 获取语音独占窗口时长
     * 
     * @param result 语音意图结果
     * @return 独占窗口时长（毫秒）
     */
    fun getVoiceExclusiveWindowMs(result: VoiceIntentResult): Long {
        return processVoiceIntentUseCase.getVoiceExclusiveWindowMs(result)
    }
}
