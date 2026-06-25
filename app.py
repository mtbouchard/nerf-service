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
    operation_id: str | None = None      # worldlabs mode: World API operation id (for polling)
    world_url: str | None = None         # worldlabs mode: navigable Marble world URL when done
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
    elif BACKEND == "worldlabs":
        import worldlabs_backend
        missing = worldlabs_backend.required_config()
    else:
        missing = []
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
    elif BACKEND == "worldlabs":
        import worldlabs_backend
        asset_id = worldlabs_backend.upload_image(file.file, f"{image_id}.jpg")
        uploads[image_id] = asset_id  # worldlabs mode: uploads[] holds a World Labs media_asset_id
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
    elif BACKEND == "worldlabs":
        import worldlabs_backend
        job.operation_id = worldlabs_backend.submit([uploads[i] for i in req.images])
    else:
        background_tasks.add_task(run_job, job_id)
    return JobCreatedResponse(job_id=job_id, status=JobStatus.PENDING)

@app.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="job not found")
    job= jobs[job_id]
    terminal = (JobStatus.DONE, JobStatus.FAILED)
    if BACKEND == "runpod" and job.runpod_id and job.status not in terminal:
        import runpod_client
        state, error = runpod_client.fetch_status(job.runpod_id)
        job.status = JobStatus(state)
        if error:
            job.error = error
    elif BACKEND == "worldlabs" and job.operation_id and job.status not in terminal:
        import worldlabs_backend
        state, error, world_url = worldlabs_backend.fetch_status(job.operation_id)
        job.status = JobStatus(state)
        if error:
            job.error = error
        if world_url:
            job.world_url = world_url
    fmt = "world" if BACKEND == "worldlabs" else RESULT_FORMAT
    return JobStatusResponse(
        job_id=job.id, 
        status=job.status, 
        error=job.error, 
        result_format=fmt if job.status == JobStatus.DONE else None)

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
    if BACKEND == "worldlabs":
        if job.world_url is None:
            raise HTTPException(status_code=500, detail="world url unavailable")
        return RedirectResponse(url=job.world_url)
    if job.result_path is None:
        raise HTTPException(status_code=500, detail="job failed")
    return FileResponse(job.result_path, media_type="application/octet-stream")



