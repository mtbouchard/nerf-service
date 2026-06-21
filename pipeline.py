"""
CPU stand-in for the GPU NeRF pipeline (the analog of stitch-service's stitch.py).

It does NOT reconstruct geometry. It samples colors from the uploaded frames and lays them
out as a colored point cloud wrapped on a cylinder, then writes a valid ASCII .ply. The
point is to exercise the whole upload -> job -> poll -> download contract end to end with a
real 3D file artifact, with no GPU and no cloud. The real reconstruction (COLMAP +
nerfstudio) lives in worker/ and runs on RunPod.

Set LOCAL_DELAY_SECONDS (seconds) to make jobs take long enough that the client visibly polls.
"""
import math
import os
import time

from PIL import Image

LOCAL_DELAY_SECONDS = float(os.environ.get("LOCAL_DELAY_SECONDS", "0"))


def generate_pointcloud_ply(image_paths: list[str], out_path: str) -> None:
    if LOCAL_DELAY_SECONDS:
        time.sleep(LOCAL_DELAY_SECONDS)  # stand in for minutes-long GPU compute

    grid = 48  # sample grid per image
    n = max(1, len(image_paths))
    points: list[tuple[float, float, float, int, int, int]] = []

    for layer, path in enumerate(image_paths):
        img = Image.open(path).convert("RGB").resize((grid, grid))
        px = img.load()
        # Wrap each frame onto a cylinder slice so the cloud reads as 3D when viewed.
        angle0 = (layer / n) * 2 * math.pi
        for j in range(grid):
            for i in range(grid):
                r, g, b = px[i, j]
                theta = angle0 + (i / grid) * (2 * math.pi / n)
                x = math.cos(theta)
                z = math.sin(theta)
                y = 1.0 - 2.0 * (j / grid)
                points.append((x, y, z, r, g, b))

    with open(out_path, "w") as f:
        f.write("ply\n")
        f.write("format ascii 1.0\n")
        f.write(f"element vertex {len(points)}\n")
        f.write("property float x\nproperty float y\nproperty float z\n")
        f.write("property uchar red\nproperty uchar green\nproperty uchar blue\n")
        f.write("end_header\n")
        for x, y, z, r, g, b in points:
            f.write(f"{x:.5f} {y:.5f} {z:.5f} {r} {g} {b}\n")
