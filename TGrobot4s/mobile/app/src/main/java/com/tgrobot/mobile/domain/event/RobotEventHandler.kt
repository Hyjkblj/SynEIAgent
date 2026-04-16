package com.tgrobot.mobile.domain.event

import com.tgrobot.mobile.core.model.RobotEvent

/**
 * 机器人事件处理器接口
 */
interface RobotEventHandler {
    /**
     * 处理事件
     * 
     * @param event 机器人事件
     */
    suspend fun handle(event: RobotEvent)
}

/**
 * 延迟更新处理器
 * 
 * 处理 JoystickAck 和 ControlAck 中的时间戳，计算延迟。
 */
class LatencyUpdateHandler(
    private val onLatencyUpdate: (Long) -> Unit,
) : RobotEventHandler {
    override suspend fun handle(event: RobotEvent) {
        when (event) {
            is RobotEvent.JoystickAck -> {
                event.ts?.let { ts ->
                    val latency = (android.os.SystemClock.elapsedRealtime() - ts).coerceAtLeast(0L)
                    onLatencyUpdate(latency)
                }
            }
            is RobotEvent.ControlAck -> {
                event.ts?.let { ts ->
                    val latency = (android.os.SystemClock.elapsedRealtime() - ts).coerceAtLeast(0L)
                    onLatencyUpdate(latency)
                }
            }
            else -> Unit
        }
    }
}

/**
 * 电池更新处理器
 * 
 * 处理电池状态更新。
 */
class BatteryUpdateHandler(
    private val onBatteryUpdate: (Int) -> Unit,
) : RobotEventHandler {
    override suspend fun handle(event: RobotEvent) {
        // 电池信息通常来自本地查询，这里预留扩展
    }
}
