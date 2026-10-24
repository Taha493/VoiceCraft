"""Common TTS interface. The sync pipeline only ever talks to `TTSEngine`."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass

import numpy as np


@dataclass(frozen=True)
class VoiceInfo:
    id: str
    name: str
    language: str
    gender: str
    license: str
    engine: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Speech:
    audio: np.ndarray  # float32 mono, trimmed of leading/trailing silence
    sample_rate: int

    @property
    def duration(self) -> float:
        return len(self.audio) / self.sample_rate


class TTSEngine(ABC):
    name: str
    model_id: str  # changes whenever output for the same text could change (cache key)
    sample_rate: int

    @abstractmethod
    def voices(self) -> list[VoiceInfo]: ...

    @abstractmethod
    def _synthesize(self, text: str, voice: str, speed: float, sentence_pause: float) -> np.ndarray: ...

    def synthesize(self, text: str, voice: str, speed: float = 1.0, sentence_pause: float = 0.3) -> Speech:
        audio = self._synthesize(text, voice, speed, sentence_pause).astype(np.float32, copy=False)
        return Speech(trim_silence(audio, self.sample_rate), self.sample_rate)

    def close(self) -> None:
        pass


def trim_silence(audio: np.ndarray, sr: int, threshold_db: float = -45.0, pad_s: float = 0.03) -> np.ndarray:
    """Strip edge silence so measured duration reflects actual speech."""
    if audio.size == 0:
        return audio
    win = max(1, int(sr * 0.01))
    n = len(audio) // win
    if n == 0:
        return audio
    frames = audio[: n * win].reshape(n, win)
    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1) + 1e-12)
    peak = rms.max()
    if peak <= 0:
        return audio[:0]
    loud = np.nonzero(20 * np.log10(rms / peak) > threshold_db)[0]
    if loud.size == 0:
        return audio[:0]
    pad = int(sr * pad_s)
    start = max(0, loud[0] * win - pad)
    end = min(len(audio), (loud[-1] + 1) * win + pad)
    return audio[start:end]
