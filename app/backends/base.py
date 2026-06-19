"""The backend contract. Two implementations: LocalBackend (CPU, in-process) and
RunPodBackend (remote GPU). The router calls these three methods only."""
from abc import ABC, abstractmethod

from fastapi import BackgroundTasks
from fastapi.responses import Response

from ..models import JobStatus


class Backend(ABC):
    name: str

    @abstractmethod
    def start(self, job_id: str, background_tasks: BackgroundTasks) -> None:
        """Kick off the NeRF job for an already-created Job in the store."""

    @abstractmethod
    def refresh_status(self, job_id: str) -> JobStatus:
        """Return the current status, updating the stored Job as a side effect."""

    @abstractmethod
    def result_response(self, job_id: str) -> Response:
        """Return the finished artifact (FileResponse locally, redirect to a presigned
        URL on RunPod). Assumes status has already been checked == DONE."""
