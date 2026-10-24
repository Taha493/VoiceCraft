from __future__ import annotations

from .base import Speech, TTSEngine, VoiceInfo

ENGINES = ("kokoro", "piper")
DEFAULT_ENGINE = "kokoro"
DEFAULT_VOICE = {"kokoro": "af_heart", "piper": "en_US-joe-medium"}


def load_engine(name: str = DEFAULT_ENGINE, **kwargs) -> TTSEngine:
    """Instantiate one engine. Callers keep at most one alive (one model in RAM)."""
    if name == "kokoro":
        from .kokoro_engine import KokoroOnnxEngine

        return KokoroOnnxEngine(**kwargs)
    if name == "kokoro-torch":
        from .kokoro_engine import KokoroTorchEngine

        return KokoroTorchEngine(**kwargs)
    if name == "piper":
        from .piper_engine import PiperEngine

        return PiperEngine(**kwargs)
    raise ValueError(f"Unknown TTS engine: {name}")


def list_voices(name: str) -> list[VoiceInfo]:
    """Voice metadata without loading a model."""
    if name in ("kokoro", "kokoro-torch"):
        from .kokoro_engine import _voice_infos

        return _voice_infos(name)
    if name == "piper":
        from .. import assets
        from .piper_engine import _VOICES

        return [
            VoiceInfo(v, n, lang, g, assets.ASSETS[f"piper:{v}"].license, "piper")
            for v, (n, lang, g) in _VOICES.items()
        ]
    raise ValueError(f"Unknown TTS engine: {name}")


__all__ = ["Speech", "TTSEngine", "VoiceInfo", "load_engine", "list_voices", "ENGINES", "DEFAULT_ENGINE", "DEFAULT_VOICE"]
