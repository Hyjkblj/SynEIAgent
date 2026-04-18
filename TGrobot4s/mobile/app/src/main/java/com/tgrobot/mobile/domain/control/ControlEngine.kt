package com.tgrobot.mobile.domain.control

import com.tgrobot.mobile.core.model.JoystickInput
import com.tgrobot.mobile.core.model.TeleopCommand
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * 控制引擎
 * 
 * 封装控制算法细节，提供简洁的控制 API。
 * 隐藏 CommandMapper、Smoother、SafetyController、RateLimiter 的复杂性。
 * 
 * 职责：
 * - 接收摇杆输入
 * - 应用平滑、安全限制、速率限制
 * - 生成控制命令流
 * - 管理控制循环生命周期
 */
class ControlEngine(
    private val commandMapper: CommandMapper = CommandMapper(),
    private val smoother: Smoother = Smoother(smoothingFactor = 0.35f),
    private val safetyController: SafetyController = SafetyController(
        maxLinear = 1f,
        maxAngular = 1f,
        commandTimeoutMs = 500L,
    ),
    private val rateLimiter: RateLimiter = RateLimiter(rateHz = 20),
    private val scope: CoroutineScope = CoroutineScope(Dispatchers.Default),
) {
    private val _latestInput = MutableStateFlow(JoystickInput.Zero)
    private val _lastCommand = MutableStateFlow(TeleopCommand.Zero)
    private var active: Boolean = false
    private var controlLoopJob: Job? = null

    /**
     * 最后生成的命令
     */
    val lastCommand: StateFlow<TeleopCommand> = _lastCommand.asStateFlow()

    /**
     * 更新摇杆输入
     * 
     * @param x X 轴输入 [-1, 1]
     * @param y Y 轴输入 [-1, 1]
     */
    fun updateInput(x: Float, y: Float) {
        _latestInput.value = JoystickInput(x = x, y = y).clamped()
        active = true
    }

    /**
     * 释放摇杆（停止）
     * 
     * @param nowMs 当前时间戳（毫秒）
     * @return 停止命令
     */
    fun release(nowMs: Long): TeleopCommand {
        active = false
        _latestInput.value = JoystickInput.Zero
        _lastCommand.value = TeleopCommand.Zero
        rateLimiter.forceEmitOnNext(nowMs)
        return TeleopCommand.Zero
    }

    /**
     * 紧急停止
     * 
     * @param nowMs 当前时间戳（毫秒）
     * @return 停止命令
     */
    fun emergencyStop(nowMs: Long): TeleopCommand {
        active = false
        _latestInput.value = JoystickInput.Zero
        _lastCommand.value = TeleopCommand.Zero
        rateLimiter.forceEmitOnNext(nowMs)
        return TeleopCommand.Zero
    }

    /**
     * 获取下一个命令
     * 
     * @param nowMs 当前时间戳（毫秒）
     * @return 下一个命令，如果速率限制未到则返回 null
     */
    fun nextCommand(nowMs: Long): TeleopCommand? {
        if (!rateLimiter.shouldEmit(nowMs)) {
            return null
        }

        if (safetyController.shouldForceStop(nowMs, _lastCommand.value)) {
            _lastCommand.value = TeleopCommand.Zero
            return TeleopCommand.Zero
        }

        val target = if (active) {
            commandMapper.map(_latestInput.value)
        } else {
            TeleopCommand.Zero
        }

        _lastCommand.value = safetyController.enforce(
            smoother.smooth(_lastCommand.value, target),
        )
        return _lastCommand.value
    }

    /**
     * 命令已发送回调
     * 
     * @param nowMs 当前时间戳（毫秒）
     */
    fun onCommandSent(nowMs: Long) {
        safetyController.onCommandSent(nowMs)
    }

    /**
     * 重置引擎状态
     */
    fun reset() {
        active = false
        _latestInput.value = JoystickInput.Zero
        _lastCommand.value = TeleopCommand.Zero
        rateLimiter.reset()
        safetyController.reset()
    }

    /**
     * 启动控制循环
     * 
     * @param tickMs 循环间隔（毫秒）
     * @param onCommand 命令回调（suspend 函数）
     */
    fun startControlLoop(tickMs: Long = 50L, onCommand: suspend (TeleopCommand, Long) -> Unit) {
        if (controlLoopJob?.isActive == true) return

        controlLoopJob = scope.launch {
            while (isActive) {
                val now = System.currentTimeMillis()
                val command = nextCommand(now)
                if (command != null) {
                    onCommand(command, now)
                }
                delay(tickMs)
            }
        }
    }

    /**
     * 停止控制循环
     */
    fun stopControlLoop() {
        controlLoopJob?.cancel()
        controlLoopJob = null
    }

    /**
     * 是否正在运行
     */
    val isRunning: Boolean
        get() = controlLoopJob?.isActive == true
}
