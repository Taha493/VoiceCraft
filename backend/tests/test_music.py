import random
import subprocess

import pytest

from voicecraft import music


@pytest.fixture()
def lib(tmp_path, monkeypatch):
    """A fake library of short sine-tone tracks in a temporary data home."""
    monkeypatch.setenv("VOICECRAFT_HOME", str(tmp_path))
    tracks = [
        music.Track(f"t{i}", f"Track {i}", "Test", moods, "library", "CC BY 4.0")
        for i, moods in enumerate([("corporate",), ("corporate", "inspiring"), ("inspiring",), ("upbeat",), ("upbeat",), ("calm",), ("calm",)])
    ]
    monkeypatch.setattr(music, "LIBRARY", tracks)
    music.library_dir().mkdir(parents=True)
    for i, t in enumerate(tracks):
        subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"sine=f={220 + 40 * i}:d={20 + i}", "-c:a", "aac", str(music.track_path(t))],
            check=True,
        )
    return tracks


def test_mood_matches_preset(lib):
    for _ in range(10):
        assert set(music.choose("energetic", 5).moods) == {"upbeat"}
        assert "calm" in music.choose("calm", 5).moods


def test_consecutive_videos_do_not_repeat(lib):
    rng = random.Random(1)
    picks = []
    for _ in range(12):
        t = music.choose("pitch", 5, rng=rng)
        music.record_use(t.id)
        picks.append(t.id)
    assert all(a != b for a, b in zip(picks, picks[1:]))
    # Three corporate/inspiring tracks: each window of three picks uses all of them.
    assert all(len(set(picks[i : i + 3])) == 3 for i in range(len(picks) - 2))


def test_prefers_tracks_long_enough_to_avoid_looping(lib):
    for _ in range(10):
        assert music.info(music.choose("calm", 24.5))["duration"] >= 25.5  # only t6 (26 s) covers it


def test_job_keeps_its_track_until_shuffled(lib, tmp_path):
    job = tmp_path / "job"
    job.mkdir()
    first = music.resolve_for_job(job, "auto", "pitch", 5)
    assert all(music.resolve_for_job(job, "auto", "pitch", 5).id == first.id for _ in range(5))
    shuffled = music.resolve_for_job(job, "auto", "pitch", 5, shuffle=True)
    assert shuffled.id != first.id
    assert music.resolve_for_job(job, "none", "pitch", 5) is None
    assert music.resolve_for_job(job, "t5", "pitch", 5).id == "t5"


def test_user_tracks_join_every_mood(lib):
    music.user_dir().mkdir(parents=True, exist_ok=True)
    (music.user_dir() / "mine.m4a").write_bytes(music.track_path(lib[0]).read_bytes())
    ids = {music.choose("energetic", 5, rng=random.Random(i)).id for i in range(40)}
    assert "mine.m4a" in ids


def test_credit_format(lib):
    assert lib[0].credit.startswith('"Track 0" Test (incompetech.com)')
    assert "Creative Commons: By Attribution 4.0" in lib[0].credit
