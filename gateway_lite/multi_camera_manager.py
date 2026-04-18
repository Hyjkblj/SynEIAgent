from __future__ import annotations

from dataclasses import dataclass

from .video_track import SharedVideoTrack


@dataclass(frozen=True, slots=True)
class CameraConfig:
    camera_id: str
    display_name: str
    ros_topic: str


class MultiCameraVideoManager:
    DEFAULT_CAMERAS: dict[str, CameraConfig] = {
        "head": CameraConfig("head", "Head Camera", "/G330_0/color/image_raw"),
        "chest": CameraConfig("chest", "Chest Camera", "/G330_1/color/image_raw"),
        "left_hand": CameraConfig("left_hand", "Left Hand Camera", "/G330_2/color/image_raw"),
        "right_hand": CameraConfig("right_hand", "Right Hand Camera", "/G330_3/color/image_raw"),
    }

    def __init__(self, camera_ids: list[str] | None = None, primary_camera_id: str = "head") -> None:
        self._tracks: dict[str, SharedVideoTrack] = {}
        ids = camera_ids or list(self.DEFAULT_CAMERAS.keys())
        if not ids:
            ids = ["head"]
        for camera_id in ids:
            self._tracks[camera_id] = SharedVideoTrack(camera_id=camera_id)
        self._primary_camera_id = primary_camera_id if primary_camera_id in self._tracks else ids[0]

    @property
    def primary_camera_id(self) -> str:
        return self._primary_camera_id

    def get_track(self, camera_id: str) -> SharedVideoTrack | None:
        return self._tracks.get(camera_id)

    def get_all_tracks(self) -> dict[str, SharedVideoTrack]:
        return dict(self._tracks)

    def push_frame(self, camera_id: str, jpeg: bytes) -> bool:
        normalized = self._normalize_camera_id(camera_id)
        track = self._tracks.get(normalized)
        if track is None:
            track = SharedVideoTrack(camera_id=normalized)
            self._tracks[normalized] = track
        return track.push_jpeg(jpeg)

    def get_available_cameras(self) -> list[str]:
        return [
            camera_id
            for camera_id, track in self._tracks.items()
            if track.metrics.pushed > 0
        ]

    def get_metrics(self) -> dict[str, dict]:
        return {
            camera_id: track.get_metrics()
            for camera_id, track in self._tracks.items()
        }

    def get_aggregate_metrics(self) -> dict:
        all_metrics = list(self.get_metrics().values())
        pushed = sum(int(m.get("frames_pushed", 0)) for m in all_metrics)
        dropped = sum(int(m.get("frames_dropped", 0)) for m in all_metrics)
        sent = sum(int(m.get("frames_sent", 0)) for m in all_metrics)
        return {
            "primary_camera_id": self.primary_camera_id,
            "available_cameras": self.get_available_cameras(),
            "frames_pushed": pushed,
            "frames_dropped": dropped,
            "frames_sent": sent,
            "drop_ratio": round((dropped / pushed), 4) if pushed else 0.0,
            "cameras": self.get_metrics(),
        }

    def _normalize_camera_id(self, camera_id: str) -> str:
        cleaned = (camera_id or "").strip()
        return cleaned or self.primary_camera_id
