package com.tgrobot.mobile.feature.voice

import android.content.Context
import com.tgrobot.mobile.domain.usecase.ProcessVoiceIntentUseCase
import com.tgrobot.mobile.domain.usecase.VoiceIntentResult
import com.tgrobot.mobile.feature.voice.asr.AsrResult
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancel
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
 * 语音模块（重构版）
 *
 * 作为语音功能的统一业务入口，向上对 TeleopCoordinator 暴露简洁 API，
 * 向下通过 [VoicePipelineController] 协调采集和识别。
 *
 * 支持两种工作模式（由构造方式决定）：
 *
 * 1. **Pipeline 模式（推荐）** —— 传入 [pipeline] 参数，使用 ASR 可插拔架构
 *    （[com.tgrobot.mobile.feature.voice.adapter.AospVoiceAdapter] +
 *    [com.tgrobot.mobile.feature.voice.asr.AsrRouter]）。
 *
 * 2. **Legacy 模式（兼容）** —— 不传 [pipeline]，退回使用内置 [VoiceController]，
 *    行为与重构前完全一致，可用于渐进迁移。
 *
 * 对外暴露：
 * - [state]          语音模块当前状态
 * - [events]         识别事件（完成 / 错误 / 权限拒绝）
 * - [commandResults] 处理后的语音意图结果
 *
 * API 与重构前完全兼容，[TeleopCoordinator] 无需任何修改。
 */
class VoiceModule(
    context: Context,
    private val processVoiceIntentUseCase: ProcessVoiceIntentUseCase,
    private val locale: Locale = Locale.CHINA,
    private val scope: CoroutineScope = CoroutineScope(Dispatchers.Default),
    /** 新架构流程编排器；为 null 时使用 Legacy VoiceController */
    private val pipeline: VoicePipelineController? = null,
) {
    // Legacy 兼容控制器（pipeline 为 null 时启用）
    private val legacyController: VoiceController? =
        if (pipeline == null) VoiceController(context, locale) else null

    private val _state = MutableStateFlow(VoiceModuleState())
    val state: StateFlow<VoiceModuleState> = _state.asStateFlow()

    private val _events = MutableSharedFlow<VoiceModuleEvent>(extraBufferCapacity = 32)
    val events: SharedFlow<VoiceModuleEvent> = _events.asSharedFlow()

    private val _commandResults = MutableSharedFlow<VoiceIntentResult>(extraBufferCapacity = 32)
    val commandResults: SharedFlow<VoiceIntentResult> = _commandResults.asSharedFlow()

    private var processJob: Job? = null

    init {
        if (pipeline != null) {
            observePipeline()
            _state.update { it.copy(isAvailable = true) }
        } else {
            observeLegacyController()
        }
    }

    // ── Public API ────────────────────────────────────────────────────────

    /**
     * 开始语音监听
     *
     * @return 是否成功启动
     */
    fun startListening(): Boolean {
        _state.update { it.copy(error = null) }
        return if (pipeline != null) {
            val ok = pipeline.start()
            if (ok) _state.update { it.copy(isListening = true) }
            ok
        } else {
            legacyController?.startListening() ?: false
        }
    }

    /**
     * 停止语音监听
     */
    fun stopListening() {
        if (pipeline != null) {
            pipeline.stop()
            _state.update { it.copy(isListening = false) }
        } else {
            legacyController?.stopListening()
        }
    }

    /**
     * 取消语音监听（不等待识别结果）
     */
    fun cancelListening() {
        if (pipeline != null) {
            pipeline.stop()
            _state.update { it.copy(isListening = false, partialText = "") }
        } else {
            legacyController?.cancelListening()
            _state.update { it.copy(isListening = false, partialText = "") }
        }
    }

    /**
     * 释放资源
     */
    fun release() {
        pipeline?.release() ?: legacyController?.release()
        processJob?.cancel()
        scope.cancel()
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

    // ── Pipeline Mode ─────────────────────────────────────────────────────

    private fun observePipeline() {
        scope.launch {
            pipeline!!.results.collect { asrResult ->
                when (asrResult) {
                    is AsrResult.Partial -> {
                        _state.update { it.copy(partialText = asrResult.text) }
                    }
                    is AsrResult.Final -> {
                        val text = asrResult.text.trim()
                        _state.update {
                            it.copy(
                                isListening = false,
                                partialText = "",
                                lastText = text,
                                error = null,
                            )
                        }
                        if (text.isNotBlank()) {
                            _events.tryEmit(VoiceModuleEvent.RecognitionComplete(text))
                            processVoiceIntent(text)
                        }
                    }
                    is AsrResult.Error -> {
                        val isRecoverable = asrResult.code == ASR_ERROR_NO_MATCH ||
                            asrResult.code == ASR_ERROR_SPEECH_TIMEOUT
                        _state.update {
                            it.copy(
                                isListening = false,
                                error = if (isRecoverable) null else asrResult.message,
                            )
                        }
                        _events.tryEmit(
                            VoiceModuleEvent.RecognitionError(
                                message = asrResult.message,
                                code = asrResult.code,
                                isRecoverable = isRecoverable,
                            ),
                        )
                    }
                }
            }
        }
    }

    // ── Legacy Mode ───────────────────────────────────────────────────────

    private fun observeLegacyController() {
        scope.launch {
            legacyController!!.state.collect { controllerState ->
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
            legacyController!!.events.collect { event ->
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
                        if (!event.isRecoverable) {
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

    // ── Common ────────────────────────────────────────────────────────────

    private fun processVoiceIntent(text: String) {
        processJob?.cancel()
        processJob = scope.launch {
            val result = processVoiceIntentUseCase(text)
            _commandResults.tryEmit(result)
        }
    }

    private companion object {
        // SpeechRecognizer error codes
        const val ASR_ERROR_NO_MATCH = 7
        const val ASR_ERROR_SPEECH_TIMEOUT = 6
    }
}
