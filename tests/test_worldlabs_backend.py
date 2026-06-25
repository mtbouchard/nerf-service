"""Unit tests for worldlabs_backend internals — no network, no credits.

These mock httpx directly to verify the three functions you implement in
worldlabs_backend.py. They are RED until the stub is implemented, then GREEN.

(test_worldlabs.py is different: it mocks the whole backend to test app.py wiring.
This file tests the backend's own request-building and response-parsing.)

    pytest tests/test_worldlabs_backend.py -q
"""
import io

import httpx
import pytest

import worldlabs_backend as wl


class FakeResponse:
    def __init__(self, json_data=None, status_code=200, content=b""):
        self._json = json_data or {}
        self.status_code = status_code
        self.content = content

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    # functions guard on the key; give them one so they reach the real logic
    monkeypatch.setattr(wl, "WLT_API_KEY", "test-key")


def test_upload_image_prepares_and_puts(monkeypatch):
    calls = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        calls["post_url"] = url
        calls["post_json"] = json
        calls["post_headers"] = headers
        return FakeResponse({
            "media_asset": {"id": "asset-xyz"},
            "upload_info": {
                "upload_url": "https://upload.example/signed",
                "required_headers": {"x-goog-content-length-range": "0,1048576000"},
            },
        })

    def fake_put(url, headers=None, content=None, timeout=None):
        calls["put_url"] = url
        calls["put_content"] = content
        calls["put_headers"] = headers
        return FakeResponse()

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "put", fake_put)

    asset_id = wl.upload_image(io.BytesIO(b"JPEGBYTES"), "frame_0.jpg")

    assert asset_id == "asset-xyz"
    assert calls["post_url"].endswith("/marble/v1/media-assets:prepare_upload")
    assert calls["post_json"]["kind"] == "image"
    assert calls["post_headers"]["WLT-Api-Key"] == "test-key"
    assert calls["put_url"] == "https://upload.example/signed"
    assert calls["put_content"] == b"JPEGBYTES"


def test_submit_builds_even_azimuths(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return FakeResponse({"operation_id": "op-abc"})

    monkeypatch.setattr(httpx, "post", fake_post)

    op_id = wl.submit(["a", "b", "c", "d"])

    assert op_id == "op-abc"
    assert captured["url"].endswith("/marble/v1/worlds:generate")
    prompt = captured["json"]["world_prompt"]
    assert prompt["type"] == "multi-image"
    azimuths = [item["azimuth"] for item in prompt["multi_image_prompt"]]
    assert azimuths == [0, 90, 180, 270]
    ids = [item["content"]["media_asset_id"] for item in prompt["multi_image_prompt"]]
    assert ids == ["a", "b", "c", "d"]
    assert all(item["content"]["source"] == "media_asset" for item in prompt["multi_image_prompt"])


def _operation(done=False, status=None, error=None, world_url=None):
    return FakeResponse({
        "done": done,
        "error": error,
        "metadata": {"progress": {"status": status}} if status else {},
        "response": {"world_marble_url": world_url} if world_url else None,
    })


@pytest.mark.parametrize("status,expected", [
    ("IN_QUEUE", "pending"),
    ("IN_PROGRESS", "running"),
    (None, "running"),
])
def test_fetch_status_in_progress(monkeypatch, status, expected):
    monkeypatch.setattr(httpx, "get", lambda url, headers=None, timeout=None: _operation(done=False, status=status))
    state, error, world_url = wl.fetch_status("op-1")
    assert state == expected
    assert error is None
    assert world_url is None


def test_fetch_status_done_returns_world_url(monkeypatch):
    url = "https://marble.worldlabs.ai/world/w1"
    monkeypatch.setattr(httpx, "get", lambda u, headers=None, timeout=None: _operation(done=True, status="SUCCEEDED", world_url=url))
    state, error, world_url = wl.fetch_status("op-1")
    assert state == "done"
    assert error is None
    assert world_url == url


def test_fetch_status_failed_surfaces_error(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda u, headers=None, timeout=None: _operation(done=True, error={"message": "insufficient credits"}))
    state, error, world_url = wl.fetch_status("op-1")
    assert state == "failed"
    assert "insufficient credits" in error
    assert world_url is None
