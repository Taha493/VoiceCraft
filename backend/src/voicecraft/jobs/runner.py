"""Single-worker job queue. One stage runs at a time, keeping peak memory bounded on 8 GB machines."""

from __future__ import annotations

import logging
import queue
import threading
import time

from .isolate import Cancelled, StageError, run_stage
from .store import STAGES, JobStore

log = logging.getLogger("voicecraft.runner")


class JobRunner:
    def __init__(self, store: JobStore):
        self.store = store
        self._q: queue.Queue[tuple[str, list[str]]] = queue.Queue()
        self._cancel: set[str] = set()
        self._current: str | None = None
        self._thread = threading.Thread(target=self._loop, name="voicecraft-runner", daemon=True)
        self._thread.start()

    @property
    def current(self) -> str | None:
        return self._current

    def submit(self, job_id: str, stages: list[str]) -> None:
        stages = [s for s in STAGES if s in stages]
        for s in stages:
            self.store.update_stage(job_id, s, status="queued", progress=0.0, message="Waiting", error=None)
        self._cancel.discard(job_id)
        self._q.put((job_id, stages))

    def cancel(self, job_id: str) -> None:
        self._cancel.add(job_id)

    def recover(self) -> None:
        """After a restart, anything left running/queued is marked as interrupted."""
        for job in self.store.list():
            for name, st in job.stages.items():
                if st.status in ("running", "queued"):
                    self.store.update_stage(job.id, name, status="error", error="Interrupted (server restarted). Run it again.")

    def _loop(self) -> None:
        while True:
            job_id, stages = self._q.get()
            self._current = job_id
            try:
                self._run(job_id, stages)
            except Exception:  # noqa: BLE001
                log.exception("job %s failed", job_id)
            finally:
                self._current = None

    def _run(self, job_id: str, stages: list[str]) -> None:
        for i, stage in enumerate(stages):
            if job_id in self._cancel:
                for s in stages[i:]:
                    self.store.update_stage(job_id, s, status="pending", message="Cancelled")
                return
            self.store.update_stage(job_id, stage, status="running", progress=0.0, message="Starting", started=time.time(), error=None)
            last = [0.0]

            def on_progress(message: str, frac: float, stage: str = stage) -> None:
                now = time.monotonic()
                if now - last[0] > 0.3 or frac >= 1.0:
                    last[0] = now
                    self.store.update_stage(job_id, stage, progress=round(frac, 3), message=message)

            try:
                result = run_stage(stage, self.store.dir(job_id), on_progress, lambda: job_id in self._cancel)
            except Cancelled:
                self.store.update_stage(job_id, stage, status="pending", message="Cancelled", progress=0.0)
                for s in stages[i + 1 :]:
                    self.store.update_stage(job_id, s, status="pending", message="")
                return
            except StageError as e:
                log.error("stage %s failed for %s: %s\n%s", stage, job_id, e, e.detail)
                self.store.update_stage(job_id, stage, status="error", error=str(e), message="Failed", finished=time.time())
                for s in stages[i + 1 :]:
                    self.store.update_stage(job_id, s, status="pending", message="")
                return
            self.store.update_stage(job_id, stage, status="done", progress=1.0, message="Done", finished=time.time(), result=result)
            if i == len(stages) - 1:
                # Downstream stages that were not part of this run now describe old inputs.
                self.store.invalidate_after(job_id, stage)
