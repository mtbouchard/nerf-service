"""One-off: set CORS on the R2 bucket so the WebGL /viewer can fetch result .ply files.

The viewer (served from the API origin) fetches the result via /jobs/{id}/result or /sample,
which 30x-redirects to a presigned R2 URL on a different origin. The browser only lets the
viewer read that cross-origin response if R2 returns CORS headers. This script applies a
GET/HEAD CORS rule to the bucket. It is safe to re-run (idempotent).

Credentials are read from nerf-service/.env (or the existing environment):
    S3_BUCKET, S3_ENDPOINT_URL, S3_REGION, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY

Usage:
    cd nerf-service && python scripts/set_r2_cors.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def main() -> int:
    load_dotenv(ROOT / ".env")
    sys.path.insert(0, str(ROOT))
    import storage

    missing = storage.required_config()
    if missing:
        print(f"Missing required config: {missing}")
        return 1

    storage.put_cors()
    rules = storage.get_cors()
    print(f"Applied CORS to bucket '{storage.S3_BUCKET}':")
    for rule in rules:
        print(
            f"  origins={rule.get('AllowedOrigins')} "
            f"methods={rule.get('AllowedMethods')} "
            f"maxAge={rule.get('MaxAgeSeconds')}"
        )
    if not rules:
        print("  (no rules returned — check credentials/permissions)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
