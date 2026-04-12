package com.tgrobot.mobile.domain.voice

class VoiceIntentParser(
    private val actions: List<ActionDefinition> = ActionCatalog.defaultActions,
) {
    fun parse(rawText: String): VoiceIntentCommand {
        val text = rawText.trim().lowercase()
        if (text.isBlank()) {
            return VoiceIntentCommand.Unknown(rawText)
        }

        if (BATTERY_QUERY_KEYWORDS.any { text.contains(it) }) {
            return VoiceIntentCommand.QueryBattery
        }
        if (CONFIG_QUERY_KEYWORDS.any { text.contains(it) }) {
            return VoiceIntentCommand.QueryConfig
        }
        if (STATUS_QUERY_KEYWORDS.any { text.contains(it) }) {
            return VoiceIntentCommand.QueryStatus
        }

        if (STOP_KEYWORDS.any { text.contains(it) }) {
            return VoiceIntentCommand.Stop
        }

        if (RESET_EMERGENCY_KEYWORDS.any { text.contains(it) }) {
            return VoiceIntentCommand.ResetEmergency
        }

        if (FORWARD_KEYWORDS.any { text.contains(it) }) {
            return VoiceIntentCommand.Move(linear = 0.35f, angular = 0f, durationMs = 800)
        }
        if (BACKWARD_KEYWORDS.any { text.contains(it) }) {
            return VoiceIntentCommand.Move(linear = -0.25f, angular = 0f, durationMs = 800)
        }
        if (LEFT_KEYWORDS.any { text.contains(it) }) {
            return VoiceIntentCommand.Move(linear = 0f, angular = 0.6f, durationMs = 650)
        }
        if (RIGHT_KEYWORDS.any { text.contains(it) }) {
            return VoiceIntentCommand.Move(linear = 0f, angular = -0.6f, durationMs = 650)
        }

        val action = actions.firstOrNull { def ->
            def.keywords.any { kw -> text.contains(kw.lowercase()) }
        }
        if (action != null) {
            return VoiceIntentCommand.Action(
                actionId = action.actionId,
                motionNumber = action.motionNumber,
            )
        }

        return VoiceIntentCommand.Unknown(rawText)
    }

    private companion object {
        val STOP_KEYWORDS = setOf("停止", "停下", "急停", "stop")
        val RESET_EMERGENCY_KEYWORDS = setOf("解除急停", "恢复控制", "reset emergency")
        val FORWARD_KEYWORDS = setOf("前进", "往前", "向前", "forward")
        val BACKWARD_KEYWORDS = setOf("后退", "往后", "向后", "back")
        val LEFT_KEYWORDS = setOf("左转", "向左", "left")
        val RIGHT_KEYWORDS = setOf("右转", "向右", "right")

        val BATTERY_QUERY_KEYWORDS = setOf("电量", "电池", "battery", "power")
        val CONFIG_QUERY_KEYWORDS = setOf("配置", "参数", "config", "setting")
        val STATUS_QUERY_KEYWORDS = setOf("状态", "在线", "health", "status")
    }
}
