"""Validate S3/R2 credentials end-to-end, independent of RunPod.

Loads nerf-service/.env, then exercises the exact storage operations the service relies on:
  1. upload_fileobj          (API uploads frames)
  2. presigned GET           (worker downloads frames; client downloads result)
  3. presigned PUT           (worker uploads the result .ply)

Run (after filling S3_* in .env):
    .venv/bin/python nerf-service/scripts/check_storage.py
"""
import io
import sys
import time
from pathlib import Path

import httpx

NERF_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(NERF_DIR))

try:
    from dotenv import load_dotenv
    load_dotenv(NERF_DIR / ".env")
except ImportError:
    pass  # env may already be exported

import storage  # noqa: E402  (must come after load_dotenv so module constants pick up env)


def main() -> int:
    missing = storage.required_config()
    if missing:
        print(f"FAIL: missing config: {', '.join(missing)}")
        print("Fill these in nerf-service/.env (see .env.example) and re-run.")
        return 1

    print(f"bucket   = {storage.S3_BUCKET}")
    print(f"endpoint = {storage.S3_ENDPOINT_URL or '(AWS default)'}")
    print(f"region   = {storage.S3_REGION}")

    stamp = int(time.time())
    payload = f"nerf-service storage check {stamp}".encode()

    # 1) upload via boto3
    key_a = f"healthcheck/upload-{stamp}.txt"
    storage.upload_fileobj(io.BytesIO(payload), key_a, "text/plain")
    print(f"OK  upload_fileobj -> {key_a}")

    # 2) presigned GET round-trips the same bytes
    get_url = storage.presign_get(key_a)
    got = httpx.get(get_url, timeout=30.0)
    got.raise_for_status()
    assert got.content == payload, "presigned GET returned different bytes"
    print("OK  presigned GET matches uploaded bytes")

    # 3) presigned PUT (the worker's result-upload path), then read it back
    key_b = f"healthcheck/put-{stamp}.bin"
    put_url = storage.presign_put(key_b, "application/octet-stream")
    put = httpx.put(put_url, content=payload, headers={"Content-Type": "application/octet-stream"}, timeout=30.0)
    put.raise_for_status()
    back = httpx.get(storage.presign_get(key_b), timeout=30.0)
    back.raise_for_status()
    assert back.content == payload, "presigned PUT object did not read back correctly"
    print("OK  presigned PUT round-trip works")

    print("\nSUCCESS: R2/S3 credentials are valid and presigning works.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
