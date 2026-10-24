"""HTTP API for the web UI. Heavy work never runs in this process: the runner hands each stage
to a short-lived child process, one at a time.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Literal

import psutil
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import assets, music, tts
from ..captions.importers import align_script, pace_script, parse_any
from ..captions.ocr import available_ocr
from ..jobs.runner import JobRunner
from ..jobs.store import STAGES, Job, JobStore, Settings
from ..media.frames import grab_frame
from ..media.probe import MediaError, file_fingerprint
from ..schema import Caption, CaptionTrack, Region, Timeline
from ..sync.presets import PRESETS
from ..text.lexicon import DEFAULTS as LEXICON_DEFAULTS
from ..text.lexicon import load_user_entries, save_user_entries

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
NARRATE_KEYS = {"engine", "voice", "preset", "allow_holds"}
RENDER_KEYS = {"audio_mode", "music", "music_level"}
CAPTION_KEYS = {"sample_fps", "ocr"}


class RunRequest(BaseModel):
    stages: list[Literal["captions", "narrate", "render"]]


class CaptionsUpdate(BaseModel):
    captions: list[Caption]


class ScriptRequest(BaseModel):
    script: str


class RegionUpdate(BaseModel):
    x: float
    y: float
    w: float
    h: float


def _frontend_dir() -> Path | None:
    env = os.environ.get("VOICECRAFT_FRONTEND")
    candidates = [Path(env)] if env else []
    candidates.append(Path(__file__).resolve().parents[4] / "frontend" / "dist")
    return next((p for p in candidates if (p / "index.html").exists()), None)


def create_app(store: JobStore | None = None) -> FastAPI:
    store = store or JobStore()
    runner = JobRunner(store)
    runner.recover()
    app = FastAPI(title="VoiceCraft", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.store = store
    app.state.runner = runner

    def job_or_404(job_id: str) -> Job:
        try:
            return store.get(job_id)
        except KeyError:
            raise HTTPException(404, "Job not found")

    def busy(job: Job) -> bool:
        return any(st.status in ("running", "queued") for st in job.stages.values())

    def caption_track(job: Job) -> CaptionTrack | None:
        p = store.dir(job.id) / "captions.json"
        return CaptionTrack.model_validate_json(p.read_text()) if p.exists() else None

    def save_track(job: Job, track: CaptionTrack, result: dict) -> None:
        track.captions.sort(key=lambda c: c.start)
        (store.dir(job.id) / "captions.json").write_text(track.model_dump_json(indent=2))
        store.update_stage(job.id, "captions", status="done", progress=1.0, message="Done", error=None, finished=time.time(), result=result)
        store.invalidate_after(job.id, "captions")

    # ---- system ---------------------------------------------------------------------------
    @app.get("/api/health")
    def health():
        vm = psutil.virtual_memory()
        return {
            "ok": True,
            "models_ready": assets.present("kokoro:fp32") and assets.present("kokoro:voices"),
            "piper_ready": assets.present("piper:en_US-joe-medium"),
            "ocr_engines": available_ocr(),
            "ram_available_gb": round(vm.available / 2**30, 2),
            "ram_total_gb": round(vm.total / 2**30, 2),
            "busy_job": runner.current,
            "music_tracks": len(music.installed()),
        }

    @app.get("/api/options")
    def options():
        return {
            "engines": [
                {"id": "kokoro", "label": "Kokoro (natural)", "license": "Apache-2.0", "ready": assets.present("kokoro:fp32"),
                 "voices": [v.to_dict() for v in tts.list_voices("kokoro")]},
                {"id": "piper", "label": "Piper (fast)", "license": "GPL-3.0 engine; per-voice licenses",
                 "ready": assets.present("piper:en_US-joe-medium"),
                 "voices": [v.to_dict() for v in tts.list_voices("piper") if assets.present(f"piper:{v.id}")]},
            ],
            "presets": [p.to_dict() for p in PRESETS.values()],
            "audio_modes": [
                {"id": "duck", "label": "Keep original audio, lower it under the voice"},
                {"id": "mix", "label": "Keep original audio at its level"},
                {"id": "replace", "label": "Replace original audio"},
            ],
            "ocr_engines": available_ocr(),
        }

    @app.get("/api/music")
    def list_music():
        tracks = []
        for t in music.installed():
            d = t.to_dict()
            try:
                d["duration"] = music.info(t)["duration"]
            except Exception:  # noqa: BLE001 - an unreadable user file should not break the list
                continue
            tracks.append(d)
        return {
            "tracks": tracks,
            "library_size": len(music.LIBRARY),
            "levels": list(music.LEVELS),
            "preset_moods": {k: list(v) for k, v in music.PRESET_MOODS.items()},
            "user_folder": str(music.user_dir()),
        }

    @app.get("/api/music/{track_id}/audio")
    def music_audio(track_id: str):
        t = music.get(track_id)
        if t is None:
            raise HTTPException(404, "Track not found")
        return FileResponse(music.track_path(t))

    def track_dict(t: music.Track | None) -> dict | None:
        if t is None:
            return None
        d = t.to_dict()
        d["duration"] = music.info(t)["duration"]
        return d

    @app.get("/api/jobs/{job_id}/music")
    def job_music(job_id: str):
        job = job_or_404(job_id)
        choice = job.settings.music
        if choice == "none":
            return {"track": None}
        if choice != "auto":
            return {"track": track_dict(music.get(choice))}
        state = store.dir(job_id) / "music.json"
        tid = store.read_json(job_id, "music.json") if state.exists() else None
        return {"track": track_dict(music.get(tid["track"]) if tid else None)}

    @app.post("/api/jobs/{job_id}/music/shuffle")
    def shuffle_music(job_id: str):
        job = job_or_404(job_id)
        if busy(job):
            raise HTTPException(409, "Wait for the current step to finish.")
        if job.settings.music != "auto":
            store.update(job_id, settings=job.settings.model_copy(update={"music": "auto"}))
        duration = job.info["duration"]
        tl = store.read_json(job_id, "timeline.json")
        if tl:
            duration = tl["output_duration"]
        t = music.resolve_for_job(store.dir(job_id), "auto", job.settings.preset, duration, shuffle=True)
        if t is None:
            raise HTTPException(400, "No music installed. Run `voicecraft setup` to download the music library.")
        if job.stages["render"].status == "done":
            store.update_stage(job_id, "render", status="stale")
        return {"track": track_dict(t)}

    @app.get("/api/lexicon")
    def get_lexicon():
        return {"user": load_user_entries(), "defaults": LEXICON_DEFAULTS}

    @app.put("/api/lexicon")
    def put_lexicon(entries: dict[str, str]):
        save_user_entries({k.strip(): v.strip() for k, v in entries.items() if k.strip() and v.strip()})
        return {"user": load_user_entries()}

    # ---- jobs -----------------------------------------------------------------------------
    @app.get("/api/jobs")
    def list_jobs():
        return [j.model_dump() for j in store.list()]

    @app.post("/api/jobs")
    def create_job(
        file: UploadFile = File(...),
        has_captions: bool = Form(True),
        captions: UploadFile | None = File(None),
    ):
        suffix = Path(file.filename or "video.mp4").suffix.lower()
        if suffix not in VIDEO_EXTS:
            raise HTTPException(400, f"Unsupported file type {suffix or '(none)'}. Use one of: {', '.join(sorted(VIDEO_EXTS))}")
        if not has_captions and captions is None:
            raise HTTPException(400, "This video has no captions on screen, so upload a caption file (.srt, .vtt, .json) or a .txt script.")
        caption_text = captions.file.read().decode("utf-8", errors="replace") if captions is not None else None
        name = Path(file.filename or "video").stem
        try:
            job = store.create(name, file.file, suffix)
        except MediaError as e:
            raise HTTPException(400, str(e))
        settings = job.settings.model_copy(update={"has_burned_captions": has_captions})
        store.update(job.id, settings=settings)
        if caption_text is not None:
            try:
                caps = parse_any(captions.filename or "captions.txt", caption_text, job.info["duration"])
            except (ValueError, KeyError) as e:
                store.delete(job.id)
                raise HTTPException(400, f"Could not read the caption file: {e}")
            track = CaptionTrack(
                video_fingerprint=file_fingerprint(store.dir(job.id) / job.video_file),
                duration=job.info["duration"],
                ocr_engine="import",
                captions=caps,
            )
            save_track(store.get(job.id), track, {"captions": len(caps), "flagged": 0, "imported": captions.filename})
        return store.get(job.id).model_dump()

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        return job_or_404(job_id).model_dump()

    @app.delete("/api/jobs/{job_id}")
    def delete_job(job_id: str):
        job = job_or_404(job_id)
        if busy(job):
            runner.cancel(job_id)
            raise HTTPException(409, "Job is running; it has been cancelled. Try deleting again in a moment.")
        store.delete(job_id)
        return {"deleted": job_id}

    @app.patch("/api/jobs/{job_id}/settings")
    def update_settings(job_id: str, changes: dict):
        job = job_or_404(job_id)
        if busy(job):
            raise HTTPException(409, "Wait for the current step to finish.")
        merged = Settings.model_validate({**job.settings.model_dump(), **changes})
        if merged.engine != job.settings.engine and "voice" not in changes:
            merged.voice = tts.DEFAULT_VOICE[merged.engine]
        diff = {k for k, v in merged.model_dump().items() if getattr(job.settings, k) != v}
        store.update(job_id, settings=merged)
        if diff & CAPTION_KEYS:
            store.invalidate_after(job_id, "captions")
            if job.stages["captions"].status == "done":
                store.update_stage(job_id, "captions", status="stale")
        elif diff & NARRATE_KEYS:
            if job.stages["narrate"].status == "done":
                store.update_stage(job_id, "narrate", status="stale")
            store.invalidate_after(job_id, "narrate")
        elif diff & RENDER_KEYS and job.stages["render"].status == "done":
            store.update_stage(job_id, "render", status="stale")
        return store.get(job_id).model_dump()

    @app.post("/api/jobs/{job_id}/run")
    def run(job_id: str, req: RunRequest):
        job = job_or_404(job_id)
        if busy(job):
            raise HTTPException(409, "This job is already processing.")
        if not req.stages:
            raise HTTPException(400, "No stages requested.")
        if "captions" in req.stages and not job.settings.has_burned_captions:
            raise HTTPException(400, "This video is marked as having no captions on screen. Import a caption file or script instead.")
        first = min(STAGES.index(s) for s in req.stages)
        for needed in STAGES[:first]:
            if job.stages[needed].status != "done":
                raise HTTPException(400, f"Run '{needed}' first.")
        runner.submit(job_id, list(req.stages))
        return store.get(job_id).model_dump()

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(job_id: str):
        job_or_404(job_id)
        runner.cancel(job_id)
        return {"cancelling": job_id}

    # ---- media ----------------------------------------------------------------------------
    @app.get("/api/jobs/{job_id}/video")
    def video(job_id: str):
        job = job_or_404(job_id)
        return FileResponse(store.dir(job_id) / job.video_file)

    @app.get("/api/jobs/{job_id}/frame")
    def frame(job_id: str, t: float = Query(0.0, ge=0)):
        job = job_or_404(job_id)
        try:
            data = grab_frame(str(store.dir(job_id) / job.video_file), min(t, job.info["duration"] - 0.05))
        except RuntimeError as e:
            raise HTTPException(400, str(e))
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})

    @app.get("/api/jobs/{job_id}/output")
    def output(job_id: str, download: bool = False):
        job = job_or_404(job_id)
        p = store.dir(job_id) / "output.mp4"
        if not p.exists():
            raise HTTPException(404, "Not rendered yet")
        name = f"{job.name}.narrated.mp4" if download else None
        return FileResponse(p, media_type="video/mp4", filename=name, content_disposition_type="attachment" if download else "inline")

    @app.get("/api/jobs/{job_id}/clips/{name}")
    def clip(job_id: str, name: str):
        job_or_404(job_id)
        if "/" in name or ".." in name:
            raise HTTPException(400, "Bad name")
        p = store.dir(job_id) / "clips" / name
        if not p.exists():
            raise HTTPException(404, "Clip not found")
        return FileResponse(p, media_type="audio/wav")

    # ---- captions -------------------------------------------------------------------------
    @app.get("/api/jobs/{job_id}/captions")
    def get_captions(job_id: str):
        track = caption_track(job_or_404(job_id))
        if track is None:
            raise HTTPException(404, "No captions yet")
        return track.model_dump()

    @app.put("/api/jobs/{job_id}/captions")
    def put_captions(job_id: str, body: CaptionsUpdate):
        job = job_or_404(job_id)
        if busy(job):
            raise HTTPException(409, "Wait for the current step to finish.")
        track = caption_track(job) or CaptionTrack(
            video_fingerprint=file_fingerprint(store.dir(job_id) / job.video_file), duration=job.info["duration"], ocr_engine="manual"
        )
        old = {c.id: c for c in track.captions}
        cleaned = []
        for c in body.captions:
            if not c.text.strip() or c.end <= c.start:
                continue
            c.start = max(0.0, min(c.start, job.info["duration"]))
            c.end = max(c.start + 0.1, min(c.end, job.info["duration"]))
            prev = old.get(c.id)
            if prev is None or (prev.text, prev.start, prev.end) != (c.text, c.start, c.end):
                c.source = "edit"
                c.flagged = False
                c.flag_reason = None
                c.confidence = 1.0
            cleaned.append(c)
        ids = set()
        for i, c in enumerate(sorted(cleaned, key=lambda c: c.start)):
            if c.id in ids or not c.id:
                c.id = f"e{i + 1}-{int(time.time() * 1000) % 100000}"
            ids.add(c.id)
        track.captions = cleaned
        save_track(job, track, {"captions": len(cleaned), "flagged": sum(c.flagged for c in cleaned), "edited": True})
        return track.model_dump()

    @app.post("/api/jobs/{job_id}/captions/import")
    async def import_captions(job_id: str, file: UploadFile = File(...)):
        job = job_or_404(job_id)
        if busy(job):
            raise HTTPException(409, "Wait for the current step to finish.")
        raw = (await file.read()).decode("utf-8", errors="replace")
        try:
            caps = parse_any(file.filename or "captions", raw, job.info["duration"])
        except (ValueError, KeyError) as e:
            raise HTTPException(400, f"Could not read caption file: {e}")
        track = CaptionTrack(
            video_fingerprint=file_fingerprint(store.dir(job_id) / job.video_file), duration=job.info["duration"], ocr_engine="import", captions=caps
        )
        save_track(job, track, {"captions": len(caps), "flagged": 0, "imported": file.filename})
        return track.model_dump()

    @app.post("/api/jobs/{job_id}/captions/script")
    def import_script(job_id: str, body: ScriptRequest):
        job = job_or_404(job_id)
        if busy(job):
            raise HTTPException(409, "Wait for the current step to finish.")
        track = caption_track(job) or CaptionTrack(
            video_fingerprint=file_fingerprint(store.dir(job_id) / job.video_file), duration=job.info["duration"], ocr_engine="script"
        )
        try:
            if job.settings.has_burned_captions:
                track.captions = align_script(body.script, track.captions, job.info["duration"])
            else:
                track.captions = pace_script(body.script, job.info["duration"])
        except ValueError as e:
            raise HTTPException(400, str(e))
        save_track(job, track, {"captions": len(track.captions), "flagged": sum(c.flagged for c in track.captions), "script": True})
        return track.model_dump()

    @app.put("/api/jobs/{job_id}/region")
    def put_region(job_id: str, body: RegionUpdate):
        job = job_or_404(job_id)
        x, y = max(0.0, min(body.x, 0.95)), max(0.0, min(body.y, 0.95))
        region = Region(x=x, y=y, w=max(0.05, min(body.w, 1 - x)), h=max(0.03, min(body.h, 1 - y)), auto=False, confidence=1.0)
        (store.dir(job_id) / "region.json").write_text(region.model_dump_json())
        if job.stages["captions"].status == "done":
            store.update_stage(job_id, "captions", status="stale")
        return region.model_dump()

    @app.delete("/api/jobs/{job_id}/region")
    def delete_region(job_id: str):
        job_or_404(job_id)
        (store.dir(job_id) / "region.json").unlink(missing_ok=True)
        return {"auto": True}

    # ---- timeline -------------------------------------------------------------------------
    @app.get("/api/jobs/{job_id}/timeline")
    def get_timeline(job_id: str):
        job_or_404(job_id)
        p = store.dir(job_id) / "timeline.json"
        if not p.exists():
            raise HTTPException(404, "No narration yet")
        return Timeline.model_validate_json(p.read_text()).model_dump()

    # ---- frontend -------------------------------------------------------------------------
    dist = _frontend_dir()
    if dist:
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404)
            f = dist / path
            if path and f.is_file() and dist in f.resolve().parents:
                return FileResponse(f)
            return FileResponse(dist / "index.html")
    else:

        @app.get("/", include_in_schema=False)
        def no_frontend():
            return JSONResponse({"message": "VoiceCraft API is running. Build the frontend (cd frontend && pnpm build) to get the UI.", "docs": "/api/docs"})

    return app
