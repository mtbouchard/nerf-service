"""World Labs (Marble) World API backend — used only when NERF_BACKEND=worldlabs.

This module implements the integration with World Labs' public World API.
It handles uploading local files to World Labs' media assets platform,
submitting long-running async world-generation jobs from those assets,
and polling status until a fully navigable 3D world URL is ready.

The user must provide their World Labs platform key via the WLT_API_KEY env var.
"""
import os
import uuid
from typing import Any

import httpx

# Global configurations
WLT_API_BASE = "https://api.worldlabs.ai"
WLT_API_KEY = os.environ.get("WLT_API_KEY")
WLT_MODEL = os.environ.get("WLT_MODEL", "marble-1.1")


def required_config() -> list[str]:
    """Return a list of missing configuration environment variables.
    An empty list means everything required is present and correct.
    """
    missing = []
    if not WLT_API_KEY:
        missing.append("WLT_API_KEY")
    return missing


def upload_image(fileobj: Any, file_name: str) -> str:
    """Prepare and upload a local image file to World Labs as a media asset.

    Workflow:
      1. POST /marble/v1/media-assets:prepare_upload with:
         {
           "file_name": file_name,
           "kind": "image",
           "extension": "jpg"  (or extracted extension)
         }
         Set headers: {"WLT-Api-Key": WLT_API_KEY}
      2. Extract "media_asset" -> "id" and "upload_info" -> "upload_url" / "required_headers".
      3. PUT the file's raw binary data to the "upload_url" using the "required_headers".
      4. Return the media asset ID.

    Args:
        fileobj: A file-like object (e.g., UploadFile.file or BytesIO) containing the JPEG bytes.
        file_name: The original file name.

    Returns:
        str: The generated World Labs media_asset_id.
    """
    if not WLT_API_KEY:
        raise ValueError("WLT_API_KEY environment variable is not configured.")

    ext = file_name.split(".")[-1].lower() if "." in file_name else "jpg"
    if ext not in ("jpg", "jpeg", "png", "webp"):
        ext = "jpg"

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

    fileobj.seek(0)
    file_bytes = fileobj.read()

    put_headers = {**required_headers}
    if "Content-Type" not in put_headers and ext in ("jpg", "jpeg"):
        put_headers["Content-Type"] = "image/jpeg"
    elif "Content-Type" not in put_headers and ext == "png":
        put_headers["Content-Type"] = "image/png"

    put_resp = httpx.put(upload_url, headers=put_headers, content=file_bytes, timeout=60.0)
    put_resp.raise_for_status()

    return asset_id


def submit(asset_ids: list[str]) -> str:
    """Submit a multi-image world generation job to World Labs, returning the operation_id.

    Workflow:
      1. Distribute the assets evenly around a 360-degree orbit (the azimuths).
         Specifically, for N images, the i-th image should have:
         azimuth = int(i * 360 / N)
      2. Construct the request body for POST /marble/v1/worlds:generate:
         {
           "display_name": f"World {uuid[:6]}",
           "model": WLT_MODEL,
           "world_prompt": {
             "type": "multi-image",
             "multi_image_prompt": [
               {
                 "azimuth": azimuth,
                 "content": {
                   "source": "media_asset",
                   "media_asset_id": asset_id
                 }
               },
               ...
             ]
           }
         }
      3. POST the request to the generate endpoint with WLT-Api-Key header.
      4. Extract and return the "operation_id".

    Args:
        asset_ids: List of media_asset_id strings uploaded in step 1.

    Returns:
        str: The long-running operation_id to poll.
    """
    if not WLT_API_KEY:
        raise ValueError("WLT_API_KEY environment variable is not configured.")

    multi_image_prompt = []
    n = len(asset_ids)
    for i, asset_id in enumerate(asset_ids):
        azimuth = int(i * 360 / n)
        multi_image_prompt.append({
            "azimuth": azimuth,
            "content": {
                "source": "media_asset",
                "media_asset_id": asset_id,
            },
        })

    payload = {
        "display_name": f"World {uuid.uuid4().hex[:6]}",
        "model": WLT_MODEL,
        "world_prompt": {
            "type": "multi-image",
            "multi_image_prompt": multi_image_prompt,
        },
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
    """Retrieve the status of a long-running world generation operation.

    Workflow:
      1. GET /marble/v1/operations/{operation_id} with WLT-Api-Key header.
      2. If "done" is False:
         - Map the progress state (metadata.progress.status) or default to "running".
         - Return (mapped_status, None, None).
         - Note: Map "IN_QUEUE" -> "pending", "IN_PROGRESS" -> "running".
      3. If "done" is True:
         - If "error" is present in the response: return ("failed", error_message, None).
         - If successful:
           - Extract "response" -> "world_marble_url".
           - Return ("done", None, world_marble_url).

    Args:
        operation_id: The World Labs operation ID returned from submit().

    Returns:
        tuple[str, str | None, str | None]:
            - status (one of: "pending", "running", "done", "failed")
            - error (string or None if no error occurred)
            - world_url (string or None if not finished)
    """
    if not WLT_API_KEY:
        raise ValueError("WLT_API_KEY environment variable is not configured.")

    status_url = f"{WLT_API_BASE}/marble/v1/operations/{operation_id}"
    headers = {"WLT-Api-Key": WLT_API_KEY}

    resp = httpx.get(status_url, headers=headers, timeout=30.0)
    resp.raise_for_status()
    data = resp.json()

    if not data.get("done", False):
        metadata = data.get("metadata") or {}
        progress = metadata.get("progress") or {}
        status_str = progress.get("status", "IN_PROGRESS")
        if status_str == "IN_QUEUE":
            return "pending", None, None
        return "running", None, None

    error = data.get("error")
    if error:
        err_msg = error.get("message") if isinstance(error, dict) else str(error)
        return "failed", err_msg, None

    response_data = data.get("response") or {}
    world_url = response_data.get("world_marble_url")
    if not world_url:
        return "failed", "Operation completed but world_marble_url is missing.", None

    return "done", None, world_url
