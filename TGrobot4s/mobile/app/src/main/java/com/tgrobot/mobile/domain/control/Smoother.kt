package com.tgrobot.mobile.domain.control

import com.tgrobot.mobile.core.model.TeleopCommand

class Smoother(
    smoothingFactor: Float = 0.35f,
) {
    private val alpha = smoothingFactor.coerceIn(0f, 1f)

    fun smooth(previous: TeleopCommand, target: TeleopCommand): TeleopCommand {
        return TeleopCommand(
            linear = lerp(previous.linear, target.linear, alpha),
            angular = lerp(previous.angular, target.angular, alpha),
        )
    }

    private fun lerp(start: Float, end: Float, progress: Float): Float {
        return start + (end - start) * progress
    }
}
