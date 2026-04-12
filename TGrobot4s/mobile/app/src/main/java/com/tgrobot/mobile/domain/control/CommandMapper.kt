package com.tgrobot.mobile.domain.control

import com.tgrobot.mobile.core.model.JoystickInput
import com.tgrobot.mobile.core.model.TeleopCommand

class CommandMapper {
    fun map(input: JoystickInput): TeleopCommand {
        val clamped = input.clamped()
        return TeleopCommand(
            linear = clamped.y,
            angular = clamped.x,
        )
    }
}
