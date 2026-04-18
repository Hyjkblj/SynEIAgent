package com.tgrobot.mobile.feature.voice.policy

import android.content.Context
import android.os.Build
import android.util.Log

/**
 * ASR 模式枚举
 *
 * 决定优先使用哪类识别引擎。
 */
enum class AsrMode {
    /** 优先使用系统 SpeechRecognizer */
    SYSTEM,

    /** 优先使用自建云端 ASR（FunASR 等） */
    CLOUD,

    /** 优先使用离线引擎（Vosk / Whisper 本地） */
    OFFLINE,

    /** 自动选择：依赖 [DevicePolicy] 策略 */
    AUTO,
}

/**
 * 设备策略
 *
 * 根据设备厂商、Android 版本、网络状态等因素推断最佳 ASR 模式。
 * 供 [com.tgrobot.mobile.feature.voice.asr.AsrRouter] 使用。
 */
class DevicePolicy(private val context: Context) {

    /** 当前设备的推荐 ASR 模式 */
    val preferredMode: AsrMode
        get() {
            // 优先使用云端 ASR（火山引擎）
            return AsrMode.CLOUD
        }

    /**
     * 返回该设备上推荐的引擎名称优先级列表
     *
     * 列表中第一个可用的引擎将被 [com.tgrobot.mobile.feature.voice.asr.AsrRouter] 选中。
     */
    fun enginePriority(mode: AsrMode): List<String> {
        return when (mode) {
            AsrMode.SYSTEM -> listOf("SystemAsrEngine", "VolcAsrEngine", "FunAsrEngine", "VoskEngine")
            AsrMode.CLOUD -> listOf("VolcAsrEngine", "FunAsrEngine", "SystemAsrEngine", "VoskEngine")
            AsrMode.OFFLINE -> listOf("VoskEngine", "WhisperEngine", "SystemAsrEngine")
            AsrMode.AUTO -> enginePriority(preferredMode)
        }
    }

    private companion object {
        const val TAG = "DevicePolicy"
    }
}
