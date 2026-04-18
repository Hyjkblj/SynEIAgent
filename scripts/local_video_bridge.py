from __future__ import annotations

import argparse
import time
from typing import Any
from urllib.parse import quote

import cv2  # type: ignore
import httpx


def _parse_source(raw: str) -> Any:
    raw = raw.strip()
    if raw.isdigit():
        return int(raw)
    return raw


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Push local/RTSP video frames to SynEIAgent /push_frame")
    p.add_argument("--gateway", default="http://127.0.0.1:9100", help="Gateway base url")
    p.add_argument("--source", default="0", help="OpenCV source index or URL, e.g. 0 / rtsp://...")
    p.add_argument("--fps", type=float, default=15.0, help="Target push FPS")
    p.add_argument("--jpeg-quality", type=int, default=80, help="JPEG quality 1..100")
    p.add_argument("--camera-id", default="head", help="Camera id, e.g. head/chest/left_hand/right_hand")
    p.add_argument("--push-token", default="", help="Optional X-Push-Token header")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    source = _parse_source(args.source)
    interval_s = 1.0 / max(1.0, float(args.fps))
    quality = max(1, min(100, int(args.jpeg_quality)))
    camera_id = (args.camera_id or "head").strip() or "head"

    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise SystemExit(f"Failed to open video source: {source!r}")

    camera_q = quote(camera_id, safe="_-")
    push_url = f"{args.gateway.rstrip('/')}/push_frame?camera_id={camera_q}"
    headers = {"X-Push-Token": args.push_token} if args.push_token else {}

    sent = 0
    failed = 0
    start = time.time()
    last_log = start

    with httpx.Client(timeout=1.2) as client:
        print(f"Video bridge started: source={source!r} camera_id={camera_id} -> {push_url}")
        try:
            while True:
                t0 = time.time()
                ok, frame = cap.read()
                if not ok or frame is None:
                    failed += 1
                    time.sleep(0.02)
                    continue

                ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
                if not ok:
                    failed += 1
                    continue

                try:
                    resp = client.post(push_url, content=buf.tobytes(), headers=headers)
                    if resp.status_code >= 400:
                        failed += 1
                    else:
                        sent += 1
                except Exception:
                    failed += 1

                now = time.time()
                if now - last_log >= 1.0:
                    elapsed = max(1e-6, now - start)
                    print(
                        f"sent={sent} failed={failed} avg_fps={sent / elapsed:.2f}",
                        flush=True,
                    )
                    last_log = now

                sleep_s = interval_s - (time.time() - t0)
                if sleep_s > 0:
                    time.sleep(sleep_s)
        except KeyboardInterrupt:
            pass
        finally:
            cap.release()
            elapsed = max(1e-6, time.time() - start)
            print(f"Stopped. sent={sent}, failed={failed}, avg_fps={sent / elapsed:.2f}")


if __name__ == "__main__":
    main()
