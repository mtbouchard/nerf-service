"""nerf-service API entrypoint.

Run locally (CPU stand-in backend, no GPU/cloud needed):
    uv run uvicorn app.main:app --reload

On Render the start command is:
    uvicorn app.main:app --host 0.0.0.0 --port $PORT

Set NERF_BACKEND=runpod (+ RUNPOD_* and S3_* vars) to offload the real GPU job.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from .config import settings
from .routers import health, jobs

settings.uploads_dir.mkdir(parents=True, exist_ok=True)
settings.results_dir.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description=(
        "Upload a series of frames, reconstruct a 3D Gaussian-splat with a NeRF pipeline "
        "(GPU on RunPod, or a CPU stand-in locally), poll the job, then download the splat."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(jobs.router)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def landing():
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{settings.app_name}</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 720px; margin: 64px auto;
         padding: 0 20px; line-height: 1.6; }}
  code, pre {{ background:#f0f0f3; padding:2px 6px; border-radius:4px; }}
  a {{ color:#7c3aed; }} .pill {{ background:#ede9fe; color:#6d28d9; padding:2px 10px;
       border-radius:999px; font-size:13px; }}
</style></head>
<body>
  <h1>{settings.app_name} <span class="pill">backend: {settings.backend}</span></h1>
  <p>Upload a series of overlapping photos of an object/scene, start a NeRF job, poll it,
     then download a 3D Gaussian-splat (<code>.{settings.result_format}</code>).</p>
  <ul>
    <li><a href="/docs">Interactive API docs (/docs)</a></li>
    <li><a href="/healthz">Health check (/healthz)</a></li>
  </ul>
  <pre><code>POST /upload          multipart "file"          -> {{"id": "..."}}   (repeat per frame)
POST /nerfify         {{"images": [id1, ...]}}    -> 202 {{"job_id": "...", "status": "pending"}}
GET  /jobs/&lt;job_id&gt;                              -> {{"status": "running", ...}}
GET  /jobs/&lt;job_id&gt;/result                       -> the .{settings.result_format} splat</code></pre>
</body></html>"""
