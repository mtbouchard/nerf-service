"""RunPod-mode tests — no GPU, no bucket, no network.

We flip the app into backend=runpod and monkeypatch the two integration modules
(storage, runpod_client) so we can assert the *wiring*: that /upload stores S3 keys,
/nerfify submits to RunPod, /jobs maps RunPod state -> our status, and /result redirects
to a presigned url. The real boto3/httpx calls are never made.
"""
import importlib
import os

import pytest
from fastapi.testclient import TestClient

import runpod_client
import storage
from tests.conftest import make_jpeg

target = importlib.import_module(os.environ.get("APP_MODULE", "app"))


@pytest.fixture()
def runpod_client_fixture(monkeypatch):
    """Put the app in runpod mode and stub out storage + RunPod calls."""
    monkeypatch.setattr(target, "BACKEND", "runpod")

    uploaded_keys: list[str] = []
    submitted: dict = {}

    def fake_upload_fileobj(fileobj, key, content_type="application/octet-stream"):
        fileobj.read()  # drain like the real client would
        uploaded_keys.append(key)

    def fake_submit(job_id, image_keys):
        submitted["job_id"] = job_id
        submitted["image_keys"] = list(image_keys)
        return f"runpod-{job_id}"

    monkeypatch.setattr(storage, "upload_fileobj", fake_upload_fileobj)
    monkeypatch.setattr(runpod_client, "submit", fake_submit)
    monkeypatch.setattr(
        runpod_client, "presign_result_get", lambda job_id: f"https://signed.example/{job_id}.ply"
    )

    client = TestClient(target.app)
    client.uploaded_keys = uploaded_keys  # expose for assertions
    client.submitted = submitted
    return client


def _upload_frames(client, n=3):
    ids = []
    for _ in range(n):
        r = client.post("/upload", files={"file": ("f.jpg", make_jpeg(), "image/jpeg")})
        assert r.status_code == 200
        ids.append(r.json()["id"])
    return ids


def test_upload_stores_s3_keys_not_paths(runpod_client_fixture):
    client = runpod_client_fixture
    ids = _upload_frames(client, 3)
    # uploads[] should hold "uploads/<id>.jpg" keys, and storage.upload_fileobj saw each one
    assert client.uploaded_keys == [f"uploads/{i}.jpg" for i in ids]
    assert all(target.uploads[i] == f"uploads/{i}.jpg" for i in ids)


def test_nerfify_submits_to_runpod(runpod_client_fixture, monkeypatch):
    client = runpod_client_fixture
    ids = _upload_frames(client, 3)

    r = client.post("/nerfify", json={"images": ids})
    assert r.status_code == 202
    job_id = r.json()["job_id"]

    # submit() got the job id and the S3 keys (not local paths)
    assert client.submitted["job_id"] == job_id
    assert client.submitted["image_keys"] == [f"uploads/{i}.jpg" for i in ids]
    # the job remembered RunPod's id so /jobs can poll it
    assert target.jobs[job_id].runpod_id == f"runpod-{job_id}"


def test_jobs_maps_runpod_state(runpod_client_fixture, monkeypatch):
    client = runpod_client_fixture
    ids = _upload_frames(client, 3)
    job_id = client.post("/nerfify", json={"images": ids}).json()["job_id"]

    # First poll: RunPod says IN_PROGRESS -> our "running"
    monkeypatch.setattr(runpod_client, "fetch_status", lambda rid: ("running", None))
    assert client.get(f"/jobs/{job_id}").json()["status"] == "running"

    # Next poll: COMPLETED -> "done"
    monkeypatch.setattr(runpod_client, "fetch_status", lambda rid: ("done", None))
    body = client.get(f"/jobs/{job_id}").json()
    assert body["status"] == "done"
    assert body["result_format"] == "ply"


def test_failed_job_surfaces_error(runpod_client_fixture, monkeypatch):
    client = runpod_client_fixture
    ids = _upload_frames(client, 3)
    job_id = client.post("/nerfify", json={"images": ids}).json()["job_id"]

    monkeypatch.setattr(runpod_client, "fetch_status", lambda rid: ("failed", "colmap blew up"))
    body = client.get(f"/jobs/{job_id}").json()
    assert body["status"] == "failed"
    assert body["error"] == "colmap blew up"


def test_result_redirects_to_presigned_url(runpod_client_fixture, monkeypatch):
    client = runpod_client_fixture
    ids = _upload_frames(client, 3)
    job_id = client.post("/nerfify", json={"images": ids}).json()["job_id"]

    # force the job to done
    monkeypatch.setattr(runpod_client, "fetch_status", lambda rid: ("done", None))
    client.get(f"/jobs/{job_id}")

    r = client.get(f"/jobs/{job_id}/result", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert r.headers["location"] == f"https://signed.example/{job_id}.ply"
