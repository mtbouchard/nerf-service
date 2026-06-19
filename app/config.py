"""Configuration for the nerf-service API.

The API runs in one of two backends:
  - NERF_BACKEND=local  : runs a CPU stand-in pipeline in-process (produces a real .ply
                          point cloud). Needs no cloud accounts; used for dev, tests, and a
                          deployable demo on Render.
  - NERF_BACKEND=runpod : offloads the real GPU NeRF job (COLMAP + nerfstudio) to a RunPod
                          Serverless endpoint, exchanging files via S3-compatible storage
                          (e.g. Cloudflare R2). Needs the RUNPOD_* and S3_* vars below.
"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "NeRF Service"
    version: str = "1.0.0"

    backend: str = "local"  # "local" | "runpod"

    data_dir: Path = Path(__file__).resolve().parent.parent / "data"

    # A NeRF needs several overlapping views. Keep a sane floor/ceiling.
    min_frames: int = 3
    max_frames: int = 80

    max_upload_bytes: int = 25 * 1024 * 1024
    result_format: str = "ply"  # gaussian-splat export

    cors_allow_origins: str = "*"

    # Stand-in pipeline delay (seconds) so local jobs visibly poll. 0 = fast.
    local_delay_seconds: float = 0.0

    # --- RunPod (backend=runpod) ---
    runpod_api_key: str = ""
    runpod_endpoint_id: str = ""

    # --- S3 / R2 (backend=runpod) ---
    s3_bucket: str = ""
    s3_endpoint_url: str = ""          # e.g. https://<acct>.r2.cloudflarestorage.com
    s3_region: str = "auto"
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    presign_expiry_seconds: int = 3600

    @property
    def cors_origins_list(self) -> list[str]:
        if self.cors_allow_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def results_dir(self) -> Path:
        return self.data_dir / "results"


settings = Settings()
