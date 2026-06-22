"""Tests run against the local CPU pipeline - no GPU/cloud required.

APP_MODULE picks which module to test (default: app):
    pytest                          # tests app.py
    APP_MODULE=solution_app pytest  # tests the reference implementation
"""
import importlib
import io
import os

os.environ.setdefault("NERF_BACKEND", "local")

import pytest
from fastapi.testclient import TestClient
from PIL import Image

target = importlib.import_module(os.environ.get("APP_MODULE", "app"))


@pytest.fixture()
def client():
    return TestClient(target.app)


@pytest.fixture(autouse=True)
def fresh_state():
    target.reset_state()
    yield
    target.reset_state()


def make_jpeg(color=(120, 80, 200), size=(160, 120)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    buf.seek(0)
    return buf
