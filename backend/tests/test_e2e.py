"""Slow end-to-end tests with the real models. Run with:  VOICECRAFT_E2E=1 uv run pytest tests/test_e2e.py

Requires `voicecraft setup` to have been run.
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from voicecraft import assets
from voicecraft.api.app import create_app
from voicecraft.jobs.store import JobStore

pytestmark = pytest.mark.skipif(
    os.environ.get("VOICECRAFT_E2E") != "1" or not assets.present("kokoro:fp32"),
    reason="set VOICECRAFT_E2E=1 and run `voicecraft setup` first",
)

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def video(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("v") / "pitch.mp4"
    subprocess.run([sys.executable, str(BACKEND / "bench" / "make_test_video.py"), str(out)], check=True, capture_output=True)
    return out


@pytest.mark.skipif(shutil.which("unshare") is None, reason="needs util-linux unshare")
def test_pipeline_runs_without_network(video, tmp_path):
    probe = subprocess.run(["unshare", "-rn", "true"], capture_output=True)
    if probe.returncode != 0:
        pytest.skip("unprivileged network namespaces are disabled")
    out = tmp_path / "out.mp4"
    env = {**os.environ, "VOICECRAFT_CACHE": str(tmp_path / "cache")}
    cli = Path(sys.executable).with_name("voicecraft")
    proc = subprocess.run(["unshare", "-rn", str(cli), "run", str(video), "-o", str(out)], env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-2000:]
    streams = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout.split()
    assert streams == ["video", "audio"]


def wait(client: TestClient, jid: str, timeout: float = 300) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        job = client.get(f"/api/jobs/{jid}").json()
        if not any(s["status"] in ("running", "queued") for s in job["stages"].values()):
            return job
        time.sleep(0.5)
    raise TimeoutError


def test_edit_regenerates_only_changed_segment(video, tmp_path, monkeypatch):
    monkeypatch.setenv("VOICECRAFT_CACHE", str(tmp_path / "cache"))
    client = TestClient(create_app(JobStore(tmp_path / "jobs")))
    with video.open("rb") as f:
        jid = client.post("/api/jobs", files={"file": ("pitch.mp4", f, "video/mp4")}).json()["id"]
    truth = (video.with_suffix(".truth.json")).read_text()
    client.post(f"/api/jobs/{jid}/captions/import", files={"file": ("c.json", truth, "application/json")})

    client.post(f"/api/jobs/{jid}/run", json={"stages": ["narrate", "render"]})
    job = wait(client, jid)
    assert job["stages"]["render"]["status"] == "done", job["stages"]
    first = job["stages"]["narrate"]["result"]

    caps = client.get(f"/api/jobs/{jid}/captions").json()["captions"]
    caps[0]["text"] = "Say hello to VoiceCraft."
    client.put(f"/api/jobs/{jid}/captions", json={"captions": caps})
    assert client.get(f"/api/jobs/{jid}").json()["stages"]["narrate"]["status"] == "stale"

    client.post(f"/api/jobs/{jid}/run", json={"stages": ["narrate", "render"]})
    job = wait(client, jid)
    second = job["stages"]["narrate"]["result"]
    assert second["generated"] == 1
    assert second["reused"] == first["generated"] - 1
    assert client.get(f"/api/jobs/{jid}/output").status_code == 200
