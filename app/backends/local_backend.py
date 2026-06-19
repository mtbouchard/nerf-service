"""CPU backend: runs the stand-in pipeline in a background task and serves the .ply from
local disk. Fully self-contained (no cloud, no GPU) - used for dev, tests, and the Render
demo."""
from fastapi import BackgroundTasks, HTTPException, status
from fastapi.responses import FileResponse, Response

from .. import local_pipeline
from ..config import settings
from ..models import JobStatus
from ..store import jobs, uploads
from .base import Backend


def _run(job_id: str) -> None:
    job = jobs.get(job_id)
    if job is None:
        return
    job.status = JobStatus.RUNNING
    try:
        paths = [uploads[i] for i in job.image_ids]
        out_path = str(settings.results_dir / f"{job_id}.{settings.result_format}")
        local_pipeline.generate_pointcloud_ply(paths, out_path)
        job.result_path = out_path
        job.status = JobStatus.DONE
    except Exception as exc:  # noqa: BLE001
        job.status = JobStatus.FAILED
        job.error = str(exc)


class LocalBackend(Backend):
    name = "local"

    def start(self, job_id: str, background_tasks: BackgroundTasks) -> None:
        background_tasks.add_task(_run, job_id)

    def refresh_status(self, job_id: str) -> JobStatus:
        return jobs[job_id].status

    def result_response(self, job_id: str) -> Response:
        job = jobs[job_id]
        if not job.result_path:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Missing result file")
        return FileResponse(
            job.result_path,
            media_type="application/octet-stream",
            filename=f"{job_id}.{settings.result_format}",
        )
