# VOICE SYSTEM USAGE

## 1. Scope

This document describes how to initialize and use the mobile voice pipeline after the ASR refactor.

Current architecture:

```text
VoiceModule
  -> VoicePipelineController
  -> VoiceAdapter (AospVoiceAdapter / vendor adapter)
  -> AsrRouter
  -> AsrEngine (System / Volc / FunASR / Whisper / Vosk)
  -> ProcessVoiceIntentUseCase
```

## 2. Minimal Startup (System ASR)

In `MainActivity`, use `VoiceEngineBootstrap` to register engines and pass a pipeline into `VoiceModule`.

```kotlin
private val devicePolicy by lazy { DevicePolicy(applicationContext) }
private val voiceEngineConfig by lazy { VoiceEngineConfig.fromBuildConfig() }
private val asrBootstrap by lazy { VoiceEngineBootstrap(applicationContext) }
private val asrRouter by lazy {
    AsrRouter(devicePolicy = devicePolicy).apply {
        overrideMode = voiceEngineConfig.overrideMode
    }
}
private val voicePipeline by lazy {
    asrBootstrap.register(voiceEngineConfig)
    VoicePipelineController(
        adapterProvider = { AospVoiceAdapter(applicationContext) },
        asrRouter = asrRouter,
    )
}
private val voiceModule by lazy {
    VoiceModule(
        context = this,
        processVoiceIntentUseCase = processVoiceUseCase,
        pipeline = voicePipeline,
    )
}
```

## 3. Engine Configuration (`gradle.properties`)

Set engine switches and endpoints in `TGrobot4s/mobile/gradle.properties` (or user-level `~/.gradle/gradle.properties`):

```properties
voiceEnableVolcAsr=true
voiceVolcWsUrl=wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async
voiceVolcAppKey=123456789
voiceVolcAccessKey=your-access-key
voiceVolcResourceId=volc.seedasr.sauc.duration
voiceVolcLanguage=zh-CN
voiceVolcEnableItn=true
voiceVolcEnablePunc=true
voiceVolcEnableDdc=false
voiceVolcEnableNonstream=false
voiceVolcResultType=full
voiceVolcEndWindowSizeMs=800

voiceEnableFunAsr=true
voiceFunAsrWsUrl=ws://192.168.1.10:10095

voiceEnableWhisper=true
voiceWhisperHttpUrl=http://192.168.1.10:9000/v1/audio/transcriptions
voiceWhisperModel=whisper-1
voiceWhisperLanguage=zh

voiceEnableVosk=true
voiceVoskModelPath=/sdcard/models/vosk-model-cn

voiceAsrModeOverride=AUTO
```

Notes:
- `AsrRouter` selects engines by `DevicePolicy` priority and engine availability.
- `VolcAsrEngine` uses ByteDance binary WebSocket protocol and sends `X-Tt-Logid` to logs.
- `VoskEngine` uses reflection and requires Vosk SDK + local model path at runtime.
- If an engine is not available, router automatically falls back to the next candidate.
- `voiceAsrModeOverride` supports `AUTO / SYSTEM / CLOUD / OFFLINE / NONE`.

## 4. Permission and Input Requirements

- Android manifest must include `RECORD_AUDIO`.
- Runtime microphone permission must be granted before `startListening()`.
- Default audio format in `AudioConfig`: `16kHz / mono / 16-bit / 100ms frame`.

## 5. Runtime Control

Public API remains unchanged:

```kotlin
voiceModule.startListening()
voiceModule.stopListening()
voiceModule.cancelListening()
voiceModule.release()
```

Outputs:
- `voiceModule.events`: recognition complete/error events.
- `voiceModule.commandResults`: parsed intent execution results.
- `voiceModule.state`: availability/listening/partial/error state.

## 6. Integration Checklist

- Build check: `:app:compileDebugKotlin`
- Verify microphone permission flow in UI.
- Verify end-to-end path: speech -> ASR -> intent -> robot command.
- Verify fallback path by disabling the preferred engine.
- Run 30+ minutes continuous start/stop and confirm no resource leak symptoms.

## 7. Known Gaps (2026-04-17)

- `VoskEngine`: skeleton is implemented, but still needs real device model validation.
- `VolcAsrEngine`: protocol is wired, still needs real AK/SK + resource id integration test.
- `FunAsrEngine` and `WhisperEngine`: code is present, pending service-side integration test.
- Unit/integration tests are still pending in `PR-11`.
