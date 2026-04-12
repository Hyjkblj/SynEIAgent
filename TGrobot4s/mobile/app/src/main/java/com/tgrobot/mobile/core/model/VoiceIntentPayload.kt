package com.tgrobot.mobile.core.model

data class VoiceIntentPayload(
    val intent: String,
    val linear: Float? = null,
    val angular: Float? = null,
    val durationMs: Int? = null,
    val actionId: String? = null,
    val motionNumber: Int? = null,
    val requestId: String? = null,
)
