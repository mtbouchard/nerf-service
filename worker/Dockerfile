# GPU worker image for RunPod Serverless. Based on the official nerfstudio image, which
# already ships CUDA, PyTorch, COLMAP, tiny-cuda-nn and the ns-* CLIs (so nothing GPU-specific
# is compiled at build time — required for RunPod's GitHub builder).
#
# Deploy via RunPod GitHub integration (no local Docker needed):
#   New Endpoint > Import Git Repository > select this repo
#   Branch: main   |   Dockerfile Path: worker/Dockerfile
# RunPod uses the REPO ROOT as the build context, so the COPY paths below are written
# relative to the repo root (worker/...), not to this file's directory.
#
# Or build + push manually (needs a CUDA-capable build host), from the repo root:
#   docker build -f worker/Dockerfile -t <dockerhub-user>/nerf-worker:latest .
#   docker push  <dockerhub-user>/nerf-worker:latest
FROM ghcr.io/nerfstudio-project/nerfstudio:latest

WORKDIR /worker

COPY worker/requirements.txt .
# Use `python3 -m pip` (not bare `pip`): the nerfstudio base installs as a non-root user,
# so the pip console script isn't on PATH in a RUN shell (bare `pip` -> exit 127).
RUN python3 -m pip install --no-cache-dir -r requirements.txt

COPY worker/nerf_pipeline.py worker/handler.py ./

# Number of training iterations (quality vs time). Override per-endpoint on RunPod.
ENV NERF_ITERATIONS=7000

# RunPod Serverless invokes the handler; it blocks waiting for jobs.
CMD ["python3", "-u", "handler.py"]
