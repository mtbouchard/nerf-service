"""World Labs-mode tests — no network, completely mocked.

We flip the app into BACKEND=worldlabs and monkeypatch worldlabs_backend so we can
assert the entire integration: uploading frames, submitting jobs, mapping operation
status, and redirecting result requests.
"""
import importlib
import os
import pytest
from fastapi.testclient import TestClient

import worldlabs_backend
from tests.conftest import make_jpeg

target = importlib.import_module(os.environ.get("APP_MODULE", "app"))


@pytest.fixture()
def worldlabs_client_fixture(monkeypatch):
    """Put the app in worldlabs mode and stub out the worldlabs_backend calls."""
    monkeypatch.setattr(target, "BACKEND", "worldlabs")

    uploaded_files: list[tuple[str, str]] = []
    submitted_assets: list[str] = []

    def fake_upload_image(fileobj, file_name):
        fileobj.read()  # drain like the real call
        asset_id = f"asset-{len(uploaded_files)}"
        uploaded_files.append((file_name, asset_id))
        return asset_id

    def fake_submit(asset_ids):
        for aid in asset_ids:
            submitted_assets.append(aid)
        return "op-12345"

    monkeypatch.setattr(worldlabs_backend, "upload_image", fake_upload_image)
    monkeypatch.setattr(worldlabs_backend, "submit", fake_submit)

    client = TestClient(target.app)
    client.uploaded_files = uploaded_files  # expose for assertions
    client.submitted_assets = submitted_assets
    return client


def _upload_frames(client, n=3):
    ids = []
    for i in range(n):
        r = client.post("/upload", files={"file": (f"frame_{i}.jpg", make_jpeg(), "image/jpeg")})
        assert r.status_code == 200
        ids.append(r.json()["id"])
    return ids


def test_upload_stores_asset_ids(worldlabs_client_fixture):
    client = worldlabs_client_fixture
    ids = _upload_frames(client, 3)

    # In worldlabs mode, uploads[] maps our internal image_id -> worldlabs asset_id
    assert len(client.uploaded_files) == 3
    assert client.uploaded_files[0][0] == f"{ids[0]}.jpg"
    assert client.uploaded_files[0][1] == "asset-0"

    assert target.uploads[ids[0]] == "asset-0"
    assert target.uploads[ids[1]] == "asset-1"
    assert target.uploads[ids[2]] == "asset-2"


def test_nerfify_submits_to_worldlabs(worldlabs_client_fixture):
    client = worldlabs_client_fixture
    ids = _upload_frames(client, 3)

    r = client.post("/nerfify", json={"images": ids})
    assert r.status_code == 202
    job_id = r.json()["job_id"]

    # Submit received the correct asset_ids
    assert client.submitted_assets == ["asset-0", "asset-1", "asset-2"]
    
    # Job stored the operation_id
    assert target.jobs[job_id].operation_id == "op-12345"


def test_jobs_maps_worldlabs_state(worldlabs_client_fixture, monkeypatch):
    client = worldlabs_client_fixture
    ids = _upload_frames(client, 3)
    job_id = client.post("/nerfify", json={"images": ids}).json()["job_id"]

    # 1. World Labs says IN_QUEUE -> our "pending"
    monkeypatch.setattr(worldlabs_backend, "fetch_status", lambda opid: ("pending", None, None))
    assert client.get(f"/jobs/{job_id}").json()["status"] == "pending"

    # 2. World Labs says IN_PROGRESS -> our "running"
    monkeypatch.setattr(worldlabs_backend, "fetch_status", lambda opid: ("running", None, None))
    assert client.get(f"/jobs/{job_id}").json()["status"] == "running"

    # 3. World Labs says COMPLETED -> our "done", returns the world_url
    fake_world_url = "https://marble.worldlabs.ai/world/world-999"
    monkeypatch.setattr(worldlabs_backend, "fetch_status", lambda opid: ("done", None, fake_world_url))
    
    body = client.get(f"/jobs/{job_id}").json()
    assert body["status"] == "done"
    assert body["result_format"] == "world"


def test_failed_job_surfaces_error(worldlabs_client_fixture, monkeypatch):
    client = worldlabs_client_fixture
    ids = _upload_frames(client, 3)
    job_id = client.post("/nerfify", json={"images": ids}).json()["job_id"]

    monkeypatch.setattr(worldlabs_backend, "fetch_status", lambda opid: ("failed", "credit limit reached", None))
    body = client.get(f"/jobs/{job_id}").json()
    assert body["status"] == "failed"
    assert body["error"] == "credit limit reached"


def test_result_redirects_to_marble_url(worldlabs_client_fixture, monkeypatch):
    client = worldlabs_client_fixture
    ids = _upload_frames(client, 3)
    job_id = client.post("/nerfify", json={"images": ids}).json()["job_id"]

    # Mark job as done
    fake_world_url = "https://marble.worldlabs.ai/world/world-999"
    monkeypatch.setattr(worldlabs_backend, "fetch_status", lambda opid: ("done", None, fake_world_url))
    client.get(f"/jobs/{job_id}")  # trigger state update

    # Result endpoint should 3xx redirect to the marble world URL
    r = client.get(f"/jobs/{job_id}/result", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert r.headers["location"] == fake_world_url
