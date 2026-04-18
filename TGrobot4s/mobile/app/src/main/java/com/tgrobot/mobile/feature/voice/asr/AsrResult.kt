package com.tgrobot.mobile.feature.voice.asr

/**
 * ASR 识别结果
 *
 * 密封类，覆盖识别的所有阶段：中间结果、最终结果、错误。
 */
sealed class AsrResult {
    /** 统一文本字段；错误结果固定为空字符串 */
    abstract val text: String

    /** 中间识别结果（流式，可能变化） */
    data class Partial(override val text: String) : AsrResult()

    /** 最终识别结果（本次识别结束） */
    data class Final(override val text: String) : AsrResult()

    /** 识别错误 */
    data class Error(val code: Int, val message: String) : AsrResult() {
        override val text: String = ""
    }

    /** 是否为最终结果 */
    val isFinal: Boolean get() = this is Final
}
