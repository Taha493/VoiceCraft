"""Background music: a curated CC BY 4.0 library plus the user's own tracks.

- Library tracks are downloaded once by `voicecraft setup`, converted to AAC, and their loudness,
  duration and leading silence are measured then, so rendering only applies a known gain.
- Tracks are picked to match the delivery preset's mood, never repeating the most recent picks.
- A job keeps its track across re-renders until the user shuffles or picks another one.
- Users can drop their own audio files into ~/.local/share/voicecraft/music/ (they are used in
  every mood; licensing is then the user's responsibility).
"""

from __future__ import annotations

import json
import random
import re
import subprocess
import tempfile
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from . import config

INCOMPETECH = "https://incompetech.com/music/royalty-free/mp3-royaltyfree/"
CC_BY = "Creative Commons: By Attribution 4.0 License"
CC_BY_URL = "http://creativecommons.org/licenses/by/4.0/"
AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus"}
HISTORY_SIZE = 6

# Which moods suit each delivery preset.
PRESET_MOODS = {
    "pitch": ("corporate", "inspiring"),
    "energetic": ("upbeat",),
    "calm": ("calm",),
    "neutral": ("corporate", "calm"),
}
MOOD_LABELS = {"corporate": "Corporate", "inspiring": "Inspiring", "upbeat": "Upbeat", "calm": "Calm", "any": "Your track"}

# Bed loudness before ducking. The voice sits at -16 LUFS; ducking takes a further ~9 dB off
# while it speaks, so "medium" lands about 19 LU under the voice and comes up in the pauses.
LEVELS = {"low": -30.0, "medium": -26.0, "high": -23.0}


@dataclass(frozen=True)
class Track:
    id: str
    title: str
    artist: str
    moods: tuple[str, ...]
    source: str  # "library" | "user"
    license: str
    url: str = ""

    @property
    def credit(self) -> str:
        if self.source != "library":
            return ""
        return f'"{self.title}" {self.artist} (incompetech.com)\nLicensed under {CC_BY}\n{CC_BY_URL}'

    def to_dict(self) -> dict:
        d = asdict(self)
        d["credit"] = self.credit
        d["mood_labels"] = [MOOD_LABELS.get(m, m) for m in self.moods]
        return d


def _km(title: str, *moods: str) -> Track:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return Track(slug, title, "Kevin MacLeod", moods, "library", "CC BY 4.0", INCOMPETECH + urllib.parse.quote(title) + ".mp3")


# Chosen by measured steadiness (no near-silent sections or big level jumps), length (long enough
# to cover a typical video without looping) and mood. See docs/BENCHMARKS.md, "Music library".
LIBRARY: list[Track] = [
    _km("Inspired", "inspiring", "corporate"),
    _km("Wholesome", "corporate", "inspiring"),
    _km("Easy Lemon", "corporate", "calm"),
    _km("Carefree", "corporate", "upbeat"),
    _km("Fearless First", "inspiring", "upbeat"),
    _km("Getting it Done", "upbeat", "corporate"),
    _km("Upbeat Forever", "upbeat"),
    _km("Digital Lemonade", "upbeat"),
    _km("Daily Beetle", "upbeat"),
    _km("Floating Cities", "calm"),
    _km("Airport Lounge", "calm"),
    _km("Vibing Over Venus", "calm"),
    _km("Backbay Lounge", "calm"),
    _km("Chill Wave", "calm"),
]


def library_dir() -> Path:
    return config.models_dir() / "music"


def user_dir() -> Path:
    return config.data_home() / "music"


def _index_path() -> Path:
    return library_dir() / "index.json"


def _load_index() -> dict:
    try:
        return json.loads(_index_path().read_text())
    except (OSError, ValueError):
        return {}


def _save_index(index: dict) -> None:
    library_dir().mkdir(parents=True, exist_ok=True)
    _index_path().write_text(json.dumps(index, indent=1))


def track_path(track: Track) -> Path:
    if track.source == "library":
        return library_dir() / f"{track.id}.m4a"
    return user_dir() / track.id


def _user_tracks() -> list[Track]:
    d = user_dir()
    if not d.is_dir():
        return []
    return [
        Track(p.name, p.stem.replace("_", " "), "", ("any",), "user", "Your own track")
        for p in sorted(d.iterdir())
        if p.suffix.lower() in AUDIO_EXTS and p.is_file()
    ]


def installed() -> list[Track]:
    return [t for t in LIBRARY if track_path(t).exists()] + _user_tracks()


def get(track_id: str) -> Track | None:
    return next((t for t in installed() if t.id == track_id), None)


