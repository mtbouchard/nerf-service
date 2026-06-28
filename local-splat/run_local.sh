#!/usr/bin/env bash
# Run splat reconstruction using nerfstudio CLIs installed on this machine.
# Requires: NVIDIA GPU + ns-process-data, ns-train, ns-export on PATH.
#
# Usage:
#   ./local-splat/run_local.sh /path/to/frames
#   NERF_ITERATIONS=16000 ./local-splat/run_local.sh /path/to/frames
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
FRAMES="${1:?usage: $0 <frames-directory>}"
NAME="$(basename "$FRAMES")"

for cmd in ns-process-data ns-train ns-export; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "[error] '$cmd' not found on PATH."
    echo "        Install nerfstudio, or use: ./local-splat/run_docker.sh \"$FRAMES\""
    exit 1
  fi
done

python3 "$DIR/reconstruct.py" \
  --frames "$FRAMES" \
  --out "$DIR/outputs/$NAME/splat.ply" \
  --work-dir "$DIR/work/$NAME"

echo ""
echo "Output: $DIR/outputs/$NAME/splat.ply"
echo "Preview (upload to R2 or serve over HTTP, then open in /viewer):"
echo "  https://nerf.mattbouchard.com/viewer?url=<your-ply-url>"
