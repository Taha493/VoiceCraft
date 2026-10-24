"""On-disk job state. Every stage reads and writes files in the job directory, so a failed stage
can be retried without repeating earlier ones, and progress survives a server restart.

    jobs/<id>/job.json        settings + per-stage status
    jobs/<id>/input.<ext>     the original video (never modified)
    jobs/<id>/captions.json   editable caption track
    jobs/<id>/timeline.json   narration plan
    jobs/<id>/clips/          synthesized segments
    jobs/<id>/output.mp4      final render
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any, BinaryIO, Literal

from pydantic import BaseModel, Field

from .. import config
from ..sync.presets import DEFAULT_PRESET
from ..tts import DEFAULT_ENGINE, DEFAULT_VOICE

StageName = Literal["captions", "narrate", "render"]
STAGES: tuple[StageName, ...] = ("captions", "narrate", "render")
StageStatus = Literal["pending", "queued", "running", "done", "error", "stale"]


class StageState(BaseModel):
    status: StageStatus = "pending"
    progress: float = 0.0
    message: str = ""
    error: str | None = None
    started: float | None = None
    finished: float | None = None
    result: dict = Field(default_factory=dict)


class Settings(BaseModel):
    has_burned_captions: bool = True  # False: captions come from an uploaded file or script, no OCR
    engine: str = DEFAULT_ENGINE
    voice: str = DEFAULT_VOICE[DEFAULT_ENGINE]
    preset: str = DEFAULT_PRESET
    allow_holds: bool = True
    audio_mode: Literal["duck", "replace", "mix"] = "duck"
    sample_fps: float = 4.0
    ocr: str = "rapidocr"
    music: str = "auto"  # "auto" (mood-matched, varies per video), "none", or a track id
    music_level: Literal["low", "medium", "high"] = "medium"


class Job(BaseModel):
    id: str
    name: str
    created: float
    video_file: str
    info: dict = Field(default_factory=dict)
    settings: Settings = Field(default_factory=Settings)
    stages: dict[str, StageState] = Field(default_factory=lambda: {s: StageState() for s in STAGES})


class JobStore:
    def __init__(self, root: Path | None = None):
        self.root = root or config.jobs_dir()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def dir(self, job_id: str) -> Path:
        if not job_id or "/" in job_id or ".." in job_id:
            raise KeyError(job_id)
        return self.root / job_id

    def _write(self, job: Job) -> None:
        path = self.dir(job.id) / "job.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(job.model_dump_json(indent=2))
        os.replace(tmp, path)

    def create(self, name: str, source: Path | BinaryIO, suffix: str) -> Job:
        from ..media.probe import probe

        job_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        d = self.dir(job_id)
        d.mkdir(parents=True)
        video = d / f"input{suffix.lower() or '.mp4'}"
        try:
            if isinstance(source, Path):
                try:
                    os.link(source, video)  # same filesystem: no copy, original untouched
                except OSError:
                    shutil.copyfile(source, video)
            else:
                with video.open("wb") as f:
                    shutil.copyfileobj(source, f, 1 << 20)
            info = probe(video).to_dict()
        except Exception:
            shutil.rmtree(d, ignore_errors=True)
            raise
        info.pop("path", None)
        # Videos that already have sound (often their own music) get no extra music by default.
        settings = Settings(music="none" if info.get("has_audio") else "auto")
        job = Job(id=job_id, name=name, created=time.time(), video_file=video.name, info=info, settings=settings)
        with self._lock:
            self._write(job)
        return job

    def get(self, job_id: str) -> Job:
        path = self.dir(job_id) / "job.json"
        if not path.exists():
            raise KeyError(job_id)
        with self._lock:
            return Job.model_validate_json(path.read_text())

    def list(self) -> list[Job]:
        jobs = []
        for p in sorted(self.root.glob("*/job.json"), reverse=True):
            try:
                jobs.append(Job.model_validate_json(p.read_text()))
            except ValueError:
                continue
        return jobs

    def update(self, job_id: str, **changes: Any) -> Job:
        with self._lock:
            job = self.get(job_id)
            for k, v in changes.items():
                setattr(job, k, v)
            self._write(job)
            return job

    def update_stage(self, job_id: str, stage: str, **changes: Any) -> Job:
        with self._lock:
            job = self.get(job_id)
            st = job.stages[stage]
            for k, v in changes.items():
                setattr(st, k, v)
            self._write(job)
            return job

    def invalidate_after(self, job_id: str, stage: str) -> None:
        """Mark later stages stale after an upstream change (captions edited, voice changed...)."""
        with self._lock:
            job = self.get(job_id)
            for s in STAGES[STAGES.index(stage) + 1 :]:
                if job.stages[s].status == "done":
                    job.stages[s].status = "stale"
            self._write(job)

    def delete(self, job_id: str) -> None:
        shutil.rmtree(self.dir(job_id), ignore_errors=True)

    # Convenience file accessors
    def read_json(self, job_id: str, name: str) -> dict | None:
        p = self.dir(job_id) / name
        return json.loads(p.read_text()) if p.exists() else None

    def write_json(self, job_id: str, name: str, data: dict) -> None:
        p = self.dir(job_id) / name
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        os.replace(tmp, p)
