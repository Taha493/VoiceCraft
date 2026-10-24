"""VoiceCraft command line.

    voicecraft setup              download models once (the only step that needs internet)
    voicecraft doctor             check the environment
    voicecraft run VIDEO          detect captions → narrate → render, in one go
    voicecraft captions VIDEO     only detect captions (prints JSON)
    voicecraft voices             list voices and their licenses
    voicecraft serve              start the web app on http://127.0.0.1:8765
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path


def _bar(label: str, frac: float) -> None:
    width = 28
    filled = int(width * max(0.0, min(1.0, frac)))
    sys.stderr.write(f"\r  {label[:34]:<34} [{'#' * filled}{'.' * (width - filled)}] {frac * 100:5.1f}%")
    sys.stderr.flush()


def cmd_setup(args: argparse.Namespace) -> int:
    from . import assets

    keys = ["kokoro:fp32", "kokoro:voices"]
    if args.piper:
        keys += [k for k in assets.ASSETS if k.startswith("piper:")]
    for key in keys:
        a = assets.ASSETS[key]
        if a.path.exists():
            print(f"  ✓ {a.filename} (already present)")
            continue
        assets.download(key, progress=lambda name, f: _bar(name, f))
        sys.stderr.write("\n")
        print(f"  ✓ {a.filename} ({a.license})")

    if not args.no_music:
        from . import music

        print(f"  Background music: {len(music.LIBRARY)} tracks by Kevin MacLeod (CC BY 4.0)")
        music.install_library(progress=lambda name, f: _bar(name, f), source_dir=Path(args.music_from) if args.music_from else None)
        sys.stderr.write("\n")
        print(f"  ✓ music library ({len(music.installed())} tracks, credits are added to each export)")

    print("  Warming up the pronunciation model (spaCy + misaki)...")
    from . import config

    config.force_offline()
    from . import tts

    engine = tts.load_engine("kokoro")
    engine.synthesize("VoiceCraft is ready.", tts.DEFAULT_VOICE["kokoro"])
    print("  ✓ Kokoro voice works offline")

    from .captions.ocr import RapidOcrEngine
    import numpy as np

    RapidOcrEngine().read(np.full((64, 256, 3), 255, np.uint8))
    print("  ✓ OCR models present")
    print("Setup complete. VoiceCraft no longer needs the internet.")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    import psutil

    from . import assets, config
    from .captions.ocr import available_ocr

    ok = True

    def line(good: bool, text: str) -> None:
        nonlocal ok
        ok &= good
        print(f"  {'✓' if good else '✗'} {text}")

    line(shutil.which("ffmpeg") is not None, "ffmpeg found")
    line(shutil.which("ffprobe") is not None, "ffprobe found")
    for key in ("kokoro:fp32", "kokoro:voices"):
        line(assets.present(key), f"{assets.ASSETS[key].filename}")
    print(f"  · OCR engines: {', '.join(available_ocr())}")
    from . import music

    print(f"  · Background music: {len(music.installed())} tracks installed")
    vm = psutil.virtual_memory()
    print(f"  · RAM available: {vm.available / 2**30:.1f} GiB of {vm.total / 2**30:.1f} GiB (VoiceCraft peaks near 0.8 GiB)")
    print(f"  · Inference threads: {config.cpu_threads()}")
    print(f"  · Data directory: {config.data_home()}")
    if not ok:
        print("Run `voicecraft setup` to download missing models.")
    return 0 if ok else 1


def cmd_voices(args: argparse.Namespace) -> int:
    from . import tts

    for engine in tts.ENGINES:
        for v in tts.list_voices(engine):
            print(f"  {engine:<7} {v.id:<26} {v.name:<12} {v.language:<6} {v.gender:<7} {v.license}")
    return 0


def cmd_music(args: argparse.Namespace) -> int:
    from . import music

    tracks = music.installed()
    if not tracks:
        print("No music installed. Run `voicecraft setup`.")
    for t in tracks:
        print(f"  {t.id:<24} {t.title:<24} {', '.join(t.moods):<20} {t.license}")
    print(f"Add your own tracks to {music.user_dir()}")
    return 0


def cmd_captions(args: argparse.Namespace) -> int:
    from . import config

    config.limit_threads()
    config.force_offline()
    from .captions.detect import extract_captions

    track = extract_captions(args.video, sample_fps=args.fps, ocr=args.ocr, progress=lambda m, f: _bar(m, f))
    sys.stderr.write("\n")
    data = track.model_dump_json(indent=2)
    if args.output:
        Path(args.output).write_text(data)
        print(f"Wrote {len(track.captions)} captions to {args.output}")
    else:
        print(data)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from .captions.importers import align_script, pace_script, parse_any
    from .jobs.isolate import StageError, run_stage
    from .jobs.store import JobStore, Settings
    from .schema import CaptionTrack
    from .media.probe import file_fingerprint

    video = Path(args.video).resolve()
    if not video.exists():
        print(f"No such file: {video}", file=sys.stderr)
        return 2
    out = Path(args.output) if args.output else video.with_name(video.stem + ".narrated.mp4")
    if out.resolve() == video:
        print("Refusing to overwrite the original video.", file=sys.stderr)
        return 2

    store = JobStore()
    job = store.create(video.stem, video, video.suffix)
    settings = Settings(
        has_burned_captions=not args.no_ocr,
        engine=args.engine,
        voice=args.voice or ("af_heart" if args.engine == "kokoro" else "en_US-joe-medium"),
        preset=args.preset,
        allow_holds=not args.no_hold,
        audio_mode=args.audio,
        sample_fps=args.fps,
        ocr=args.ocr,
        music=args.music or ("none" if job.info["has_audio"] else "auto"),
        music_level=args.music_level,
    )
    store.update(job.id, settings=settings)
    job_dir = store.dir(job.id)
    print(f"Job {job.id}  ({job.info['width']}x{job.info['height']}, {job.info['duration']:.1f}s)")

    if args.no_ocr and not (args.captions or args.script):
        print("--no-ocr needs --captions or --script.", file=sys.stderr)
        return 2
    stages = ["captions", "narrate", "render"]
    if args.no_ocr and args.script and not args.captions:
        args.captions = args.script  # paced from speaking time below
    if args.captions:
        content = Path(args.captions).read_text()
        caps = pace_script(content, job.info["duration"]) if args.no_ocr and args.captions == args.script else parse_any(args.captions, content, job.info["duration"])
        track = CaptionTrack(video_fingerprint=file_fingerprint(job_dir / job.video_file), duration=job.info["duration"], captions=caps, ocr_engine="import")
        (job_dir / "captions.json").write_text(track.model_dump_json(indent=2))
        stages.remove("captions")
        store.update_stage(job.id, "captions", status="done", progress=1.0, message="Done", finished=time.time(),
                           result={"captions": len(caps), "flagged": 0, "imported": Path(args.captions).name})
        print(f"  Imported {len(caps)} captions from {args.captions}")

    t0 = time.perf_counter()
    for stage in stages:
        st = time.perf_counter()
        store.update_stage(job.id, stage, status="running", progress=0.0, started=time.time(), error=None)
        try:
            result = run_stage(stage, job_dir, lambda m, f: _bar(m, f))
        except StageError as e:
            sys.stderr.write("\n")
            store.update_stage(job.id, stage, status="error", error=str(e), finished=time.time())
            print(f"✗ {stage} failed: {e}", file=sys.stderr)
            if args.verbose and e.detail:
                print(e.detail, file=sys.stderr)
            return 1
        store.update_stage(job.id, stage, status="done", progress=1.0, message="Done", finished=time.time(), result=result)
        sys.stderr.write("\n")
        print(f"  ✓ {stage:<8} {time.perf_counter() - st:6.1f}s  {json.dumps(result)}")
        if stage == "captions" and args.script and not args.no_ocr:
            track = CaptionTrack.model_validate_json((job_dir / "captions.json").read_text())
            track.captions = align_script(Path(args.script).read_text(), track.captions, job.info["duration"])
            (job_dir / "captions.json").write_text(track.model_dump_json(indent=2))
            print(f"  ✓ aligned script ({len(track.captions)} lines)")

    timeline = json.loads((job_dir / "timeline.json").read_text())
    for seg in timeline["segments"]:
        mark = {"fits": " ", "borrowed": "~", "sped_up": "»", "held": "‖", "overrun": "!"}[seg["status"]]
        print(f"   {mark} {seg['start']:6.2f}-{seg['end']:6.2f}  {seg['text'][:70]}" + (f"  ({seg['note']})" if seg.get("note") else ""))
    shutil.copyfile(job_dir / "output.mp4", out)
    if (job_dir / "credits.txt").exists():
        credits = out.with_suffix(".credits.txt")
        shutil.copyfile(job_dir / "credits.txt", credits)
        print(f"  Music credit (required by CC BY 4.0) saved to {credits}")
    print(f"Done in {time.perf_counter() - t0:.1f}s → {out}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .api.app import create_app

    if args.host not in ("127.0.0.1", "localhost") and not args.allow_remote:
        print("Refusing to listen on a non-local address without --allow-remote.", file=sys.stderr)
        return 2
    url = f"http://{args.host}:{args.port}"
    print(f"VoiceCraft running at {url}")
    if args.open:
        import webbrowser

        webbrowser.open(url)
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="warning")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="voicecraft", description="Local AI voice-over for silent, captioned videos.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("setup", help="download models (needs internet once)")
    p.add_argument("--piper", action="store_true", help="also download Piper voices (GPL engine)")
    p.add_argument("--no-music", action="store_true", help="skip the background music library")
    p.add_argument("--music-from", help="folder with already-downloaded library MP3s (\"<Title>.mp3\")")
    p.set_defaults(func=cmd_setup)

    sub.add_parser("doctor", help="check the environment").set_defaults(func=cmd_doctor)
    sub.add_parser("voices", help="list voices").set_defaults(func=cmd_voices)
    sub.add_parser("music", help="list background music").set_defaults(func=cmd_music)

    p = sub.add_parser("captions", help="detect captions only")
    p.add_argument("video")
    p.add_argument("-o", "--output")
    p.add_argument("--fps", type=float, default=4.0)
    p.add_argument("--ocr", default="rapidocr", choices=["rapidocr", "tesseract"])
    p.set_defaults(func=cmd_captions)

    p = sub.add_parser("run", help="full pipeline: video in, narrated MP4 out")
    p.add_argument("video")
    p.add_argument("-o", "--output")
    p.add_argument("--captions", help="use an .srt/.vtt/.json caption file (or .txt script) instead of OCR")
    p.add_argument("--script", help="plain-text script, one caption per line; replaces OCR wording, keeps on-screen timing")
    p.add_argument("--no-ocr", action="store_true", help="the video has no captions on screen; with --script, time lines by speaking pace")
    p.add_argument("--engine", default="kokoro", choices=["kokoro", "piper"])
    p.add_argument("--voice")
    p.add_argument("--preset", default="pitch", choices=["pitch", "energetic", "calm", "neutral"])
    p.add_argument("--no-hold", action="store_true", help="never freeze frames; flag overruns instead")
    p.add_argument("--audio", default="duck", choices=["duck", "replace", "mix"], help="what to do with existing audio")
    p.add_argument("--music", help="'auto' (mood-matched, default for silent videos), 'none', or a track id (see `voicecraft music`)")
    p.add_argument("--music-level", default="medium", choices=["low", "medium", "high"])
    p.add_argument("--fps", type=float, default=4.0, help="caption sampling rate")
    p.add_argument("--ocr", default="rapidocr", choices=["rapidocr", "tesseract"])
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("serve", help="start the web app")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--open", action="store_true", help="open a browser")
    p.add_argument("--allow-remote", action="store_true")
    p.set_defaults(func=cmd_serve)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
