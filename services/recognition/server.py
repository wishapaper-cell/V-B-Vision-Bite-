"""FastAPI video session backend for real-time food measurement.

Run with:
    cd services\recognition
    set PYTHONPATH=.
    python server.py

Or from repo root:
    set PYTHONPATH=services\recognition
    python services\recognition\server.py
"""
from __future__ import annotations

import binascii
import io
import sys
import time
from pathlib import Path

import qrcode
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from PIL import UnidentifiedImageError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

# Make `backend.*` imports work when running this file directly.
_demo_root = Path(__file__).resolve().parent
if str(_demo_root) not in sys.path:
    sys.path.insert(0, str(_demo_root))

from backend.models.schemas import (
    CaptureEvent,
    CreateSessionResponse,
    DeviceInfo,
    FrameUpload,
    JoinSessionRequest,
)
from backend.services.analyzer import FoodAnalyzer
from backend.services.session_store import SessionStore
from backend.services.udp_stream import UdpStreamReceiver


app = FastAPI(title="NutritionGlass Video Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_analyzer = FoodAnalyzer()
_store = SessionStore(_analyzer)
_udp_receiver = UdpStreamReceiver(_store)


@app.on_event("startup")
async def _start_udp_receiver():
    import asyncio

    _udp_receiver.start(asyncio.get_running_loop())


@app.on_event("shutdown")
async def _stop_udp_receiver():
    _udp_receiver.stop()


@app.get("/api/rokid-stream/status")
async def rokid_stream_status():
    return _udp_receiver.status()


def _public_base_url(request) -> str:
    """Build public base URL from request headers or fallback to origin."""
    forwarded_host = request.headers.get("x-forwarded-host")
    forwarded_proto = request.headers.get("x-forwarded-proto", "http")
    if forwarded_host:
        return f"{forwarded_proto}://{forwarded_host}"
    host = request.headers.get("host", "127.0.0.1:8000")
    scheme = request.url.scheme or "http"
    return f"{scheme}://{host}"


@app.get("/")
async def root():
    return FileResponse(_demo_root / "static" / "dashboard.html")


@app.get("/capture")
async def capture_page():
    return FileResponse(_demo_root / "static" / "capture.html")


@app.post("/api/sessions", response_model=CreateSessionResponse)
async def create_session(request: Request):
    return _store.create_session(public_base_url=_public_base_url(request))


@app.post("/api/sessions/{session_id}/join")
async def join_session(session_id: str, body: JoinSessionRequest):
    try:
        return await _store.join_mobile(
            session_id=session_id,
            token=body.token,
            device=body.device,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="session not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="invalid token")


@app.post("/api/sessions/{session_id}/capture-event")
async def capture_event(session_id: str, body: CaptureEvent):
    try:
        return await _store.capture_event(session_id, body)
    except KeyError:
        raise HTTPException(status_code=404, detail="session not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="invalid token")


@app.post("/api/sessions/{session_id}/frames")
async def upload_frame(session_id: str, body: FrameUpload):
    try:
        return await _store.process_frame(session_id, body)
    except (ValueError, binascii.Error, UnidentifiedImageError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid image: {exc}")
    except KeyError:
        raise HTTPException(status_code=404, detail="session not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="invalid token")


@app.get("/api/sessions/{session_id}/state")
async def session_state(session_id: str):
    try:
        return _store.get(session_id).state
    except KeyError:
        raise HTTPException(status_code=404, detail="session not found")


@app.get("/api/sessions/{session_id}/latest-frame")
async def latest_frame(session_id: str):
    try:
        record = _store.get(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="session not found")

    if not record.latest_frame_bytes:
        raise HTTPException(status_code=404, detail="no frame received yet")

    return Response(
        content=record.latest_frame_bytes,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


@app.get("/api/sessions/{session_id}/qrcode")
async def session_qrcode(session_id: str):
    try:
        record = _store.get(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="session not found")

    img = qrcode.make(record.state.capture_url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="image/png",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


@app.post("/api/sessions/{session_id}/finish")
async def finish_session(session_id: str):
    try:
        return await _store.finish(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="session not found")


@app.websocket("/ws/sessions/{session_id}/events")
async def events_websocket(websocket: WebSocket, session_id: str):
    try:
        _store.get(session_id)
    except KeyError:
        await websocket.close(code=4004, reason="session not found")
        return

    await _store.add_socket(session_id, websocket)
    try:
        while True:
            # Keep connection alive; clients may send ping messages.
            data = await websocket.receive_text()
            if data:
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        _store.remove_socket(session_id, websocket)


# Serve static assets (HTML, JS, CSS) under /static and root.
app.mount("/static", StaticFiles(directory=_demo_root / "static"), name="static")


def main() -> None:
    import uvicorn

    print(f"Analyzer backend: {_analyzer.backend_name}")
    print(f"Model: {_analyzer.model_name}")
    print("Starting NutritionGlass video backend on http://127.0.0.1:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")


if __name__ == "__main__":
    main()
