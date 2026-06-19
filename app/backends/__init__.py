"""Backend selection. The router talks only to `get_backend()`, so swapping local <-> GPU
is a one-line env change (NERF_BACKEND)."""
from functools import lru_cache

from ..config import settings
from .base import Backend


@lru_cache(maxsize=1)
def get_backend() -> Backend:
    if settings.backend == "runpod":
        from .runpod_backend import RunPodBackend

        return RunPodBackend()
    from .local_backend import LocalBackend

    return LocalBackend()
