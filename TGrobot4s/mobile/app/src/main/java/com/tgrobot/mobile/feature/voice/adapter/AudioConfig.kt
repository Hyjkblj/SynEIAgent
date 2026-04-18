package com.tgrobot.mobile.feature.voice.adapter

/**
 * 音频采集配置
 *
 * 默认参数与当前语音链路保持一致：16kHz / 16-bit / mono / 100ms 帧长。
 */
data class AudioConfig(
    val sampleRateHz: Int = 16_000,
    val channelCount: Int = 1,
    val bitsPerSample: Int = 16,
    val frameDurationMs: Int = 100,
) {
    val bytesPerSample: Int
        get() = bitsPerSample / 8

    val bytesPerSecond: Int
        get() = sampleRateHz * channelCount * bytesPerSample

    val frameBytes: Int
        get() = (bytesPerSecond * frameDurationMs) / 1000
}
