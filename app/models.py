"""Schemas + the in-memory job model for nerf-service."""
from enum import Enum

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class UploadResponse(BaseModel):
    id: str


class NerfifyRequest(BaseModel):
    # The series of frame ids returned by /upload. Min is enforced again in the route
    # against settings.min_frames (Field can't read settings at class-def time).
    images: list[str] = Field(min_length=2)


class JobCreatedResponse(BaseModel):
    job_id: str
    status: JobStatus


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    error: str | None = None
    result_format: str | None = None


class Job(BaseModel):
    id: str
    status: JobStatus = JobStatus.PENDING
    image_ids: list[str] = []
    # Backend bookkeeping: RunPod's own job id, and where the result lives.
    backend_job_id: str | None = None
    result_path: str | None = None   # local backend: filesystem path
    result_key: str | None = None    # runpod backend: S3 object key
    error: str | None = None
