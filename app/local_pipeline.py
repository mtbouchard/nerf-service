"""CPU stand-in for the GPU NeRF pipeline.

It does NOT reconstruct geometry. It samples colors from the uploaded frames and lays them
out as a colored point cloud, then writes a valid ASCII .ply. The point: exercise the whole
API + job + download contract end to end with a real 3D file artifact, with no GPU/cloud.
The real reconstruction lives in worker/ (COLMAP + nerfstudio) and runs on RunPod.
"""
import math
import time

from PIL import Image

from .config import settings


def generate_pointcloud_ply(image_paths: list[str], out_path: str) -> None:
    if settings.local_delay_seconds:
        time.sleep(settings.local_delay_seconds)

    grid = 48  # sample grid per image
    points: list[tuple[float, float, float, int, int, int]] = []

    for layer, path in enumerate(image_paths):
        img = Image.open(path).convert("RGB").resize((grid, grid))
        px = img.load()
        # Wrap each frame onto a cylinder slice so the cloud reads as 3D when viewed.
        angle0 = (layer / max(1, len(image_paths))) * 2 * math.pi
        for j in range(grid):
            for i in range(grid):
                r, g, b = px[i, j]
                theta = angle0 + (i / grid) * (2 * math.pi / len(image_paths))
                radius = 1.0
                x = radius * math.cos(theta)
                z = radius * math.sin(theta)
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
