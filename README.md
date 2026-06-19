# nerf-service

Upload a series of photos, reconstruct a **3D Gaussian-splat** with a real NeRF pipeline
(**COLMAP + nerfstudio**) on a GPU, then download the `.ply`. Same upload → `202` → poll →
download job contract as `stitch-service`, but the heavy compute is offloaded to a **RunPod
GPU worker**, with files exchanged through S3-compatible storage.

> Same async-job API as the interview problem, scaled up to a genuine GPU workload. A CPU
> "local" backend ships in the box so the whole thing runs and tests without any GPU/cloud.

## Two backends (one env var)

| `NERF_BACKEND` | Compute | Needs | Use |
|---|---|---|---|
| `local` (default) | CPU stand-in → real `.ply` point cloud, in-process | nothing | dev, tests, Render demo |
| `runpod` | real COLMAP + nerfstudio on a GPU | RunPod endpoint + S3/R2 | production |

The API code is identical; only `app/backends/get_backend()` differs.

## API

```
POST /upload          multipart "file"          -> {"id": "..."}      (repeat per frame)
POST /nerfify         {"images": [id1, ...]}    -> 202 {"job_id": "...", "status": "pending"}
GET  /jobs/{job_id}                             -> {"job_id":..,"status":"pending|running|done|failed"}
GET  /jobs/{job_id}/result                      -> the .ply splat (302 redirect to a presigned URL in runpod mode)
GET  /healthz                                   -> {"status":"ok","backend":"local"}
```

## Architecture (runpod mode)

```
client ──upload──▶ API ──put──▶ S3/R2 (uploads/<id>.jpg)
client ──nerfify─▶ API ──presign GET urls + PUT url──▶ RunPod /run ──▶ GPU worker
                                                          worker: download frames
                                                                  COLMAP (poses)
                                                                  nerfstudio splatfacto (train)
                                                                  export gaussian-splat .ply
                                                                  PUT result ──▶ S3/R2 (results/<job>.ply)
client ──poll────▶ API ──▶ RunPod /status/<id>
client ──result──▶ API ──302──▶ presigned GET (results/<job>.ply)
```

The worker holds **no credentials** — the API hands it presigned GET/PUT URLs.

## Run locally (CPU stand-in)

```bash
cd nerf-service
pip install -r requirements-dev.txt          # or: uv run pip install -r requirements-dev.txt
uvicorn app.main:app --reload                 # NERF_BACKEND defaults to local

# end-to-end demo (new terminal): uploads client/sample_frames/ -> downloads client/scene.ply
SERVER_URL=http://127.0.0.1:8000 python client/client.py
```

## Tests

```bash
PYTHONPATH=. pytest      # local backend, all green
```

## Going real (GPU)

1. **Build & deploy the worker** to RunPod Serverless — see [`worker/README.md`](./worker/README.md).
2. **Create an S3/R2 bucket** (Cloudflare R2 recommended) and an access key pair.
3. **Deploy the API** to Render via `render.yaml`, then set these env vars (secrets):
   `NERF_BACKEND=runpod`, `RUNPOD_API_KEY`, `RUNPOD_ENDPOINT_ID`, `S3_BUCKET`,
   `S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`.
4. Point the client at the deployed URL with **real overlapping photos** of one object
   (20–60 frames): `SERVER_URL=https://nerf-service.onrender.com python client/client.py path/to/photos`.

See the top-level `DEPLOY_GUIDE.md` for the full GitHub + Render + RunPod + domain walkthrough.

## What's verified vs what needs your GPU
- **Verified locally**: the entire API, job lifecycle, validation, the client, and a real
  `.ply` artifact (via the CPU backend).
- **Needs your accounts**: the GPU reconstruction itself (RunPod) and the S3/R2 file
  exchange. That code is written and documented but can't run on a CPU-only laptop —
  COLMAP/nerfstudio need CUDA. The `runpod` backend is a thin, well-typed RunPod + presigned-URL client.

## Layout

```
nerf-service/
  app/                     # CPU API (deploys to Render)
    main.py config.py models.py store.py storage.py
    local_pipeline.py      # CPU stand-in -> real .ply
    backends/              # base.py, local_backend.py, runpod_backend.py, get_backend()
    routers/               # health.py, jobs.py
  worker/                  # GPU container for RunPod
    handler.py nerf_pipeline.py Dockerfile requirements.txt README.md
  client/                  # upload series -> nerfify -> poll -> download splat
    client.py sample_frames/
  tests/                   # local-backend acceptance tests
  Dockerfile render.yaml requirements*.txt
```
