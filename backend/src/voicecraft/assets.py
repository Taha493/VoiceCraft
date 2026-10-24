"""Model files: where they live, how `voicecraft setup` fetches them, and whether they are present.

Downloads happen only here. Processing stages call `require()` and fail with a clear message
instead of silently reaching the network.
"""

from __future__ import annotations

import shutil
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import config

KOKORO_RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1"
PIPER_VOICES = "https://huggingface.co/rhasspy/piper-voices/resolve/main"


@dataclass(frozen=True)
class Asset:
    key: str
    filename: str
    url: str
    size_mb: float
    license: str

    @property
    def path(self) -> Path:
        return config.models_dir() / self.filename


def _piper(lang: str, name: str, quality: str, license: str, size_mb: float) -> list[Asset]:
    family = lang.split("_")[0]
    base = f"{PIPER_VOICES}/{family}/{lang}/{name}/{quality}/{lang}-{name}-{quality}"
    fname = f"piper/{lang}-{name}-{quality}"
    return [
        Asset(f"piper:{lang}-{name}-{quality}", f"{fname}.onnx", f"{base}.onnx", size_mb, license),
        Asset(f"piper:{lang}-{name}-{quality}:config", f"{fname}.onnx.json", f"{base}.onnx.json", 0.01, license),
    ]


ASSETS: dict[str, Asset] = {
    a.key: a
    for a in [
        Asset("kokoro:fp32", "kokoro/kokoro-v1.0.onnx", f"{KOKORO_RELEASE}/kokoro-v1.0.onnx", 325.5, "Apache-2.0"),
        Asset("kokoro:fp16", "kokoro/kokoro-v1.0.fp16.onnx", f"{KOKORO_RELEASE}/kokoro-v1.0.fp16.onnx", 163.5, "Apache-2.0"),
        Asset("kokoro:int8", "kokoro/kokoro-v1.0.int8.onnx", f"{KOKORO_RELEASE}/kokoro-v1.0.int8.onnx", 114.1, "Apache-2.0"),
        Asset("kokoro:voices", "kokoro/voices-v1.0.bin", f"{KOKORO_RELEASE}/voices-v1.0.bin", 28.2, "Apache-2.0"),
        # Piper voices carry the license of their training dataset (checked against each MODEL_CARD).
        # Popular voices such as lessac (Blizzard research license) and ryan (CC BY-NC-SA) are
        # deliberately not offered.
        *_piper("en_US", "joe", "medium", "CC0-1.0", 63.0),
        *_piper("en_US", "libritts_r", "medium", "CC-BY-4.0", 78.0),
    ]
}


class MissingModelError(RuntimeError):
    pass


def require(key: str) -> Path:
    asset = ASSETS[key]
    if not asset.path.exists():
        raise MissingModelError(
            f"Model file '{asset.filename}' is missing. Run `voicecraft setup` once while online."
        )
    return asset.path


def present(key: str) -> bool:
    return ASSETS[key].path.exists()


def download(key: str, progress: Callable[[str, float], None] | None = None) -> Path:
    asset = ASSETS[key]
    dest = asset.path
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=dest.parent, delete=False, suffix=".part") as tmp:
        tmp_path = Path(tmp.name)
        try:
            with urllib.request.urlopen(asset.url, timeout=60) as resp:
                total = int(resp.headers.get("Content-Length") or 0)
                done = 0
                while chunk := resp.read(1 << 20):
                    tmp.write(chunk)
                    done += len(chunk)
                    if progress and total:
                        progress(asset.filename, done / total)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise
    shutil.move(tmp_path, dest)
    return dest
