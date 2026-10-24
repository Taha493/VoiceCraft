"""Paths and runtime limits shared by every stage."""

from __future__ import annotations

import os
from pathlib import Path


def data_home() -> Path:
    root = os.environ.get("VOICECRAFT_HOME")
    if root:
        return Path(root).expanduser()
    xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(xdg) / "voicecraft"


def models_dir() -> Path:
    return data_home() / "models"


def cache_dir() -> Path:
    env = os.environ.get("VOICECRAFT_CACHE")
    return Path(env).expanduser() if env else data_home() / "cache"


def jobs_dir() -> Path:
    return data_home() / "jobs"


def lexicon_path() -> Path:
    return data_home() / "lexicon.json"


def cpu_threads() -> int:
    """Thread budget for inference. Physical cores on the target laptop are 4."""
    env = os.environ.get("VOICECRAFT_THREADS")
    if env:
        return max(1, int(env))
    logical = os.cpu_count() or 2
    return max(1, min(4, logical // 2 or 1))


def limit_threads(n: int | None = None) -> None:
    """Cap BLAS/OpenMP pools before numpy/onnxruntime/torch are imported in a worker."""
    n = n or cpu_threads()
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ.setdefault(var, str(n))


def force_offline() -> None:
    """Normal processing must never reach the network; models come from `voicecraft setup`."""
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
