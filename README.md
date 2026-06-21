# nerf-service

Upload a series of photos, reconstruct a 3D point cloud, then download the `.ply`. This is
the **long-job sibling** of `stitch-service`: a NeRF reconstruction takes minutes, so instead
of returning the result inline it uses the **`202 + poll`** job pattern.

A CPU **stand-in pipeline** ships in the box, so the whole API runs, tests, and deploys with
no GPU and no cloud. The real GPU reconstruction (**COLMAP + nerfstudio**) lives in
[`worker/`](./worker) and runs on RunPod — wiring that up is phase 2.

> Same async-job API as the interview problem, scaled up to a minutes-long workload that
> returns immediately and is polled to completion.

## API

```
POST /upload          multipart "file"          -> {"id": "..."}      (repeat per frame)
POST /nerfify         {"images": [id1, ...]}    -> 202 {"job_id": "...", "status": "pending"}
GET  /jobs/{job_id}                             -> {"job_id":..,"status":"pending|running|done|failed"}
GET  /jobs/{job_id}/result                      -> the .ply file (409 until done)
GET  /healthz                                   -> {"status":"ok","backend":"local"}
```

## How it works (local backend)

```
client ──upload──▶ API ──save──▶ data/uploads/<id>.jpg          (once per frame)
client ──nerfify─▶ API: create Job(pending), background_tasks.add_task(run_job) ─▶ 202 {job_id}
                       run_job: status=running -> pipeline.generate_pointcloud_ply() -> status=done
client ──poll────▶ API ──▶ GET /jobs/<id>          (pending -> running -> done)
client ──result──▶ API ──▶ FileResponse(data/results/<job>.ply)
```

`/nerfify` returns **immediately** after scheduling a FastAPI `BackgroundTask`; the heavy work
runs in the background while the client polls `/jobs/{id}`. Contrast with `stitch-service`,
where a seconds-long job is awaited and the image is returned in the same response.

`pipeline.py` is the compute stand-in (the analog of stitch-service's `stitch.py`) — it writes
a real ASCII `.ply` colored point cloud from the frames. Set `LOCAL_DELAY_SECONDS` to make
jobs take long enough that you actually watch them poll.

## Run locally

```bash
cd nerf-service
pip install -r requirements-dev.txt

LOCAL_DELAY_SECONDS=2 uvicorn solution_app:app --reload     # working reference (visibly polls)
# end-to-end demo (new terminal): uploads client/sample_frames/ -> downloads client/scene.ply
SERVER_URL=http://127.0.0.1:8000 python client/client.py
```

There's a learning **assignment**: implement the four endpoints yourself in `app.py`
(then run with `uvicorn app:app`).

## Tests

```bash
KATA_TARGET=solution_app pytest    # reference: all green
pytest                             # your implementation (app.py)
```

## Deploy to Render

Connected via `render.yaml` (Blueprint): build `pip install -r requirements.txt`, start
`uvicorn $APP_MODULE:app --host 0.0.0.0 --port $PORT`, health check `/healthz`. Ships with
`APP_MODULE=solution_app` so it's green immediately; set `APP_MODULE=app` once you've
implemented `app.py`. The CPU stand-in needs no extra config.

> Free-tier caveats apply (cold start, ephemeral disk) — fine for a demo. In-memory job store
> means jobs don't survive a restart; a real system uses Redis + object storage.

## Phase 2 — the real GPU pipeline (planned)

The CPU backend proves out the entire API + job + poll + download contract. To make it a
*real* NeRF:
1. Build & deploy [`worker/`](./worker/README.md) (COLMAP + nerfstudio) to RunPod Serverless.
2. Create an S3/R2 bucket for exchanging frames + results via presigned URLs.
3. Add a `runpod` code path to the API that submits to RunPod and hands back the result.

The worker holds **no credentials** — the API gives it presigned GET/PUT URLs. (The API-side
RunPod wiring isn't in `app.py` yet; that's the phase-2 task.)

## Layout

```
nerf-service/
  app.py               # ← the whole API + the assignment (you implement the 4 endpoints)
  solution_app.py      # complete single-file reference
  pipeline.py          # CPU stand-in compute -> real .ply (analog of stitch.py)
  worker/              # real GPU pipeline for RunPod (phase 2)
    handler.py nerf_pipeline.py Dockerfile requirements.txt README.md
  client/              # upload series -> nerfify -> poll -> download splat
    client.py sample_frames/
  tests/               # local-backend acceptance tests
  Dockerfile render.yaml requirements*.txt pytest.ini
```
