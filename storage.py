"""S3 / R2 object storage helper — used only when NERF_BACKEND=runpod.

It moves files between the API and the remote GPU worker WITHOUT handing the worker any
credentials: the API uploads frames to the bucket, then generates presigned GET urls for
those frames and a presigned PUT url for the result. The worker just follows those urls
with plain HTTP GET/PUT.

boto3 is imported lazily inside _client(), so local mode needs neither boto3 nor any cloud
account — importing this module is always safe.

Config comes from the environment (works with AWS S3 or any S3-compatible store like
Cloudflare R2 / Backblaze B2):
    S3_BUCKET                 bucket name
    S3_ENDPOINT_URL           custom endpoint (R2/B2); leave unset for real AWS S3
    S3_REGION                 region (use "auto" for R2); default "auto"
    S3_ACCESS_KEY_ID          access key
    S3_SECRET_ACCESS_KEY      secret key
    PRESIGN_EXPIRY_SECONDS    how long presigned urls stay valid; default 3600
"""
import os
from functools import lru_cache

S3_BUCKET = os.environ.get("S3_BUCKET")
S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL")  # e.g. https://<acct>.r2.cloudflarestorage.com
S3_REGION = os.environ.get("S3_REGION", "auto")
S3_ACCESS_KEY_ID = os.environ.get("S3_ACCESS_KEY_ID")
S3_SECRET_ACCESS_KEY = os.environ.get("S3_SECRET_ACCESS_KEY")
PRESIGN_EXPIRY_SECONDS = int(os.environ.get("PRESIGN_EXPIRY_SECONDS", "3600"))


def required_config() -> list[str]:
    """Names of any required settings that are missing (empty list == good to go)."""
    missing = []
    if not S3_BUCKET:
        missing.append("S3_BUCKET")
    if not S3_ACCESS_KEY_ID:
        missing.append("S3_ACCESS_KEY_ID")
    if not S3_SECRET_ACCESS_KEY:
        missing.append("S3_SECRET_ACCESS_KEY")
    return missing


@lru_cache(maxsize=1)
def _client():
    import boto3  # lazy: only needed in runpod mode
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT_URL or None,
        region_name=S3_REGION,
        aws_access_key_id=S3_ACCESS_KEY_ID,
        aws_secret_access_key=S3_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
    )


def upload_fileobj(fileobj, key: str, content_type: str = "application/octet-stream") -> None:
    _client().upload_fileobj(
        fileobj, S3_BUCKET, key, ExtraArgs={"ContentType": content_type}
    )


def presign_get(key: str) -> str:
    return _client().generate_presigned_url(
        "get_object",
        Params={"Bucket": S3_BUCKET, "Key": key},
        ExpiresIn=PRESIGN_EXPIRY_SECONDS,
    )


def presign_put(key: str, content_type: str = "application/octet-stream") -> str:
    return _client().generate_presigned_url(
        "put_object",
        Params={"Bucket": S3_BUCKET, "Key": key, "ContentType": content_type},
        ExpiresIn=PRESIGN_EXPIRY_SECONDS,
    )
