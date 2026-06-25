"""Acceptance tests for the nerf-service API (local backend)."""
import io

from tests.conftest import make_jpeg
from tests.workflow_helpers import run_upload_to_ply_workflow, upload_frame, upload_n_frames


def upload(client, color=(120, 80, 200)):
    return upload_frame(client, color=color)


def upload_n(client, n):
    return upload_n_frames(client, n)


def test_health(client):
    body = client.get("/healthz").json()
    assert body["status"] == "ok"
    assert body["backend"] == "local"


def test_upload_returns_id(client):
    res = upload(client)
    assert res.status_code == 200
    assert isinstance(res.json()["id"], str)


def test_upload_rejects_non_image(client):
    res = client.post("/upload", files={"file": ("x.txt", io.BytesIO(b"hi"), "text/plain")})
    assert res.status_code == 400


def test_nerfify_happy_path(client):
    _, ply_bytes = run_upload_to_ply_workflow(client, n_frames=5)
    assert ply_bytes.startswith(b"ply\n")
    assert b"element vertex" in ply_bytes


def test_nerfify_too_few_frames(client):
    ids = upload_n(client, 1)  # below min_frames; NerfifyRequest needs >=2, route needs >=3
    # one id -> schema 422
    assert client.post("/nerfify", json={"images": ids}).status_code == 422
    # two ids -> passes schema, fails the min_frames business rule -> 400
    ids2 = upload_n(client, 2)
    assert client.post("/nerfify", json={"images": ids2}).status_code == 400


def test_nerfify_unknown_id_404(client):
    ids = upload_n(client, 3)
    ids[1] = "nope"
    assert client.post("/nerfify", json={"images": ids}).status_code == 404


def test_status_unknown_job_404(client):
    assert client.get("/jobs/doesnotexist").status_code == 404


def test_result_unknown_job_404(client):
    assert client.get("/jobs/doesnotexist/result").status_code == 404
