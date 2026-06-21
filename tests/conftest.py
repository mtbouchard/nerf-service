"""Tests run against the local (CPU stand-in) backend - no GPU/cloud required.

KATA_TARGET picks which module to test (default: app.py, your code):
    pytest                          # tests YOUR app.py
    KATA_TARGET=solution_app pytest # tests the reference (should be all green)
"""
import importlib
import io
import os

os.environ.setdefault("NERF_BACKEND", "local")

import pytest
from fastapi.testclient import TestClient
from PIL import Image

target = importlib.import_module(os.environ.get("KATA_TARGET", "app"))


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
