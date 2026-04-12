package com.tgrobot.mobile.domain.voice

data class ActionDefinition(
    val actionId: String,
    val motionNumber: Int,
    val keywords: Set<String>,
)

object ActionCatalog {
    /**
     * 用户自定义动作表入口：
     * 1. 新增一条 ActionDefinition
     * 2. 分配 motionNumber (1..5)
     * 3. 配置 keywords 的中英文别名
     */
    val defaultActions: List<ActionDefinition> = listOf(
        ActionDefinition(
            actionId = "wave_hand",
            motionNumber = 1,
            keywords = setOf("挥手", "招手", "wave"),
        ),
        ActionDefinition(
            actionId = "hand_shake",
            motionNumber = 2,
            keywords = setOf("握手", "shake", "handshake"),
        ),
        ActionDefinition(
            actionId = "bow",
            motionNumber = 3,
            keywords = setOf("鞠躬", "弯腰", "bow"),
        ),
        ActionDefinition(
            actionId = "dance_1",
            motionNumber = 4,
            keywords = setOf("跳舞", "舞蹈", "dance"),
        ),
        ActionDefinition(
            actionId = "dance_2",
            motionNumber = 5,
            keywords = setOf("舞蹈2", "第二段舞", "dance 2"),
        ),
    )
}
