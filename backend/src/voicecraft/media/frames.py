"""Stream decoded frames from FFmpeg without loading the video into RAM.

FFmpeg does the decoding, crop, resample-to-fixed-fps and scaling; Python only ever holds one
frame. Timestamps come from the fps filter's output timeline, which follows the source PTS
(so variable-frame-rate screen recordings stay correct to within one sample interval).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Iterator

import numpy as np


@dataclass(frozen=True)
class Crop:
    """Normalized crop box (0..1)."""

    x: float = 0.0
    y: float = 0.0
    w: float = 1.0
    h: float = 1.0

    def pixels(self, width: int, height: int) -> tuple[int, int, int, int]:
        x = int(round(self.x * width))
        y = int(round(self.y * height))
        w = max(2, int(round(self.w * width)) // 2 * 2)
        h = max(2, int(round(self.h * height)) // 2 * 2)
        w = min(w, width - x) // 2 * 2
        h = min(h, height - y) // 2 * 2
        return x, y, w, h


def iter_frames(
    path: str,
    width: int,
    height: int,
    fps: float,
    crop: Crop | None = None,
    max_width: int | None = None,
    start: float = 0.0,
    duration: float | None = None,
) -> Iterator[tuple[float, np.ndarray]]:
    """Yield (timestamp_seconds, BGR uint8 frame) at `fps` samples per second."""
    filters = []
    out_w, out_h = width, height
    if crop is not None:
        x, y, w, h = crop.pixels(width, height)
        filters.append(f"crop={w}:{h}:{x}:{y}")
        out_w, out_h = w, h
    # round=up: each sample is the newest source frame at or before i/fps (no look-ahead bias).
    filters.append(f"fps={fps}:round=up")
    if max_width and out_w > max_width:
        out_h = int(round(out_h * max_width / out_w / 2)) * 2
        out_w = max_width
        filters.append(f"scale={out_w}:{out_h}:flags=area")

    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin"]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", path]
    if duration is not None:
        cmd += ["-t", f"{duration:.3f}"]
    cmd += ["-an", "-sn", "-vf", ",".join(filters), "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]

    frame_bytes = out_w * out_h * 3
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=frame_bytes)
    try:
        i = 0
        assert proc.stdout is not None
        while True:
            buf = proc.stdout.read(frame_bytes)
            if len(buf) < frame_bytes:
                break
            frame = np.frombuffer(buf, dtype=np.uint8).reshape(out_h, out_w, 3)
            yield start + i / fps, frame
            i += 1
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()


def grab_frame(path: str, t: float, max_width: int | None = 1280) -> bytes:
    """A single JPEG frame (for the region editor in the UI)."""
    vf = f"scale='min({max_width},iw)':-2" if max_width else "null"
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{max(0.0, t):.3f}", "-i", path,
         "-frames:v", "1", "-vf", vf, "-f", "image2", "-c:v", "mjpeg", "-q:v", "4", "-"],
        capture_output=True,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError(f"Could not extract frame at {t:.2f}s")
    return proc.stdout
