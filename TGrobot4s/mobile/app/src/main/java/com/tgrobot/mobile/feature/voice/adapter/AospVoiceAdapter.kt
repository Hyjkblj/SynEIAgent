package com.tgrobot.mobile.feature.voice.adapter

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.util.Log
import androidx.core.content.ContextCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * 标准 AOSP 音频采集适配器
 *
 * 使用 [AudioRecord] 采集 16kHz / 16-bit / mono PCM 数据。
 * 适用于标准 Android 设备（Pixel、三星、OPPO/VIVO 等）。
 *
 * 要求：AndroidManifest.xml 声明 `RECORD_AUDIO` 权限，且运行时已授权。
 */
class AospVoiceAdapter(
    private val context: Context,
    override val audioConfig: AudioConfig = AudioConfig(),
) : VoiceAdapter {

    private var audioRecord: AudioRecord? = null
    private var recordingJob: Job? = null
    private val scope = CoroutineScope(Dispatchers.IO)

    override fun isAvailable(): Boolean {
        return ContextCompat.checkSelfPermission(
            context,
            Manifest.permission.RECORD_AUDIO,
        ) == PackageManager.PERMISSION_GRANTED
    }

    override fun startRecording(onAudio: (ByteArray) -> Unit) {
        if (!isAvailable()) {
            Log.w(TAG, "RECORD_AUDIO permission not granted, cannot start recording")
            return
        }
        stopRecording() // 防止重复开启

        val frameBytes = maxOf(audioConfig.frameBytes, MIN_FRAME_BYTES)
        val bufferSize = AudioRecord.getMinBufferSize(
            audioConfig.sampleRateHz,
            CHANNEL_CONFIG,
            AUDIO_FORMAT,
        ).let { min ->
            if (min <= 0) frameBytes else maxOf(min, frameBytes)
        }

        val record = runCatching {
            AudioRecord(
                MediaRecorder.AudioSource.VOICE_RECOGNITION,
                audioConfig.sampleRateHz,
                CHANNEL_CONFIG,
                AUDIO_FORMAT,
                bufferSize,
            )
        }.onFailure { e ->
            Log.e(TAG, "Failed to create AudioRecord", e)
        }.getOrNull()

        if (record == null || record.state != AudioRecord.STATE_INITIALIZED) {
            Log.e(TAG, "AudioRecord initialization failed")
            record?.release()
            return
        }

        audioRecord = record
        record.startRecording()
        Log.d(TAG, "AudioRecord started (bufferSize=$bufferSize)")

        recordingJob = scope.launch {
            val buffer = ByteArray(frameBytes)
            while (isActive) {
                val read = record.read(buffer, 0, buffer.size)
                if (read > 0) {
                    onAudio(buffer.copyOf(read))
                } else if (read < 0) {
                    Log.w(TAG, "AudioRecord read error: $read")
                    break
                }
            }
        }
    }

    override fun stopRecording() {
        recordingJob?.cancel()
        recordingJob = null
        runCatching {
            audioRecord?.stop()
        }.onFailure { e ->
            Log.w(TAG, "AudioRecord stop error", e)
        }
        Log.d(TAG, "AudioRecord stopped")
    }

    override fun release() {
        stopRecording()
        runCatching {
            audioRecord?.release()
        }.onFailure { e ->
            Log.w(TAG, "AudioRecord release error", e)
        }
        audioRecord = null
        Log.d(TAG, "AudioRecord released")
    }

    private companion object {
        const val TAG = "AospVoiceAdapter"
        const val CHANNEL_CONFIG = AudioFormat.CHANNEL_IN_MONO
        const val AUDIO_FORMAT = AudioFormat.ENCODING_PCM_16BIT
        const val MIN_FRAME_BYTES = 3_200
    }
}
