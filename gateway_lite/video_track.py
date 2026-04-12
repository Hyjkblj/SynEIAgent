from __future__ import annotations

import asyncio
import io
from dataclasses import dataclass

import av
from aiortc import VideoStreamTrack

try:
    import numpy as np
    from PIL import Image
except Exception:  # pragma: no cover
    np = None
    Image = None


@dataclass(slots=True)
class VideoMetrics:
    pushed: int = 0
    dropped: int = 0
    sent: int = 0


class SharedVideoTrack(VideoStreamTrack):
    kind = "video"

    def __init__(self) -> None:
        super().__init__()
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=4)
        self.metrics = VideoMetrics()

    def push_jpeg(self, jpeg: bytes) -> bool:
        if not jpeg:
            return False
        if np is None or Image is None:
            return False

        try:
            rgb = np.array(Image.open(io.BytesIO(jpeg)).convert("RGB"))
        except Exception:
            return False

        self.metrics.pushed += 1
        try:
            self._queue.put_nowait(rgb)
            return True
        except asyncio.QueueFull:
            try:
                _ = self._queue.get_nowait()
                self.metrics.dropped += 1
                self._queue.put_nowait(rgb)
                return True
            except Exception:
                return False

    def get_metrics(self) -> dict:
        pushed = self.metrics.pushed
        dropped = self.metrics.dropped
        return {
            "frames_pushed": pushed,
            "frames_dropped": dropped,
            "frames_sent": self.metrics.sent,
            "drop_ratio": round((dropped / pushed), 4) if pushed else 0.0,
        }

    async def recv(self) -> av.VideoFrame:
        rgb = await self._queue.get()
        self.metrics.sent += 1
        frame = av.VideoFrame.from_ndarray(rgb, format="rgb24")
        pts, time_base = await self.next_timestamp()
        frame.pts = pts
        frame.time_base = time_base
        return frame
