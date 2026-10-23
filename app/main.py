import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
import websockets
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from app import go2rtc
from app.rtsp_url import normalize_rtsp_url
from app.storage import CamerasCorruptError, load_cameras, save_cameras

STATIC_DIR = Path(__file__).parent / "static"
GO2RTC_URL = os.environ.get("GO2RTC_URL", "http://go2rtc:1984").rstrip("/")
GO2RTC_WS = GO2RTC_URL.replace("http://", "ws://").replace("https://", "wss://")

_store_lock = asyncio.Lock()


class CameraCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    rtsp: str = Field(min_length=1, max_length=2048)

    @field_validator("rtsp")
    @classmethod
    def validate_rtsp(cls, value: str) -> str:
        return normalize_rtsp_url(value)


class CameraUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    rtsp: str | None = Field(default=None, min_length=1, max_length=2048)

    @field_validator("rtsp")
    @classmethod
    def validate_rtsp(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return normalize_rtsp_url(value)


class OrderUpdate(BaseModel):
    order: list[str]


def _public_camera(cam: dict[str, Any]) -> dict[str, str]:
    return {
        "id": cam["id"],
        "name": cam["name"],
        "stream": go2rtc.stream_name(cam["id"]),
    }


def _load_cameras() -> list[dict[str, Any]]:
    try:
        return load_cameras()
    except CamerasCorruptError:
        raise HTTPException(status_code=500, detail="Camera storage is corrupt") from None


def _allowed_ws_stream(query_params: Any) -> str | None:
    """Return stream name if query is exactly one src=cam-{known-id}, else None."""
    items = list(query_params.multi_items())
    src_values = [v for k, v in items if k == "src"]
    if any(k != "src" for k, _ in items):
        return None
    if len(src_values) != 1:
        return None
    src = src_values[0]
    try:
        cameras = load_cameras()
    except CamerasCorruptError:
        return None
    for cam in cameras:
        if go2rtc.stream_name(cam["id"]) == src:
            return src
    return None


async def _sync_go2rtc_until_ok(stop: asyncio.Event) -> None:
    delay = 0.5
    while not stop.is_set():
        try:
            cameras = load_cameras()
            await go2rtc.sync_all(cameras)
            return
        except CamerasCorruptError as exc:
            print(f"go2rtc sync skipped: camera storage corrupt: {exc}")
            return
        except httpx.HTTPError as exc:
            print(f"go2rtc sync failed, retrying in {delay}s: {exc}")
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
            return
        except asyncio.TimeoutError:
            pass
        delay = min(delay * 2, 5.0)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    stop = asyncio.Event()
    sync_task = asyncio.create_task(_sync_go2rtc_until_ok(stop))
    yield
    stop.set()
    sync_task.cancel()
    try:
        await sync_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Homecam", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def homecam_identity(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Homecam"] = "1"
    return response


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/cameras")
async def list_cameras() -> list[dict[str, str]]:
    cameras = _load_cameras()
    return [_public_camera(c) for c in cameras]


@app.post("/api/cameras", status_code=201)
async def create_camera(body: CameraCreate) -> dict[str, str]:
    camera = {
        "id": uuid.uuid4().hex,
        "name": body.name.strip(),
        "rtsp": body.rtsp,
    }
    async with _store_lock:
        cameras = _load_cameras()
        cameras.append(camera)
        save_cameras(cameras)
    try:
        await go2rtc.register_stream(camera["id"], camera["rtsp"])
    except httpx.HTTPError as exc:
        async with _store_lock:
            cameras = _load_cameras()
            cameras = [c for c in cameras if c["id"] != camera["id"]]
            save_cameras(cameras)
        raise HTTPException(status_code=502, detail=f"go2rtc error: {exc}") from exc
    return _public_camera(camera)


@app.patch("/api/cameras/{camera_id}")
async def update_camera(camera_id: str, body: CameraUpdate) -> dict[str, str]:
    async with _store_lock:
        cameras = _load_cameras()
        idx = next((i for i, c in enumerate(cameras) if c["id"] == camera_id), None)
        if idx is None:
            raise HTTPException(status_code=404, detail="Camera not found")
        previous = cameras[idx].copy()
        cam = cameras[idx].copy()
        if body.name is not None:
            cam["name"] = body.name.strip()
        if body.rtsp is not None:
            cam["rtsp"] = body.rtsp
        cameras[idx] = cam
        save_cameras(cameras)
    try:
        await go2rtc.register_stream(cam["id"], cam["rtsp"])
    except httpx.HTTPError as exc:
        async with _store_lock:
            cameras = _load_cameras()
            idx = next((i for i, c in enumerate(cameras) if c["id"] == camera_id), None)
            if idx is not None and cameras[idx] == cam:
                cameras[idx] = previous
                save_cameras(cameras)
        raise HTTPException(status_code=502, detail=f"go2rtc error: {exc}") from exc
    return _public_camera(cam)


@app.delete("/api/cameras/{camera_id}", status_code=204)
async def delete_camera(camera_id: str) -> Response:
    async with _store_lock:
        cameras = _load_cameras()
        if not any(c["id"] == camera_id for c in cameras):
            raise HTTPException(status_code=404, detail="Camera not found")
    try:
        await go2rtc.unregister_stream(camera_id)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"go2rtc error: {exc}") from exc
    async with _store_lock:
        cameras = _load_cameras()
        cameras = [c for c in cameras if c["id"] != camera_id]
        save_cameras(cameras)
    return Response(status_code=204)


@app.put("/api/cameras/order")
async def reorder_cameras(body: OrderUpdate) -> list[dict[str, str]]:
    async with _store_lock:
        cameras = _load_cameras()
        by_id = {c["id"]: c for c in cameras}
        if set(body.order) != set(by_id.keys()):
            raise HTTPException(status_code=400, detail="Order must include every camera id once")
        cameras = [by_id[cid] for cid in body.order]
        save_cameras(cameras)
    return [_public_camera(c) for c in cameras]


@app.websocket("/rtc/api/ws")
async def proxy_ws(websocket: WebSocket) -> None:
    stream = _allowed_ws_stream(websocket.query_params)
    if stream is None:
        await websocket.close(code=1008, reason="Forbidden")
        return

    await websocket.accept()
    upstream_url = f"{GO2RTC_WS}/api/ws?{urlencode({'src': stream})}"

    try:
        async with websockets.connect(upstream_url, max_size=None) as upstream:
            async def client_to_upstream() -> None:
                try:
                    while True:
                        message = await websocket.receive()
                        if message["type"] == "websocket.disconnect":
                            break
                        if "text" in message:
                            await upstream.send(message["text"])
                        elif "bytes" in message:
                            await upstream.send(message["bytes"])
                except WebSocketDisconnect:
                    pass

            async def upstream_to_client() -> None:
                try:
                    async for msg in upstream:
                        if isinstance(msg, str):
                            await websocket.send_text(msg)
                        else:
                            await websocket.send_bytes(msg)
                except websockets.ConnectionClosed:
                    pass

            client_task = asyncio.create_task(client_to_upstream())
            upstream_task = asyncio.create_task(upstream_to_client())
            done, pending = await asyncio.wait(
                {client_task, upstream_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
    except Exception:
        await websocket.close()
