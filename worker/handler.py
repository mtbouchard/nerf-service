"""RunPod Serverless handler.

RunPod calls handler({"input": {...}}) for each job. Our input (built by the API in
app/backends/runpod_backend.py) is:

    {
      "images": ["https://...presigned-get...", ...],   # the uploaded frames
      "result_put_url": "https://...presigned-put...",   # where to upload the splat
      "result_format": "ply"
    }

The worker needs NO cloud credentials - it only follows the presigned URLs:
download frames -> reconstruct on GPU -> upload the .ply to result_put_url.
"""
import os
import tempfile

import requests
import runpod

from nerf_pipeline import reconstruct


def _download(url: str, dest: str) -> None:
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)


def handler(event: dict) -> dict:
    job_input = event.get("input", {})
    image_urls = job_input.get("images", [])
    result_put_url = job_input.get("result_put_url")

    if not image_urls or not result_put_url:
        return {"error": "input must include non-empty 'images' and 'result_put_url'"}

    with tempfile.TemporaryDirectory() as tmp:
        frames_dir = os.path.join(tmp, "frames")
        os.makedirs(frames_dir, exist_ok=True)
        for i, url in enumerate(image_urls):
            _download(url, os.path.join(frames_dir, f"frame_{i:04d}.jpg"))

        try:
            ply_path = reconstruct(frames_dir, os.path.join(tmp, "work"))
        except Exception as exc:  # noqa: BLE001 - return a clean error to the API
            return {"error": str(exc)}

        with open(ply_path, "rb") as f:
            put = requests.put(
                result_put_url,
                data=f,
                headers={"Content-Type": "application/octet-stream"},
                timeout=300,
            )
        put.raise_for_status()

    return {"status": "ok", "bytes": os.path.getsize(ply_path) if os.path.exists(ply_path) else 0}


runpod.serverless.start({"handler": handler})
