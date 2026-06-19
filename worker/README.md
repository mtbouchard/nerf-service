# nerf-worker (RunPod GPU container)

The GPU half of nerf-service. A RunPod Serverless worker that turns a series of photos into
a 3D Gaussian-splat `.ply` using **COLMAP + nerfstudio (splatfacto)**.

## Contract (set by the API)

RunPod invokes `handler(event)` with:

```json
{ "input": {
    "images": ["<presigned GET url>", "..."],
    "result_put_url": "<presigned PUT url>",
    "result_format": "ply"
} }
```

The worker downloads the frames, runs `nerf_pipeline.reconstruct()` on the GPU, and PUTs
the resulting `splat.ply` to `result_put_url`. It needs **no** cloud credentials.

## Pipeline (`nerf_pipeline.py`)

1. `ns-process-data images` — COLMAP structure-from-motion → camera poses.
2. `ns-train splatfacto` — train Gaussian splatting on the GPU (`NERF_ITERATIONS`, default 7000).
3. `ns-export gaussian-splat` — export the scene to a single `.ply`.

## Build & deploy

```bash
docker build -t <dockerhub-user>/nerf-worker:latest worker/
docker push  <dockerhub-user>/nerf-worker:latest
```

Then in RunPod → Serverless → New Endpoint:
- Container image: `<dockerhub-user>/nerf-worker:latest`
- GPU: a 16–24 GB card (e.g. RTX A4000/A5000/3090) is plenty for splatfacto.
- (Optional) env `NERF_ITERATIONS` to trade quality vs cost.
- Copy the **Endpoint ID** and a RunPod **API key** into the API's env
  (`RUNPOD_ENDPOINT_ID`, `RUNPOD_API_KEY`).

## Notes
- Needs **real overlapping photos** of one object/scene (20–60 frames, good coverage). COLMAP
  will fail to register synthetic/gradient images — those only work with the local CPU
  stand-in backend.
- Build this image on a machine with the CUDA toolchain (or RunPod's image builder); it
  won't build on a CPU-only laptop because of the CUDA extensions.
