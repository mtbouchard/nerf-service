"""The real NeRF reconstruction, run on a CUDA GPU. Three nerfstudio CLI stages:

  1. ns-process-data images   -> COLMAP structure-from-motion (camera poses)
  2. ns-train splatfacto       -> train a 3D Gaussian-splatting model on the GPU
  3. ns-export gaussian-splat  -> export the trained scene to a single .ply splat

Each stage is a subprocess; we stream output and fail loudly with stderr so the API can
surface a real error. Tune iterations via NERF_ITERATIONS (default 7000).
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ITERATIONS = int(os.environ.get("NERF_ITERATIONS", "7000"))


def _run(cmd: list[str]) -> None:
    print("RUN:", " ".join(cmd), flush=True)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        raise RuntimeError(
            f"command failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr[-2000:]}"
        )


def reconstruct(frames_dir: str, work_dir: str) -> str:
    """Run COLMAP + splatfacto + export. Returns the path to the exported .ply splat."""
    work = Path(work_dir)
    processed = work / "processed"
    train_out = work / "train"
    export_out = work / "export"
    for d in (processed, train_out, export_out):
        d.mkdir(parents=True, exist_ok=True)

    # 1) COLMAP SfM -> nerfstudio dataset
    _run([
        "ns-process-data", "images",
        "--data", frames_dir,
        "--output-dir", str(processed),
    ])

    # 2) Train Gaussian splatting on the GPU
    _run([
        "ns-train", "splatfacto",
        "--data", str(processed),
        "--output-dir", str(train_out),
        "--max-num-iterations", str(ITERATIONS),
        "--viewer.quit-on-train-completion", "True",
    ])

    # nerfstudio writes config to train_out/<exp>/splatfacto/<timestamp>/config.yml
    configs = list(train_out.glob("**/config.yml"))
    if not configs:
        raise RuntimeError("training produced no config.yml")
    config_path = configs[0]

    # 3) Export the splat to a single .ply
    _run([
        "ns-export", "gaussian-splat",
        "--load-config", str(config_path),
        "--output-dir", str(export_out),
    ])

    plys = list(export_out.glob("*.ply"))
    if not plys:
        raise RuntimeError("export produced no .ply")

    final = work / "splat.ply"
    shutil.copyfile(plys[0], final)
    return str(final)
