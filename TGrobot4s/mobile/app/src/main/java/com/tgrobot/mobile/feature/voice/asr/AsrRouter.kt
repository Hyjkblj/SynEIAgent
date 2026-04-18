package com.tgrobot.mobile.feature.voice.asr

import android.util.Log
import com.tgrobot.mobile.feature.voice.policy.AsrMode
import com.tgrobot.mobile.feature.voice.policy.DevicePolicy

/**
 * ASR 路由决策器
 *
 * 根据 [DevicePolicy] 策略，从 [AsrRegistry] 中选择最合适的可用引擎。
 * 支持运行时指定模式覆盖策略决策。
 */
class AsrRouter(
    private val registry: AsrRegistry = AsrRegistry,
    private val devicePolicy: DevicePolicy,
) {
    /**
     * 强制覆盖模式；为 null 时使用策略自动推断
     */
    var overrideMode: AsrMode? = null

    /**
     * 选择当前最优可用引擎
     *
     * 按优先级列表依次检查引擎可用性，返回第一个可用的引擎。
     * 若全部不可用则返回 null。
     *
     * @return 选中的引擎，或 null
     */
    fun select(): AsrEngine? {
        val mode = overrideMode ?: devicePolicy.preferredMode
        val priority = devicePolicy.enginePriority(mode)

        for (name in priority) {
            val engine = registry.find(name)
            if (engine != null && engine.isAvailable()) {
                Log.d(TAG, "Selected ASR engine: $name (mode=$mode)")
                return engine
            }
            Log.d(TAG, "ASR engine '$name' not available, trying next")
        }

        // 最终降级：尝试任意可用引擎
        val fallback = registry.available().firstOrNull()
        if (fallback != null) {
            Log.w(TAG, "All priority engines unavailable, fallback to: ${fallback.name}")
        } else {
            Log.e(TAG, "No ASR engine available at all")
        }
        return fallback
    }

    /**
     * 按名称强制选择引擎（忽略可用性检查，用于调试）
     *
     * @param name 引擎名称
     * @return 引擎实例，未注册则返回 null
     */
    fun selectByName(name: String): AsrEngine? = registry.find(name)

    private companion object {
        const val TAG = "AsrRouter"
    }
}
