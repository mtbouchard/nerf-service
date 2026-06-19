"""Upload frames, start a NeRF job, poll it, download the splat.

Same job contract as the original interview problem and as stitch-service - the only new
thing is that the heavy compute can live on a remote GPU (selected by NERF_BACKEND).
"""
import os
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile, status
from fastapi.responses import Response

from .. import storage
from ..backends import get_backend
from ..config import settings
from ..models import (
    Job,
    JobCreatedResponse,
    JobStatus,
    JobStatusResponse,
    NerfifyRequest,
    UploadResponse,
)
from ..store import jobs, uploads

router = APIRouter(tags=["nerf"])


@router.post("/upload", response_model=UploadResponse)
def upload_frame(file: UploadFile = File(...)):
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File must be an image")

    image_id = uuid4().hex[:12]

    if settings.backend == "runpod":
        key = f"uploads/{image_id}.jpg"
        storage.upload_fileobj(file.file, key, content_type=file.content_type or "image/jpeg")
        uploads[image_id] = key
    else:
        path = str(settings.uploads_dir / f"{image_id}.jpg")
        size = 0
        with open(path, "wb") as out:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    out.close()
                    os.remove(path)
                    raise HTTPException(
                        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File too large"
                    )
                out.write(chunk)
        uploads[image_id] = path

    return UploadResponse(id=image_id)


@router.post(
    "/nerfify", response_model=JobCreatedResponse, status_code=status.HTTP_202_ACCEPTED
)
def start_nerfify(req: NerfifyRequest, background_tasks: BackgroundTasks):
    if len(req.images) < settings.min_frames:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Need at least {settings.min_frames} frames for a reconstruction",
        )
    if len(req.images) > settings.max_frames:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Too many frames (max {settings.max_frames})"
        )
    for image_id in req.images:
        if image_id not in uploads:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Frame id not found: {image_id}")

    job_id = uuid4().hex[:12]
    jobs[job_id] = Job(id=job_id, status=JobStatus.PENDING, image_ids=list(req.images))

    try:
        get_backend().start(job_id, background_tasks)
    except Exception as exc:  # noqa: BLE001 - surface backend submit failures cleanly
        jobs[job_id].status = JobStatus.FAILED
        jobs[job_id].error = str(exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Could not start job: {exc}")

    return JobCreatedResponse(job_id=job_id, status=jobs[job_id].status)


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    current = get_backend().refresh_status(job_id)
    job = jobs[job_id]
    return JobStatusResponse(
        job_id=job_id,
        status=current,
        error=job.error,
        result_format=settings.result_format if current is JobStatus.DONE else None,
    )


@router.get("/jobs/{job_id}/result")
def get_job_result(job_id: str) -> Response:
    if job_id not in jobs:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    current = get_backend().refresh_status(job_id)
    if current is JobStatus.FAILED:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, f"Job failed: {jobs[job_id].error}"
        )
    if current is not JobStatus.DONE:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Job not finished (status: {current.value})"
        )
    return get_backend().result_response(job_id)
