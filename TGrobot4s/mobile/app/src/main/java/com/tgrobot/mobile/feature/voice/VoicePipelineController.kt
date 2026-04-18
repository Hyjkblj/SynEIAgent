package com.tgrobot.mobile.feature.voice

import android.util.Log
import com.tgrobot.mobile.feature.voice.adapter.VoiceAdapter
import com.tgrobot.mobile.feature.voice.asr.AsrEngine
import com.tgrobot.mobile.feature.voice.asr.AsrResult
import com.tgrobot.mobile.feature.voice.asr.AsrRouter
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.launch

/**
 * 语音流程编排器
 *
 * 将 VoiceAdapter（音频采集）和 AsrRouter（识别路由）组合成完整的识别流程：
 *
 * ```
 * 用户说话
 *   ↓ VoiceAdapter（PCM 采集）
 *   ↓ AsrEngine.sendAudio()
 *   ↓ AsrEngine.observe()（Flow<AsrResult>）
 *   ↓ 对外暴露 results SharedFlow
 * ```
 *
 * 对于 [com.tgrobot.mobile.feature.voice.asr.SystemAsrEngine]，音频由引擎内部采集，
 * VoiceAdapter 的 PCM 回路不参与；Pipeline 仍然统一通过 AsrEngine 接口订阅结果。
 *
 * 职责：
 * - 启动/停止会话
 * - 将 PCM 帧转发给 AsrEngine
 * - 将 AsrResult 向下游暴露
 * - 正确释放资源
 */
class VoicePipelineController(
    private val adapterProvider: () -> VoiceAdapter,
    private val asrRouter: AsrRouter,
    private val scope: CoroutineScope = CoroutineScope(Dispatchers.Default),
) {
    private val _results = MutableSharedFlow<AsrResult>(extraBufferCapacity = 64)

    /** 识别结果流，下游订阅此 Flow 获取 Partial / Final / Error */
    val results: SharedFlow<AsrResult> = _results.asSharedFlow()

    private var adapter: VoiceAdapter? = null
    private var activeEngine: AsrEngine? = null
    private var currentSessionId: String? = null
    private var observeJob: Job? = null

    /** 当前是否正在识别 */
    var isActive: Boolean = false
        private set

    /**
     * 启动语音采集 + 识别会话
     *
     * @return true 启动成功，false 无可用引擎
     */
    fun start(): Boolean {
        if (isActive) {
            Log.d(TAG, "Pipeline already active, ignoring start()")
            return true
        }

        val engine = asrRouter.select()
        if (engine == null) {
            Log.e(TAG, "No ASR engine available")
            return false
        }

        val sessionId = runCatching { engine.startSession() }
            .onFailure { error ->
                Log.e(TAG, "Failed to start ASR session (engine=${engine.name})", error)
            }
            .getOrNull() ?: return false

        activeEngine = engine
        currentSessionId = sessionId
        isActive = true

        // 订阅识别结果
        observeJob = scope.launch {
            engine.observe(sessionId).collect { result ->
                _results.tryEmit(result)
                // 终态结果后关闭当前会话，允许下一次 start() 重新建立会话。
                if (result is AsrResult.Final || result is AsrResult.Error) {
                    finishSessionFromObserver()
                }
            }
        }

        // SystemAsrEngine 由系统服务自行采集麦克风，无需外部 PCM 适配器。
        if (engine.name != SYSTEM_ASR_ENGINE_NAME) {
            val voiceAdapter = adapter ?: adapterProvider().also { adapter = it }
            if (!voiceAdapter.isAvailable()) {
                _results.tryEmit(AsrResult.Error(ERROR_ADAPTER_UNAVAILABLE, "Voice adapter unavailable"))
                stop()
                return false
            }
            voiceAdapter.startRecording { pcm ->
                engine.sendAudio(sessionId, pcm)
            }
        } else {
            Log.d(TAG, "SystemAsrEngine selected: skip VoiceAdapter recording")
        }

        Log.d(TAG, "Pipeline started (engine=${engine.name}, session=$sessionId)")
        return true
    }

    /**
     * 停止语音采集和识别会话，释放相关资源
     */
    fun stop() {
        if (!isActive) return
        isActive = false
        stopAdapterOnly()
        endCurrentSession()
        Log.d(TAG, "Pipeline stopped")
    }

    /**
     * 释放所有资源（含 VoiceAdapter）
     */
    fun release() {
        stop()
        adapter?.release()
        adapter = null
    }

    // ── Private ───────────────────────────────────────────────────────────

    private fun stopAdapterOnly() {
        adapter?.stopRecording()
    }

    private fun endCurrentSession() {
        observeJob?.cancel()
        observeJob = null
        val sessionId = currentSessionId ?: return
        activeEngine?.endSession(sessionId)
        currentSessionId = null
        activeEngine = null
    }

    private fun finishSessionFromObserver() {
        if (!isActive) return
        isActive = false
        stopAdapterOnly()
        val sessionId = currentSessionId
        if (sessionId != null) {
            activeEngine?.endSession(sessionId)
        }
        currentSessionId = null
        activeEngine = null
        observeJob = null
    }

    companion object {
        private const val TAG = "VoicePipelineController"
        private const val SYSTEM_ASR_ENGINE_NAME = "SystemAsrEngine"
        private const val ERROR_ADAPTER_UNAVAILABLE = -300
    }
}
