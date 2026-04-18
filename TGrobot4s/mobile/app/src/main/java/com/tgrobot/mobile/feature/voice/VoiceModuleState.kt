package com.tgrobot.mobile.feature.voice

/**
 * 语音模块状态
 * 
 * @param isAvailable 语音识别是否可用
 * @param isListening 是否正在监听
 * @param partialText 部分识别文本
 * @param lastText 最后识别的完整文本
 * @param error 错误信息
 */
data class VoiceModuleState(
    val isAvailable: Boolean = true,
    val isListening: Boolean = false,
    val partialText: String = "",
    val lastText: String = "",
    val error: String? = null,
)
