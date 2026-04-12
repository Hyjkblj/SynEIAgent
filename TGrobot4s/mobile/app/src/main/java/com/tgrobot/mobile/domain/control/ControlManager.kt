package com.tgrobot.mobile.domain.control

import com.tgrobot.mobile.core.model.JoystickInput
import com.tgrobot.mobile.core.model.TeleopCommand

class ControlManager(
    private val commandMapper: CommandMapper = CommandMapper(),
    private val rateLimiter: RateLimiter = RateLimiter(rateHz = 20),
    private val smoother: Smoother = Smoother(smoothingFactor = 0.35f),
    private val safetyController: SafetyController = SafetyController(
        maxLinear = 1f,
        maxAngular = 1f,
        commandTimeoutMs = 500L,
    ),
) {
    private var latestInput: JoystickInput = JoystickInput.Zero
    private var lastCommand: TeleopCommand = TeleopCommand.Zero
    private var active: Boolean = false

    fun updateInput(x: Float, y: Float) {
        latestInput = JoystickInput(x = x, y = y).clamped()
        active = true
    }

    fun release(nowMs: Long): TeleopCommand {
        active = false
        latestInput = JoystickInput.Zero
        lastCommand = TeleopCommand.Zero
        rateLimiter.forceEmitOnNext(nowMs)
        return lastCommand
    }

    fun emergencyStop(nowMs: Long): TeleopCommand {
        active = false
        latestInput = JoystickInput.Zero
        lastCommand = TeleopCommand.Zero
        rateLimiter.forceEmitOnNext(nowMs)
        return lastCommand
    }

    fun nextCommand(nowMs: Long): TeleopCommand? {
        if (!rateLimiter.shouldEmit(nowMs)) {
            return null
        }

        if (safetyController.shouldForceStop(nowMs, lastCommand)) {
            lastCommand = TeleopCommand.Zero
            return lastCommand
        }

        val target = if (active) {
            commandMapper.map(latestInput)
        } else {
            TeleopCommand.Zero
        }

        lastCommand = safetyController.enforce(
            smoother.smooth(lastCommand, target),
        )
        return lastCommand
    }

    fun onCommandSent(nowMs: Long) {
        safetyController.onCommandSent(nowMs)
    }

    fun reset() {
        active = false
        latestInput = JoystickInput.Zero
        lastCommand = TeleopCommand.Zero
        rateLimiter.reset()
        safetyController.reset()
    }
}
