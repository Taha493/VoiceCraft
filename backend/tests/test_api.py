"""API smoke test: upload → import captions → edit → settings invalidation. No models needed."""

import subprocess

import pytest
from fastapi.testclient import TestClient

from voicecraft.api.app import create_app
from voicecraft.jobs.store import JobStore


@pytest.fixture(scope="module")
def video(tmp_path_factory):
    p = tmp_path_factory.mktemp("v") / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=navy:s=320x180:r=25:d=3",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(p)],
        check=True,
    )
    return p


@pytest.fixture()
def client(tmp_path):
    return TestClient(create_app(JobStore(tmp_path / "jobs")))


def test_job_flow(client, video):
    with video.open("rb") as f:
        r = client.post("/api/jobs", files={"file": ("clip.mp4", f, "video/mp4")})
    assert r.status_code == 200, r.text
    job = r.json()
    jid = job["id"]
    assert job["info"]["duration"] == pytest.approx(3.0, abs=0.1)
    assert not job["info"]["has_audio"]

    # Narration requires captions first.
    assert client.post(f"/api/jobs/{jid}/run", json={"stages": ["narrate"]}).status_code == 400

    srt = "1\n00:00:00,500 --> 00:00:02,000\nHello there.\n"
    r = client.post(f"/api/jobs/{jid}/captions/import", files={"file": ("c.srt", srt, "text/plain")})
    assert r.status_code == 200 and r.json()["captions"][0]["text"] == "Hello there."
    assert client.get(f"/api/jobs/{jid}").json()["stages"]["captions"]["status"] == "done"

    caps = r.json()["captions"]
    caps[0]["text"] = "Hello, world."
    r = client.put(f"/api/jobs/{jid}/captions", json={"captions": caps})
    assert r.json()["captions"][0]["source"] == "edit"

    r = client.patch(f"/api/jobs/{jid}/settings", json={"engine": "piper"})
    assert r.json()["settings"]["voice"] == "en_US-joe-medium"

    assert client.get(f"/api/jobs/{jid}/frame", params={"t": 1}).headers["content-type"] == "image/jpeg"
    assert client.get(f"/api/jobs/{jid}/output").status_code == 404
    assert client.delete(f"/api/jobs/{jid}").status_code == 200


def test_rejects_non_video(client):
    r = client.post("/api/jobs", files={"file": ("notes.txt", b"hi", "text/plain")})
    assert r.status_code == 400


def test_options(client):
    data = client.get("/api/options").json()
    assert {e["id"] for e in data["engines"]} == {"kokoro", "piper"}
    assert any(p["id"] == "pitch" for p in data["presets"])


def test_upload_without_burned_captions_needs_a_file(client, video):
    with video.open("rb") as f:
        r = client.post("/api/jobs", files={"file": ("clip.mp4", f, "video/mp4")}, data={"has_captions": "false"})
    assert r.status_code == 400


def test_upload_with_caption_file_skips_ocr(client, video):
    srt = "1\n00:00:00,500 --> 00:00:02,000\nHello there.\n"
    with video.open("rb") as f:
        r = client.post(
            "/api/jobs",
            files={"file": ("clip.mp4", f, "video/mp4"), "captions": ("subs.srt", srt, "text/plain")},
            data={"has_captions": "false"},
        )
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["settings"]["has_burned_captions"] is False
    assert job["stages"]["captions"]["status"] == "done"
    assert client.get(f"/api/jobs/{job['id']}/captions").json()["captions"][0]["text"] == "Hello there."
    # OCR is refused for a job without on-screen captions.
    assert client.post(f"/api/jobs/{job['id']}/run", json={"stages": ["captions"]}).status_code == 400


def test_upload_with_script_paces_lines(client, video):
    with video.open("rb") as f:
        r = client.post(
            "/api/jobs",
            files={"file": ("clip.mp4", f, "video/mp4"), "captions": ("script.txt", "One line.\nTwo lines here.", "text/plain")},
            data={"has_captions": "false"},
        )
    caps = client.get(f"/api/jobs/{r.json()['id']}/captions").json()["captions"]
    assert [c["text"] for c in caps] == ["One line.", "Two lines here."]
    assert caps[1]["start"] >= caps[0]["end"] and caps[1]["end"] <= 3.0
