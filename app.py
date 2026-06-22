"""
nerf-service — a FastAPI service for long-running 3D reconstruction jobs.

A reconstruction takes minutes, so the client can't wait on one request — the API uses the
202 + poll pattern:

    POST /upload          multipart "file"        -> {"id": "..."}        (once per frame)
    POST /nerfify         {"images": [id1, ...]}  -> 202 {"job_id", "status": "pending"}
    GET  /jobs/<job_id>                           -> {"status": "running"|"done"|"failed"}
    GET  /jobs/<job_id>/result                    -> the .ply file (409 until done)

The compute runs as a FastAPI BackgroundTask (in-process) via `run_job(...)`, which calls
pipeline.generate_pointcloud_ply. solution_app.py is an equivalent reference implementation.

Run:
    uvicorn app:app --reload
    pytest
    uvicorn solution_app:app --reload
"""
import os
import shutil

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
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
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
SAMPLE_RESULT_KEY = os.environ.get("SAMPLE_RESULT_KEY", "samples/fern.ply")  # runpod-mode demo result

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
    result_path: str | None = None       # local mode: path to the .ply on disk
    runpod_id: str | None = None         # runpod mode: RunPod's job id (for polling)
    result_key: str | None = None        # runpod mode: the S3/R2 key of the result
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
    body = {"status": "ok", "backend": BACKEND}
    if BACKEND == "runpod":
        import runpod_client
        missing = runpod_client.required_config()
        if missing:
            body["status"] = "degraded"
            body["missing_config"] = missing
    return body


# Endpoints to implement (TODO):
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

@app.post("/upload", response_model=UploadResponse)
async def upload_file(file: UploadFile = File(...)):
    if file.content_type != "image/jpeg":
        raise HTTPException(status_code=400, detail="please upload a JPEG image")
    image_id = uuid4().hex[:8]
    if BACKEND == "runpod":
        import storage
        key = f"uploads/{image_id}.jpg"
        storage.upload_fileobj(file.file, key, "image/jpeg")
        uploads[image_id] = key  # runpod mode: uploads[] holds the S3/R2 key, not a path
    else:
        path = os.path.join(UPLOADS_DIR, f"{image_id}.jpg")
        with open(path, "wb") as f:
            shutil.copyfileobj(file.file, f)
        uploads[image_id] = path
    return UploadResponse(id=image_id)

@app.post("/nerfify", response_model=JobCreatedResponse, status_code=status.HTTP_202_ACCEPTED)
def nerfify(req: NerfifyRequest, background_tasks: BackgroundTasks):
    if len(req.images) < MIN_FRAMES or len(req.images) > MAX_FRAMES:
        raise HTTPException(status_code=400, detail="must have between 3 and 80 images") 
    for image_id in req.images:
        if image_id not in uploads:
            raise HTTPException(status_code=404, detail=f"image id {image_id} not found")

    job_id= uuid4().hex[:8]
    job = Job(id=job_id, status=JobStatus.PENDING, image_ids=req.images)
    jobs[job_id] = job
    if BACKEND == "runpod":
        import runpod_client
        job.runpod_id = runpod_client.submit(job_id, [uploads[i] for i in req.images])
        job.result_key = runpod_client.result_key(job_id)
    else:
        background_tasks.add_task(run_job, job_id)
    return JobCreatedResponse(job_id=job_id, status=JobStatus.PENDING)

@app.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="job not found")
    job= jobs[job_id]
    if BACKEND == "runpod" and job.runpod_id and job.status not in (JobStatus.DONE, JobStatus.FAILED):
        import runpod_client
        state, error = runpod_client.fetch_status(job.runpod_id)
        job.status = JobStatus(state)
        if error:
            job.error = error
    return JobStatusResponse(
        job_id=job.id, 
        status=job.status, 
        error=job.error, 
        result_format=RESULT_FORMAT if job.status == JobStatus.DONE else None)

@app.get("/jobs/{job_id}/result")
def get_result(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="job not found")
    job = jobs[job_id]
    if job.status != JobStatus.DONE:
        raise HTTPException(status_code=409, detail="job not done yet")
    if BACKEND == "runpod":
        import runpod_client
        return RedirectResponse(url=runpod_client.presign_result_get(job_id))
    if job.result_path is None:
        raise HTTPException(status_code=500, detail="job failed")
    return FileResponse(job.result_path, media_type="application/octet-stream")



@app.get("/sample", include_in_schema=False)
def sample():
    """Redirect to a presigned download of a pre-baked example result (runpod mode)."""
    if BACKEND != "runpod":
        raise HTTPException(status_code=404, detail="no sample available in this mode")
    import storage
    return RedirectResponse(url=storage.presign_get(SAMPLE_RESULT_KEY))


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def landing():
    sample_block = (
        '<li><a href="/sample">Download a sample result</a> (a real splat from 20 photos) — '
        'then drag the <code>.ply</code> into a viewer like '
        '<a href="https://antimatter15.com/splat/">antimatter15.com/splat</a> or '
        '<a href="https://superspl.at/editor">SuperSplat</a></li>'
        if BACKEND == "runpod" else ""
    )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{app.title}</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 720px; margin: 64px auto;
         padding: 0 20px; line-height: 1.6; }}
  code, pre {{ background:#f0f0f3; padding:2px 6px; border-radius:4px; }}
  a {{ color:#7c3aed; }} .pill {{ background:#ede9fe; color:#6d28d9; padding:2px 10px;
       border-radius:999px; font-size:13px; }}
  h2 {{ margin-top:32px; }}
</style></head>
<body>
  <h1>{app.title} <span class="pill">backend: {BACKEND}</span></h1>
  <p>A small service that turns a set of overlapping photos into a 3D scene. You upload
     frames, it runs structure-from-motion + Gaussian-splatting on a GPU worker, and returns
     a <code>.{RESULT_FORMAT}</code>. The job takes minutes, so the API is asynchronous:
     <strong>submit &rarr; poll &rarr; download</strong> (HTTP 202 + polling).</p>

  <h2>Try it</h2>
  <ul>
    <li><a href="/docs">Open the interactive API docs (/docs)</a> — drive the whole flow from
        your browser: <code>/upload</code> a few overlapping photos, <code>/nerfify</code>,
        poll <code>/jobs/&lt;id&gt;</code>, then <code>/jobs/&lt;id&gt;/result</code>.</li>
    {sample_block}
    <li>Source (FastAPI API + RunPod GPU worker + client):
        <a href="https://github.com/mtbouchard/nerf-service">github.com/mtbouchard/nerf-service</a></li>
    <li><a href="/healthz">Health check (/healthz)</a></li>
  </ul>

  <h2>API</h2>
  <pre><code>POST /upload          multipart "file"          -> {{"id": "..."}}   (repeat per frame)
POST /nerfify         {{"images": [id1, ...]}}    -> 202 {{"job_id": "...", "status": "pending"}}
GET  /jobs/&lt;job_id&gt;                              -> {{"status": "running", ...}}
GET  /jobs/&lt;job_id&gt;/result                       -> the .{RESULT_FORMAT} file</code></pre>
</body></html>"""
