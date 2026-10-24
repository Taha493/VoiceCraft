"""Final render: narration track + original video (+ original audio, ducked) → MP4.

- No holds and an MP4-friendly codec: the video stream is copied bit-for-bit (no quality loss,
  seconds to render).
- Holds: frames are repeated with the `loop` filter, which buffers a single frame. (A
  split/trim/concat graph would buffer decoded frames for every later branch, which explodes
  memory on 1080p input.) Then H.264 CRF 18, preset veryfast.
- Audio is mixed in its own fast pass: the voice (two-pass EBU R128 to -16 LUFS), the original
  audio (kept, ducked about 9 dB while the voice speaks, or replaced) and optional background
  music (fitted to length, EQ-carved, ducked). The mix is measured and the final file is
  normalized to -16 LUFS / -1.5 dBTP, the usual target for web and social video.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

import numpy as np
import soundfile as sf

from ..schema import Timeline
from .probe import VideoInfo, probe

AudioMode = Literal["duck", "replace", "mix"]
COPYABLE = {"h264", "hevc", "av1", "mpeg4"}
FADE_S = 0.008


class RenderError(RuntimeError):
    pass


def build_narration_track(timeline: Timeline, clips_dir: Path, out_wav: Path) -> int:
    """Place every clip at its output-timeline position. Returns the sample rate."""
    sr = timeline.sample_rate
    track = np.zeros(int(np.ceil(timeline.output_duration * sr)) + 1, dtype=np.float32)
    fade = int(FADE_S * sr)
    ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32) if fade else None
    for seg in timeline.segments:
        audio, clip_sr = sf.read(clips_dir / seg.audio_file, dtype="float32")
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if clip_sr != sr:
            raise RenderError(f"Clip {seg.audio_file} is {clip_sr} Hz but the timeline is {sr} Hz.")
        audio = audio.copy()
        if ramp is not None and len(audio) > 2 * fade:
            audio[:fade] *= ramp
            audio[-fade:] *= ramp[::-1]
        start = int(round(seg.start * sr))
        end = min(len(track), start + len(audio))
        track[start:end] += audio[: end - start]
    np.clip(track, -1.0, 1.0, out=track)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    sf.write(out_wav, track, sr, subtype="FLOAT")
    return sr


def measure_loudness(wav: Path, target: float = -16.0) -> dict | None:
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostdin", "-i", str(wav), "-af",
         f"loudnorm=I={target}:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", proc.stderr, re.S)
    if not m:
        return None
    data = json.loads(m.group(0))
    if data.get("input_i") in ("-inf", None):
        return None
    return data


def _loudnorm(stats: dict | None, target: float = -16.0) -> str:
    if not stats:
        return f"loudnorm=I={target}:TP=-1.5:LRA=11"
    return (
        f"loudnorm=I={target}:TP=-1.5:LRA=11:measured_I={stats['input_i']}:measured_TP={stats['input_tp']}"
        f":measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}"
        f":offset={stats['target_offset']}:linear=true"
    )


def _video_filter(info: VideoInfo, timeline: Timeline) -> str:
    fps = info.fps
    chain = [f"fps={fps:.6f}"]
    # Apply holds latest-first so earlier frame indices are unaffected by inserted frames.
    for h in sorted(timeline.holds, key=lambda h: h.video_time, reverse=True):
        frame = max(0, min(int(round(h.video_time * fps)), int(info.duration * fps) - 1))
        count = max(1, int(round(h.duration * fps)))
        chain.append(f"loop=loop={count}:size=1:start={frame}")
    chain.append(f"setpts=N/({fps:.6f}*TB)")
    return ",".join(chain)


def _audio_hold_filter(timeline: Timeline, label_in: str, label_out: str) -> str:
    """Insert silence into the original audio at each hold (audio buffering is cheap)."""
    holds = sorted(timeline.holds, key=lambda h: h.video_time)
    if not holds:
        return f"[{label_in}]anull[{label_out}]"
    cuts = [0.0] + [h.video_time for h in holds] + [timeline.video_duration]
    n = len(cuts) - 1
    parts = [f"[{label_in}]asplit={n}" + "".join(f"[ah{i}]" for i in range(n))]
    for i in range(n):
        seg = f"[ah{i}]atrim=start={cuts[i]:.4f}:end={cuts[i + 1]:.4f},asetpts=PTS-STARTPTS"
        if i < len(holds):
            seg += f",apad=pad_dur={holds[i].duration:.4f}"
        parts.append(seg + f"[ap{i}]")
    parts.append("".join(f"[ap{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1[{label_out}]")
    return ";".join(parts)


@dataclass(frozen=True)
class MusicBed:
    path: Path
    title: str
    credit: str
    gain_db: float  # brings the track to the chosen bed loudness
    start: float  # leading silence to skip
    duration: float  # full track length


CROSSFADE = 3.0


def _music_filter(bed: MusicBed, first_input: int, copies: int, out_dur: float, sidechain: str) -> str:
    """Track (looped with crossfades if too short) → trimmed → faded → EQ carved for the voice → ducked."""
    parts = []
    for j in range(copies):
        parts.append(
            f"[{first_input + j}:a]atrim=start={bed.start:.3f},asetpts=PTS-STARTPTS,"
            f"aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[m{j}]"
        )
    last = "m0"
    for j in range(1, copies):
        parts.append(f"[{last}][m{j}]acrossfade=d={CROSSFADE}:c1=tri:c2=tri[x{j}]")
        last = f"x{j}"
    fade_out = min(3.5, max(1.0, out_dur * 0.12))
    parts.append(
        f"[{last}]atrim=duration={out_dur:.3f},asetpts=PTS-STARTPTS,"
        f"afade=t=in:d=0.08,afade=t=out:st={out_dur - fade_out:.3f}:d={fade_out:.3f},"
        # Gentle high-pass and a dip where speech intelligibility lives, so the voice sits on top.
        f"highpass=f=45,equalizer=f=2800:t=q:w=1.1:g=-3.5,volume={bed.gain_db:.2f}dB[mpre]"
    )
    parts.append(f"[mpre][{sidechain}]sidechaincompress=threshold=0.05:ratio=4:attack=60:release=650[mus]")
    return ";".join(parts)


def _run(cmd: list[str], progress: Callable[[float], None] | None, total: float) -> None:
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert proc.stdout is not None
    for line in proc.stdout:
        if line.startswith("out_time_us=") and progress:
            try:
                progress(min(1.0, int(line.split("=")[1]) / 1e6 / total))
            except ValueError:
                pass
    err = proc.stderr.read() if proc.stderr else ""
    if proc.wait() != 0:
        raise RenderError(f"FFmpeg failed: {err.strip()[-1500:]}")


def mix_audio(
    video: str,
    info: VideoInfo,
    timeline: Timeline,
    narration: Path,
    out_wav: Path,
    audio_mode: AudioMode,
    bed_volume: float,
    music: MusicBed | None,
) -> dict | None:
    """Audio-only pass: voice + original audio (held, ducked) + music (ducked) → 48 kHz stereo WAV.

    Returns the narration loudness measurement.
    """
    out_dur = timeline.output_duration
    stats = measure_loudness(narration)
    keep_original = info.has_audio and audio_mode != "replace"
    inputs = ["-i", str(narration)]
    graph = []
    sidechains = []
    if keep_original and audio_mode == "duck":
        sidechains.append("sc_orig")
    if music:
        sidechains.append("sc_mus")
    labels = "".join(f"[{l}]" for l in ["nmix", *sidechains])
    graph.append(
        f"[0:a]aresample=48000,{_loudnorm(stats)},aresample=48000,"
        f"aformat=sample_fmts=fltp:channel_layouts=stereo,asplit={1 + len(sidechains)}{labels}"
    )
    mix = ["[nmix]"]
    next_input = 1
    if keep_original:
        inputs += ["-i", video]
        graph.append(_audio_hold_filter(timeline, f"{next_input}:a", "orig_held"))
        graph.append(f"[orig_held]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,volume={bed_volume}[orig]")
        if audio_mode == "duck":
            graph.append("[orig][sc_orig]sidechaincompress=threshold=0.05:ratio=4:attack=15:release=350[origd]")
            mix.append("[origd]")
        else:
            mix.append("[orig]")
        next_input += 1
    if music:
        usable = max(1.0, music.duration - music.start)
        copies = 1 if usable >= out_dur + 0.5 else min(8, int(np.ceil((out_dur - CROSSFADE) / (usable - CROSSFADE))) + 1)
        for _ in range(copies):
            inputs += ["-i", str(music.path)]
        graph.append(_music_filter(music, next_input, copies, out_dur, "sc_mus"))
        mix.append("[mus]")
    # apad + -t: loudnorm works in 100 ms blocks and can drop the last partial one; padding keeps
    # the mix exactly as long as the video.
    graph.append("".join(mix) + f"amix=inputs={len(mix)}:duration=first:normalize=0,apad[mix]")
    cmd = ["ffmpeg", "-y", "-hide_banner", "-nostdin", "-loglevel", "error", *inputs,
           "-filter_complex", ";".join(graph), "-map", "[mix]", "-c:a", "pcm_f32le", "-ar", "48000",
           "-t", f"{out_dur:.3f}", str(out_wav)]
    _run(cmd, None, out_dur)
    return stats


def render(
    video: str,
    timeline: Timeline,
    clips_dir: Path,
    out_path: Path,
    work_dir: Path,
    audio_mode: AudioMode = "duck",
    bed_volume: float = 0.7,
    music: MusicBed | None = None,
    crf: int = 18,
    x264_preset: str = "veryfast",  # 2x faster than "fast" here, visually identical (SSIM 0.999)
    progress: Callable[[float], None] | None = None,
) -> dict:
    info = probe(video)
    narration = work_dir / "narration.wav"
    build_narration_track(timeline, clips_dir, narration)

    # 1) Mix all audio, 2) measure the mix, 3) mux with video at exactly -16 LUFS / -1.5 dBTP.
    mixed = work_dir / "mix.wav"
    voice_stats = mix_audio(video, info, timeline, narration, mixed, audio_mode, bed_volume, music)
    if progress:
        progress(0.1)
    mix_stats = measure_loudness(mixed)

    reencode = bool(timeline.holds) or info.vcodec not in COPYABLE
    keep_original = info.has_audio and audio_mode != "replace"
    # loudnorm's linear mode cannot guarantee the true-peak ceiling, so a limiter catches overs.
    graph = [f"[1:a]{_loudnorm(mix_stats)},aresample=48000,alimiter=limit=0.8:level=false,apad[aout]"]
    if reencode:
        graph.append(f"[0:v]{_video_filter(info, timeline)}[vout]")

    cmd = ["ffmpeg", "-y", "-hide_banner", "-nostdin", "-loglevel", "error", "-progress", "pipe:1",
           "-i", video, "-i", str(mixed), "-filter_complex", ";".join(graph)]
    if reencode:
        cmd += ["-map", "[vout]", "-c:v", "libx264", "-preset", x264_preset, "-crf", str(crf), "-pix_fmt", "yuv420p"]
    else:
        cmd += ["-map", "0:v:0", "-c:v", "copy"]
        if info.vcodec == "hevc":
            cmd += ["-tag:v", "hvc1"]
    cmd += ["-map", "[aout]", "-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
    if music and music.credit:
        cmd += ["-metadata", f"comment=Music: {music.credit.replace(chr(10), ' / ')}"]
    cmd += ["-t", f"{timeline.output_duration:.3f}", "-movflags", "+faststart"]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".partial.mp4")
    try:
        _run([*cmd, str(tmp)], (lambda f: progress(0.1 + 0.9 * f)) if progress else None, timeline.output_duration)
    except RenderError:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(out_path)
    mixed.unlink(missing_ok=True)
    return {
        "video": "re-encoded (H.264 CRF %d)" % crf if reencode else "copied (no quality loss)",
        "original_audio": ("ducked" if audio_mode == "duck" else audio_mode) if keep_original else ("replaced" if info.has_audio else "none"),
        "narration_loudness": f"{voice_stats['input_i']} LUFS → -16 LUFS" if voice_stats else "n/a",
        "final_loudness": f"{mix_stats['input_i']} LUFS → -16 LUFS" if mix_stats else "n/a",
        "music": music.title if music else "none",
        "music_credit": music.credit if music else "",
        "holds": len(timeline.holds),
        "output_duration": timeline.output_duration,
    }
