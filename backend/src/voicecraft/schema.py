"""Data passed between stages. Each is persisted as editable JSON in the job directory."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Box(BaseModel):
    x: float
    y: float
    w: float
    h: float


class Region(BaseModel):
    """Normalized caption region (0..1 of frame width/height).

    x/y/w/h is the overall area (what the UI edits). `boxes` lists the separate caption bands
    found automatically (e.g. headline captions at the top and callouts at the bottom); when it is
    empty the single x/y/w/h box is used.
    """

    x: float = 0.0
    y: float = 0.65
    w: float = 1.0
    h: float = 0.35
    auto: bool = True
    confidence: float = 0.0
    ignore_texts: list[str] = Field(default_factory=list)  # static text inside the band (logos, watermarks)
    boxes: list[Box] = Field(default_factory=list)


class Caption(BaseModel):
    id: str
    start: float
    end: float
    text: str
    confidence: float = 1.0
    flagged: bool = False
    flag_reason: str | None = None
    source: Literal["ocr", "import", "edit", "script"] = "ocr"


class CaptionTrack(BaseModel):
    video_fingerprint: str
    duration: float
    region: Region | None = None
    sample_fps: float = 4.0
    ocr_engine: str = "rapidocr"
    captions: list[Caption] = Field(default_factory=list)
    stats: dict = Field(default_factory=dict)


SegmentStatus = Literal["fits", "borrowed", "sped_up", "held", "overrun"]


class Segment(BaseModel):
    id: str
    caption_ids: list[str]
    text: str  # as displayed
    spoken_text: str  # after normalization + lexicon
    preset: str
    caption_start: float  # video time
    caption_end: float  # video time
    start: float  # output time narration starts
    end: float  # output time narration ends
    speed: float
    audio_file: str  # relative to the job's clips dir
    audio_duration: float
    status: SegmentStatus = "fits"
    hold: float = 0.0  # seconds of frozen frame inserted after this segment's caption
    note: str | None = None


class Hold(BaseModel):
    video_time: float  # freeze the frame at this source-video time
    duration: float
    segment_id: str


class Timeline(BaseModel):
    engine: str
    model_id: str
    voice: str
    preset: str
    sample_rate: int
    video_duration: float
    output_duration: float
    segments: list[Segment] = Field(default_factory=list)
    holds: list[Hold] = Field(default_factory=list)
    stats: dict = Field(default_factory=dict)

    def to_output_time(self, video_time: float) -> float:
        return video_time + sum(h.duration for h in self.holds if h.video_time < video_time)
