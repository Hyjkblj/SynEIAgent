package com.tgrobot.mobile.feature.voice

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import com.tgrobot.mobile.feature.voice.asr.AsrResult

/**
 * 语音识别测试弹窗
 *
 * 显示实时识别结果，用于调试和验证 ASR 引擎。
 */
@Composable
fun VoiceTestDialog(
    isListening: Boolean,
    partialText: String,
    finalText: String?,
    error: String?,
    onDismiss: () -> Unit,
) {
    Dialog(onDismissRequest = onDismiss) {
        Surface(
            shape = RoundedCornerShape(16.dp),
            color = Color(0xFF1E1E1E),
            modifier = Modifier
                .fillMaxWidth(0.9f)
                .wrapContentHeight(),
        ) {
            Column(
                modifier = Modifier.padding(24.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                // 标题
                Text(
                    text = "语音识别测试",
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.Bold,
                    color = Color.White,
                )

                // 状态指示
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Box(
                        modifier = Modifier
                            .size(12.dp)
                            .background(
                                when {
                                    error != null -> Color.Red
                                    isListening -> Color(0xFF4CAF50)
                                    else -> Color.Gray
                                },
                                RoundedCornerShape(6.dp),
                            ),
                    )
                    Text(
                        text = when {
                            error != null -> "错误"
                            isListening -> "正在识别..."
                            else -> "已停止"
                        },
                        color = Color.White.copy(alpha = 0.8f),
                        fontSize = 14.sp,
                    )
                }

                // 分隔线
                HorizontalDivider(color = Color.White.copy(alpha = 0.2f))

                // 实时识别结果
                if (partialText.isNotBlank()) {
                    Column {
                        Text(
                            text = "实时结果",
                            color = Color.White.copy(alpha = 0.6f),
                            fontSize = 12.sp,
                        )
                        Text(
                            text = partialText,
                            color = Color(0xFF80CBC4),
                            fontSize = 18.sp,
                            fontWeight = FontWeight.Medium,
                        )
                    }
                }

                // 最终结果
                if (!finalText.isNullOrBlank()) {
                    Column {
                        Text(
                            text = "最终结果",
                            color = Color.White.copy(alpha = 0.6f),
                            fontSize = 12.sp,
                        )
                        Text(
                            text = finalText,
                            color = Color(0xFF90CAF9),
                            fontSize = 20.sp,
                            fontWeight = FontWeight.Bold,
                        )
                    }
                }

                // 错误信息
                if (!error.isNullOrBlank()) {
                    Column {
                        Text(
                            text = "错误",
                            color = Color(0xFFFFAB91),
                            fontSize = 12.sp,
                        )
                        Text(
                            text = error,
                            color = Color(0xFFFFCC80),
                            fontSize = 14.sp,
                        )
                    }
                }

                // 关闭按钮
                TextButton(
                    onClick = onDismiss,
                    modifier = Modifier.align(Alignment.End),
                ) {
                    Text("关闭", color = Color.White.copy(alpha = 0.7f))
                }
            }
        }
    }
}
