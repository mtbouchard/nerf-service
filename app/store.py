"""In-memory stores. Same caveats as stitch-service: fine for a demo, swap for Redis +
object storage in production. (In runpod mode the *files* already live in S3/R2; only this
small job-metadata map is in-process.)"""
from .models import Job

uploads: dict[str, str] = {}  # image_id -> local path or S3 key
jobs: dict[str, Job] = {}


def reset_state() -> None:
    uploads.clear()
    jobs.clear()
