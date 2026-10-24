"""End-to-end benchmark against ground truth (videos from make_test_video.py).

    uv run python bench/pipeline_bench.py bench/data/demo30.mp4 bench/data/demo60_1080p.mp4

Reports per-stage time and peak RSS, caption accuracy (CER, recall, timing error), narration
sync error, and the measured speech onsets in the rendered file. The TTS cache is a fresh
temporary directory so synthesis cost is real.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def levenshtein(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower().replace("’", "'")).strip()


def speech_onsets(mp4: Path) -> list[float]:
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostdin", "-i", str(mp4), "-af", "silencedetect=n=-38dB:d=0.2", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    return [float(x) for x in re.findall(r"silence_end: ([\d.]+)", proc.stderr)]


def bench(video: Path) -> dict:
    from voicecraft.jobs.isolate import run_stage
    from voicecraft.jobs.store import JobStore
    from voicecraft.schema import CaptionTrack, Timeline

    truth = json.loads(video.with_suffix(".truth.json").read_text())["captions"]
    store = JobStore()
    job = store.create(video.stem, video.resolve(), video.suffix)
    d = store.dir(job.id)
    out = {"video": video.name, "duration": job.info["duration"], "resolution": f"{job.info['width']}x{job.info['height']}"}

    total = 0.0
    for stage in ("captions", "narrate", "render"):
        t = time.perf_counter()
        res = run_stage(stage, d, lambda m, f: None)
        dt = time.perf_counter() - t
        total += dt
        out[f"{stage}_s"] = round(dt, 1)
        out[f"{stage}_peak_mb"] = res.get("peak_rss_mb")
    out["total_s"] = round(total, 1)
    out["x_realtime"] = round(total / job.info["duration"], 2)

    track = CaptionTrack.model_validate_json((d / "captions.json").read_text())
    caps = track.captions
    errs_chars = total_chars = 0
    start_err, end_err, matched = [], [], {}
    for i, tc in enumerate(truth):
        overl = [c for c in caps if min(c.end, tc["end"]) - max(c.start, tc["start"]) > 0]
        if not overl:
            errs_chars += len(tc["text"])
            total_chars += len(tc["text"])
            continue
        best = min(overl, key=lambda c: levenshtein(norm(c.text), norm(tc["text"])))
        e = levenshtein(norm(best.text), norm(tc["text"]))
        errs_chars += e
        total_chars += len(tc["text"])
        if e / len(tc["text"]) < 0.1:
            matched[best.id] = tc
        start_err.append(abs(best.start - tc["start"]))
        end_err.append(abs(best.end - tc["end"]))
    out["captions_truth"] = len(truth)
    out["captions_found"] = len(caps)
    out["caption_recall"] = round(len(matched) / len(truth), 3)
    out["cer"] = round(errs_chars / max(1, total_chars), 4)
    out["caption_start_err_mean_s"] = round(sum(start_err) / max(1, len(start_err)), 3)
    out["caption_start_err_max_s"] = round(max(start_err, default=0), 3)
    out["caption_end_err_max_s"] = round(max(end_err, default=0), 3)

    tl = Timeline.model_validate_json((d / "timeline.json").read_text())
    def to_video(t: float) -> float:
        shift = 0.0
        for h in sorted(tl.holds, key=lambda h: h.video_time):
            if t < h.video_time + shift:
                break
            if t < h.video_time + shift + h.duration:
                return h.video_time
            shift += h.duration
        return t - shift

    onset = []
    visible = 0
    for seg in tl.segments:
        tc = matched.get(seg.caption_ids[0])
        if not tc:
            continue
        v = to_video(seg.start)
        onset.append(v - tc["start"])
        visible += tc["start"] <= v <= tc["end"]
    out["voice_after_caption_mean_s"] = round(sum(onset) / max(1, len(onset)), 3)
    out["voice_after_caption_max_s"] = round(max(onset, default=0), 3)
    out["voice_starts_while_caption_visible"] = f"{visible}/{len(onset)}"
    out["segments"] = tl.stats

    detected = speech_onsets(d / "output.mp4")
    render_err = []
    for seg in tl.segments:
        near = min(detected, key=lambda x: abs(x - seg.start), default=None)
        if near is not None and abs(near - seg.start) < 0.5:
            render_err.append(abs(near - seg.start))
    out["render_onset_err_max_s"] = round(max(render_err, default=-1), 3)
    out["render_onsets_found"] = f"{len(render_err)}/{len(tl.segments)}"
    store.delete(job.id)
    return out


def main() -> None:
    results = []
    for v in sys.argv[1:]:
        with tempfile.TemporaryDirectory() as cache:  # each video starts with an empty TTS cache
            os.environ["VOICECRAFT_CACHE"] = cache
            results.append(bench(Path(v)))
    for r in results:
        print(json.dumps(r, indent=2))
    Path(__file__).with_name("out").mkdir(exist_ok=True)
    (Path(__file__).with_name("out") / "pipeline_results.json").write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
