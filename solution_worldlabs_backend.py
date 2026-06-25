"""Reference implementation for World Labs (Marble) World API backend."""
import os
import uuid
from typing import Any
import httpx

WLT_API_BASE = "https://api.worldlabs.ai"
WLT_API_KEY = os.environ.get("WLT_API_KEY")
WLT_MODEL = os.environ.get("WLT_MODEL", "marble-1.1")


def required_config() -> list[str]:
    """Return a list of missing configuration environment variables."""
    missing = []
    if not WLT_API_KEY:
        missing.append("WLT_API_KEY")
    return missing


def upload_image(fileobj: Any, file_name: str) -> str:
    """Prepare and upload a local image file to World Labs as a media asset."""
    if not WLT_API_KEY:
        raise ValueError("WLT_API_KEY environment variable is not configured.")

    ext = file_name.split(".")[-1].lower() if "." in file_name else "jpg"
    if ext not in ("jpg", "jpeg", "png", "webp"):
        ext = "jpg"

    # Step 1: Prepare the upload
    prepare_url = f"{WLT_API_BASE}/marble/v1/media-assets:prepare_upload"
    payload = {
        "file_name": file_name,
        "kind": "image",
        "extension": ext,
    }
    headers = {
        "WLT-Api-Key": WLT_API_KEY,
        "Content-Type": "application/json",
    }
    
    resp = httpx.post(prepare_url, json=payload, headers=headers, timeout=30.0)
    resp.raise_for_status()
    data = resp.json()

    asset_id = data["media_asset"]["id"]
    upload_url = data["upload_info"]["upload_url"]
    required_headers = data["upload_info"].get("required_headers", {})

    # Step 2: Upload the binary payload
    fileobj.seek(0)
    file_bytes = fileobj.read()
    
    # We forward required_headers exactly as returned. GCS signed URLs can be sensitive to Content-Type headers,
    # but httpx will handle the raw binary upload perfectly via 'content'.
    put_headers = {**required_headers}
    if "Content-Type" not in put_headers and ext in ("jpg", "jpeg"):
        put_headers["Content-Type"] = "image/jpeg"
    elif "Content-Type" not in put_headers and ext == "png":
        put_headers["Content-Type"] = "image/png"

    put_resp = httpx.put(upload_url, headers=put_headers, content=file_bytes, timeout=60.0)
    put_resp.raise_for_status()

    return asset_id


def submit(asset_ids: list[str]) -> str:
    """Submit a multi-image world generation job to World Labs, returning the operation_id."""
    if not WLT_API_KEY:
        raise ValueError("WLT_API_KEY environment variable is not configured.")

    multi_image_prompt = []
    n = len(asset_ids)
    for i, asset_id in enumerate(asset_ids):
        # Evenly space the horizontal azimuth angles around 360 degrees
        azimuth = int(i * 360 / n)
        multi_image_prompt.append({
            "azimuth": azimuth,
            "content": {
                "source": "media_asset",
                "media_asset_id": asset_id,
            }
        })

    display_name = f"World {uuid.uuid4().hex[:6]}"
    payload = {
        "display_name": display_name,
        "model": WLT_MODEL,
        "world_prompt": {
            "type": "multi-image",
            "multi_image_prompt": multi_image_prompt,
        }
    }
    headers = {
        "WLT-Api-Key": WLT_API_KEY,
        "Content-Type": "application/json",
    }

    generate_url = f"{WLT_API_BASE}/marble/v1/worlds:generate"
    resp = httpx.post(generate_url, json=payload, headers=headers, timeout=30.0)
    resp.raise_for_status()
    return resp.json()["operation_id"]


def fetch_status(operation_id: str) -> tuple[str, str | None, str | None]:
    """Retrieve the status of a long-running world generation operation."""
    if not WLT_API_KEY:
        raise ValueError("WLT_API_KEY environment variable is not configured.")

    status_url = f"{WLT_API_BASE}/marble/v1/operations/{operation_id}"
    headers = {
        "WLT-Api-Key": WLT_API_KEY,
    }

    resp = httpx.get(status_url, headers=headers, timeout=30.0)
    resp.raise_for_status()
    data = resp.json()

    done = data.get("done", False)
    if not done:
        metadata = data.get("metadata") or {}
        progress = metadata.get("progress") or {}
        status_str = progress.get("status", "IN_PROGRESS")
        if status_str == "IN_QUEUE":
            return "pending", None, None
        return "running", None, None

    # Handle completion (done == True)
    error = data.get("error")
    if error:
        err_msg = error.get("message") if isinstance(error, dict) else str(error)
        return "failed", err_msg, None

    response_data = data.get("response") or {}
    world_url = response_data.get("world_marble_url")
    if not world_url:
        return "failed", "Operation completed but world_marble_url is missing.", None

    return "done", None, world_url
