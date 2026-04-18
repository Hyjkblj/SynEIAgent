package com.tgrobot.mobile.feature.voice.asr

import android.content.Context
import android.util.Log

/**
 * Registers ASR engines based on [VoiceEngineConfig].
 */
class VoiceEngineBootstrap(
    private val context: Context,
    private val registry: AsrRegistry = AsrRegistry,
) {
    fun register(config: VoiceEngineConfig = VoiceEngineConfig.fromBuildConfig()) {
        registry.clear()
        registry.register(SystemAsrEngine(context))

        if (config.enableVolcAsr) {
            if (config.volcAppKey.isBlank() || config.volcAccessKey.isBlank() || config.volcResourceId.isBlank()) {
                Log.w(
                    TAG,
                    "VOICE_ENABLE_VOLC_ASR=true but app/access/resource key is missing, skip VolcAsrEngine",
                )
            } else {
                registry.register(
                    VolcAsrEngine(
                        appKey = config.volcAppKey,
                        accessKey = config.volcAccessKey,
                        resourceId = config.volcResourceId,
                        wsUrl = config.volcWsUrl,
                        language = config.volcLanguage,
                        enableItn = config.volcEnableItn,
                        enablePunc = config.volcEnablePunc,
                        enableDdc = config.volcEnableDdc,
                        enableNonstream = config.volcEnableNonstream,
                        resultType = config.volcResultType,
                        endWindowSizeMs = config.volcEndWindowSizeMs,
                    ),
                )
            }
        }

        if (config.enableFunAsr && config.funAsrWsUrl.isNotBlank()) {
            registry.register(FunAsrEngine(config.funAsrWsUrl))
        }

        if (config.enableWhisper && config.whisperHttpUrl.isNotBlank()) {
            registry.register(
                WhisperEngine(
                    httpUrl = config.whisperHttpUrl,
                    model = config.whisperModel,
                    language = config.whisperLanguage,
                ),
            )
        }

        if (config.enableVosk && config.voskModelPath.isNotBlank()) {
            registry.register(VoskEngine(modelPath = config.voskModelPath))
        }

        Log.d(
            TAG,
            "ASR engines registered: ${registry.all().map { it.name }} (overrideMode=${config.overrideMode})",
        )
    }

    companion object {
        private const val TAG = "VoiceEngineBootstrap"
    }
}
