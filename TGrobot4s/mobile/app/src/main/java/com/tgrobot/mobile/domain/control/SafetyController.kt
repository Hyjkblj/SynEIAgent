package com.tgrobot.mobile.domain.control

import com.tgrobot.mobile.core.model.TeleopCommand

class SafetyController(
    private val maxLinear: Float = 1f,
    private val maxAngular: Float = 1f,
    private val commandTimeoutMs: Long = 500L,
) {
    private var lastSentMs: Long = 0L

    fun onCommandSent(nowMs: Long) {
        lastSentMs = nowMs
    }

    fun shouldForceStop(nowMs: Long, currentCommand: TeleopCommand): Boolean {
        if (lastSentMs <= 0L || currentCommand.isZero()) {
            return false
        }
        return nowMs - lastSentMs >= commandTimeoutMs
    }

    fun enforce(command: TeleopCommand): TeleopCommand {
        return TeleopCommand(
            linear = command.linear.coerceIn(-maxLinear, maxLinear),
            angular = command.angular.coerceIn(-maxAngular, maxAngular),
        )
    }

    fun reset() {
        lastSentMs = 0L
    }
}
