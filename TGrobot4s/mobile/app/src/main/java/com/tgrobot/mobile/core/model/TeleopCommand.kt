package com.tgrobot.mobile.core.model

import kotlin.math.abs

data class JoystickInput(
    val x: Float,
    val y: Float,
) {
    fun clamped(): JoystickInput = JoystickInput(
        x = x.coerceIn(-1f, 1f),
        y = y.coerceIn(-1f, 1f),
    )

    companion object {
        val Zero = JoystickInput(x = 0f, y = 0f)
    }
}

data class TeleopCommand(
    val linear: Float,
    val angular: Float,
) {
    val x: Float get() = angular
    val y: Float get() = linear

    fun isZero(epsilon: Float = 0.001f): Boolean {
        return abs(linear) < epsilon && abs(angular) < epsilon
    }

    companion object {
        val Zero = TeleopCommand(linear = 0f, angular = 0f)
    }
}
