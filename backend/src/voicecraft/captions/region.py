"""Find where captions live in the frame.

Captions in designed videos are *large* text that *keeps changing*. Screen recordings, code and
UI inside the video change too, but their text is small; titles, logos and watermarks are large
but static; slow UI labels ("Step 1 of 3") change rarely. We OCR evenly spaced full frames, keep
caption-sized lines, cluster them into horizontal bands, and keep every band that behaves like
captions. A video can have several (headline captions at the top, callouts at the bottom, a
centered end card).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from ..media.frames import iter_frames
from ..media.probe import VideoInfo
from ..schema import Box, Region
from .ocr import OcrEngine, TextLine
from .tracker import text_key


@dataclass
class _Band:
    lines: list[tuple[int, TextLine]] = field(default_factory=list)  # (sample index, normalized line)

    @property
    def cy(self) -> float:
        return float(np.mean([ln.cy for _, ln in self.lines]))

    def texts_by_sample(self) -> dict[int, str]:
        per: dict[int, list[TextLine]] = {}
        for i, ln in self.lines:
            per.setdefault(i, []).append(ln)
        return {i: text_key(" ".join(l.text for l in sorted(ls, key=lambda l: (round(l.cy, 2), l.box[0])))) for i, ls in per.items()}


def _normalize(line: TextLine, w: int, h: int) -> TextLine:
    x0, y0, x1, y1 = line.box
    return TextLine(line.text, line.score, (x0 / w, y0 / h, x1 / w, y1 / h))


def detect_region(
    info: VideoInfo,
    engine: OcrEngine,
    samples: int = 18,
    max_width: int = 960,
    progress: Callable[[float], None] | None = None,
) -> Region:
    fps = samples / info.duration
    found: list[tuple[int, TextLine]] = []
    n = 0
    for i, (_, frame) in enumerate(iter_frames(info.path, info.width, info.height, fps, max_width=max_width)):
        h, w = frame.shape[:2]
        found += [(i, _normalize(ln, w, h)) for ln in engine.read(frame)]
        n = i + 1
        if progress:
            progress(min(1.0, n / samples))
    if n == 0:
        return Region()

    region = _select_bands(found, n)
    return region if region is not None else _single_best_band(found, n)


def _cluster(lines: list[tuple[int, TextLine]]) -> list[_Band]:
    bands: list[_Band] = []
    for i, ln in sorted(lines, key=lambda p: p[1].cy):
        tol = max(0.03, ln.height * 0.6)
        if bands and abs(bands[-1].cy - ln.cy) <= tol:
            bands[-1].lines.append((i, ln))
        else:
            bands.append(_Band([(i, ln)]))
    return bands


def _band_box(band: _Band) -> tuple[float, float]:
    line_h = float(np.median([ln.height for _, ln in band.lines]))
    y0 = min(ln.box[1] for _, ln in band.lines) - line_h * 1.1  # room for an extra wrapped line
    y1 = max(ln.box[3] for _, ln in band.lines) + line_h * 0.8
    return max(0.0, y0), min(1.0, y1)


MIN_CAPTION_HEIGHT = 0.02  # of frame height; smaller text is UI/code inside the video
SIZE_RATIO = 0.55  # caption lines are at least this fraction of the typical largest text's height


WALL_BANDS = 4  # this many closely stacked bands of large text = a screenshot/document, not captions


def _drop_text_walls(bands: list[_Band]) -> list[_Band]:
    """Remove runs of tightly stacked bands (text inside a screen recording or document).

    Captions stand alone or wrap to two or three lines; a demo window full of large text shows up
    as a wall of adjacent bands roughly one line apart.
    """
    def height(b: _Band) -> float:
        return float(np.median([ln.height for _, ln in b.lines]))

    chains: list[list[_Band]] = []
    for band in bands:  # already sorted top to bottom
        if chains and band.cy - chains[-1][-1].cy <= 2.5 * max(height(band), height(chains[-1][-1])):
            chains[-1].append(band)
        else:
            chains.append([band])
    return [b for chain in chains if len(chain) < WALL_BANDS for b in chain]


def _always_there(band: _Band, found: list[tuple[int, TextLine]], n: int) -> bool:
    """True if the band's main text is on screen in most frames, judged on lines of *any* size.

    Text near the size threshold (a header, a logo) can count as "large" in only a few frames;
    looking at those frames alone would make a fixed header look like a short-lived title card.
    """
    texts = band.texts_by_sample()
    if not texts:
        return False
    main = Counter(texts.values()).most_common(1)[0][0]
    words = set(main.split())
    lo = min(ln.box[1] for _, ln in band.lines)
    hi = max(ln.box[3] for _, ln in band.lines)
    frames = {i for i, ln in found if lo - 0.01 <= ln.cy <= hi + 0.01 and words & set(text_key(ln.text).split())}
    return len(frames) / n >= 0.6


def _select_bands(found: list[tuple[int, TextLine]], n: int) -> Region | None:
    if not found:
        return None
    # Reference size: the largest text in each sampled frame (usually the caption), taken at the
    # median across frames. A global percentile over all lines drifts towards small UI labels when
    # a video has lots of them and only one caption line per frame.
    per_frame: dict[int, float] = {}
    for i, ln in found:
        per_frame[i] = max(per_frame.get(i, 0.0), ln.height)
    big = float(np.median(list(per_frame.values())))
    large = [(i, ln) for i, ln in found if ln.height >= max(MIN_CAPTION_HEIGHT, SIZE_RATIO * big)]
    chosen: list[tuple[_Band, float]] = []
    static: list[tuple[float, str]] = []
    for band in _drop_text_walls(_cluster(large)):
        per = band.texts_by_sample()
        presence = len(per) / n
        distinct = len(set(per.values()))
        if _always_there(band, found, n):
            static.append((band.cy, Counter(per.values()).most_common(1)[0][0]))  # header / logo / watermark
            continue
        if distinct < 2 and presence >= 0.5:
            static.append((band.cy, next(iter(per.values()))))  # logo / title / watermark
            continue
        change_ratio = distinct / len(per)
        if presence >= 0.4 and change_ratio < 0.3:
            continue  # slow-changing label, not narration
        chosen.append((band, presence * change_ratio if presence >= 0.4 else 0.25))
    if not chosen:
        return None

    spans = sorted(_band_box(b) for b, _ in chosen)
    merged: list[list[float]] = []
    for y0, y1 in spans:
        if merged and y0 <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], y1)
        else:
            merged.append([y0, y1])
    boxes = [Box(x=0.0, y=round(y0, 4), w=1.0, h=round(y1 - y0, 4)) for y0, y1 in merged]
    top, bottom = merged[0][0], merged[-1][1]
    ignore = [t for cy, t in static if any(b.y <= cy <= b.y + b.h for b in boxes)]
    return Region(
        x=0.0, y=round(top, 4), w=1.0, h=round(bottom - top, 4), auto=True,
        confidence=round(min(1.0, max(score for _, score in chosen) / 0.3), 3),
        ignore_texts=ignore, boxes=boxes if len(boxes) > 1 else [],
    )


def _single_best_band(found: list[tuple[int, TextLine]], n: int) -> Region:
    """Fallback when no text looks caption-sized: the most caption-like band of any size."""
    best, best_score = None, 0.0
    static_texts: list[tuple[float, str]] = []
    for band in _cluster(found):
        per = band.texts_by_sample()
        presence = len(per) / n
        distinct = len(set(per.values()))
        if distinct < 2:
            if presence >= 0.5:
                static_texts.append((band.cy, next(iter(per.values()))))
            continue
        change_ratio = distinct / len(per)
        score = presence**0.5 * change_ratio * (0.5 + 0.5 * band.cy)
        if score > best_score:
            best, best_score = band, score

    if best is None:
        return Region(confidence=0.0, ignore_texts=[t for _, t in static_texts])
    y0, y1 = _band_box(best)
    ignore = [t for cy, t in static_texts if y0 <= cy <= y1]
    return Region(
        x=0.0, y=round(y0, 4), w=1.0, h=round(y1 - y0, 4), auto=True,
        confidence=round(min(1.0, best_score / 0.4), 3), ignore_texts=ignore,
    )
