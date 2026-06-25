"""End-to-end workflow tests: upload photos -> nerfify -> poll -> download .ply

Mirrors client/client.py using FastAPI TestClient — no live network or GPU required.
"""
import importlib
import os

import httpx
import pytest
from fastapi.testclient import TestClient

import runpod_client
import storage
from tests.workflow_helpers import (
    assert_valid_ascii_ply,
    poll_job,
    run_upload_to_ply_workflow,
    upload_n_frames,
)

target = importlib.import_module(os.environ.get("APP_MODULE", "app"))

# pipeline.py uses a 48x48 grid per uploaded frame
VERTICES_PER_FRAME = 48 * 48

FAKE_PLY = (
    b"ply\nformat ascii 1.0\nelement vertex 3\n"
    b"property float x\nproperty float y\nproperty float z\n"
    b"end_header\n"
    b"0 0 0\n1 0 0\n0 1 0\n"
)


def test_full_workflow_upload_nerfify_returns_ply(client):
    """Upload several JPEGs, start a job, poll to completion, and receive a valid .ply."""
    n_frames = 5
    job_id, ply_bytes = run_upload_to_ply_workflow(client, n_frames=n_frames)

    assert job_id
    assert_valid_ascii_ply(ply_bytes, min_vertices=n_frames * VERTICES_PER_FRAME)


@pytest.fixture()
def runpod_e2e_client(monkeypatch):
    """RunPod mode with mocked storage, job status transitions, and signed .ply download."""
    monkeypatch.setattr(target, "BACKEND", "runpod")

    poll_state = {"phase": 0}

    def fake_upload_fileobj(fileobj, key, content_type="application/octet-stream"):
        fileobj.read()

    def fake_submit(job_id, image_keys):
        return f"runpod-{job_id}"

    def fake_fetch_status(_runpod_id):
        if poll_state["phase"] == 0:
            poll_state["phase"] = 1
            return "running", None
        return "done", None

    def fake_presign(job_id):
        return f"https://signed.example/results/{job_id}.ply"

    def fake_get(url, headers=None, timeout=None, follow_redirects=None):
        if "signed.example" in url:
            return httpx.Response(200, content=FAKE_PLY)
        raise AssertionError(f"unexpected GET {url}")

    monkeypatch.setattr(storage, "upload_fileobj", fake_upload_fileobj)
    monkeypatch.setattr(runpod_client, "submit", fake_submit)
    monkeypatch.setattr(runpod_client, "fetch_status", fake_fetch_status)
    monkeypatch.setattr(runpod_client, "presign_result_get", fake_presign)
    monkeypatch.setattr(httpx, "get", fake_get)

    return TestClient(target.app)


def test_full_workflow_runpod_upload_nerfify_returns_ply(runpod_e2e_client):
    """Production backend wiring: upload to object storage, submit GPU job, poll, fetch .ply."""
    client = runpod_e2e_client
    ids = upload_n_frames(client, 3)

    res = client.post("/nerfify", json={"images": ids})
    assert res.status_code == 202
    job_id = res.json()["job_id"]

    first = client.get(f"/jobs/{job_id}").json()
    assert first["status"] == "running"

    done = poll_job(client, job_id)
    assert done["status"] == "done"
    assert done["result_format"] == "ply"

    result = client.get(f"/jobs/{job_id}/result", follow_redirects=False)
    assert result.status_code in (302, 307)
    assert result.headers["location"] == f"https://signed.example/results/{job_id}.ply"

    # TestClient does not use our httpx.get mock when following redirects; fetch explicitly.
    signed = httpx.get(result.headers["location"])
    assert signed.status_code == 200
    assert_valid_ascii_ply(signed.content, min_vertices=3)
