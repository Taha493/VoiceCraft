import pytest

from voicecraft.captions.importers import align_script, parse_captions_file
from voicecraft.schema import Caption

SRT = """1
00:00:00,600 --> 00:00:03,400
Meet <b>VoiceCraft</b>.

2
00:00:04,000 --> 00:00:07,400
Turn silent videos
into narrated stories.
"""

VTT = """WEBVTT

00:00.600 --> 00:03.400 align:center
Meet VoiceCraft.

00:01:04.000 --> 00:01:07.400
Second.
"""


def test_srt():
    caps = parse_captions_file("a.srt", SRT)
    assert [(c.start, c.end, c.text) for c in caps] == [
        (0.6, 3.4, "Meet VoiceCraft."),
        (4.0, 7.4, "Turn silent videos into narrated stories."),
    ]
    assert all(c.source == "import" for c in caps)


def test_vtt():
    caps = parse_captions_file("a.vtt", VTT)
    assert caps[0].start == 0.6 and caps[1].start == 64.0 and caps[1].text == "Second."


def test_json():
    caps = parse_captions_file("a.json", '{"captions": [{"start": 1, "end": 2, "text": "Hi"}]}')
    assert caps[0].text == "Hi"


def test_bad_format():
    with pytest.raises(ValueError):
        parse_captions_file("a.txt", "hello")


def test_align_script_uses_script_words_and_ocr_times():
    ocr = [
        Caption(id="c1", start=0.6, end=3.4, text="Meet VoiceCraf."),
        Caption(id="c2", start=4.0, end=7.4, text="Turn silent videos into narrated stories"),
    ]
    out = align_script("Meet VoiceCraft.\nAn unseen line.\nTurn silent videos into narrated stories.", ocr, 10.0)
    assert [c.text for c in out] == ["Meet VoiceCraft.", "An unseen line.", "Turn silent videos into narrated stories."]
    assert out[0].start == 0.6 and out[2].start == 4.0
    assert out[1].flagged and 3.4 <= out[1].start < out[1].end <= 4.0


def test_pace_script_spreads_lines_by_speaking_time():
    from voicecraft.captions.importers import pace_script

    caps = pace_script("Short one.\nThis line is quite a bit longer than the first one.\nEnd.", 30.0)
    assert [c.text for c in caps] == ["Short one.", "This line is quite a bit longer than the first one.", "End."]
    assert all(b.start >= a.end for a, b in zip(caps, caps[1:]))
    assert (caps[1].end - caps[1].start) > (caps[0].end - caps[0].start)
    assert caps[-1].end <= 30.0 and caps[-1].start > 15.0  # spread across the video, not bunched


def test_pace_script_packs_when_longer_than_video():
    from voicecraft.captions.importers import pace_script

    caps = pace_script("\n".join(["word " * 12] * 4), 8.0)
    assert all(b.start >= a.end - 1e-6 for a, b in zip(caps, caps[1:]))
    assert all(0 <= c.start < c.end <= 8.0 for c in caps)  # never placed past the end of the video


def test_parse_any_accepts_txt_script():
    from voicecraft.captions.importers import parse_any

    caps = parse_any("script.txt", "Hello there.\nSecond line.", 10.0)
    assert len(caps) == 2 and caps[0].source == "script"
