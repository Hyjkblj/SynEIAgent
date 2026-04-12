package com.tgrobot.mobile.data.local

import com.tgrobot.mobile.core.model.RobotEndpoint
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject

data class LocalRobotSnapshot(
    val gatewayOk: Boolean,
    val sessions: Int?,
    val videoEnabled: Boolean?,
    val framesPushed: Int?,
    val framesSent: Int?,
    val dropRatio: Double?,
    val deadmanTimeoutMs: Int?,
    val joystickMaxHz: Int?,
    val voiceMaxDurationMs: Int?,
    val batteryPercent: Int?,
    val rosEnabled: Boolean?,
    val rosError: String?,
)

class LocalRobotInfoService(
    private val client: OkHttpClient = OkHttpClient(),
) {
    suspend fun fetchSnapshot(endpoint: RobotEndpoint): LocalRobotSnapshot? = withContext(Dispatchers.IO) {
        val gatewayBase = "http://${endpoint.host}:${endpoint.port}"

        val health = getJson("$gatewayBase/health")
        val status = getJson("$gatewayBase/status")
        if (health == null && status == null) {
            return@withContext null
        }

        // Optional: attempt ROS bridge health on common port 8080.
        val rosHealth = getJson("http://${endpoint.host}:8080/health")

        val control = status?.optJSONObject("control")
        val video = status?.optJSONObject("video")

        LocalRobotSnapshot(
            gatewayOk = (status?.optBoolean("ok") == true) || (health?.optBoolean("ok") == true),
            sessions = status?.optIntOrNull("sessions") ?: health?.optIntOrNull("sessions"),
            videoEnabled = health?.optBooleanOrNull("video_enabled"),
            framesPushed = video?.optIntOrNull("frames_pushed"),
            framesSent = video?.optIntOrNull("frames_sent"),
            dropRatio = video?.optDoubleOrNull("drop_ratio"),
            deadmanTimeoutMs = control?.optIntOrNull("deadman_timeout_ms"),
            joystickMaxHz = control?.optIntOrNull("joystick_max_hz"),
            voiceMaxDurationMs = control?.optIntOrNull("voice_max_duration_ms"),
            batteryPercent = parseBatteryPercent(status = status, health = health, rosHealth = rosHealth),
            rosEnabled = rosHealth?.optBooleanOrNull("ros_enabled"),
            rosError = rosHealth?.optStringOrNull("ros_error"),
        )
    }

    private fun getJson(url: String): JSONObject? {
        return runCatching {
            val req = Request.Builder().url(url).get().build()
            client.newCall(req).execute().use { resp ->
                if (!resp.isSuccessful) {
                    return null
                }
                val body = resp.body?.string()?.trim().orEmpty()
                if (body.isEmpty()) {
                    return null
                }
                JSONObject(body)
            }
        }.getOrNull()
    }

    private fun parseBatteryPercent(
        status: JSONObject?,
        health: JSONObject?,
        rosHealth: JSONObject?,
    ): Int? {
        val candidates = listOf(status, health, rosHealth)
        candidates.forEach { json ->
            if (json == null) return@forEach
            json.optIntOrNull("battery_percent")?.let { return it }
            json.optIntOrNull("battery")?.let { return it }

            json.optJSONObject("robot")?.let { robot ->
                robot.optIntOrNull("battery_percent")?.let { return it }
                robot.optIntOrNull("battery")?.let { return it }
            }
        }
        return null
    }
}

private fun JSONObject.optIntOrNull(key: String): Int? {
    return if (has(key) && !isNull(key)) optInt(key) else null
}

private fun JSONObject.optDoubleOrNull(key: String): Double? {
    return if (has(key) && !isNull(key)) optDouble(key) else null
}

private fun JSONObject.optBooleanOrNull(key: String): Boolean? {
    return if (has(key) && !isNull(key)) optBoolean(key) else null
}

private fun JSONObject.optStringOrNull(key: String): String? {
    if (!has(key) || isNull(key)) return null
    val value = optString(key)
    return value.ifBlank { null }
}
