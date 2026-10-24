"""Piper (piper1-gpl, GPL-3.0) — optional speed-oriented fallback. Install with the `piper` extra."""

from __future__ import annotations

import json

import numpy as np

from .. import assets, config
from .base import TTSEngine, VoiceInfo

_VOICES = {
    "en_US-joe-medium": ("Joe", "en-us", "male"),
    "en_US-libritts_r-medium": ("LibriTTS-R", "en-us", "mixed"),
}


class PiperEngine(TTSEngine):
    name = "piper"

    def __init__(self, threads: int | None = None):
        import onnxruntime as rt  # noqa: F401  (piper builds its own session)
        from piper import PiperVoice, SynthesisConfig

        self._PiperVoice = PiperVoice
        self._SynthesisConfig = SynthesisConfig
        self._loaded: dict[str, object] = {}
        self._threads = threads or config.cpu_threads()
        self.sample_rate = 22050
        self.model_id = "piper-1.8"

    def _voice(self, voice: str):
        if voice not in self._loaded:
            # Only one voice model stays loaded at a time.
            self._loaded.clear()
            model = assets.require(f"piper:{voice}")
            assets.require(f"piper:{voice}:config")
            loaded = self._PiperVoice.load(model)
            self.sample_rate = json.loads(model.with_suffix(".onnx.json").read_text())["audio"]["sample_rate"]
            self._loaded[voice] = loaded
        return self._loaded[voice]

    def voices(self) -> list[VoiceInfo]:
        out = []
        for vid, (name, lang, gender) in _VOICES.items():
            lic = assets.ASSETS[f"piper:{vid}"].license
            out.append(VoiceInfo(vid, name, lang, gender, lic, self.name))
        return out

    def _synthesize(self, text: str, voice: str, speed: float, sentence_pause: float) -> np.ndarray:
        pv = self._voice(voice)
        cfg = self._SynthesisConfig(length_scale=1.0 / max(0.5, min(2.0, speed)))
        gap = np.zeros(int(sentence_pause * self.sample_rate), dtype=np.float32)
        parts: list[np.ndarray] = []
        for chunk in pv.synthesize(text, syn_config=cfg):
            if parts:
                parts.append(gap)
            parts.append(chunk.audio_float_array)
        return np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)
