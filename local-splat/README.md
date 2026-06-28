# local-splat — run the Gaussian splat pipeline on your machine

Same reconstruction path as the RunPod GPU worker:

1. **COLMAP** (`ns-process-data images`) — camera poses from photos  
2. **Train** (`ns-train splatfacto`) — 3D Gaussian splatting  
3. **Export** (`ns-export gaussian-splat`) — single `.ply` file  

Implementation lives in `../worker/nerf_pipeline.py`. This folder is a thin local wrapper so you can iterate on quality without cloud round-trips.

## Directory layout

```
local-splat/
  inputs/          ← optional: drop test frames here (or pass any path)
  outputs/         ← splat.ply results (gitignored)
  work/            ← COLMAP + train scratch (gitignored)
  reconstruct.py   ← CLI entry point
  run_local.sh     ← native nerfstudio on PATH
  run_docker.sh    ← Docker + NVIDIA GPU (matches RunPod image)
```

## Quick start

### Option A — Docker (recommended if nerfstudio isn't installed)

Requires **Docker + NVIDIA GPU** (`--gpus all`).

```bash
cd nerf-service

# bounded indoor scene (Mip-NeRF 360 bonsai, images_4 folder, etc.)
./local-splat/run_docker.sh ~/Downloads/bonsai/images_4

# tune iterations
NERF_ITERATIONS=16000 ./local-splat/run_docker.sh /path/to/frames
```

Output: `local-splat/outputs/<scene-name>/splat.ply`

### Option B — native nerfstudio

If `ns-process-data`, `ns-train`, and `ns-export` are already on your PATH:

```bash
./local-splat/run_local.sh /path/to/frames
```

Or directly:

```bash
python local-splat/reconstruct.py \
  --frames /path/to/frames \
  --iterations 16000
```

## Viewing the result

The production WebGL viewer at `/viewer` needs a URL the browser can fetch. Options:

- Upload the `.ply` to R2 and open  
  `https://nerf.mattbouchard.com/viewer?url=<presigned-or-public-url>`
- Or run `python scripts/render_splat.py local-splat/outputs/<name>/splat.ply` for a static PNG preview (no GPU viewer needed).

## Mac note

Apple Silicon / MacBook has no CUDA. You cannot train splats locally on a Mac without a remote GPU. Use:

- **`run_docker.sh` on a Linux box with an NVIDIA GPU**, or  
- keep using **`scripts/e2e_runpod.py`** for cloud validation, and use this folder to **organize inputs/outputs** and tune settings before pushing to RunPod.

## What to test with

| Scene type | Example | Expected quality |
|---|---|---|
| Bounded object / indoor | Mip-NeRF360 `bonsai`, `kitchen` | Clean splats |
| Forward-facing | LLFF `fern` | Good |
| Unbounded outdoor 360° | `vasedeck`, `pinecone` | Noisy floaters (hard case) |

Download Mip-NeRF 360: [jonbarron.info/mipnerf360](https://jonbarron.info/mipnerf360/)  
Use the `images_4` or `images_8` subfolder for faster COLMAP.

## Relation to other parts of the repo

| Component | Role |
|---|---|
| `worker/nerf_pipeline.py` | Shared pipeline (RunPod + local) |
| `scripts/e2e_runpod.py` | Upload frames → RunPod → poll → viewer URL |
| `app.py` `/viewer` | WebGL display (gsplat.js) |
| `pipeline.py` | CPU stub for FastAPI local mode (not real splats) |