@app.get("/viewer", response_class=HTMLResponse, include_in_schema=False)
def viewer(url: str):
    """Serve a lightweight, mobile-responsive WebGL 3D Gaussian Splat viewer."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <title>SplatCapture 3D Viewer</title>
    <style>
        body, html {
            margin: 0;
            padding: 0;
            overflow: hidden;
            width: 100%;
            height: 100%;
            background-color: #0d0e14;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            color: #ffffff;
        }
        #canvas {
            width: 100%;
            height: 100%;
            display: block;
        }
        #loader {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            text-align: center;
            pointer-events: none;
            transition: opacity 0.5s ease;
            z-index: 10;
        }
        .spinner {
            border: 3px solid rgba(255, 255, 255, 0.1);
            width: 40px;
            height: 400px;
            width: 48px;
            height: 48px;
            border-radius: 50%;
            border-left-color: #7c3aed;
            animation: spin 1s linear infinite;
            margin: 0 auto 16px auto;
        }
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        .progress-text {
            color: #a78bfa;
            font-size: 15px;
            font-weight: 500;
            letter-spacing: 0.05em;
        }
        #error-msg {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            background: rgba(239, 68, 68, 0.15);
            border: 1px solid rgba(239, 68, 68, 0.4);
            padding: 24px;
            border-radius: 16px;
            text-align: center;
            max-width: 80%;
            display: none;
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            z-index: 20;
        }
        #error-msg h3 {
            margin-top: 0;
            color: #ef4444;
        }
        #error-msg p {
            color: #cbd5e1;
            font-size: 14px;
            line-height: 1.5;
            margin-bottom: 0;
        }
    </style>
</head>
<body>
    <div id="loader">
        <div class="spinner"></div>
        <div id="progress" class="progress-text">Loading 3D Splat... 0%</div>
    </div>
    <div id="error-msg">
        <h3>Viewer Error</h3>
        <p id="error-text">An error occurred while fetching or rendering the 3D model.</p>
    </div>
    <canvas id="canvas"></canvas>

    <script type="module">
        import * as SPLAT from "https://cdn.jsdelivr.net/npm/gsplat@1.2.3";

        const canvas = document.getElementById("canvas");
        const loader = document.getElementById("loader");
        const progressEl = document.getElementById("progress");
        const errorEl = document.getElementById("error-msg");
        const errorTextEl = document.getElementById("error-text");

        function showError(text) {
            loader.style.opacity = "0";
            setTimeout(() => { loader.style.display = "none"; }, 500);
            errorTextEl.textContent = text;
            errorEl.style.display = "block";
        }

        async function main() {
            const urlParams = new URLSearchParams(window.location.search);
            const plyUrl = urlParams.get('url');

            if (!plyUrl) {
                showError("No 'url' parameter provided in the viewer request query.");
                return;
            }

            try {
                const renderer = new SPLAT.WebGLRenderer(canvas);
                const scene = new SPLAT.Scene();
                const camera = new SPLAT.Camera();
                const controls = new SPLAT.OrbitControls(camera, canvas);

                // Set default camera positioning for splats
                camera.position.z = -3;
                camera.position.y = 0.5;

                progressEl.textContent = "Fetching 3D Splat...";
                
                const response = await fetch(plyUrl);
                if (!response.ok) {
                    throw new Error(`Splat fetch failed: Server returned ${response.status}`);
                }

                const contentLength = response.headers.get('content-length');
                let totalBytes = contentLength ? parseInt(contentLength, 10) : 0;
                
                let loadedBytes = 0;
                const reader = response.body.getReader();
                const chunks = [];
                
                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    chunks.push(value);
                    loadedBytes += value.length;
                    if (totalBytes > 0) {
                        const progress = Math.min(Math.round((loadedBytes / totalBytes) * 100), 99);
                        progressEl.textContent = `Downloading... ${progress}%`;
                    } else {
                        progressEl.textContent = `Downloading... ${(loadedBytes / (1024 * 1024)).toFixed(1)}MB`;
                    }
                }

                progressEl.textContent = "Processing 3D Data...";
                const blob = new Blob(chunks, { type: "application/octet-stream" });

                await SPLAT.PLYLoader.LoadFromFileAsync(blob, scene, (progress) => {
                    const p = Math.round(progress * 100);
                    progressEl.textContent = `Building Splats... ${p}%`;
                });

                loader.style.opacity = "0";
                setTimeout(() => {
                    loader.style.display = "none";
                }, 500);

                const handleResize = () => {
                    renderer.setSize(window.innerWidth, window.innerHeight);
                };

                const frame = () => {
                    controls.update();
                    renderer.render(scene, camera);
                    requestAnimationFrame(frame);
                };

                handleResize();
                window.addEventListener("resize", handleResize);
                requestAnimationFrame(frame);

            } catch (err) {
                console.error(err);
                showError(err.message || "An error occurred while loading or initializing the 3D scene.");
            }
        }

        main();
    </script>
</body>
</html>"""


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
    if BACKEND == "worldlabs":
        compute_desc = ("it sends the frames to the <a href=\"https://www.worldlabs.ai\">World "
                        "Labs</a> World API, which generates a fully navigable 3D world")
        result_desc = "redirect to the explorable Marble world"
    else:
        compute_desc = ("it runs structure-from-motion + Gaussian-splatting on a GPU worker, and "
                        f"returns a <code>.{RESULT_FORMAT}</code>")
        result_desc = f"the .{RESULT_FORMAT} file"
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
     frames, {compute_desc}. The job takes minutes, so the API is asynchronous:
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
GET  /jobs/&lt;job_id&gt;/result                       -> {result_desc}</code></pre>
</body></html>"""
