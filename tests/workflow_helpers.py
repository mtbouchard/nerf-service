"""Shared helpers for upload -> nerfify -> poll -> .ply workflow tests."""
from __future__ import annotations

import re

import pytest


def upload_frame(client, *, index: int = 0, color=None):
    from tests.conftest import make_jpeg

    if color is None:
        color = (60 + index * 20, 80, 200)
    return client.post(
        "/upload",
        files={"file": (f"frame_{index:02d}.jpg", make_jpeg(color), "image/jpeg")},
    )


def upload_n_frames(client, n: int) -> list[str]:
    ids: list[str] = []
    for i in range(n):
        res = upload_frame(client, index=i)
        assert res.status_code == 200, res.text
        ids.append(res.json()["id"])
    return ids


def poll_job(client, job_id: str, *, max_polls: int = 60):
    """Poll /jobs/{id} until done or failed, mirroring client/client.py."""
    last = None
    for _ in range(max_polls):
        res = client.get(f"/jobs/{job_id}")
        assert res.status_code == 200, res.text
        last = res.json()
        if last["status"] in ("done", "failed"):
            return last
    pytest.fail(f"job {job_id} did not finish within {max_polls} polls (last={last})")


def assert_valid_ascii_ply(content: bytes, *, min_vertices: int = 1) -> int:
    assert content.startswith(b"ply\n"), "missing PLY magic header"
    text = content.decode("ascii")
    assert "format ascii" in text
    assert "element vertex" in text
    assert "end_header" in text

    match = re.search(r"^element vertex (\d+)$", text, re.MULTILINE)
    assert match is not None, "PLY header missing vertex count"
    vertex_count = int(match.group(1))
    assert vertex_count >= min_vertices, f"expected >= {min_vertices} vertices, got {vertex_count}"

    header_end = text.index("end_header\n") + len("end_header\n")
    data_lines = [ln for ln in text[header_end:].splitlines() if ln.strip()]
    assert len(data_lines) == vertex_count, "vertex data row count does not match header"
    return vertex_count


def run_upload_to_ply_workflow(client, *, n_frames: int = 5) -> tuple[str, bytes]:
    """Full API path: upload frames, nerfify, poll, download result bytes."""
    ids = upload_n_frames(client, n_frames)

    res = client.post("/nerfify", json={"images": ids})
    assert res.status_code == 202, res.text
    body = res.json()
    job_id = body["job_id"]
    assert body["status"] == "pending"

    status = poll_job(client, job_id)
    assert status["status"] == "done", status
    assert status["result_format"] == "ply"

    result = client.get(f"/jobs/{job_id}/result")
    assert result.status_code == 200, result.text
    return job_id, result.content
