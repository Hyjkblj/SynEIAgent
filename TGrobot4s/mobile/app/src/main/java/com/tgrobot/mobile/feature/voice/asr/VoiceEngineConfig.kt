package com.tgrobot.mobile.feature.voice.asr

import com.tgrobot.mobile.BuildConfig
import com.tgrobot.mobile.feature.voice.policy.AsrMode

/**
 * Runtime configuration for voice ASR engines.
 *
 * Values are loaded from BuildConfig fields so deployment can be adjusted via
 * Gradle properties without touching source code.
 */
data class VoiceEngineConfig(
    val enableVolcAsr: Boolean,
    val volcWsUrl: String,
    val volcAppKey: String,
    val volcAccessKey: String,
    val volcResourceId: String,
    val volcLanguage: String,
    val volcEnableItn: Boolean,
    val volcEnablePunc: Boolean,
    val volcEnableDdc: Boolean,
    val volcEnableNonstream: Boolean,
    val volcResultType: String,
    val volcEndWindowSizeMs: Int,
    val enableFunAsr: Boolean,
    val funAsrWsUrl: String,
    val enableWhisper: Boolean,
    val whisperHttpUrl: String,
    val whisperModel: String,
    val whisperLanguage: String,
    val enableVosk: Boolean,
    val voskModelPath: String,
    val overrideMode: AsrMode?,
) {
    companion object {
        fun fromBuildConfig(): VoiceEngineConfig {
            return VoiceEngineConfig(
                enableVolcAsr = BuildConfig.VOICE_ENABLE_VOLC_ASR,
                volcWsUrl = BuildConfig.VOICE_VOLC_WS_URL.trim()
                    .ifBlank { VolcAsrEngine.DEFAULT_WS_URL },
                volcAppKey = BuildConfig.VOICE_VOLC_APP_KEY.trim(),
                volcAccessKey = BuildConfig.VOICE_VOLC_ACCESS_KEY.trim(),
                volcResourceId = BuildConfig.VOICE_VOLC_RESOURCE_ID.trim(),
                volcLanguage = BuildConfig.VOICE_VOLC_LANGUAGE.trim().ifBlank { "zh-CN" },
                volcEnableItn = BuildConfig.VOICE_VOLC_ENABLE_ITN,
                volcEnablePunc = BuildConfig.VOICE_VOLC_ENABLE_PUNC,
                volcEnableDdc = BuildConfig.VOICE_VOLC_ENABLE_DDC,
                volcEnableNonstream = BuildConfig.VOICE_VOLC_ENABLE_NONSTREAM,
                volcResultType = BuildConfig.VOICE_VOLC_RESULT_TYPE.trim().ifBlank { "full" },
                volcEndWindowSizeMs = BuildConfig.VOICE_VOLC_END_WINDOW_SIZE_MS.coerceAtLeast(200),
                enableFunAsr = BuildConfig.VOICE_ENABLE_FUN_ASR,
                funAsrWsUrl = BuildConfig.VOICE_FUN_ASR_WS_URL.trim(),
                enableWhisper = BuildConfig.VOICE_ENABLE_WHISPER,
                whisperHttpUrl = BuildConfig.VOICE_WHISPER_HTTP_URL.trim(),
                whisperModel = BuildConfig.VOICE_WHISPER_MODEL.trim().ifBlank { "whisper-1" },
                whisperLanguage = BuildConfig.VOICE_WHISPER_LANGUAGE.trim().ifBlank { "zh" },
                enableVosk = BuildConfig.VOICE_ENABLE_VOSK,
                voskModelPath = BuildConfig.VOICE_VOSK_MODEL_PATH.trim(),
                overrideMode = parseMode(BuildConfig.VOICE_ASR_MODE_OVERRIDE),
            )
        }

        private fun parseMode(raw: String): AsrMode? {
            val value = raw.trim().uppercase()
            if (value.isBlank() || value == "NONE" || value == "DISABLED") {
                return null
            }
            return runCatching { AsrMode.valueOf(value) }.getOrNull()
        }
    }
}
