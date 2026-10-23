import os
from urllib.parse import urlencode

import httpx

from app.rtsp_url import normalize_rtsp_url

GO2RTC_URL = os.environ.get("GO2RTC_URL", "http://go2rtc:1984").rstrip("/")


def stream_name(camera_id: str) -> str:
    return f"cam-{camera_id}"


async def register_stream(camera_id: str, rtsp: str) -> None:
    rtsp = normalize_rtsp_url(rtsp)
    name = stream_name(camera_id)
    query = urlencode({"name": name, "src": rtsp})
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.put(f"{GO2RTC_URL}/api/streams?{query}")
        if response.status_code >= 400:
            detail = response.text.strip() or response.reason_phrase
            raise httpx.HTTPStatusError(
                f"go2rtc: {detail}",
                request=response.request,
                response=response,
            )


async def unregister_stream(camera_id: str) -> None:
    name = stream_name(camera_id)
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.delete(
            f"{GO2RTC_URL}/api/streams",
            params={"src": name},
        )
        if response.status_code not in (200, 204, 404):
            response.raise_for_status()


async def sync_all(cameras: list[dict]) -> None:
    for cam in cameras:
        await register_stream(cam["id"], cam["rtsp"])
