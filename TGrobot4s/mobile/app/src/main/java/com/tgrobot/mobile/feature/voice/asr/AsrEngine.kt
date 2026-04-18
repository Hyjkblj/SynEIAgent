package com.tgrobot.mobile.feature.voice.asr

import kotlinx.coroutines.flow.Flow

/**
 * ASR 引擎接口
 *
 * 可插拔的语音识别后端。每个实现对应一种识别方案（系统、FunASR、Whisper、Vosk 等）。
 * 引擎之间可在运行时通过 [AsrRouter] 切换，业务层无需改动。
 */
interface AsrEngine {
    /** 引擎唯一名称，用于注册和路由 */
    val name: String

    /**
     * 判断当前引擎是否可用（服务在线、库已加载等）
     */
    fun isAvailable(): Boolean

    /**
     * 开启一个识别会话
     *
     * @return 会话 ID，用于后续音频投递和结果订阅
     */
    fun startSession(): String

    /**
     * 向指定会话投递 PCM 音频帧
     *
     * @param sessionId [startSession] 返回的 ID
     * @param audio     16kHz / 16-bit / mono PCM 数据
     */
    fun sendAudio(sessionId: String, audio: ByteArray)

    /**
     * 订阅识别结果流
     *
     * @param sessionId [startSession] 返回的 ID
     * @return [AsrResult] 流（Partial / Final / Error）
     */
    fun observe(sessionId: String): Flow<AsrResult>

    /**
     * 结束并释放指定会话
     *
     * @param sessionId [startSession] 返回的 ID
     */
    fun endSession(sessionId: String)
}
