"""Optional caption sources that bypass or assist OCR.

- SRT / WebVTT / JSON: exact text and timings (e.g. exported from the code that rendered the video).
- Plain script: exact text, one caption per line. Timings come from aligning it to OCR captions,
  or, for a video with no captions on screen, from how long each line takes to say.
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher

from ..schema import Caption
from .tracker import clean_text, text_key

_TS = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})")


def _ts(s: str) -> float:
    m = _TS.search(s)
    if not m:
        raise ValueError(f"Bad timestamp: {s!r}")
    h, mnt, sec, ms = m.groups()
    return int(h or 0) * 3600 + int(mnt) * 60 + int(sec) + int(ms.ljust(3, "0")) / 1000


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>|\{\\[^}]*\}", "", text)


def parse_srt_or_vtt(content: str) -> list[Caption]:
    content = content.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    caps: list[Caption] = []
    for block in re.split(r"\n\s*\n", content):
        lines = [l for l in block.strip().split("\n") if l.strip()]
        arrow = next((i for i, l in enumerate(lines) if "-->" in l), None)
        if arrow is None:
            continue
        start_s, end_s = lines[arrow].split("-->", 1)
        text = clean_text(" ".join(_strip_tags(l) for l in lines[arrow + 1 :]))
        if not text:
            continue
        caps.append(Caption(id=f"c{len(caps) + 1}", start=_ts(start_s), end=_ts(end_s.strip().split(" ")[0]), text=text, source="import"))
    return caps


def parse_json(content: str) -> list[Caption]:
    data = json.loads(content)
    items = data.get("captions", data) if isinstance(data, dict) else data
    caps = []
    for it in items:
        caps.append(
            Caption(id=f"c{len(caps) + 1}", start=float(it["start"]), end=float(it["end"]), text=clean_text(str(it["text"])), source="import")
        )
    return caps


def parse_captions_file(filename: str, content: str) -> list[Caption]:
    name = filename.lower()
    if name.endswith((".srt", ".vtt")) or "-->" in content[:2000]:
        caps = parse_srt_or_vtt(content)
    elif name.endswith(".json"):
        caps = parse_json(content)
    else:
        raise ValueError("Unsupported caption file. Use .srt, .vtt or .json (or import a plain-text script).")
    if not caps:
        raise ValueError("No captions found in the file.")
    return sorted(caps, key=lambda c: c.start)


def align_script(script: str, ocr_captions: list[Caption], duration: float) -> list[Caption]:
    """Use the script's exact wording with timings borrowed from OCR captions.

    Monotonic alignment: each script line takes the best-matching OCR caption among the next few
    unclaimed ones. Unmatched lines are placed between their neighbours and flagged.
    """
    lines = _script_lines(script)
    if not ocr_captions:
        return pace_script(script, duration)
    out: list[Caption] = []
    j = 0
    for line in lines:
        key = text_key(line)
        best, best_r = None, 0.0
        for k in range(j, min(j + 5, len(ocr_captions))):
            r = SequenceMatcher(None, key, text_key(ocr_captions[k].text), autojunk=False).ratio()
            if r > best_r:
                best, best_r = k, r
        if best is not None and best_r >= 0.5:
            oc = ocr_captions[best]
            out.append(Caption(id="", start=oc.start, end=oc.end, text=line, source="script", confidence=round(best_r, 3)))
            j = best + 1
        else:
            out.append(Caption(id="", start=-1, end=-1, text=line, source="script", confidence=0.0, flagged=True, flag_reason="No matching caption on screen; timing estimated"))

    # Fill unmatched timings by spreading them across the gap between matched neighbours.
    i = 0
    while i < len(out):
        if out[i].start >= 0:
            i += 1
            continue
        k = i
        while k < len(out) and out[k].start < 0:
            k += 1
        lo = out[i - 1].end if i > 0 else 0.0
        hi = out[k].start if k < len(out) else duration
        span = max(0.5, (hi - lo)) / (k - i)
        for n in range(i, k):
            out[n].start = round(lo + (n - i) * span, 3)
            out[n].end = round(lo + (n - i + 1) * span, 3)
        i = k
    for n, c in enumerate(out):
        c.id = f"c{n + 1}"
    return out


SPEAKING_RATE = 2.6  # words per second for an unhurried narration voice
LINE_PAUSE = 0.5  # breathing room after each line


def _script_lines(script: str) -> list[str]:
    lines = [clean_text(l) for l in script.replace("\r", "").split("\n") if l.strip()]
    if not lines:
        raise ValueError("The script is empty.")
    return lines


def pace_script(script: str, duration: float, lead_in: float = 0.5) -> list[Caption]:
    """Time a plain script for a video with no captions on screen.

    Each line gets a slot proportional to how long it takes to say. Leftover time is shared out as
    extra pauses so the narration spans the whole video instead of bunching at the start. If the
    script takes longer to say than the video lasts, slots are squeezed to fit inside the video and
    the planner's overrun ladder (speed-up, frame holds) makes room for the speech.
    """
    lines = _script_lines(script)
    need = [len(l.split()) / SPEAKING_RATE + LINE_PAUSE for l in lines]
    usable = max(1.0, duration - lead_in - 0.5)
    if sum(need) > usable:
        need = [n * usable / sum(need) for n in need]
    spare = max(0.0, usable - sum(need))
    gap = spare / len(lines)
    out, t = [], lead_in
    for i, (line, n) in enumerate(zip(lines, need)):
        out.append(Caption(id=f"c{i + 1}", start=round(t, 3), end=round(min(duration, t + n), 3), text=line, source="script"))
        t += n + gap
    return out


def parse_any(filename: str, content: str, duration: float) -> list[Caption]:
    """Caption file (.srt/.vtt/.json) or a plain-text script (.txt), for videos without on-screen captions."""
    name = filename.lower()
    if name.endswith((".srt", ".vtt", ".json")) or "-->" in content[:2000]:
        return parse_captions_file(filename, content)
    if name.endswith((".txt", ".md")) or "." not in name:
        return pace_script(content, duration)
    raise ValueError("Unsupported file. Use .srt, .vtt, .json, or a .txt script with one line per caption.")
