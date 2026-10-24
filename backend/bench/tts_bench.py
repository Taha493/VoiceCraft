"""Phase 1 TTS benchmark: speed (sustained real-time factor), peak RSS, and samples to listen to.

    uv run python bench/tts_bench.py                    # all candidates, each in its own process
    uv run python bench/tts_bench.py --engine kokoro:int8 --child

Real-time factor (RTF) = synthesis seconds / audio seconds; below 1.0 is faster than real time.
"""

from __future__ import annotations

import argparse
import json
import resource
import subprocess
import sys
import time
from pathlib import Path

LINES = [
    "Meet VoiceCraft, the fastest way to give your silent videos a voice.",
    "Upload a video, and we detect every caption automatically.",
    "No cloud. No subscriptions. Everything runs on your own laptop.",
    "Our API handles ten thousand requests per second with ninety nine percent uptime.",
    "Why spend hours recording narration when your captions already tell the story?",
    "It's built with React, TypeScript, and a FastAPI backend.",
    "Here's how it works: first, we scan the frames; then, we read the text.",
    "Launching today, and it's completely free!",
    "Every voice is generated locally, so your content stays private.",
    "Ready to try it? Let's get started.",
]

CANDIDATES = ["kokoro:fp32:misaki", "kokoro:fp32:espeak", "kokoro:fp16:misaki", "kokoro:int8:misaki", "piper", "kokoro-torch"]
OUT = Path(__file__).parent / "out"


def run_child(spec: str, passes: int) -> dict:
    import numpy as np
    import soundfile as sf

    from voicecraft import tts

    t0 = time.perf_counter()
    if spec.startswith("kokoro:"):
        _, precision, *g2p = spec.split(":")
        engine = tts.load_engine("kokoro", precision=precision, g2p=g2p[0] if g2p else "misaki")
    else:
        engine = tts.load_engine(spec)
    load_s = time.perf_counter() - t0
    voice = tts.DEFAULT_VOICE.get(engine.name, "af_heart")

    first_s = None
    synth_s = audio_s = 0.0
    tag = spec.replace(":", "-")
    for p in range(passes):
        for i, line in enumerate(LINES):
            t = time.perf_counter()
            speech = engine.synthesize(line, voice)
            dt = time.perf_counter() - t
            if first_s is None:
                first_s = dt
            if p == passes - 1:  # last pass = sustained, warmed-up numbers
                synth_s += dt
                audio_s += speech.duration
                sf.write(OUT / f"{tag}_{i:02d}.wav", speech.audio, speech.sample_rate)
    _ = np  # keep import explicit for readers
    return {
        "engine": spec,
        "model_id": engine.model_id,
        "voice": voice,
        "load_s": round(load_s, 2),
        "first_call_s": round(first_s or 0, 2),
        "audio_s": round(audio_s, 2),
        "synth_s": round(synth_s, 2),
        "rtf": round(synth_s / audio_s, 3) if audio_s else None,
        "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", action="append", help=f"one of {CANDIDATES}")
    ap.add_argument("--passes", type=int, default=2)
    ap.add_argument("--child", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)

    if args.child:
        from voicecraft import config

        config.limit_threads()
        print(json.dumps(run_child(args.engine[0], args.passes)))
        return

    results = []
    for spec in args.engine or CANDIDATES:
        proc = subprocess.run(
            [sys.executable, __file__, "--child", "--engine", spec, "--passes", str(args.passes)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            print(f"[{spec}] FAILED\n{proc.stderr[-2000:]}", file=sys.stderr)
            results.append({"engine": spec, "error": proc.stderr.strip().splitlines()[-1:]})
            continue
        res = json.loads(proc.stdout.strip().splitlines()[-1])
        results.append(res)
        print(json.dumps(res), flush=True)
    (OUT / "results.json").write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
