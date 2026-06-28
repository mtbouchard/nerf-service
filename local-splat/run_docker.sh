#!/usr/bin/env bash
# Run splat reconstruction inside the official nerfstudio Docker image.
# Same base image as worker/Dockerfile (RunPod worker). Needs Docker + NVIDIA GPU.
#
# Usage:
#   ./local-splat/run_docker.sh /path/to/frames
#   NERF_ITERATIONS=16000 ./local-splat/run_docker.sh /path/to/frames
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$DIR/.." && pwd)"
FRAMES="$(cd "${1:?usage: $0 <frames-directory>}" && pwd)"
NAME="$(basename "$FRAMES")"
OUT_DIR="$DIR/outputs/$NAME"
WORK_DIR="$DIR/work/$NAME"
ITER="${NERF_ITERATIONS:-7000}"

mkdir -p "$OUT_DIR" "$WORK_DIR"

if ! docker info >/dev/null 2>&1; then
  echo "[error] Docker is not running."
  exit 1
fi

echo "[local-splat/docker] image=ghcr.io/nerfstudio-project/nerfstudio:latest"
echo "[local-splat/docker] frames=$FRAMES"
echo "[local-splat/docker] iterations=$ITER"

docker run --gpus all --rm \
  -v "$FRAMES:/frames:ro" \
  -v "$OUT_DIR:/out" \
  -v "$WORK_DIR:/work" \
  -v "$REPO/worker/nerf_pipeline.py:/worker/nerf_pipeline.py:ro" \
  -v "$DIR/reconstruct.py:/worker/reconstruct.py:ro" \
  -e NERF_ITERATIONS="$ITER" \
  -w /worker \
  ghcr.io/nerfstudio-project/nerfstudio:latest \
  python3 -u reconstruct.py \
    --frames /frames \
    --out /out/splat.ply \
    --work-dir /work

echo ""
echo "Output: $OUT_DIR/splat.ply"
