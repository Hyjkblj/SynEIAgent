package com.tgrobot.mobile.core.model

import org.webrtc.VideoTrack
import java.util.LinkedHashMap

data class VideoStream(
    val cameraId: String,
    val displayName: String,
    val track: VideoTrack?,
    val isPrimary: Boolean = false,
    val order: Int = Int.MAX_VALUE,
) {
    val isAvailable: Boolean
        get() = track != null
}

enum class CameraType(
    val id: String,
    val displayName: String,
    val defaultOrder: Int,
) {
    HEAD("head", "Head", 0),
    CHEST("chest", "Chest", 1),
    LEFT_HAND("left_hand", "Left Hand", 2),
    RIGHT_HAND("right_hand", "Right Hand", 3),
    ;

    companion object {
        fun fromId(id: String): CameraType? = entries.firstOrNull { it.id == id }
    }
}

fun buildVideoStreams(
    tracks: Map<String, VideoTrack>,
    primaryCameraId: String,
): LinkedHashMap<String, VideoStream> {
    val normalizedTracks = tracks
        .mapKeys { (k, _) -> k.trim() }
        .filterKeys { it.isNotBlank() }

    val orderedIds = LinkedHashSet<String>()
    CameraType.entries.forEach { orderedIds += it.id }
    normalizedTracks.keys.forEach { orderedIds += it }

    val streams = LinkedHashMap<String, VideoStream>(orderedIds.size)
    orderedIds.forEachIndexed { index, cameraId ->
        val cameraType = CameraType.fromId(cameraId)
        streams[cameraId] = VideoStream(
            cameraId = cameraId,
            displayName = cameraType?.displayName ?: cameraId.replace("_", " ").replaceFirstChar { it.uppercase() },
            track = normalizedTracks[cameraId],
            isPrimary = cameraId == primaryCameraId,
            order = cameraType?.defaultOrder ?: (CameraType.entries.size + index),
        )
    }
    return streams
}
