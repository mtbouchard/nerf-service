"""S3 / R2 helper, used only in backend=runpod.

It moves files between the API and the remote GPU worker WITHOUT giving the worker any
credentials: the API generates presigned GET urls for the input frames and a presigned PUT
url for the result. The worker just does plain HTTP GET/PUT.

boto3 is imported lazily so local mode needs neither boto3 nor any cloud account.
"""
from functools import lru_cache

from .config import settings


@lru_cache(maxsize=1)
def _s3_client():
    import boto3  # lazy: only needed in runpod mode
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url or None,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        config=Config(signature_version="s3v4"),
    )


def upload_fileobj(fileobj, key: str, content_type: str = "application/octet-stream") -> None:
    _s3_client().upload_fileobj(
        fileobj, settings.s3_bucket, key, ExtraArgs={"ContentType": content_type}
    )


def presign_get(key: str) -> str:
    return _s3_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket, "Key": key},
        ExpiresIn=settings.presign_expiry_seconds,
    )


def presign_put(key: str, content_type: str = "application/octet-stream") -> str:
    return _s3_client().generate_presigned_url(
        "put_object",
        Params={"Bucket": settings.s3_bucket, "Key": key, "ContentType": content_type},
        ExpiresIn=settings.presign_expiry_seconds,
    )


def object_exists(key: str) -> bool:
    import botocore

    try:
        _s3_client().head_object(Bucket=settings.s3_bucket, Key=key)
        return True
    except botocore.exceptions.ClientError:
        return False
