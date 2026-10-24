from dataclasses import dataclass
from pathlib import Path

from voicecraft.schema import Caption
from voicecraft.sync.planner import PlanOptions, group_captions, plan_narration
from voicecraft.sync.presets import PRESETS

WORDS_PER_SECOND = 2.5


@dataclass
class FakeClip:
    path: Path
    duration: float


class FakeSynth:
    """Duration = words / (2.5 * speed). Records every call."""

    def __init__(self):
        self.calls = []

    def __call__(self, text, speed, pause):
        self.calls.append((text, speed))
        return FakeClip(Path(f"clip{len(self.calls)}.wav"), len(text.split()) / (WORDS_PER_SECOND * speed))


def cap(i, start, end, text):
    return Caption(id=f"c{i}", start=start, end=end, text=text)


PITCH = PRESETS["pitch"]


def test_fitting_segment_starts_after_lead_in():
    tl = plan_narration([cap(1, 1.0, 4.0, "Meet VoiceCraft today.")], 10.0, FakeSynth(), PITCH, None)
    seg = tl.segments[0]
    assert seg.status == "fits"
    assert abs(seg.start - (1.0 + PITCH.lead_in)) < 1e-6
    assert tl.output_duration == 10.0 and not tl.holds


def test_overrun_borrows_gap_before_next_caption():
    caps = [cap(1, 1.0, 2.0, "one two three four five six"), cap(2, 6.0, 8.0, "Next.")]
    tl = plan_narration(caps, 10.0, FakeSynth(), PITCH, None)
    assert tl.segments[0].status == "borrowed"
    assert tl.segments[0].end <= tl.segments[1].start - PITCH.gap + 1e-6


def test_small_overrun_is_fixed_with_speedup():
    # 11 words = 4.4s at 1.0x; the slot (up to the next line, which may start 0.15s late) is 4.0s.
    caps = [cap(1, 0.0, 3.5, " ".join(["word"] * 11)), cap(2, 4.1, 4.6, "Next.")]
    synth = FakeSynth()
    tl = plan_narration(caps, 10.0, synth, PITCH, None)
    s = tl.segments[0]
    assert s.status == "sped_up"
    assert 1.0 < s.speed <= PITCH.speed * 1.12 + 1e-9
    assert not tl.holds


def test_large_overrun_freezes_frame_and_shifts_later_segments():
    caps = [cap(1, 0.0, 1.5, " ".join(["word"] * 12)), cap(2, 2.0, 4.0, "Next line here.")]
    tl = plan_narration(caps, 10.0, FakeSynth(), PITCH, None, PlanOptions(fps=30))
    first, second = tl.segments
    assert first.status == "held" and first.hold > 0
    assert len(tl.holds) == 1
    assert abs(tl.output_duration - (10.0 + tl.holds[0].duration)) < 1e-6
    # Second segment keeps its alignment with its caption on the shifted output timeline.
    assert abs(second.start - (2.0 + tl.holds[0].duration + PITCH.lead_in)) < 1e-3
    assert second.start >= first.end + PITCH.gap - 1e-6
    # Hold duration is a whole number of frames.
    assert abs(round(first.hold * 30) - first.hold * 30) < 0.05  # whole frames (stored to 1 ms)


def test_without_holds_overrun_is_flagged_and_never_overlaps():
    caps = [cap(1, 0.0, 1.5, " ".join(["word"] * 12)), cap(2, 2.0, 4.0, "Next line here.")]
    tl = plan_narration(caps, 10.0, FakeSynth(), PITCH, None, PlanOptions(allow_holds=False))
    first, second = tl.segments
    assert first.status == "overrun"
    assert second.start >= first.end + PITCH.gap - 1e-6
    assert not tl.holds


def test_last_segment_extends_video_end_with_hold():
    tl = plan_narration([cap(1, 8.0, 9.5, " ".join(["word"] * 8))], 10.0, FakeSynth(), PITCH, None)
    assert tl.holds and tl.holds[0].video_time == 10.0
    assert tl.segments[0].end <= tl.output_duration


def test_grouping_merges_lowercase_continuations_only():
    caps = [cap(1, 0.0, 1.0, "We turn silent videos"), cap(2, 1.1, 2.0, "into narrated stories."), cap(3, 2.1, 3.0, "Try it now")]
    groups = group_captions(caps)
    assert [[c.id for c in g] for g in groups] == [["c1", "c2"], ["c3"]]


def test_unspeakable_captions_are_skipped():
    tl = plan_narration([cap(1, 0.0, 1.0, "|| --"), cap(2, 2.0, 4.0, "Hello there.")], 10.0, FakeSynth(), PITCH, None)
    assert [s.caption_ids for s in tl.segments] == [["c2"]]


def test_next_line_may_start_slightly_late_instead_of_freezing():
    # 3 words = 1.2 s, but the next caption appears 0.8 s later (and stays up for 4 s).
    caps = [cap(1, 1.0, 1.8, "one two three"), cap(2, 1.8, 5.8, "Second line here.")]
    tl = plan_narration(caps, 10.0, FakeSynth(), PITCH, None)
    first, second = tl.segments
    assert not tl.holds
    assert second.start >= first.end + PITCH.gap - 1e-6
    assert second.start <= 1.8 + PITCH.lead_in + 0.8 + 1e-6  # at most 0.8 s late
