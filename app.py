"""
nerf-service — single-file app (the one YOU edit).

This is the long-job sibling of stitch-service. A NeRF reconstruction takes minutes, so the
client can't wait on one request — instead we use the 202 + poll pattern:

    POST /upload          multipart "file"        -> {"id": "..."}        (once per frame)
    POST /nerfify         {"images": [id1, ...]}  -> 202 {"job_id", "status": "pending"}
    GET  /jobs/<job_id>                           -> {"status": "running"|"done"|"failed"}
    GET  /jobs/<job_id>/result                    -> the .ply splat (409 until done)

Locally the "compute" runs as a FastAPI BackgroundTask (in-process) via the given helper
`run_job(...)`, which calls pipeline.generate_pointcloud_ply. You implement the 4 endpoints
marked TODO. /healthz and / are done for you. solution_app.py is the full reference.

Run:
    uvicorn app:app --reload
    pytest
    uvicorn solution_app:app --reload   # the working reference
"""
import os
from enum import Enum
from pathlib import Path
from uuid import uuid4

from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, Field

import pipeline

# --- config (plain constants; env overrides where useful) --------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
RESULTS_DIR = DATA_DIR / "results"
BACKEND = os.environ.get("NERF_BACKEND", "local")  # only "local" is implemented here
MIN_FRAMES = 3              # a NeRF needs several overlapping views
MAX_FRAMES = 80
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
RESULT_FORMAT = "ply"

UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


# --- models ------------------------------------------------------------------
class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class UploadResponse(BaseModel):
    id: str


class NerfifyRequest(BaseModel):
    # >=2 enforced by the schema; the >=MIN_FRAMES business rule is checked in the route.
    images: list[str] = Field(min_length=2)


class JobCreatedResponse(BaseModel):
    job_id: str
    status: JobStatus


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    error: str | None = None
    result_format: str | None = None


class Job(BaseModel):
    id: str
    status: JobStatus = JobStatus.PENDING
    image_ids: list[str] = []
    result_path: str | None = None
    error: str | None = None


# --- in-memory stores --------------------------------------------------------
uploads: dict[str, str] = {}   # image_id -> saved file path
jobs: dict[str, Job] = {}      # job_id   -> Job


def reset_state() -> None:
    uploads.clear()
    jobs.clear()


# --- the background worker (GIVEN) -------------------------------------------
def run_job(job_id: str) -> None:
    """Runs in a BackgroundTask: flip the job to RUNNING, run the pipeline, then DONE/FAILED.
    Your /nerfify endpoint schedules this with background_tasks.add_task(run_job, job_id)."""
    job = jobs.get(job_id)
    if job is None:
        return
    job.status = JobStatus.RUNNING
    try:
        paths = [uploads[i] for i in job.image_ids]
        out_path = str(RESULTS_DIR / f"{job_id}.{RESULT_FORMAT}")
        pipeline.generate_pointcloud_ply(paths, out_path)
        job.result_path = out_path
        job.status = JobStatus.DONE
    except Exception as exc:  # noqa: BLE001 - record the failure for the status endpoint
        job.status = JobStatus.FAILED
        job.error = str(exc)


# --- app ---------------------------------------------------------------------
app = FastAPI(title="NeRF Service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=(os.environ.get("CORS_ALLOW_ORIGINS", "*").split(",")),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
def healthz():
    return {"status": "ok", "backend": BACKEND}


# =============================================================================
# YOUR ASSIGNMENT — implement the four endpoints below.
# =============================================================================
#
# POST /upload   (multipart "file")  -> {"id": ...}
#   - 400 if not an image; 413 if larger than MAX_UPLOAD_BYTES
#   - save under UPLOADS_DIR as "<id>.jpg"; record uploads[id] = path
#
# POST /nerfify  body {"images": [id1, ...]}  -> 202 {"job_id", "status"}
#   - 400 if fewer than MIN_FRAMES or more than MAX_FRAMES ids
#   - 404 if any id isn't in uploads
#   - create a Job (status PENDING) in `jobs`, then schedule the work WITHOUT blocking:
#         background_tasks.add_task(run_job, job_id)
#   - return JobCreatedResponse with HTTP 202 (set status_code on the decorator)
#
# GET /jobs/{job_id}  -> JobStatusResponse
#   - 404 if unknown; otherwise return the job's status (+ error, + result_format when DONE)
#
# GET /jobs/{job_id}/result  -> the .ply file
#   - 404 if unknown; 500 if FAILED; 409 if not DONE yet
#   - otherwise FileResponse(job.result_path, media_type="application/octet-stream")
#
# The job returns immediately (202) and the heavy work happens in the background task; the
# client polls /jobs/{id} until "done", then downloads /jobs/{id}/result.

# Your code here.


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def landing():
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{app.title}</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 720px; margin: 64px auto;
         padding: 0 20px; line-height: 1.6; }}
  code, pre {{ background:#f0f0f3; padding:2px 6px; border-radius:4px; }}
  a {{ color:#7c3aed; }} .pill {{ background:#ede9fe; color:#6d28d9; padding:2px 10px;
       border-radius:999px; font-size:13px; }}
</style></head>
<body>
  <h1>{app.title} <span class="pill">backend: {BACKEND}</span></h1>
  <p>Upload a series of overlapping photos, start a NeRF job, poll it, then download a 3D
     point cloud (<code>.{RESULT_FORMAT}</code>). Minutes-long work, so it's 202 + poll.</p>
  <ul>
    <li><a href="/docs">Interactive API docs (/docs)</a></li>
    <li><a href="/healthz">Health check (/healthz)</a></li>
  </ul>
  <pre><code>POST /upload          multipart "file"          -> {{"id": "..."}}   (repeat per frame)
POST /nerfify         {{"images": [id1, ...]}}    -> 202 {{"job_id": "...", "status": "pending"}}
GET  /jobs/&lt;job_id&gt;                              -> {{"status": "running", ...}}
GET  /jobs/&lt;job_id&gt;/result                       -> the .{RESULT_FORMAT} file</code></pre>
</body></html>"""
