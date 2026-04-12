package com.tgrobot.mobile.domain.control

class RateLimiter(
    rateHz: Int,
) {
    private val intervalMs: Long = (1000f / rateHz.coerceIn(1, 100)).toLong().coerceAtLeast(1L)
    private var lastEmitMs: Long = 0L

    fun shouldEmit(nowMs: Long): Boolean {
        if (nowMs - lastEmitMs >= intervalMs) {
            lastEmitMs = nowMs
            return true
        }
        return false
    }

    fun forceEmitOnNext(nowMs: Long) {
        lastEmitMs = nowMs - intervalMs
    }

    fun reset() {
        lastEmitMs = 0L
    }
}
