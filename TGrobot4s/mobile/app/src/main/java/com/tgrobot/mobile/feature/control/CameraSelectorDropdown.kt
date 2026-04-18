package com.tgrobot.mobile.feature.control

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.tgrobot.mobile.core.model.VideoStream

@Composable
fun CameraSelectorDropdown(
    streams: List<VideoStream>,
    primaryCameraId: String,
    onCameraSelected: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    var expanded by remember { mutableStateOf(false) }
    val orderedStreams = streams.sortedBy { it.order }
    val active = orderedStreams.firstOrNull { it.cameraId == primaryCameraId }
        ?: orderedStreams.firstOrNull { it.isAvailable }
        ?: orderedStreams.firstOrNull()

    Box(modifier = modifier) {
        Surface(
            shape = RoundedCornerShape(8.dp),
            color = Color.Black.copy(alpha = 0.5f),
            modifier = Modifier.clickable { expanded = true },
        ) {
            Row(
                modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                Text(
                    text = "Camera",
                    color = Color.White.copy(alpha = 0.7f),
                    style = MaterialTheme.typography.labelMedium,
                )
                Text(
                    text = active?.displayName ?: "--",
                    color = Color.White,
                    style = MaterialTheme.typography.bodyMedium,
                )
            }
        }

        DropdownMenu(
            expanded = expanded,
            onDismissRequest = { expanded = false },
            modifier = Modifier
                .widthIn(min = 180.dp)
                .background(Color.Black.copy(alpha = 0.9f)),
        ) {
            orderedStreams.forEach { stream ->
                val selected = stream.cameraId == primaryCameraId
                val baseColor = when {
                    selected -> Color(0xFF4CAF50)
                    stream.isAvailable -> Color.White
                    else -> Color.White.copy(alpha = 0.45f)
                }
                val prefix = if (selected) "* " else ""
                DropdownMenuItem(
                    text = { Text(text = "$prefix${stream.displayName}", color = baseColor) },
                    enabled = stream.isAvailable,
                    onClick = {
                        onCameraSelected(stream.cameraId)
                        expanded = false
                    },
                )
            }
        }
    }
}
