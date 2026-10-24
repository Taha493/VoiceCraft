"""Delivery presets.

Neither Kokoro nor Piper exposes emotion or style controls, so "delivery" here means what we can
actually control: speaking rate, the pause between sentences, and how soon after a caption
appears the voice comes in. These are honest approximations of a style, not acted emotion.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Preset:
    id: str
    label: str
    description: str
    speed: float  # engine speed multiplier
    sentence_pause: float  # seconds between sentences inside one segment
    lead_in: float  # seconds after the caption appears before narration starts
    gap: float  # minimum silence between consecutive segments

    def to_dict(self) -> dict:
        return asdict(self)


PRESETS = {
    p.id: p
    for p in [
        Preset("pitch", "Confident pitch", "Steady, professional pace for product pitches and demos.", 1.0, 0.30, 0.20, 0.25),
        Preset("energetic", "Energetic", "Quicker pace and tighter pauses for launches and announcements.", 1.08, 0.22, 0.12, 0.18),
        Preset("calm", "Calm explainer", "Slower pace and longer pauses for tutorials and walkthroughs.", 0.94, 0.45, 0.25, 0.35),
        Preset("neutral", "Neutral", "The voice's natural pace.", 1.0, 0.35, 0.20, 0.25),
    ]
}
DEFAULT_PRESET = "pitch"

MAX_SPEEDUP = 1.12  # relative to the preset speed; beyond this speech starts to sound rushed


def segment_speed(preset: Preset, text: str) -> float:
    """Small, rule-based cue: exclamations get a touch more pace unless the preset is calm."""
    if text.rstrip().endswith("!") and preset.id != "calm":
        return round(preset.speed * 1.03, 3)
    return preset.speed
