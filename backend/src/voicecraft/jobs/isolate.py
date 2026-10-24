"""Run a stage in a fresh child process.

Python seldom returns freed model memory to the OS, so the OCR and TTS models live only in a child
that exits when its stage finishes. The child also gets capped thread pools and is forced
offline.
"""

from __future__ import annotations

import multiprocessing as mp
import queue
import resource
import traceback
from pathlib import Path
from typing import Callable


class StageError(RuntimeError):
    def __init__(self, message: str, detail: str = ""):
        super().__init__(message)
        self.detail = detail


class Cancelled(RuntimeError):
    pass


def _child(stage: str, job_dir: str, q: mp.Queue) -> None:
    from .. import config

    config.limit_threads()
    config.force_offline()
    try:
        from .stages import STAGE_FUNCS

        def progress(message: str, frac: float) -> None:
            q.put(("progress", message, float(frac)))

        result = STAGE_FUNCS[stage](Path(job_dir), progress)
        result = dict(result or {})
        result["peak_rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
        q.put(("done", result))
    except BaseException as e:  # noqa: BLE001 - report everything to the parent
        q.put(("error", f"{e}", traceback.format_exc()))


def run_stage(
    stage: str,
    job_dir: Path,
    on_progress: Callable[[str, float], None],
    should_cancel: Callable[[], bool] = lambda: False,
) -> dict:
    ctx = mp.get_context("spawn")
    q: mp.Queue = ctx.Queue()
    proc = ctx.Process(target=_child, args=(stage, str(job_dir), q), daemon=True)
    proc.start()
    try:
        while True:
            if should_cancel():
                proc.terminate()
                raise Cancelled("Cancelled")
            try:
                msg = q.get(timeout=0.25)
            except queue.Empty:
                if not proc.is_alive():
                    # Drain anything sent just before exit.
                    try:
                        msg = q.get(timeout=0.5)
                    except queue.Empty:
                        raise StageError(f"The {stage} worker exited unexpectedly (code {proc.exitcode}). It may have run out of memory.")
                else:
                    continue
            kind = msg[0]
            if kind == "progress":
                on_progress(msg[1], msg[2])
            elif kind == "done":
                return msg[1]
            elif kind == "error":
                raise StageError(msg[1], msg[2])
    finally:
        proc.join(timeout=5)
        if proc.is_alive():
            proc.kill()