def measure(path: Path) -> dict:
    """Duration, integrated loudness and leading silence of an audio file."""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostdin", "-i", str(path), "-af",
         "silencedetect=n=-45dB:d=0.3,loudnorm=print_format=json", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", proc.stderr, re.S)
    stats = json.loads(m.group(0)) if m else {}
    dur = re.search(r"Duration: (\d+):(\d+):([\d.]+)", proc.stderr)
    duration = int(dur.group(1)) * 3600 + int(dur.group(2)) * 60 + float(dur.group(3)) if dur else 0.0
    lead = 0.0
    first = re.search(r"silence_start: (-?[\d.]+)\n.*?silence_end: ([\d.]+)", proc.stderr, re.S)
    if first and float(first.group(1)) <= 0.05:
        lead = float(first.group(2))
    lufs = float(stats.get("input_i", -20)) if stats.get("input_i") not in (None, "-inf") else -20.0
    return {"duration": round(duration, 2), "lufs": round(lufs, 2), "lead": round(min(lead, 5.0), 2)}


def info(track: Track) -> dict:
    """Cached measurements (library tracks are measured at setup; user tracks on first use)."""
    index = _load_index()
    path = track_path(track)
    key = track.id if track.source == "library" else f"user:{track.id}:{int(path.stat().st_mtime)}"
    if key not in index:
        index[key] = measure(path)
        _save_index(index)
    return index[key]


def install_library(progress: Callable[[str, float], None] | None = None, source_dir: Path | None = None) -> list[str]:
    """Download library tracks, convert to AAC 160k stereo, and measure them. Returns installed ids.

    `source_dir` may hold already-downloaded "<Title>.mp3" files (offline install).
    """
    library_dir().mkdir(parents=True, exist_ok=True)
    done = []
    for i, track in enumerate(LIBRARY):
        dest = track_path(track)
        if not dest.exists():
            with tempfile.TemporaryDirectory() as tmp:
                local = source_dir / f"{track.title}.mp3" if source_dir else None
                src = local if local and local.exists() else Path(tmp) / "src.mp3"
                if src != local:
                    with urllib.request.urlopen(track.url, timeout=120) as resp, src.open("wb") as f:
                        while chunk := resp.read(1 << 20):
                            f.write(chunk)
                part = dest.with_suffix(".part.m4a")
                subprocess.run(
                    ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vn", "-ac", "2", "-ar", "48000",
                     "-c:a", "aac", "-b:a", "160k", "-metadata", f"title={track.title}",
                     "-metadata", f"artist={track.artist}", "-metadata", f"comment={track.credit}", str(part)],
                    check=True,
                )
                part.replace(dest)
        info(track)
        done.append(track.id)
        if progress:
            progress(track.title, (i + 1) / len(LIBRARY))
    return done


# ---- selection ---------------------------------------------------------------------------------


def _history_path() -> Path:
    return config.data_home() / "music_history.json"


def recent() -> list[str]:
    try:
        return list(json.loads(_history_path().read_text()))
    except (OSError, ValueError):
        return []


def record_use(track_id: str) -> None:
    hist = [t for t in recent() if t != track_id]
    hist.insert(0, track_id)
    _history_path().parent.mkdir(parents=True, exist_ok=True)
    _history_path().write_text(json.dumps(hist[:HISTORY_SIZE]))


def choose(preset: str, duration: float, avoid: set[str] | None = None, rng: random.Random | None = None) -> Track | None:
    """Random mood-matched track, skipping recent picks; prefers tracks long enough not to loop."""
    rng = rng or random.Random()
    tracks = installed()
    if not tracks:
        return None
    moods = set(PRESET_MOODS.get(preset, PRESET_MOODS["neutral"]))
    matched = [t for t in tracks if moods & set(t.moods) or "any" in t.moods] or tracks
    avoid = (avoid or set()) | set(recent()[: max(0, min(HISTORY_SIZE, len(matched) - 1))])
    fresh = [t for t in matched if t.id not in avoid] or [t for t in matched if t.id not in (avoid & set(recent()[:1]))] or matched
    long_enough = [t for t in fresh if info(t)["duration"] - info(t)["lead"] >= duration + 1]
    return rng.choice(long_enough or fresh)


def resolve_for_job(job_dir: Path, choice: str, preset: str, duration: float, shuffle: bool = False) -> Track | None:
    """The job's track: kept stable across re-renders, re-picked on shuffle or when it disappears."""
    if choice == "none":
        return None
    state = job_dir / "music.json"
    if choice != "auto":
        return get(choice) or resolve_for_job(job_dir, "auto", preset, duration, shuffle)
    current = None
    try:
        current = json.loads(state.read_text()).get("track")
    except (OSError, ValueError):
        pass
    if current and not shuffle and get(current):
        return get(current)
    track = choose(preset, duration, avoid={current} if current else None)
    if track:
        state.write_text(json.dumps({"track": track.id}))
        record_use(track.id)
    return track
