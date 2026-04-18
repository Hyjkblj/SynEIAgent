package com.tgrobot.mobile.feature.voice.asr

import android.util.Log
import java.util.concurrent.ConcurrentHashMap

/**
 * ASR 引擎注册中心
 *
 * 管理所有已注册的 [AsrEngine]，支持动态注册和注销。
 * 线程安全，通常在应用启动时完成注册。
 */
object AsrRegistry {

    private val engines: ConcurrentHashMap<String, AsrEngine> = ConcurrentHashMap()

    /**
     * 注册一个 ASR 引擎
     *
     * @param engine 要注册的引擎；[AsrEngine.name] 作为唯一 key
     */
    fun register(engine: AsrEngine) {
        engines[engine.name] = engine
        Log.d(TAG, "Registered ASR engine: ${engine.name}")
    }

    /**
     * 注销一个 ASR 引擎
     *
     * @param name 引擎名称
     */
    fun unregister(name: String) {
        engines.remove(name)
        Log.d(TAG, "Unregistered ASR engine: $name")
    }

    /**
     * 按名称查找引擎
     *
     * @return 找到则返回引擎实例，否则返回 null
     */
    fun find(name: String): AsrEngine? = engines[name]

    /**
     * 清空所有已注册引擎
     */
    fun clear() {
        engines.clear()
        Log.d(TAG, "Cleared ASR registry")
    }

    /**
     * 返回所有已注册的引擎（可用性不保证）
     */
    fun all(): List<AsrEngine> = engines.values.toList()

    /**
     * 返回所有当前可用的引擎
     */
    fun available(): List<AsrEngine> = engines.values.filter { it.isAvailable() }

    /**
     * 是否存在任意可用引擎
     */
    fun hasAvailable(): Boolean = engines.values.any { it.isAvailable() }

    private const val TAG = "AsrRegistry"
}
