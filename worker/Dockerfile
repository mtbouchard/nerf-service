# GPU worker image for RunPod Serverless. Based on the official nerfstudio image, which
# already ships CUDA, PyTorch, COLMAP, tiny-cuda-nn and the ns-* CLIs.
#
# Build + push (needs a CUDA build host or buildx):
#   docker build -t <dockerhub-user>/nerf-worker:latest worker/
#   docker push  <dockerhub-user>/nerf-worker:latest
# Then point a RunPod Serverless endpoint at that image.
FROM ghcr.io/nerfstudio-project/nerfstudio:latest

WORKDIR /worker

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY nerf_pipeline.py handler.py ./

# Number of training iterations (quality vs time). Override per-endpoint on RunPod.
ENV NERF_ITERATIONS=7000

# RunPod Serverless invokes the handler; it blocks waiting for jobs.
CMD ["python", "-u", "handler.py"]
