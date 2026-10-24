"""Cached synthesis. A clip is only generated once per (engine model, voice, speed, pause, text)."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

import soundfile as sf

from .. import config
from ..tts.base import TTSEngine


@dataclass(frozen=True)
class Clip:
    path: Path
    duration: float
    cached: bool


class CachedSynth:
    def __init__(self, engine: TTSEngine, voice: str, clips_dir: Path, cache_dir: Path | None = None):
        self.engine = engine
        self.voice = voice
        self.clips_dir = clips_dir
        self.cache_dir = (cache_dir or config.cache_dir()) / "tts"
        self.clips_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.generated = 0
        self.reused = 0

    def key(self, text: str, speed: float, pause: float) -> str:
        payload = json.dumps([self.engine.model_id, self.voice, round(speed, 3), round(pause, 3), text])
        return hashlib.sha256(payload.encode()).hexdigest()[:20]

    def __call__(self, text: str, speed: float, pause: float) -> Clip:
        key = self.key(text, speed, pause)
        cached = self.cache_dir / f"{key}.wav"
        hit = cached.exists()
        if not hit:
            speech = self.engine.synthesize(text, self.voice, speed=speed, sentence_pause=pause)
            tmp = cached.with_suffix(".tmp.wav")
            sf.write(tmp, speech.audio, speech.sample_rate, subtype="FLOAT")
            os.replace(tmp, cached)
            self.generated += 1
        else:
            self.reused += 1
        dest = self.clips_dir / cached.name
        if not dest.exists():
            try:
                os.link(cached, dest)
            except OSError:
                shutil.copyfile(cached, dest)
        return Clip(dest, sf.info(dest).duration, hit)
