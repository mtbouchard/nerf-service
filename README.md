# nerf-service

A FastAPI service for long-running 3D reconstruction jobs. Upload a series of photos, start a
job, poll it to completion, then download a `.ply` point cloud.

Because a reconstruction takes minutes, the API uses the **`202 + poll`** pattern instead of
blocking on a single request. A CPU pipeline runs out of the box (no GPU or cloud needed); the
GPU pipeline (**COLMAP + nerfstudio**) lives in [`worker/`](./worker) and runs on RunPod.

## API

```
POST /upload          multipart "file"          -> {"id": "..."}      (repeat per frame)
POST /nerfify         {"images": [id1, ...]}    -> 202 {"job_id": "...", "status": "pending"}
GET  /jobs/{job_id}                             -> {"status": "pending|running|done|failed"}
GET  /jobs/{job_id}/result                      -> the .ply file (409 until done)
GET  /healthz                                   -> {"status": "ok", "backend": "local"}
```

## How it works

`/nerfify` creates a job, schedules the work as a FastAPI `BackgroundTask`, and returns `202`
immediately. The client polls `/jobs/{id}` until `done`, then downloads the result. `pipeline.py`
turns the frames into a real ASCII `.ply` colored point cloud (set `LOCAL_DELAY_SECONDS` to
simulate longer compute).

## Run locally

```bash
cd nerf-service
pip install -r requirements-dev.txt

LOCAL_DELAY_SECONDS=2 uvicorn solution_app:app --reload
# new terminal: uploads client/sample_frames/ -> downloads client/scene.ply
SERVER_URL=http://127.0.0.1:8000 python client/client.py
```

`app.py` is the implementation you build out; `solution_app.py` is the complete reference.

## Tests

```bash
APP_MODULE=solution_app pytest     # reference: all green
pytest                             # your implementation (app.py)
```

## Deploy to Render

Connected via `render.yaml` (Blueprint): start `uvicorn $APP_MODULE:app`, health check
`/healthz`. `APP_MODULE` selects which module to serve (`solution_app` or `app`).

## Phase 2 — real GPU pipeline

Make it a true NeRF by deploying [`worker/`](./worker/README.md) (COLMAP + nerfstudio) to
RunPod Serverless, adding an S3/R2 bucket to exchange frames and results via presigned URLs,
and wiring a `runpod` path into the API. The worker holds no credentials — the API hands it
presigned GET/PUT URLs.

## Layout

```
nerf-service/
  app.py            # the API (4 endpoints)
  solution_app.py   # complete reference
  pipeline.py       # CPU pipeline -> .ply
  worker/           # GPU pipeline for RunPod (phase 2)
  client/           # upload -> nerfify -> poll -> download
  tests/
  Dockerfile  render.yaml  requirements*.txt  pytest.ini
```
