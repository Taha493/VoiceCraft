"""Turn per-sample OCR readings into caption segments.

Rules:
- Consecutive readings belong to the same caption when their text is similar, or when one is a
  word-prefix of the other (typewriter / word-by-word reveals, fade-ins read half-way).
- A caption is "settled" once its final text was read in at least two samples. Single-sample
  readings are dropped unless very confident, and are then flagged for review.
- A one-sample dropout inside a caption (OCR miss, flicker) is bridged.
- Timestamps are midpoints between the last sample without and the first sample with the text,
  so error is bounded by half the sample interval.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from ..schema import Caption

_NON_ALNUM = re.compile(r"[^0-9a-z]+")


@dataclass(frozen=True)
class Observation:
    t: float
    text: str
    score: float = 1.0

    @property
    def key(self) -> str:
        return text_key(self.text)


def text_key(text: str) -> str:
    return _NON_ALNUM.sub(" ", text.lower()).strip()


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 1.0 if a == b else 0.0
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def continues(prev_key: str, key: str, threshold: float = 0.8) -> bool:
    if similarity(prev_key, key) >= threshold:
        return True
    short, long_ = sorted((prev_key, key), key=len)
    sw, lw = short.split(), long_.split()
    if not sw:
        return False
    if lw[: len(sw)] == sw:
        return True
    # OCR noise during a reveal: compare the shorter text with the same-length head of the longer.
    return len(short) >= 6 and similarity(short, long_[: len(short)]) >= 0.85


@dataclass
class _Run:
    obs: list[Observation] = field(default_factory=list)

    @property
    def first_t(self) -> float:
        return self.obs[0].t

    @property
    def last_t(self) -> float:
        return self.obs[-1].t

    @property
    def last_key(self) -> str:
        return self.obs[-1].key


def _final_variant(run: _Run) -> tuple[str, Observation, int]:
    counts = Counter(o.key for o in run.obs)
    settled = [k for k, c in counts.items() if c >= 2]
    pool = settled or list(counts)
    max_words = max(len(k.split()) for k in pool)
    finalists = [k for k in pool if len(k.split()) >= max_words - 1]
    best_key = max(finalists, key=lambda k: (counts[k], len(k)))
    # Prefer the longest settled reading when it is a strict extension of the most frequent one.
    longest = max(finalists, key=len)
    if longest != best_key and longest.startswith(best_key) and counts[longest] >= 2:
        best_key = longest
    best_obs = max((o for o in run.obs if o.key == best_key), key=lambda o: o.score)
    return best_key, best_obs, counts[best_key]


def build_captions(
    observations: list[Observation],
    dt: float,
    duration: float,
    min_single_score: float = 0.9,
    flag_below: float = 0.75,
) -> list[Caption]:
    eps = dt * 0.25
    runs: list[_Run] = []
    cur: _Run | None = None
    for ob in observations:
        if not ob.key:
            cur = None
            continue
        if cur and ob.t - cur.last_t <= dt + eps and continues(cur.last_key, ob.key):
            cur.obs.append(ob)
        else:
            cur = _Run([ob])
            runs.append(cur)

    # Bridge single-sample dropouts.
    merged: list[_Run] = []
    for run in runs:
        if merged:
            prev = merged[-1]
            gap = run.first_t - prev.last_t
            if gap <= 2 * dt + eps and continues(_final_variant(prev)[0], run.obs[0].key):
                prev.obs.extend(run.obs)
                continue
        merged.append(run)

    captions: list[Caption] = []
    for run in merged:
        key, best, count = _final_variant(run)
        matching = [o.score for o in run.obs if o.key == key]
        conf = sum(matching) / len(matching) * min(1.0, count / 2)
        reason = None
        if count < 2:
            if len(run.obs) == 1 and best.score < min_single_score:
                continue
            reason = "Seen in only one sample"
        alpha = sum(ch.isalpha() for ch in best.text)
        if alpha < 2:
            continue
        if alpha / max(1, len(best.text.replace(" ", ""))) < 0.6:
            reason = reason or "Unusual characters"
        if conf < flag_below:
            reason = reason or "Low OCR confidence"
        start = max(0.0, run.first_t - dt / 2)
        end = min(duration, run.last_t + dt / 2)
        captions.append(
            Caption(
                id=f"c{len(captions) + 1}",
                start=round(start, 3),
                end=round(max(end, start + dt), 3),
                text=fix_ocr_confusions(clean_text(best.text)),
                confidence=round(conf, 3),
                flagged=reason is not None,
                flag_reason=reason,
            )
        )
    return captions


def clean_text(text: str) -> str:
    t = re.sub(r"\s+", " ", text).strip()
    t = re.sub(r"\s+([,.!?;:])", r"\1", t)
    return t


def fix_ocr_confusions(text: str) -> str:
    """Correct look-alike misreads that would change what the voice says.

    In most sans-serif fonts a capital I and a lowercase l are identical, so "AI" is read as "Al"
    (which the voice would pronounce like the name). In product-video captions the standalone word
    is almost always "AI". Only applied to OCR output, never to imported caption files.
    """
    return re.sub(r"\bAl(?=\b|-)", "AI", text)
