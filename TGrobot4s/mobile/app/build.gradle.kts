plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

fun escapeBuildConfigString(raw: String): String {
    return "\"${raw.replace("\\", "\\\\").replace("\"", "\\\"")}\""
}

val voiceEnableFunAsr = providers.gradleProperty("voiceEnableFunAsr").orElse("false").get().toBoolean()
val voiceFunAsrWsUrl = providers.gradleProperty("voiceFunAsrWsUrl").orElse("").get()
val voiceEnableVolcAsr = providers.gradleProperty("voiceEnableVolcAsr").orElse("false").get().toBoolean()
val voiceVolcWsUrl = providers.gradleProperty("voiceVolcWsUrl")
    .orElse("wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async")
    .get()
val voiceVolcAppKey = providers.gradleProperty("voiceVolcAppKey").orElse("").get()
val voiceVolcAccessKey = providers.gradleProperty("voiceVolcAccessKey").orElse("").get()
val voiceVolcResourceId = providers.gradleProperty("voiceVolcResourceId").orElse("").get()
val voiceVolcLanguage = providers.gradleProperty("voiceVolcLanguage").orElse("zh-CN").get()
val voiceVolcEnableItn = providers.gradleProperty("voiceVolcEnableItn").orElse("true").get().toBoolean()
val voiceVolcEnablePunc = providers.gradleProperty("voiceVolcEnablePunc").orElse("true").get().toBoolean()
val voiceVolcEnableDdc = providers.gradleProperty("voiceVolcEnableDdc").orElse("false").get().toBoolean()
val voiceVolcEnableNonstream = providers.gradleProperty("voiceVolcEnableNonstream").orElse("false").get().toBoolean()
val voiceVolcResultType = providers.gradleProperty("voiceVolcResultType").orElse("full").get()
val voiceVolcEndWindowSizeMs = providers.gradleProperty("voiceVolcEndWindowSizeMs")
    .orElse("800")
    .get()
    .toIntOrNull() ?: 800
val voiceEnableWhisper = providers.gradleProperty("voiceEnableWhisper").orElse("false").get().toBoolean()
val voiceWhisperHttpUrl = providers.gradleProperty("voiceWhisperHttpUrl").orElse("").get()
val voiceWhisperModel = providers.gradleProperty("voiceWhisperModel").orElse("whisper-1").get()
val voiceWhisperLanguage = providers.gradleProperty("voiceWhisperLanguage").orElse("zh").get()
val voiceEnableVosk = providers.gradleProperty("voiceEnableVosk").orElse("false").get().toBoolean()
val voiceVoskModelPath = providers.gradleProperty("voiceVoskModelPath").orElse("").get()
val voiceAsrModeOverride = providers.gradleProperty("voiceAsrModeOverride").orElse("AUTO").get()

android {
    namespace = "com.tgrobot.mobile"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.tgrobot.mobile"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        vectorDrawables {
            useSupportLibrary = true
        }

        buildConfigField("boolean", "VOICE_ENABLE_FUN_ASR", voiceEnableFunAsr.toString())
        buildConfigField("String", "VOICE_FUN_ASR_WS_URL", escapeBuildConfigString(voiceFunAsrWsUrl))
        buildConfigField("boolean", "VOICE_ENABLE_VOLC_ASR", voiceEnableVolcAsr.toString())
        buildConfigField("String", "VOICE_VOLC_WS_URL", escapeBuildConfigString(voiceVolcWsUrl))
        buildConfigField("String", "VOICE_VOLC_APP_KEY", escapeBuildConfigString(voiceVolcAppKey))
        buildConfigField("String", "VOICE_VOLC_ACCESS_KEY", escapeBuildConfigString(voiceVolcAccessKey))
        buildConfigField("String", "VOICE_VOLC_RESOURCE_ID", escapeBuildConfigString(voiceVolcResourceId))
        buildConfigField("String", "VOICE_VOLC_LANGUAGE", escapeBuildConfigString(voiceVolcLanguage))
        buildConfigField("boolean", "VOICE_VOLC_ENABLE_ITN", voiceVolcEnableItn.toString())
        buildConfigField("boolean", "VOICE_VOLC_ENABLE_PUNC", voiceVolcEnablePunc.toString())
        buildConfigField("boolean", "VOICE_VOLC_ENABLE_DDC", voiceVolcEnableDdc.toString())
        buildConfigField("boolean", "VOICE_VOLC_ENABLE_NONSTREAM", voiceVolcEnableNonstream.toString())
        buildConfigField("String", "VOICE_VOLC_RESULT_TYPE", escapeBuildConfigString(voiceVolcResultType))
        buildConfigField("int", "VOICE_VOLC_END_WINDOW_SIZE_MS", voiceVolcEndWindowSizeMs.toString())
        buildConfigField("boolean", "VOICE_ENABLE_WHISPER", voiceEnableWhisper.toString())
        buildConfigField("String", "VOICE_WHISPER_HTTP_URL", escapeBuildConfigString(voiceWhisperHttpUrl))
        buildConfigField("String", "VOICE_WHISPER_MODEL", escapeBuildConfigString(voiceWhisperModel))
        buildConfigField("String", "VOICE_WHISPER_LANGUAGE", escapeBuildConfigString(voiceWhisperLanguage))
        buildConfigField("boolean", "VOICE_ENABLE_VOSK", voiceEnableVosk.toString())
        buildConfigField("String", "VOICE_VOSK_MODEL_PATH", escapeBuildConfigString(voiceVoskModelPath))
        buildConfigField("String", "VOICE_ASR_MODE_OVERRIDE", escapeBuildConfigString(voiceAsrModeOverride))
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        buildConfig = true
        compose = true
    }

    composeOptions {
        kotlinCompilerExtensionVersion = "1.5.14"
    }

    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.6")
    implementation("androidx.lifecycle:lifecycle-viewmodel-ktx:2.8.6")
    implementation("androidx.activity:activity-compose:1.9.2")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.6")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.6")

    implementation(platform("androidx.compose:compose-bom:2024.09.03"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.animation:animation")
    debugImplementation("androidx.compose.ui:ui-tooling")

    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("org.webrtc:google-webrtc:1.0.32006")
}
