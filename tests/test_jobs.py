"""Acceptance tests for the nerf-service API (local backend)."""
import io

from tests.conftest import make_jpeg


def upload(client, color=(120, 80, 200)):
    return client.post(
        "/upload", files={"file": ("f.jpg", make_jpeg(color), "image/jpeg")}
    )


def upload_n(client, n):
    return [upload(client, (60 + i * 20, 80, 200)).json()["id"] for i in range(n)]


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
    ids = upload_n(client, 5)
    res = client.post("/nerfify", json={"images": ids})
    assert res.status_code == 202
    job_id = res.json()["job_id"]
    assert res.json()["status"] == "pending"

    # Local backend: BackgroundTasks finishes before POST returns under TestClient.
    status_res = client.get(f"/jobs/{job_id}")
    assert status_res.status_code == 200
    assert status_res.json()["status"] == "done"
    assert status_res.json()["result_format"] == "ply"

    result = client.get(f"/jobs/{job_id}/result")
    assert result.status_code == 200
    body = result.content
    assert body.startswith(b"ply\n")  # a real .ply header
    assert b"element vertex" in body


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
