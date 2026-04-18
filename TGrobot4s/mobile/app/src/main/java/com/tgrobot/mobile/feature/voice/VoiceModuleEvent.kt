package com.tgrobot.mobile.feature.voice

/**
 * 语音模块事件
 */
sealed interface VoiceModuleEvent {
    /**
     * 语音识别完成
     * 
     * @param text 识别文本
     */
    data class RecognitionComplete(val text: String) : VoiceModuleEvent

    /**
     * 语音识别错误
     * 
     * @param message 错误消息
     * @param code 错误代码
     * @param isRecoverable 是否可恢复
     */
    data class RecognitionError(
        val message: String,
        val code: Int,
        val isRecoverable: Boolean = false,
    ) : VoiceModuleEvent

    /**
     * 权限被拒绝
     */
    data object PermissionDenied : VoiceModuleEvent
}
