"""Generate a synthetic "Claude-style" pitch video with known caption ground truth.

It deliberately includes things that break naive detectors: an animated gradient background,
a static title, a changing non-caption label mid-screen, fade-ins, a typewriter caption, and a
caption window too short for its text (to exercise the overrun ladder).

    uv run python bench/make_test_video.py bench/data/pitch.mp4 [--music]
    uv run python bench/make_test_video.py bench/data/demo60.mp4 --duration 60 --size 1920x1080
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
from pathlib import Path

FONT = "/usr/share/fonts/noto/NotoSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/noto/NotoSans-Regular.ttf"

CAPTIONS = [
    (0.6, 3.4, "Meet VoiceCraft."),
    (4.0, 7.4, "Turn silent, captioned videos into narrated stories."),
    (8.0, 9.8, "No cloud. No subscriptions. No API keys required, ever."),
    (10.4, 14.6, "It reads your captions and speaks them naturally.", "typewriter"),
    (15.0, 17.2, "Everything runs locally on your laptop."),
    (17.8, 19.6, "Ready to give your videos a voice?"),
]
DURATION = 20.0

POOL = [
    "Meet VoiceCraft.",
    "Turn silent, captioned videos into narrated stories.",
    "No cloud. No subscriptions. No API keys required, ever.",
    "It reads your captions and speaks them naturally.",
    "Everything runs locally on your laptop.",
    "Built with React, TypeScript and FastAPI.",
    "Detect captions in seconds, not minutes.",
    "Fix any line before you export.",
    "Ship product demos 10x faster.",
    "Your visuals stay exactly as they are.",
    "Choose a voice that fits your brand.",
    "Perfect for launches, walkthroughs and pitch decks.",
    "Export a ready-to-share MP4.",
    "Works with videos made in Claude Code and Claude Design.",
    "Private by default. Nothing leaves your machine.",
    "Ready to give your videos a voice?",
]


def generate_captions(duration: float, seed: int = 7) -> list[tuple]:
    """Caption timings like a real pitch video: mostly comfortable, some tight, some typewriter."""
    rng = random.Random(seed)
    caps, t, i = [], 0.6, 0
    while True:
        text = POOL[i % len(POOL)]
        words = len(text.split())
        length = min(4.5, max(1.6, words / 3.0 + 0.6))
        if i % 5 == 2:
            length *= 0.6  # deliberately too short to speak
        style = "typewriter" if i % 4 == 3 else None
        if t + length > duration - 0.3:
            break
        caps.append((round(t, 2), round(t + length, 2), text, style))
        t += length + rng.uniform(0.4, 0.9)
        i += 1
    return caps


def esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "’").replace(",", "\\,")


def caption_filters(start: float, end: float, text: str, style: str | None, scale: float = 1.0) -> list[str]:
    common = (
        f"fontfile={FONT}:fontsize={round(40 * scale)}:fontcolor=white:x=(w-text_w)/2:y=h-{round(120 * scale)}"
        f":box=1:boxcolor=black@0.45:boxborderw={round(18 * scale)}"
    )
    if style == "typewriter":
        out = []
        words = text.split()
        step = 0.12
        for i in range(1, len(words) + 1):
            a = start + (i - 1) * step
            b = start + i * step if i < len(words) else end
            out.append(f"drawtext={common}:text='{esc(' '.join(words[:i]))}':enable='between(t,{a:.3f},{b:.3f})'")
        return out
    fade = 0.25
    alpha = f"if(lt(t,{start + fade}),(t-{start})/{fade},1)"
    return [f"drawtext={common}:text='{esc(text)}':alpha='{alpha}':enable='between(t,{start},{end})'"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--music", action="store_true", help="add a quiet background bed")
    ap.add_argument("--duration", type=float, default=DURATION)
    ap.add_argument("--size", default="1280x720")
    args = ap.parse_args()
    width, height = (int(v) for v in args.size.split("x"))
    scale = height / 720
    duration = args.duration
    captions = CAPTIONS if duration == DURATION else generate_captions(duration)
    args.out.parent.mkdir(parents=True, exist_ok=True)

    vf = [
        f"drawtext=fontfile={FONT}:fontsize={round(64 * scale)}:fontcolor=white:x={round(80 * scale)}:y={round(60 * scale)}:text='VoiceCraft'",
        f"drawtext=fontfile={FONT_REG}:fontsize={round(26 * scale)}:fontcolor=white@0.8:x=w-tw-{round(80 * scale)}:y={round(80 * scale)}:text='v2.0 Demo'",
    ]
    steps = 3
    for i in range(steps):
        a, b = duration * i / steps, duration * (i + 1) / steps
        vf.append(
            f"drawtext=fontfile={FONT_REG}:fontsize={round(34 * scale)}:fontcolor=white@0.9:x=(w-tw)/2:y=h/2-{round(40 * scale)}"
            f":text='Step {i + 1} of {steps}':enable='gte(t,{a:.3f})*lt(t,{b:.3f})'"
        )
    for c in captions:
        vf += caption_filters(c[0], c[1], c[2], c[3] if len(c) > 3 else None, scale)

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"gradients=s={width}x{height}:r=30:d={duration}:speed=0.02:c0=0x1e1b4b:c1=0x7c3aed:c2=0x0ea5e9",
    ]
    if args.music:
        cmd += ["-f", "lavfi", "-i",
                f"aevalsrc='0.08*sin(2*PI*220*t)*(0.6+0.4*sin(2*PI*0.5*t))+0.05*sin(2*PI*330*t)':s=48000:d={duration}"]
    cmd += ["-vf", ",".join(vf), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "20"]
    cmd += ["-c:a", "aac", "-b:a", "128k"] if args.music else ["-an"]
    cmd += [str(args.out)]
    subprocess.run(cmd, check=True)

    truth = [{"start": c[0], "end": c[1], "text": c[2]} for c in captions]
    args.out.with_suffix(".truth.json").write_text(json.dumps({"duration": duration, "captions": truth}, indent=2))
    print(args.out)


if __name__ == "__main__":
    main()
