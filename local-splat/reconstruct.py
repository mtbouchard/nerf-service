#!/usr/bin/env python3
"""Run the same COLMAP + splatfacto + export pipeline as the RunPod worker, locally.

Requires nerfstudio CLIs on PATH (ns-process-data, ns-train, ns-export) and an NVIDIA GPU.
Use run_docker.sh if you don't have nerfstudio installed natively.

Example:
    python local-splat/reconstruct.py \\
        --frames ~/Downloads/nerf_real_360/vasedeck/images \\
        --out local-splat/outputs/vasedeck/splat.ply
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

# Reuse the worker module — single source of truth with RunPod.
_WORKER_DIR = Path(__file__).resolve().parent.parent / "worker"
sys.path.insert(0, str(_WORKER_DIR))
from nerf_pipeline import ITERATIONS, reconstruct  # noqa: E402


def main() -> int:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--frames",
        required=True,
        type=Path,
        help="directory of input photos (jpg/jpeg/png)",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="output .ply path (default: local-splat/outputs/<frames-name>/splat.ply)",
    )
    ap.add_argument(
        "--work-dir",
        type=Path,
        default=None,
        help="scratch dir for COLMAP/train/export (default: local-splat/work/<frames-name>)",
    )
    ap.add_argument(
        "--iterations",
        type=int,
        default=None,
        help=f"training iterations (default: NERF_ITERATIONS env or {ITERATIONS})",
    )
    args = ap.parse_args()

    frames = args.frames.expanduser().resolve()
    if not frames.is_dir():
        print(f"[error] frames directory not found: {frames}", file=sys.stderr)
        return 2

    n_images = sum(
        1 for p in frames.iterdir()
        if p.suffix.lower() in {".jpg", ".jpeg", ".png"}
    )
    if n_images < 3:
        print(f"[error] need >=3 images in {frames}, found {n_images}", file=sys.stderr)
        return 2

    name = frames.name
    out = (args.out or here / "outputs" / name / "splat.ply").expanduser().resolve()
    work = (args.work_dir or here / "work" / name).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)

    if args.iterations is not None:
        os.environ["NERF_ITERATIONS"] = str(args.iterations)

    iters = int(os.environ.get("NERF_ITERATIONS", str(ITERATIONS)))
    print(f"[local-splat] frames={frames} ({n_images} images)")
    print(f"[local-splat] work={work}")
    print(f"[local-splat] iterations={iters}")
    print(f"[local-splat] out={out}")

    ply_path = reconstruct(str(frames), str(work))
    shutil.copy2(ply_path, out)
    print(f"\n[done] {out} ({out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
