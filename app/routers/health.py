"""Liveness endpoint + which backend is active (handy when debugging a deploy)."""
from fastapi import APIRouter

from ..config import settings

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz():
    return {"status": "ok", "backend": settings.backend}
