"""Tests run against the local (CPU stand-in) backend - no GPU/cloud required."""
import io
import os

os.environ.setdefault("NERF_BACKEND", "local")

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.store import reset_state


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def fresh_state():
    reset_state()
    yield
    reset_state()


def make_jpeg(color=(120, 80, 200), size=(160, 120)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    buf.seek(0)
    return buf
