"""Validate World Labs credentials and inspect available API credits.

Loads nerf-service/.env, then hits the World Labs credits endpoint to verify
that the WLT_API_KEY is configured and valid.

Run (after filling WLT_API_KEY in .env):
    .venv/bin/python nerf-service/scripts/check_worldlabs.py
"""
import sys
from pathlib import Path

import httpx

NERF_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(NERF_DIR))

try:
    from dotenv import load_dotenv
    load_dotenv(NERF_DIR / ".env")
except ImportError:
    pass  # env may already be exported

import worldlabs_backend  # noqa: E402


def main() -> int:
    missing = worldlabs_backend.required_config()
    if missing:
        print(f"FAIL: missing config: {', '.join(missing)}")
        print("Fill these in nerf-service/.env (see .env.example) and re-run.")
        return 1

    print(f"Base URL = {worldlabs_backend.WLT_API_BASE}")
    print(f"Model    = {worldlabs_backend.WLT_MODEL}")
    print("Checking credits to verify API Key...")

    url = f"{worldlabs_backend.WLT_API_BASE}/marble/v1/credits"
    headers = {
        "WLT-Api-Key": worldlabs_backend.WLT_API_KEY,
    }

    try:
        resp = httpx.get(url, headers=headers, timeout=15.0)
        if resp.status_code == 401:
            print("FAIL: Unauthorized. Your WLT_API_KEY is invalid.")
            return 1
        elif resp.status_code != 200:
            print(f"FAIL: Unexpected status {resp.status_code}: {resp.text}")
            return 1

        data = resp.json()
        # Typical credits response carries 'credits' or similar balance representation
        print("SUCCESS: WLT_API_KEY is valid.")
        print(f"Credit balance response: {data}")
        return 0

    except Exception as exc:
        print(f"FAIL: Request failed: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
