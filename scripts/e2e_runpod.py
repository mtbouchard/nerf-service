#!/usr/bin/env python3
"""End-to-end smoke test against a live nerf-service (runpod backend).

Uploads a directory of JPEG frames, kicks off a /nerfify job, polls until the
RunPod worker finishes the reconstruction, then prints a ready-to-open viewer
URL for the generated .ply splat.

Zero third-party deps (stdlib only) so it runs anywhere:

    python3 scripts/e2e_runpod.py \
        --api https://nerf.mattbouchard.com \
        --frames SplatCapture-iOS/SampleFrames/fern

Use --frames-glob to point at arbitrary jpgs, and --max-frames to cap the count.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def _post_multipart(url: str, field: str, filename: str, data: bytes, content_type: str) -> dict:
    boundary = f"----nerf{uuid.uuid4().hex}"
    body = b"".join([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'.encode(),
        f"Content-Type: {content_type}\r\n\r\n".encode(),
        data,
        f"\r\n--{boundary}--\r\n".encode(),
    ])
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def _post_json(url: str, payload: dict) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=60) as resp:
        return json.loads(resp.read())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--api", default="https://nerf.mattbouchard.com")
    ap.add_argument("--frames", default="SplatCapture-iOS/SampleFrames/fern",
                    help="directory of .jpg frames to upload")
    ap.add_argument("--frames-glob", default="*.jpg")
    ap.add_argument("--max-frames", type=int, default=40)
    ap.add_argument("--poll-interval", type=float, default=10.0)
    ap.add_argument("--timeout", type=float, default=3600.0,
                    help="seconds to wait for the job before giving up")
    args = ap.parse_args()

    api = args.api.rstrip("/")

    # health check
    health = _get_json(f"{api}/healthz")
    print(f"[health] {health}")
    if health.get("status") != "ok":
        print("[warn] backend not fully healthy; continuing anyway")

    frame_paths = sorted(Path(args.frames).glob(args.frames_glob))[: args.max_frames]
    if len(frame_paths) < 3:
        print(f"[error] need >=3 frames, found {len(frame_paths)} in {args.frames}")
        return 2
    print(f"[upload] {len(frame_paths)} frames from {args.frames}")

    image_ids: list[str] = []
    for i, path in enumerate(frame_paths, 1):
        ctype = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        out = _post_multipart(f"{api}/upload", "file", path.name, path.read_bytes(), ctype)
        image_ids.append(out["id"])
        print(f"  [{i:>2}/{len(frame_paths)}] {path.name} -> {out['id']}")

    print("[nerfify] submitting job ...")
    job = _post_json(f"{api}/nerfify", {"images": image_ids})
    job_id = job["job_id"]
    print(f"[nerfify] job_id={job_id} status={job['status']}")

    start = time.time()
    last = None
    while True:
        elapsed = time.time() - start
        if elapsed > args.timeout:
            print(f"[timeout] job still {last} after {elapsed:.0f}s")
            return 3
        status = _get_json(f"{api}/jobs/{job_id}")
        state = status.get("status")
        if state != last:
            print(f"[poll] t+{elapsed:>5.0f}s status={state}"
                  + (f" error={status.get('error')}" if status.get("error") else ""))
            last = state
        if state == "done":
            break
        if state == "failed":
            print(f"[failed] {status.get('error')}")
            return 1
        time.sleep(args.poll_interval)

    result_url = f"{api}/jobs/{job_id}/result"
    viewer_url = f"{api}/viewer?url={urllib.parse.quote(result_url, safe='')}"
    print("\n[done] reconstruction complete")
    print(f"  result (ply): {result_url}")
    print(f"  viewer:       {viewer_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
