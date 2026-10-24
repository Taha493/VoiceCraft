"""Kokoro-82M via ONNX Runtime (default) or the reference PyTorch package (benchmark only).

Kokoro has no emotion, style or SSML controls. The levers we have are voice, speed and the
pauses inserted between sentences, and VoiceCraft's delivery presets are built from those.
"""

from __future__ import annotations

import numpy as np

from .. import assets, config
from .base import TTSEngine, VoiceInfo

SAMPLE_RATE = 24000

# American (a*) and British (b*) English voices from Kokoro v1.0. Weights are Apache-2.0.
_VOICES = [
    ("af_heart", "Heart", "en-us", "female"),
    ("af_bella", "Bella", "en-us", "female"),
    ("af_nicole", "Nicole", "en-us", "female"),
    ("af_sarah", "Sarah", "en-us", "female"),
    ("af_sky", "Sky", "en-us", "female"),
    ("am_michael", "Michael", "en-us", "male"),
    ("am_fenrir", "Fenrir", "en-us", "male"),
    ("am_puck", "Puck", "en-us", "male"),
    ("am_adam", "Adam", "en-us", "male"),
    ("bf_emma", "Emma", "en-gb", "female"),
    ("bf_isabella", "Isabella", "en-gb", "female"),
    ("bm_george", "George", "en-gb", "male"),
    ("bm_fable", "Fable", "en-gb", "male"),
]


def _voice_infos(engine: str) -> list[VoiceInfo]:
    return [VoiceInfo(v, n, lang, g, "Apache-2.0", engine) for v, n, lang, g in _VOICES]


class KokoroOnnxEngine(TTSEngine):
    name = "kokoro"
    sample_rate = SAMPLE_RATE

    def __init__(self, precision: str = "fp32", threads: int | None = None, g2p: str = "misaki"):
        import onnxruntime as rt
        from kokoro_onnx import Kokoro

        model = assets.require(f"kokoro:{precision}")
        voices = assets.require("kokoro:voices")
        opts = rt.SessionOptions()
        opts.intra_op_num_threads = threads or config.cpu_threads()
        opts.inter_op_num_threads = 1
        opts.graph_optimization_level = rt.GraphOptimizationLevel.ORT_ENABLE_ALL
        session = rt.InferenceSession(str(model), sess_options=opts, providers=["CPUExecutionProvider"])
        self._kokoro = Kokoro.from_session(session, str(voices))
        self.model_id = f"kokoro-onnx-v1.0-{precision}-{g2p}"
        self._lang = {v: lang for v, _, lang, _ in _VOICES}
        self._g2p_kind = g2p
        self._g2ps: dict[bool, object] = {}

    def _misaki(self, british: bool):
        """misaki G2P (what Kokoro was trained on), with espeak-ng for out-of-vocabulary words."""
        if british not in self._g2ps:
            from misaki import en, espeak

            self._g2ps[british] = en.G2P(trf=False, british=british, fallback=espeak.EspeakFallback(british=british))
        return self._g2ps[british]

    def voices(self) -> list[VoiceInfo]:
        return _voice_infos(self.name)

    def _synthesize(self, text: str, voice: str, speed: float, sentence_pause: float) -> np.ndarray:
        lang = self._lang.get(voice, "en-us")
        is_phonemes = self._g2p_kind == "misaki"
        payload = self._misaki(lang == "en-gb")(text)[0] if is_phonemes else text
        audio, _ = self._kokoro.create(
            payload,
            voice=voice,
            speed=float(np.clip(speed, 0.5, 2.0)),
            lang=lang,
            is_phonemes=is_phonemes,
            sentence_pause=sentence_pause,
            clause_pause=min(0.12, sentence_pause / 2),
        )
        return audio


class KokoroTorchEngine(TTSEngine):
    """Reference implementation (misaki G2P). Heavier; downloads from Hugging Face on first use."""

    name = "kokoro-torch"
    sample_rate = SAMPLE_RATE
    model_id = "kokoro-torch-0.9.4"

    def __init__(self, threads: int | None = None):
        import torch
        from kokoro import KPipeline

        torch.set_num_threads(threads or config.cpu_threads())
        self._pipes: dict[str, object] = {}
        self._KPipeline = KPipeline

    def _pipe(self, voice: str):
        code = voice[0]
        if code not in self._pipes:
            self._pipes[code] = self._KPipeline(lang_code=code, repo_id="hexgrad/Kokoro-82M")
        return self._pipes[code]

    def voices(self) -> list[VoiceInfo]:
        return _voice_infos(self.name)

    def _synthesize(self, text: str, voice: str, speed: float, sentence_pause: float) -> np.ndarray:
        parts = []
        gap = np.zeros(int(sentence_pause * SAMPLE_RATE), dtype=np.float32)
        for _, _, audio in self._pipe(voice)(text, voice=voice, speed=speed, split_pattern=r"(?<=[.!?])\s+"):
            if parts:
                parts.append(gap)
            parts.append(audio.numpy() if hasattr(audio, "numpy") else np.asarray(audio))
        return np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)
