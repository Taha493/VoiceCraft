"""Stage entry points. Each runs inside a short-lived child process (see isolate.py), reads its
inputs from the job directory, and writes its output there.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

Progress = Callable[[str, float], None]


def _job(job_dir: Path) -> dict:
    return json.loads((job_dir / "job.json").read_text())


def run_captions(job_dir: Path, progress: Progress) -> dict:
    from ..captions.detect import extract_captions
    from ..media.probe import file_fingerprint
    from ..schema import CaptionTrack, Region

    job = _job(job_dir)
    s = job["settings"]
    video = str(job_dir / job["video_file"])
    out = job_dir / "captions.json"

    region = None
    if out.exists():
        prev = CaptionTrack.model_validate_json(out.read_text())
        # A manually adjusted region is reused; an automatic one is re-detected.
        if prev.region is not None and not prev.region.auto:
            region = prev.region
    override = job_dir / "region.json"
    if override.exists():
        region = Region.model_validate_json(override.read_text())

    track = extract_captions(video, region=region, sample_fps=s["sample_fps"], ocr=s["ocr"], progress=progress)
    track.video_fingerprint = file_fingerprint(video)
    out.write_text(track.model_dump_json(indent=2))
    return {
        "captions": len(track.captions),
        "flagged": track.stats.get("flagged", 0),
        "seconds": track.stats.get("seconds"),
        "ocr_calls": track.stats.get("ocr_calls"),
        "region_confidence": track.region.confidence if track.region else None,
    }


def run_narrate(job_dir: Path, progress: Progress) -> dict:
    from .. import tts
    from ..schema import CaptionTrack
    from ..sync.planner import PlanOptions, plan_narration
    from ..sync.presets import PRESETS, DEFAULT_PRESET
    from ..sync.synth import CachedSynth
    from ..text.lexicon import load_lexicon

    job = _job(job_dir)
    s = job["settings"]
    track = CaptionTrack.model_validate_json((job_dir / "captions.json").read_text())
    if not track.captions:
        raise RuntimeError("No captions to narrate. Detect captions, import a caption file, or add captions by hand.")

    progress("Loading voice model", 0.0)
    engine = tts.load_engine(s["engine"])
    try:
        synth = CachedSynth(engine, s["voice"], job_dir / "clips")
        preset = PRESETS.get(s["preset"], PRESETS[DEFAULT_PRESET])
        timeline = plan_narration(
            track.captions,
            video_duration=job["info"]["duration"],
            synth=synth,
            preset=preset,
            lexicon=load_lexicon(),
            options=PlanOptions(allow_holds=s["allow_holds"], fps=job["info"]["fps"]),
            progress=lambda f: progress("Generating narration", f),
            meta={"engine": engine.name, "model_id": engine.model_id, "voice": s["voice"], "sample_rate": engine.sample_rate},
        )
    finally:
        engine.close()
    timeline.stats.update({"generated": synth.generated, "reused": synth.reused})
    (job_dir / "timeline.json").write_text(timeline.model_dump_json(indent=2))
    return timeline.stats


def run_render(job_dir: Path, progress: Progress) -> dict:
    from .. import music
    from ..media.render import MusicBed, render
    from ..schema import Timeline

    job = _job(job_dir)
    s = job["settings"]
    timeline = Timeline.model_validate_json((job_dir / "timeline.json").read_text())

    bed = None
    track = music.resolve_for_job(job_dir, s.get("music", "auto"), s["preset"], timeline.output_duration)
    if track:
        progress("Preparing music", 0.0)
        m = music.info(track)
        level = music.LEVELS.get(s.get("music_level", "medium"), music.LEVELS["medium"])
        bed = MusicBed(music.track_path(track), track.title, track.credit, level - m["lufs"], m["lead"], m["duration"])

    progress("Mixing audio", 0.0)
    result = render(
        str(job_dir / job["video_file"]),
        timeline,
        clips_dir=job_dir / "clips",
        out_path=job_dir / "output.mp4",
        work_dir=job_dir,
        audio_mode=s["audio_mode"],
        music=bed,
        progress=lambda f: progress("Rendering video", f),
    )
    credits = job_dir / "credits.txt"
    if bed and bed.credit:
        credits.write_text(f"Music: {bed.credit}\n")
    else:
        credits.unlink(missing_ok=True)
    result["music_id"] = track.id if track else None
    return result


STAGE_FUNCS = {"captions": run_captions, "narrate": run_narrate, "render": run_render}
