"""RunPod Serverless client — used only when NERF_BACKEND=runpod.

Talks to a RunPod Serverless endpoint over its REST API:
    submit(...)        POST /run         -> queue a job, get RunPod's job id back
    fetch_status(...)  GET  /status/{id} -> RunPod state, mapped to our JobStatus values
    presign_result_get GET  presigned    -> a url the client can download the .ply from

File exchange goes through S3/R2 (see storage.py): we presign GET urls for the frames and a
PUT url for the result, and hand those to the worker. The worker (worker/handler.py) needs
no credentials of its own.

Config from the environment:
    RUNPOD_API_KEY        RunPod API key
    RUNPOD_ENDPOINT_ID    the Serverless endpoint id
    RESULT_FORMAT         result extension; default "ply"
"""
import os

import httpx

import storage

RUNPOD_BASE = "https://api.runpod.ai/v2"
RUNPOD_API_KEY = os.environ.get("RUNPOD_API_KEY")
RUNPOD_ENDPOINT_ID = os.environ.get("RUNPOD_ENDPOINT_ID")
RESULT_FORMAT = os.environ.get("RESULT_FORMAT", "ply")
HTTP_TIMEOUT = 30.0

# Per-job execution timeout (ms) sent to RunPod as `policy.executionTimeout`. RunPod's default
# is 600000 (10 min), which a full-resolution COLMAP + splatfacto run can exceed. We bump it so
# larger / higher-res captures finish instead of being killed mid-train. `ttl` must cover queue
# + execution time. Both override the endpoint defaults for this job only.
RUNPOD_EXECUTION_TIMEOUT_MS = int(os.environ.get("RUNPOD_EXECUTION_TIMEOUT_MS", "1800000"))  # 30 min
RUNPOD_TTL_MS = int(os.environ.get("RUNPOD_TTL_MS", "3600000"))  # 1 hour

# RunPod serverless states -> our four-state model (string values of JobStatus).
_STATE_MAP = {
    "IN_QUEUE": "pending",
    "IN_PROGRESS": "running",
    "COMPLETED": "done",
    "FAILED": "failed",
    "CANCELLED": "failed",
    "TIMED_OUT": "failed",
}


def required_config() -> list[str]:
    """Names of any required settings that are missing (empty list == good to go)."""
    missing = []
    if not RUNPOD_API_KEY:
        missing.append("RUNPOD_API_KEY")
    if not RUNPOD_ENDPOINT_ID:
        missing.append("RUNPOD_ENDPOINT_ID")
    return missing + storage.required_config()


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {RUNPOD_API_KEY}"}


def result_key(job_id: str) -> str:
    return f"results/{job_id}.{RESULT_FORMAT}"


def submit(job_id: str, image_keys: list[str]) -> str:
    """Presign the frames + a result slot, POST the job to RunPod, return its job id."""
    image_urls = [storage.presign_get(k) for k in image_keys]
    result_put_url = storage.presign_put(result_key(job_id))
    payload = {
        "input": {
            "images": image_urls,
            "result_put_url": result_put_url,
            "result_format": RESULT_FORMAT,
        },
        "policy": {
            "executionTimeout": RUNPOD_EXECUTION_TIMEOUT_MS,
            "ttl": RUNPOD_TTL_MS,
        },
    }
    resp = httpx.post(
        f"{RUNPOD_BASE}/{RUNPOD_ENDPOINT_ID}/run",
        json=payload,
        headers=_headers(),
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def fetch_status(runpod_id: str) -> tuple[str, str | None]:
    """Return (normalized_status, error_message_or_None) for a RunPod job."""
    resp = httpx.get(
        f"{RUNPOD_BASE}/{RUNPOD_ENDPOINT_ID}/status/{runpod_id}",
        headers=_headers(),
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    state = _STATE_MAP.get(data.get("status"), "running")
    error = None
    if state == "failed":
        error = str(data.get("error") or data.get("output") or "job failed")
    return state, error


def presign_result_get(job_id: str) -> str:
    return storage.presign_get(result_key(job_id))
