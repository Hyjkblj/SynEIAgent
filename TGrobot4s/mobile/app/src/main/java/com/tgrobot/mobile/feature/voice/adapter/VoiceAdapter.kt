package com.tgrobot.mobile.feature.voice.adapter

/**
 * 音频采集适配器接口
 *
 * 屏蔽厂商差异，统一音频 PCM 数据采集方式。
 * 业务层只调用此接口，不关心底层录音实现。
 */
interface VoiceAdapter {
    /**
     * 采集参数配置
     */
    val audioConfig: AudioConfig
        get() = AudioConfig()

    /**
     * 判断当前设备是否支持音频采集
     */
    fun isAvailable(): Boolean

    /**
     * 开始录音
     *
     * @param onAudio 每帧 PCM 数据回调（由 [audioConfig] 定义）
     */
    fun startRecording(onAudio: (ByteArray) -> Unit)

    /**
     * 停止录音（等待当前帧处理完毕）
     */
    fun stopRecording()

    /**
     * 释放底层资源
     */
    fun release()
}
