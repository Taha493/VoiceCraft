"""Caption extraction stage: region → gated OCR at a fixed sample rate → tracker."""

from __future__ import annotations

import time
from typing import Callable

import cv2
import numpy as np

from ..media.frames import Crop, iter_frames
from ..media.probe import file_fingerprint, probe
from ..schema import Box, Caption, CaptionTrack, Region
from .ocr import TextLine, load_ocr
from .region import detect_region
from .tracker import Observation, build_captions, similarity, text_key

Progress = Callable[[str, float], None]

BLANK_EDGE_DENSITY = 0.001  # no text-like edges in the band → skip OCR
CHANGE_FRACTION = 0.002  # fraction of thumbnail pixels that changed by >20 levels → re-OCR


def _thumb(frame: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    tw = min(320, w)
    return cv2.resize(gray, (tw, max(8, int(h * tw / w))), interpolation=cv2.INTER_AREA)


def join_lines(lines: list[TextLine]) -> str:
    rows: list[list[TextLine]] = []
    for ln in sorted(lines, key=lambda l: l.cy):
        if rows and abs(rows[-1][-1].cy - ln.cy) < 0.5 * max(ln.height, rows[-1][-1].height):
            rows[-1].append(ln)
        else:
            rows.append([ln])
    return " ".join(" ".join(l.text for l in sorted(r, key=lambda l: l.box[0])) for r in rows)


class _BandReader:
    """Change-gated OCR for one caption band."""

    def __init__(self, engine, ignore: list[str]):
        self.engine = engine
        self.ignore = ignore
        self.obs: list[Observation] = []
        self.last_thumb: np.ndarray | None = None
        self.last = ("", 0.0)
        self.ocr_calls = 0

    def sample(self, t: float, frame: np.ndarray) -> None:
        thumb = _thumb(frame)
        edges = (cv2.Canny(thumb, 80, 160) > 0).mean()
        if edges < BLANK_EDGE_DENSITY:
            self.last, self.last_thumb = ("", 0.0), thumb
        elif self.last_thumb is None or (np.abs(thumb.astype(np.int16) - self.last_thumb) > 20).mean() >= CHANGE_FRACTION:
            lines = [ln for ln in self.engine.read(frame) if not any(similarity(text_key(ln.text), k) >= 0.85 for k in self.ignore)]
            self.ocr_calls += 1
            self.last = (join_lines(lines), float(np.mean([l.score for l in lines])) if lines else 0.0)
            self.last_thumb = thumb
        self.obs.append(Observation(t, *self.last))


def _slice(frame: np.ndarray, b: Box) -> np.ndarray:
    h, w = frame.shape[:2]
    y0, y1 = int(b.y * h), max(int(b.y * h) + 2, int((b.y + b.h) * h))
    x0, x1 = int(b.x * w), max(int(b.x * w) + 2, int((b.x + b.w) * w))
    return frame[y0:y1, x0:x1]


SIMULTANEOUS = 0.6  # captions in different bands appearing this close together (staggered animation) are one thought


def merge_bands(per_band: list[list[Caption]]) -> list[Caption]:
    """Interleave captions from several bands by time. Lines that appear together (a headline and
    its sub-line) become one caption, read top band first."""
    tagged = sorted(((c.start, band, c) for band, caps in enumerate(per_band) for c in caps), key=lambda x: (x[0], x[1]))
    out: list[Caption] = []
    last_band: int | None = None
    for _, band, c in tagged:
        prev = out[-1] if out else None
        if prev is not None and band != last_band and abs(c.start - prev.start) <= SIMULTANEOUS:
            head = prev.text.rstrip()
            sep = " " if head.endswith((".", "!", "?", ":", ";", ",", "…")) else ". "  # headline + sub-line
            prev.text = f"{head}{sep}{c.text.lstrip()}"
            prev.end = max(prev.end, c.end)
            prev.confidence = min(prev.confidence, c.confidence)
            prev.flagged = prev.flagged or c.flagged
            prev.flag_reason = prev.flag_reason or c.flag_reason
            continue
        out.append(c.model_copy())
        last_band = band
    for i, c in enumerate(out):
        c.id = f"c{i + 1}"
    return out


def extract_captions(
    video: str,
    region: Region | None = None,
    sample_fps: float = 4.0,
    ocr: str = "rapidocr",
    progress: Progress | None = None,
) -> CaptionTrack:
    t_start = time.perf_counter()
    report = progress or (lambda stage, frac: None)
    info = probe(video)
    engine = load_ocr(ocr)

    if region is None:
        report("Finding the caption area", 0.0)
        region = detect_region(info, engine, progress=lambda f: report("Finding the caption area", f * 0.2))
    ignore = [text_key(t) for t in region.ignore_texts]

    boxes = region.boxes or [Box(x=region.x, y=region.y, w=region.w, h=region.h)]
    dt = 1.0 / sample_fps
    total = max(1, int(info.duration * sample_fps))
    bands = [_BandReader(engine, ignore) for _ in boxes]
    if len(boxes) == 1:
        # One band: let FFmpeg crop, so only the band is decoded into Python.
        b = boxes[0]
        frames = ((t, [f]) for t, f in iter_frames(video, info.width, info.height, sample_fps, crop=Crop(b.x, b.y, b.w, b.h), max_width=1280))
    else:
        frames = ((t, [_slice(f, b) for b in boxes]) for t, f in iter_frames(video, info.width, info.height, sample_fps, max_width=1280))
    for i, (t, crops) in enumerate(frames):
        for reader, crop in zip(bands, crops):
            reader.sample(t, crop)
        if i % 4 == 0:
            report("Reading captions", 0.2 + 0.8 * min(1.0, (i + 1) / total))

    per_band = [build_captions(r.obs, dt=dt, duration=info.duration) for r in bands]
    captions = merge_bands(per_band)
    ocr_calls = sum(r.ocr_calls for r in bands)
    obs = bands[0].obs
    report("Reading captions", 1.0)
    return CaptionTrack(
        video_fingerprint=file_fingerprint(video),
        duration=info.duration,
        region=region,
        sample_fps=sample_fps,
        ocr_engine=ocr,
        captions=captions,
        stats={
            "samples": len(obs),
            "ocr_calls": ocr_calls,
            "seconds": round(time.perf_counter() - t_start, 2),
            "flagged": sum(c.flagged for c in captions),
        },
    )
