"""GPU backend: submits the job to a RunPod Serverless endpoint and exchanges files via
S3/R2 presigned URLs.

Flow:
  start()          -> presign GET urls for every uploaded frame + a PUT url for the result,
                      POST them to RunPod /run, store RunPod's job id.
  refresh_status() -> GET RunPod /status/{id}, map RunPod state -> our JobStatus.
  result_response()-> redirect the client to a presigned GET url for the result object.

The worker (worker/handler.py) needs no credentials: it only follows the presigned urls.
"""
import httpx
from fastapi import BackgroundTasks, HTTPException, status
from fastapi.responses import RedirectResponse, Response

from .. import storage
from ..config import settings
from ..models import JobStatus
from ..store import jobs
from .base import Backend

RUNPOD_BASE = "https://api.runpod.ai/v2"

# RunPod serverless states -> our four-state model.
_STATE_MAP = {
    "IN_QUEUE": JobStatus.PENDING,
    "IN_PROGRESS": JobStatus.RUNNING,
    "COMPLETED": JobStatus.DONE,
    "FAILED": JobStatus.FAILED,
    "CANCELLED": JobStatus.FAILED,
    "TIMED_OUT": JobStatus.FAILED,
}


class RunPodBackend(Backend):
    name = "runpod"

    def __init__(self) -> None:
        missing = [
            k
            for k in ("runpod_api_key", "runpod_endpoint_id", "s3_bucket", "s3_endpoint_url")
            if not getattr(settings, k)
        ]
        if missing:
            raise RuntimeError(f"runpod backend missing config: {', '.join(missing)}")
        self._headers = {"Authorization": f"Bearer {settings.runpod_api_key}"}
        self._run_url = f"{RUNPOD_BASE}/{settings.runpod_endpoint_id}/run"
        self._status_url = f"{RUNPOD_BASE}/{settings.runpod_endpoint_id}/status"

    def _result_key(self, job_id: str) -> str:
        return f"results/{job_id}.{settings.result_format}"

    def start(self, job_id: str, background_tasks: BackgroundTasks) -> None:
        from ..store import uploads

        job = jobs[job_id]
        image_urls = [storage.presign_get(uploads[i]) for i in job.image_ids]
        result_key = self._result_key(job_id)
        result_put_url = storage.presign_put(result_key)

        payload = {
            "input": {
                "images": image_urls,
                "result_put_url": result_put_url,
                "result_format": settings.result_format,
            }
        }
        resp = httpx.post(self._run_url, json=payload, headers=self._headers, timeout=30.0)
        resp.raise_for_status()
        job.backend_job_id = resp.json()["id"]
        job.result_key = result_key
        job.status = JobStatus.PENDING

    def refresh_status(self, job_id: str) -> JobStatus:
        job = jobs[job_id]
        if job.backend_job_id is None:
            return job.status
        resp = httpx.get(
            f"{self._status_url}/{job.backend_job_id}", headers=self._headers, timeout=30.0
        )
        resp.raise_for_status()
        data = resp.json()
        mapped = _STATE_MAP.get(data.get("status"), JobStatus.RUNNING)
        if mapped is JobStatus.FAILED and job.error is None:
            job.error = str(data.get("error") or data.get("output") or "job failed")
        job.status = mapped
        return mapped

    def result_response(self, job_id: str) -> Response:
        job = jobs[job_id]
        if not job.result_key:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Missing result key")
        return RedirectResponse(url=storage.presign_get(job.result_key))
