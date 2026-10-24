"""ffprobe wrapper and a fast content hash for cache keys."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path


class MediaError(RuntimeError):
    pass


@dataclass(frozen=True)
class VideoInfo:
    path: str
    duration: float
    width: int
    height: int
    fps: float
    vcodec: str
    pix_fmt: str
    start_time: float
    has_audio: bool
    acodec: str | None

    def to_dict(self) -> dict:
        return asdict(self)


def _rate(value: str | None) -> float:
    try:
        r = Fraction(value or "0")
        return float(r) if r > 0 else 0.0
    except (ValueError, ZeroDivisionError):
        return 0.0


def probe(path: str | Path) -> VideoInfo:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise MediaError(f"Could not read video: {proc.stderr.strip() or 'ffprobe failed'}")
    data = json.loads(proc.stdout)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")), None)
    if video is None:
        raise MediaError("The file has no video stream.")
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fmt = data.get("format", {})
    duration = float(video.get("duration") or fmt.get("duration") or 0)
    if duration <= 0:
        raise MediaError("Could not determine the video duration.")
    fps = _rate(video.get("avg_frame_rate")) or _rate(video.get("r_frame_rate")) or 30.0
    return VideoInfo(
        path=str(path),
        duration=duration,
        width=int(video["width"]),
        height=int(video["height"]),
        fps=fps,
        vcodec=video.get("codec_name", "unknown"),
        pix_fmt=video.get("pix_fmt", "unknown"),
        start_time=float(video.get("start_time") or 0),
        has_audio=audio is not None,
        acodec=audio.get("codec_name") if audio else None,
    )


def file_fingerprint(path: str | Path, chunk: int = 4 << 20) -> str:
    """Hash of size + head + tail. Cheap for large videos and good enough as a cache key."""
    p = Path(path)
    size = p.stat().st_size
    h = hashlib.sha256(str(size).encode())
    with p.open("rb") as f:
        h.update(f.read(chunk))
        if size > chunk:
            f.seek(max(chunk, size - chunk))
            h.update(f.read(chunk))
    return h.hexdigest()[:24]
