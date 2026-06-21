"""
nerf-service — complete single-file reference (the fallback).

Identical scaffolding to app.py, but the four endpoints are implemented. Run it any time:
    uvicorn solution_app:app --reload
    KATA_TARGET=solution_app pytest        # all green

The long-job pattern: /nerfify returns 202 immediately after scheduling a BackgroundTask;
the client polls /jobs/{id} until "done", then downloads /jobs/{id}/result.
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

# --- config ------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
RESULTS_DIR = DATA_DIR / "results"
BACKEND = os.environ.get("NERF_BACKEND", "local")
MIN_FRAMES = 3
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
uploads: dict[str, str] = {}
jobs: dict[str, Job] = {}


def reset_state() -> None:
    uploads.clear()
    jobs.clear()


# --- the background worker ----------------------------------------------------
def run_job(job_id: str) -> None:
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
    except Exception as exc:  # noqa: BLE001
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


@app.post("/upload", response_model=UploadResponse)
def upload_frame(file: UploadFile = File(...)):
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File must be an image")

    image_id = uuid4().hex[:12]
    path = str(UPLOADS_DIR / f"{image_id}.jpg")

    size = 0
    with open(path, "wb") as out:
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                out.close()
                os.remove(path)
                raise HTTPException(
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File too large"
                )
            out.write(chunk)

    uploads[image_id] = path
    return UploadResponse(id=image_id)


@app.post(
    "/nerfify", response_model=JobCreatedResponse, status_code=status.HTTP_202_ACCEPTED
)
def start_nerfify(req: NerfifyRequest, background_tasks: BackgroundTasks):
    if len(req.images) < MIN_FRAMES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Need at least {MIN_FRAMES} frames for a reconstruction",
        )
    if len(req.images) > MAX_FRAMES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Too many frames (max {MAX_FRAMES})"
        )
    for image_id in req.images:
        if image_id not in uploads:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Frame id not found: {image_id}")

    job_id = uuid4().hex[:12]
    jobs[job_id] = Job(id=job_id, status=JobStatus.PENDING, image_ids=list(req.images))

    background_tasks.add_task(run_job, job_id)

    return JobCreatedResponse(job_id=job_id, status=jobs[job_id].status)


@app.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return JobStatusResponse(
        job_id=job_id,
        status=job.status,
        error=job.error,
        result_format=RESULT_FORMAT if job.status is JobStatus.DONE else None,
    )


@app.get("/jobs/{job_id}/result")
def get_job_result(job_id: str) -> Response:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    if job.status is JobStatus.FAILED:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, f"Job failed: {job.error}"
        )
    if job.status is not JobStatus.DONE:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Job not finished (status: {job.status.value})"
        )
    return FileResponse(
        job.result_path,
        media_type="application/octet-stream",
        filename=f"{job_id}.{RESULT_FORMAT}",
    )


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
