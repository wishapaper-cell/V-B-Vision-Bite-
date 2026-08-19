"""UDP MPEG-TS receiver that feeds Rokid glasses video into the session pipeline.

The glasses app (rokid_glasses_streamer) hardware-encodes H.264, wraps it in
MPEG-TS and sends it over UDP (default port 5000). This module decodes the
stream with PyAV and forwards throttled frames into SessionStore so the full
food + utensil + intake analysis runs on glasses video exactly like on
browser-uploaded frames.
"""
from __future__ import annotations

import asyncio
import io
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.services.session_store import SessionStore

DEFAULT_UDP_HOST = "0.0.0.0"
DEFAULT_UDP_PORT = 5000
FORWARD_INTERVAL_S = 0.15


def _udp_input_url(host: str, port: int) -> str:
    return f"udp://{host}:{port}?fifo_size=65536&overrun_nonfatal=1&reuse=1&timeout=1000000"


def _is_idle_error(error: Exception) -> bool:
    # On Windows, FFmpeg reports an idle UDP input as EIO (errno 5), which
    # just means the glasses have not started streaming yet.
    if getattr(error, "errno", None) in {5, 11, 60, 110, 10035, 10060}:
        return True
    message = str(error).lower()
    return "timeout" in type(error).__name__.lower() or "timed out" in message or "temporarily unavailable" in message


class UdpStreamReceiver:
    def __init__(
        self,
        store: "SessionStore",
        *,
        host: str = DEFAULT_UDP_HOST,
        port: int = DEFAULT_UDP_PORT,
        public_base_url: str = "https://127.0.0.1:8000",
    ) -> None:
        self.store = store
        self.host = host
        self.port = port
        self.public_base_url = public_base_url
        self.session_id: str | None = None
        self.last_frame_at: float = 0.0
        self.frames_forwarded = 0
        self.decode_errors = 0
        self.reconnects = 0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._loop = loop
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="rokid-udp-stream", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def status(self) -> dict[str, object]:
        return {
            "running": self._thread is not None and self._thread.is_alive(),
            "listen": f"udp://{self.host}:{self.port}",
            "session_id": self.session_id,
            "frames_forwarded": self.frames_forwarded,
            "decode_errors": self.decode_errors,
            "reconnects": self.reconnects,
            "seconds_since_last_frame": round(time.monotonic() - self.last_frame_at, 1) if self.last_frame_at else None,
            "dashboard_url": f"{self.public_base_url}/?session_id={self.session_id}" if self.session_id else None,
        }

    def _ensure_session(self) -> str:
        if self.session_id is not None and self.session_id in self.store.sessions:
            return self.session_id
        created = self.store.create_session(public_base_url=self.public_base_url)
        self.session_id = created.session_id
        return self.session_id

    def _forward(self, pil_image) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        session_id = self._ensure_session()
        buffer = io.BytesIO()
        pil_image.save(buffer, format="JPEG", quality=85)
        jpg_bytes = buffer.getvalue()
        future = asyncio.run_coroutine_threadsafe(
            self.store.process_jpg_frame(session_id, jpg_bytes),
            loop,
        )
        try:
            future.result(timeout=5)
            self.frames_forwarded += 1
            self.last_frame_at = time.monotonic()
        except Exception:
            self.decode_errors += 1

    def _run(self) -> None:
        try:
            import av
        except ImportError:
            print("[udp_stream] PyAV 未安装，UDP 视频流接收不可用。运行: pip install av")
            return

        url = _udp_input_url(self.host, self.port)
        print(f"[udp_stream] 监听眼镜视频流 {url}")
        while not self._stop_event.is_set():
            container = None
            try:
                container = av.open(
                    url,
                    mode="r",
                    format="mpegts",
                    options={
                        "fflags": "nobuffer",
                        "flags": "low_delay",
                        "probesize": "65536",
                        "analyzeduration": "1000000",
                    },
                    timeout=(2.0, 1.0),
                )
                streams = [s for s in container.streams if s.type == "video"]
                if not streams:
                    raise RuntimeError("MPEG-TS 中没有视频流")
                stream = streams[0]
                stream.thread_type = "AUTO"
                last_forward = 0.0
                for packet in container.demux(stream):
                    if self._stop_event.is_set():
                        return
                    if packet.size <= 0:
                        continue
                    try:
                        frames = packet.decode()
                    except Exception:
                        self.decode_errors += 1
                        continue
                    for frame in frames:
                        now = time.monotonic()
                        if now - last_forward < FORWARD_INTERVAL_S:
                            continue
                        last_forward = now
                        try:
                            self._forward(frame.to_image())
                        except Exception:
                            self.decode_errors += 1
            except Exception as exc:
                if not _is_idle_error(exc):
                    self.reconnects += 1
                    print(f"[udp_stream] 流中断，0.5s 后重连: {exc}")
                time.sleep(0.5)
            finally:
                if container is not None:
                    try:
                        container.close()
                    except Exception:
                        pass
