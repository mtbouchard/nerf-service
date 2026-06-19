"""
nerf-service client - upload a series of frames -> /nerfify -> poll -> download the splat.

Local (CPU stand-in backend):
    uv run uvicorn app.main:app --reload
    SERVER_URL=http://127.0.0.1:8000 python client/client.py

Deployed (GPU on RunPod):
    SERVER_URL=https://nerf-service.onrender.com python client/client.py

Uploads every image in client/sample_frames/ (or pass a directory as argv[1]).
"""
import os
import sys
import time

import httpx

BASE_URL = os.environ.get("SERVER_URL", "http://127.0.0.1:8000")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRAMES_DIR = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE_DIR, "sample_frames")
OUTPUT_FILE = os.path.join(BASE_DIR, "scene.ply")
POLL_TIMEOUT_S = 3600  # real GPU jobs can take many minutes


def frame_paths() -> list[str]:
    exts = (".jpg", ".jpeg", ".png")
    files = sorted(
        os.path.join(FRAMES_DIR, f)
        for f in os.listdir(FRAMES_DIR)
        if f.lower().endswith(exts)
    )
    return files


def upload_frame(client: httpx.Client, path: str) -> str:
    with open(path, "rb") as f:
        files = {"file": (os.path.basename(path), f, "image/jpeg")}
        r = client.post("/upload", files=files)
    r.raise_for_status()
    return r.json()["id"]


def main() -> int:
    paths = frame_paths()
    print(f"Target: {BASE_URL}  |  {len(paths)} frames from {FRAMES_DIR}")
    if not paths:
        print("  no frames found")
        return 1

    with httpx.Client(base_url=BASE_URL, timeout=120.0) as client:
        print("STEP 1: upload frames")
        try:
            ids = [upload_frame(client, p) for p in paths]
        except httpx.ConnectError:
            print(f"  Could not connect to {BASE_URL}. Is the server running?")
            return 1
        print(f"  uploaded {len(ids)} frames")

        print("STEP 2: POST /nerfify")
        r = client.post("/nerfify", json={"images": ids})
        if r.status_code != 202:
            print(f"  unexpected status {r.status_code}: {r.text}")
            return 1
        job_id = r.json()["job_id"]
        print(f"  202 Accepted -> job_id={job_id}")

        print("STEP 3: poll until done (this can take a while on a real GPU)")
        deadline = time.time() + POLL_TIMEOUT_S
        job = {"status": "pending"}
        while time.time() < deadline:
            job = client.get(f"/jobs/{job_id}").json()
            print(f"  status={job['status']}")
            if job["status"] in ("done", "failed"):
                break
            time.sleep(3)

        if job["status"] != "done":
            print(f"  job did not finish cleanly: {job}")
            return 1

        print("STEP 4: download splat")
        r = client.get(f"/jobs/{job_id}/result", follow_redirects=True)
        r.raise_for_status()
        with open(OUTPUT_FILE, "wb") as f:
            f.write(r.content)
    print(f"  saved -> {OUTPUT_FILE} ({os.path.getsize(OUTPUT_FILE)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
