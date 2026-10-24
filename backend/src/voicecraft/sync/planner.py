"""Narration planning and caption-based synchronization.

1. Group caption fragments into speakable segments (a sentence split across two captions is
   spoken as one phrase).
2. Synthesize each segment at the preset speed and measure the real duration.
3. Place it shortly after its caption appears. If it is too long, apply the overrun ladder:
     a. borrow the silence before the next caption, and let the next line start up to 0.8 s late
        when its caption stays on screen long enough,
     b. regenerate with the engine's speed control (at most MAX_SPEEDUP),
     c. freeze the caption's last frame long enough to finish (if holds are allowed),
     d. otherwise flag it; the following narration is pushed later rather than overlapping.
Words are never cut and audio is never time-stretched after synthesis.

All placement happens on the *output* timeline, which differs from video time by the holds
inserted so far.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Protocol

from ..schema import Caption, Hold, Segment, Timeline
from ..text.lexicon import Lexicon
from ..text.normalize import is_speakable, normalize
from .presets import MAX_SPEEDUP, Preset, segment_speed

TAIL = 0.15  # leave this much after the last narration before the video ends


class SynthFn(Protocol):
    def __call__(self, text: str, speed: float, pause: float): ...  # returns object with .path, .duration


@dataclass
class PlanOptions:
    allow_holds: bool = True
    max_speedup: float = MAX_SPEEDUP
    merge_gap: float = 0.35
    max_group_span: float = 9.0
    fps: float = 30.0
    max_hold: float = 6.0  # beyond this a hold is still applied but flagged for review
    max_late_start: float = 0.8  # how late the next line may start before we freeze a frame instead


def _ends_sentence(text: str) -> bool:
    return text.rstrip().rstrip("\"')]”’").endswith((".", "!", "?", ":", ";", "…"))


def group_captions(captions: list[Caption], merge_gap: float = 0.35, max_span: float = 9.0) -> list[list[Caption]]:
    groups: list[list[Caption]] = []
    for cap in sorted(captions, key=lambda c: c.start):
        if not cap.text.strip() or not is_speakable(cap.text):
            continue
        if groups:
            prev = groups[-1][-1]
            continuation = not _ends_sentence(prev.text) and cap.text.lstrip()[:1].islower()
            if continuation and cap.start - prev.end <= merge_gap and cap.end - groups[-1][0].start <= max_span:
                groups[-1].append(cap)
                continue
        groups.append([cap])
    return groups


def _join(texts: list[str]) -> str:
    return " ".join(t.strip() for t in texts)


def plan_narration(
    captions: list[Caption],
    video_duration: float,
    synth: SynthFn,
    preset: Preset,
    lexicon: Lexicon | None,
    options: PlanOptions | None = None,
    progress: Callable[[float], None] | None = None,
    meta: dict | None = None,
) -> Timeline:
    opt = options or PlanOptions()
    groups = group_captions(captions, opt.merge_gap, opt.max_group_span)
    segments: list[Segment] = []
    holds: list[Hold] = []
    offset = 0.0
    prev_end = -math.inf

    for i, group in enumerate(groups):
        text = _join([c.text for c in group])
        spoken = normalize(text, lexicon)
        cs, ce = group[0].start, group[-1].end
        next_cs = groups[i + 1][0].start if i + 1 < len(groups) else None
        next_ce = groups[i + 1][-1].end if i + 1 < len(groups) else None

        anchor = max(cs + offset + preset.lead_in, prev_end + preset.gap)
        late_ok = 0.0
        if next_cs is not None:
            # The next line may start a little late if its caption stays up long enough; that is
            # far less noticeable than freezing the picture.
            late_ok = min(opt.max_late_start, 0.3 * max(0.0, next_ce - next_cs))
            limit = next_cs + offset + preset.lead_in + late_ok - preset.gap
        else:
            limit = video_duration + offset - TAIL
        available = limit - anchor

        speed = segment_speed(preset, text)
        clip = synth(spoken, speed, preset.sentence_pause)
        status = "fits" if anchor + clip.duration <= ce + offset + 0.15 else "borrowed"
        note = None
        hold = 0.0

        if anchor + clip.duration > limit:
            needed = speed * clip.duration / max(available, 0.1)
            top = preset.speed * opt.max_speedup
            faster = min(top, needed * 1.02)
            if faster > speed:
                clip = synth(spoken, faster, preset.sentence_pause * 0.85)
                speed = round(faster, 3)
                status = "sped_up"
            overrun = anchor + clip.duration - limit
            if overrun > 0:
                if opt.allow_holds:
                    # Freezing anyway: hold long enough that the next line also starts on time.
                    hold = math.ceil((overrun + late_ok) * opt.fps) / opt.fps
                    hold_at = video_duration if next_cs is None else max(cs, min(ce, next_cs) - 0.12)
                    holds.append(Hold(video_time=round(hold_at, 3), duration=round(hold, 3), segment_id=f"s{i + 1}"))
                    offset += hold
                    status = "held"
                    note = f"Froze the frame for {hold:.2f}s so the line can finish."
                    if hold > opt.max_hold:
                        note += " That is a long pause; consider shortening this caption."
                else:
                    status = "overrun"
                    note = f"Runs {overrun:.2f}s past the next caption; following narration is delayed."
        if anchor > ce + offset - 0.1 and status != "held":
            status = "overrun"
            note = note or "Starts after its caption has disappeared because earlier narration ran long."

        segments.append(
            Segment(
                id=f"s{i + 1}",
                caption_ids=[c.id for c in group],
                text=text,
                spoken_text=spoken,
                preset=preset.id,
                caption_start=cs,
                caption_end=ce,
                start=round(anchor, 3),
                end=round(anchor + clip.duration, 3),
                speed=speed,
                audio_file=clip.path.name,
                audio_duration=round(clip.duration, 3),
                status=status,
                hold=round(hold, 3),
                note=note,
            )
        )
        prev_end = anchor + clip.duration
        if progress:
            progress((i + 1) / max(1, len(groups)))

    m = meta or {}
    output_duration = video_duration + offset
    return Timeline(
        engine=m.get("engine", "unknown"),
        model_id=m.get("model_id", "unknown"),
        voice=m.get("voice", "unknown"),
        preset=preset.id,
        sample_rate=m.get("sample_rate", 24000),
        video_duration=video_duration,
        output_duration=round(output_duration, 3),
        segments=segments,
        holds=holds,
        stats={
            "segments": len(segments),
            "held": sum(s.status == "held" for s in segments),
            "sped_up": sum(s.status == "sped_up" for s in segments),
            "overrun": sum(s.status == "overrun" for s in segments),
            "added_seconds": round(offset, 3),
        },
    )
