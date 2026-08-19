from __future__ import annotations

import argparse
import base64
import io
import json
import mimetypes
import socket
import sys
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Iterable, Protocol
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
STATIC_ROOT = ROOT / "static"
WORKSPACE_ROOT = ROOT.parents[1]
HEALTH_APP_ROOT = (
    WORKSPACE_ROOT / "apps" / "user-web"
)
MAX_FRAME_BYTES = 8 * 1024 * 1024
DEFAULT_UDP_HOST = "0.0.0.0"
DEFAULT_UDP_PORT = 5000
DEFAULT_STREAM_STALE_SECONDS = 3.0
DEFAULT_RECOGNITION_FPS = 1.5
DEFAULT_RECOGNITION_RUNTIME_THREADS = 2


_RECOGNITION_RUNTIME_LOCK = threading.Lock()
_RECOGNITION_RUNTIME_CONFIGURED = False


def configure_recognition_runtime() -> None:
    """Keep OpenCV inference from starving video decode and HTTP threads.

    The local OpenCV wheel defaults to one worker per logical CPU (32 on the
    development machine). A single analysis then monopolizes the host enough
    for `/api/status` to time out while the 30 FPS stream is active. Two OpenCV
    workers were both faster for this workload and leave the receiver
    responsive.
    """

    global _RECOGNITION_RUNTIME_CONFIGURED
    if _RECOGNITION_RUNTIME_CONFIGURED:
        return
    with _RECOGNITION_RUNTIME_LOCK:
        if _RECOGNITION_RUNTIME_CONFIGURED:
            return
        try:
            import cv2

            cv2.setNumThreads(DEFAULT_RECOGNITION_RUNTIME_THREADS)
        except (ImportError, AttributeError):
            pass
        _RECOGNITION_RUNTIME_CONFIGURED = True


def analyze_jpeg(jpeg: bytes) -> dict[str, object]:
    """Run the shared recognizer lazily so camera-only mode stays lightweight."""
    configure_recognition_runtime()
    health_root = str(HEALTH_APP_ROOT)
    if health_root not in sys.path:
        sys.path.insert(0, health_root)
    try:
        from recognition_adapter import RecognitionUnavailable, analyze_image
    except ImportError as exc:
        raise RuntimeError("无法加载健康应用识别适配层") from exc

    data_url = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")
    try:
        return analyze_image(data_url)
    except RecognitionUnavailable as exc:
        raise RuntimeError(str(exc)) from exc


@dataclass
class FrameMetadata:
    sequence: int = 0
    source_sequence: int = 0
    received_at_ms: int = 0
    device_name: str = ""
    client_ip: str = ""
    content_type: str = "image/jpeg"
    source: str = "none"
    size_bytes: int = 0
    width: int = 0
    height: int = 0


@dataclass(frozen=True)
class FrameSnapshot:
    jpeg: bytes
    metadata: FrameMetadata


class FrameStore:
    """A one-slot latest-frame center.

    Producers always replace the previous frame. There is intentionally no
    frame queue, so a slow browser or recognizer cannot create unbounded memory
    growth when the input stream runs at 30 FPS or faster.
    """

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._jpeg: bytes | None = None
        self._metadata = FrameMetadata()
        self._total_frames = 0
        self._replaced_frames = 0

    def put(
        self,
        jpeg: bytes,
        *,
        device_name: str,
        client_ip: str,
        width: int,
        height: int,
        source: str = "http_jpeg",
        source_sequence: int = 0,
        received_at_ms: int | None = None,
    ) -> FrameMetadata:
        with self._condition:
            if self._jpeg is not None:
                self._replaced_frames += 1
            sequence = self._metadata.sequence + 1
            self._jpeg = jpeg
            self._total_frames += 1
            self._metadata = FrameMetadata(
                sequence=sequence,
                source_sequence=max(0, source_sequence),
                received_at_ms=received_at_ms or int(time.time() * 1000),
                device_name=device_name[:100] or "unknown-device",
                client_ip=client_ip,
                source=source,
                size_bytes=len(jpeg),
                width=max(0, width),
                height=max(0, height),
            )
            metadata = FrameMetadata(**asdict(self._metadata))
            self._condition.notify_all()
            return metadata

    def get(self) -> tuple[bytes | None, FrameMetadata]:
        with self._condition:
            jpeg = self._jpeg
            metadata = FrameMetadata(**asdict(self._metadata))
        return jpeg, metadata

    def snapshot(self) -> FrameSnapshot | None:
        jpeg, metadata = self.get()
        if jpeg is None:
            return None
        return FrameSnapshot(jpeg=jpeg, metadata=metadata)

    def wait_for_new(self, after_sequence: int, timeout: float) -> FrameSnapshot | None:
        deadline = time.monotonic() + max(0.0, timeout)
        with self._condition:
            while self._jpeg is None or self._metadata.sequence <= after_sequence:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)
            return FrameSnapshot(
                jpeg=self._jpeg,
                metadata=FrameMetadata(**asdict(self._metadata)),
            )

    def stats(self) -> dict[str, int]:
        with self._condition:
            return {
                "capacity": 1,
                "totalFrames": self._total_frames,
                "replacedFrames": self._replaced_frames,
                "queuedFrames": 1 if self._jpeg is not None else 0,
            }


@dataclass
class DecodedFrameMetadata:
    sequence: int = 0
    received_at_ms: int = 0
    width: int = 0
    height: int = 0


@dataclass(frozen=True)
class DecodedFrameSnapshot:
    video_frame: object
    metadata: DecodedFrameMetadata


class LatestVideoFrameStore:
    """One-slot center for decoded frames before any JPEG conversion."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._video_frame: object | None = None
        self._metadata = DecodedFrameMetadata()
        self._total_frames = 0
        self._replaced_frames = 0

    def put(self, video_frame: object, *, width: int, height: int) -> DecodedFrameMetadata:
        with self._condition:
            if self._video_frame is not None:
                self._replaced_frames += 1
            sequence = self._metadata.sequence + 1
            self._video_frame = video_frame
            self._total_frames += 1
            self._metadata = DecodedFrameMetadata(
                sequence=sequence,
                received_at_ms=int(time.time() * 1000),
                width=max(0, width),
                height=max(0, height),
            )
            metadata = DecodedFrameMetadata(**asdict(self._metadata))
            self._condition.notify_all()
            return metadata

    def snapshot(self) -> DecodedFrameSnapshot | None:
        with self._condition:
            if self._video_frame is None:
                return None
            return DecodedFrameSnapshot(
                video_frame=self._video_frame,
                metadata=DecodedFrameMetadata(**asdict(self._metadata)),
            )

    def wait_for_new(
        self,
        after_sequence: int,
        timeout: float,
    ) -> DecodedFrameSnapshot | None:
        deadline = time.monotonic() + max(0.0, timeout)
        with self._condition:
            while (
                self._video_frame is None
                or self._metadata.sequence <= after_sequence
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)
            return DecodedFrameSnapshot(
                video_frame=self._video_frame,
                metadata=DecodedFrameMetadata(**asdict(self._metadata)),
            )

    def stats(self) -> dict[str, int]:
        with self._condition:
            return {
                "capacity": 1,
                "totalFrames": self._total_frames,
                "replacedFrames": self._replaced_frames,
                "queuedFrames": 1 if self._video_frame is not None else 0,
                "latestSequence": self._metadata.sequence,
            }


class RollingRate:
    """Thread-safe event rate over a recent monotonic-time window."""

    def __init__(
        self,
        window_seconds: float = 2.0,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.window_seconds = window_seconds
        self._clock = clock
        self._events: deque[float] = deque()
        self._lock = threading.Lock()

    def mark(self, *, at: float | None = None) -> None:
        timestamp = self._clock() if at is None else at
        with self._lock:
            self._events.append(timestamp)
            self._prune(timestamp)

    def rate(self, *, now: float | None = None) -> float:
        timestamp = self._clock() if now is None else now
        with self._lock:
            self._prune(timestamp)
            if len(self._events) < 2:
                return 0.0
            elapsed = max(timestamp, self._events[-1]) - self._events[0]
            if elapsed <= 0:
                return 0.0
            return (len(self._events) - 1) / elapsed

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._events and self._events[0] < cutoff:
            self._events.popleft()


class StreamMetrics:
    def __init__(
        self,
        *,
        rate_window_seconds: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._clock = clock
        self._receive_rate = RollingRate(rate_window_seconds, clock=clock)
        self._decode_rate = RollingRate(rate_window_seconds, clock=clock)
        self._lock = threading.Lock()
        self._decoder_running = False
        self._dependency_available: bool | None = None
        self._received_packets = 0
        self._decoded_frames = 0
        self._decode_errors = 0
        self._reconnects = 0
        self._idle_timeouts = 0
        self._last_receive_monotonic: float | None = None
        self._last_decode_monotonic: float | None = None
        self._last_receive_at_ms: int | None = None
        self._last_decode_at_ms: int | None = None
        self._last_error: str | None = None

    def set_running(self, running: bool) -> None:
        with self._lock:
            self._decoder_running = running

    def set_dependency_available(self, available: bool) -> None:
        with self._lock:
            self._dependency_available = available

    def mark_receive(self) -> None:
        now = self._clock()
        self._receive_rate.mark(at=now)
        with self._lock:
            self._received_packets += 1
            self._last_receive_monotonic = now
            self._last_receive_at_ms = int(time.time() * 1000)

    def mark_decode(self) -> None:
        now = self._clock()
        self._decode_rate.mark(at=now)
        with self._lock:
            self._decoded_frames += 1
            self._last_decode_monotonic = now
            self._last_decode_at_ms = int(time.time() * 1000)
            self._last_error = None

    def mark_error(self, error: BaseException | str, *, decode_error: bool = False) -> None:
        with self._lock:
            if decode_error:
                self._decode_errors += 1
            self._last_error = str(error)

    def mark_reconnect(self) -> None:
        with self._lock:
            self._reconnects += 1

    def mark_idle_timeout(self) -> None:
        """Record an empty UDP listen interval without calling it a failure."""
        with self._lock:
            self._idle_timeouts += 1

    def snapshot(self, *, stale_after_seconds: float) -> dict[str, object]:
        now = self._clock()
        receive_fps = self._receive_rate.rate(now=now)
        decode_fps = self._decode_rate.rate(now=now)
        with self._lock:
            connected = (
                self._decoder_running
                and self._last_decode_monotonic is not None
                and now - self._last_decode_monotonic <= stale_after_seconds
            )
            return {
                "streamConnected": connected,
                "decoderRunning": self._decoder_running,
                "dependencyAvailable": self._dependency_available,
                "inputFps": round(decode_fps, 2),
                "receiveFps": round(receive_fps, 2),
                "decodeFps": round(decode_fps, 2),
                "receivedPackets": self._received_packets,
                "decodedFrames": self._decoded_frames,
                "decodeErrors": self._decode_errors,
                "reconnects": self._reconnects,
                "idleTimeouts": self._idle_timeouts,
                "lastReceiveAtMs": self._last_receive_at_ms,
                "lastDecodeAtMs": self._last_decode_at_ms,
                "lastError": self._last_error,
            }


@dataclass(frozen=True)
class ReaderEvent:
    kind: str
    video_frame: object | None = None
    width: int = 0
    height: int = 0
    message: str = ""

    @classmethod
    def packet(cls) -> "ReaderEvent":
        return cls(kind="packet")

    @classmethod
    def frame(cls, video_frame: object, width: int, height: int) -> "ReaderEvent":
        return cls(
            kind="frame",
            video_frame=video_frame,
            width=width,
            height=height,
        )

    @classmethod
    def decode_error(cls, message: str) -> "ReaderEvent":
        return cls(kind="decode_error", message=message)


class VideoReader(Protocol):
    def events(self, stop_event: threading.Event) -> Iterable[ReaderEvent]:
        ...

    def close(self) -> None:
        ...


class VideoDependencyError(RuntimeError):
    pass


def is_transient_udp_wait_error(error: BaseException) -> bool:
    """Return whether PyAV/FFmpeg is only reporting an empty UDP read window.

    On Windows, FFmpeg reports an idle UDP input as EIO (errno 5) instead of a
    conventional timeout. Treating that as a reconnect made a quiet receiver
    look broken and caused the reconnect counter to climb forever before the
    glasses had even started streaming.
    """

    errno_value = getattr(error, "errno", None)
    if errno_value in {5, 11, 60, 110, 10035, 10060}:
        return True
    name = type(error).__name__.lower()
    message = str(error).lower()
    return (
        "timeout" in name
        or "timed out" in message
        or "temporarily unavailable" in message
    )


class PyAvMpegTsReader:
    """Decode an H.264 MPEG-TS UDP input without doing preview work."""

    def __init__(self, url: str) -> None:
        self.url = url
        self._lock = threading.Lock()
        self._container: object | None = None

    @staticmethod
    def _load_dependencies() -> object:
        try:
            import av
        except ImportError as exc:
            raise VideoDependencyError(
                "UDP 视频解码依赖缺失。请运行 "
                "python -m pip install -r tools/camera-link/requirements.txt"
            ) from exc
        return av

    def events(self, stop_event: threading.Event) -> Iterable[ReaderEvent]:
        av = self._load_dependencies()
        options = {
            "fflags": "nobuffer",
            "flags": "low_delay",
            "probesize": "65536",
            "analyzeduration": "1000000",
        }
        container = av.open(
            self.url,
            mode="r",
            format="mpegts",
            options=options,
            timeout=(2.0, 1.0),
        )
        with self._lock:
            self._container = container
        if stop_event.is_set():
            self.close()
            return
        try:
            video_streams = [stream for stream in container.streams if stream.type == "video"]
            if not video_streams:
                raise RuntimeError("MPEG-TS 中没有视频流")
            stream = video_streams[0]
            stream.thread_type = "AUTO"
            for packet in container.demux(stream):
                if stop_event.is_set():
                    return
                if packet.size <= 0:
                    continue
                yield ReaderEvent.packet()
                try:
                    decoded_frames = packet.decode()
                except Exception as exc:
                    yield ReaderEvent.decode_error(f"H.264 解码帧失败：{exc}")
                    continue
                for frame in decoded_frames:
                    if stop_event.is_set():
                        return
                    yield ReaderEvent.frame(frame, frame.width, frame.height)
        finally:
            should_close = False
            with self._lock:
                if self._container is container:
                    self._container = None
                    should_close = True
            if should_close:
                self._safe_close(container)

    @staticmethod
    def _safe_close(container: object) -> None:
        try:
            container.close()
        except Exception:
            pass

    def close(self) -> None:
        with self._lock:
            container = self._container
            self._container = None
        if container is not None:
            self._safe_close(container)


def udp_input_url(host: str, port: int) -> str:
    return (
        f"udp://{host}:{port}"
        "?fifo_size=65536&overrun_nonfatal=1&reuse=1&timeout=1000000"
    )


class VideoStreamReceiver:
    def __init__(
        self,
        frame_store: LatestVideoFrameStore,
        *,
        host: str = DEFAULT_UDP_HOST,
        port: int = DEFAULT_UDP_PORT,
        stale_after_seconds: float = DEFAULT_STREAM_STALE_SECONDS,
        reconnect_delay_seconds: float = 0.5,
        max_idle_retry_delay_seconds: float = 2.0,
        reader_factory: Callable[[str], VideoReader] | None = None,
        metrics: StreamMetrics | None = None,
    ) -> None:
        self.frame_store = frame_store
        self.host = host
        self.port = port
        self.stale_after_seconds = stale_after_seconds
        self.reconnect_delay_seconds = max(0.01, reconnect_delay_seconds)
        self.max_idle_retry_delay_seconds = max(
            self.reconnect_delay_seconds,
            max_idle_retry_delay_seconds,
        )
        self.url = udp_input_url(host, port)
        self.metrics = metrics or StreamMetrics()
        self._reader_factory = reader_factory or PyAvMpegTsReader
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._reader_lock = threading.Lock()
        self._active_reader: VideoReader | None = None
        self._source_sequence = 0

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="rokid-udp-video",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop_event.set()
        with self._reader_lock:
            reader = self._active_reader
        if reader is not None:
            reader.close()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)
            if not thread.is_alive():
                self._thread = None

    @property
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def status(self) -> dict[str, object]:
        payload = self.metrics.snapshot(stale_after_seconds=self.stale_after_seconds)
        payload.update(
            {
                "source": "udp_video",
                "listenHost": self.host,
                "listenPort": self.port,
                "inputUrl": self.url,
                **self.frame_store.stats(),
            }
        )
        return payload

    def _run(self) -> None:
        self.metrics.set_running(True)
        consecutive_idle_attempts = 0
        try:
            while not self._stop_event.is_set():
                reader: VideoReader | None = None
                session_had_input = False
                try:
                    reader = self._reader_factory(self.url)
                    with self._reader_lock:
                        self._active_reader = reader
                    self.metrics.set_dependency_available(True)
                    for event in reader.events(self._stop_event):
                        if self._stop_event.is_set():
                            break
                        if event.kind == "packet":
                            session_had_input = True
                            consecutive_idle_attempts = 0
                            self.metrics.mark_receive()
                        elif event.kind == "decode_error":
                            self.metrics.mark_error(event.message, decode_error=True)
                        elif event.kind == "frame" and event.video_frame is not None:
                            session_had_input = True
                            consecutive_idle_attempts = 0
                            self._source_sequence += 1
                            self.metrics.mark_decode()
                            self.frame_store.put(
                                event.video_frame,
                                width=event.width,
                                height=event.height,
                            )
                    if not self._stop_event.is_set():
                        if session_had_input:
                            raise RuntimeError("UDP 视频输入已结束")
                        self.metrics.mark_idle_timeout()
                except VideoDependencyError as exc:
                    self.metrics.set_dependency_available(False)
                    self.metrics.mark_error(exc)
                    return
                except Exception as exc:
                    if not self._stop_event.is_set():
                        if session_had_input:
                            self.metrics.mark_error(exc)
                            self.metrics.mark_reconnect()
                        elif is_transient_udp_wait_error(exc):
                            self.metrics.mark_idle_timeout()
                        else:
                            self.metrics.mark_error(exc)
                finally:
                    if reader is not None:
                        reader.close()
                        with self._reader_lock:
                            if self._active_reader is reader:
                                self._active_reader = None
                if self._stop_event.is_set():
                    break
                if session_had_input:
                    consecutive_idle_attempts = 0
                    retry_delay = self.reconnect_delay_seconds
                else:
                    consecutive_idle_attempts += 1
                    retry_delay = min(
                        self.max_idle_retry_delay_seconds,
                        self.reconnect_delay_seconds
                        * (2 ** min(consecutive_idle_attempts - 1, 8)),
                    )
                if self._stop_event.wait(retry_delay):
                    break
        finally:
            self.metrics.set_running(False)


def encode_video_frame_to_jpeg(video_frame: object, *, quality: int = 82) -> bytes:
    try:
        import PIL  # noqa: F401 - PyAV VideoFrame.to_image() needs Pillow.
    except ImportError as exc:
        raise VideoDependencyError(
            "预览 JPEG 编码依赖 Pillow 缺失。请运行 "
            "python -m pip install -r tools/camera-link/requirements.txt"
        ) from exc
    output = io.BytesIO()
    to_image = getattr(video_frame, "to_image", None)
    if not callable(to_image):
        raise TypeError("解码帧不支持 to_image()")
    to_image().save(
        output,
        format="JPEG",
        quality=min(95, max(35, quality)),
        optimize=False,
    )
    return output.getvalue()


class PreviewWorker:
    """Convert only the latest decoded frame to JPEG at a bounded rate."""

    def __init__(
        self,
        input_store: LatestVideoFrameStore,
        output_store: FrameStore,
        *,
        target_fps: float = 10.0,
        jpeg_quality: int = 82,
        encoder: Callable[[object], bytes] | None = None,
    ) -> None:
        self.input_store = input_store
        self.output_store = output_store
        self.target_fps = max(0.0, target_fps)
        self.jpeg_quality = jpeg_quality
        self._encoder = encoder or (
            lambda frame: encode_video_frame_to_jpeg(
                frame,
                quality=self.jpeg_quality,
            )
        )
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._rate = RollingRate(2.0)
        self._lock = threading.Lock()
        self._running = False
        self._busy = False
        self._encoded_frames = 0
        self._skipped_frames = 0
        self._encode_errors = 0
        self._last_sequence = 0
        self._last_duration_ms: int | None = None
        self._last_error: str | None = None

    def start(self) -> None:
        if self.target_fps <= 0:
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="rokid-latest-frame-preview",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)

    def status(self) -> dict[str, object]:
        with self._lock:
            return {
                "enabled": self.target_fps > 0,
                "running": self._running,
                "busy": self._busy,
                "targetFps": self.target_fps,
                "outputFps": round(self._rate.rate(), 2),
                "maxConcurrency": 1,
                "queueCapacity": 0,
                "encodedFrames": self._encoded_frames,
                "skippedFrames": self._skipped_frames,
                "encodeErrors": self._encode_errors,
                "lastSequence": self._last_sequence,
                "lastDurationMs": self._last_duration_ms,
                "lastError": self._last_error,
            }

    def _run(self) -> None:
        interval = 1.0 / self.target_fps
        next_due = 0.0
        last_sequence = 0
        with self._lock:
            self._running = True
        try:
            while not self._stop_event.is_set():
                wait_seconds = next_due - time.monotonic()
                if wait_seconds > 0:
                    if self._stop_event.wait(min(wait_seconds, 0.5)):
                        return
                    continue

                snapshot = self.input_store.snapshot()
                if snapshot is None or snapshot.metadata.sequence == last_sequence:
                    snapshot = self.input_store.wait_for_new(last_sequence, 0.5)
                    if snapshot is None:
                        continue

                sequence = snapshot.metadata.sequence
                with self._lock:
                    if last_sequence:
                        self._skipped_frames += max(0, sequence - last_sequence - 1)
                    self._busy = True
                started = time.monotonic()
                try:
                    jpeg = self._encoder(snapshot.video_frame)
                    if not is_jpeg(jpeg):
                        raise ValueError("预览编码器未返回有效 JPEG")
                    self.output_store.put(
                        jpeg,
                        device_name="Rokid RV101",
                        client_ip="UDP MPEG-TS",
                        width=snapshot.metadata.width,
                        height=snapshot.metadata.height,
                        source="udp_video",
                        source_sequence=sequence,
                        received_at_ms=snapshot.metadata.received_at_ms,
                    )
                    self._rate.mark()
                    error = None
                except Exception as exc:
                    error = str(exc)
                duration_ms = int((time.monotonic() - started) * 1000)
                last_sequence = sequence
                with self._lock:
                    self._busy = False
                    self._last_sequence = sequence
                    self._last_duration_ms = duration_ms
                    self._last_error = error
                    if error is None:
                        self._encoded_frames += 1
                    else:
                        self._encode_errors += 1
                next_due = started + interval
        finally:
            with self._lock:
                self._busy = False
                self._running = False


class RecognitionWorker:
    """Analyze only the newest frame at a bounded rate on one worker thread."""

    def __init__(
        self,
        frame_store: FrameStore,
        *,
        target_fps: float = DEFAULT_RECOGNITION_FPS,
        analyzer: Callable[[bytes], dict[str, object]] = analyze_jpeg,
    ) -> None:
        self.frame_store = frame_store
        self.target_fps = max(0.0, target_fps)
        self._analyzer = analyzer
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._rate = RollingRate(5.0)
        self._lock = threading.Lock()
        self._running = False
        self._busy = False
        self._analyzed_frames = 0
        self._skipped_frames = 0
        self._last_sequence = 0
        self._last_duration_ms: int | None = None
        self._last_analyzed_at_ms: int | None = None
        self._last_error: str | None = None
        self._latest_result: dict[str, object] | None = None
        self._latest_result_sequence = 0
        self._latest_result_at_ms: int | None = None

    def start(self) -> None:
        if self.target_fps <= 0:
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="rokid-latest-frame-recognition",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)

    def status(self) -> dict[str, object]:
        with self._lock:
            return {
                "enabled": self.target_fps > 0,
                "running": self._running,
                "busy": self._busy,
                "targetFps": self.target_fps,
                "analysisFps": round(self._rate.rate(), 2),
                "maxConcurrency": 1,
                "queueCapacity": 0,
                "analyzedFrames": self._analyzed_frames,
                "skippedFrames": self._skipped_frames,
                "lastSequence": self._last_sequence,
                "lastDurationMs": self._last_duration_ms,
                "lastAnalyzedAtMs": self._last_analyzed_at_ms,
                "lastError": self._last_error,
                "hasAnalysis": self._latest_result is not None,
                "latestAnalysisSequence": self._latest_result_sequence,
                "latestAnalysisAtMs": self._latest_result_at_ms,
            }

    def latest_analysis(self) -> dict[str, object]:
        now_ms = int(time.time() * 1000)
        with self._lock:
            analyzed_at_ms = self._latest_result_at_ms
            return {
                "ok": True,
                "has_analysis": self._latest_result is not None,
                "frame_sequence": self._latest_result_sequence,
                "analyzed_at_ms": analyzed_at_ms,
                "age_ms": (
                    max(0, now_ms - analyzed_at_ms)
                    if analyzed_at_ms is not None
                    else None
                ),
                "analysis": self._latest_result,
            }

    def _run(self) -> None:
        interval = 1.0 / self.target_fps
        next_due = 0.0
        with self._lock:
            self._running = True
        try:
            while not self._stop_event.is_set():
                wait_seconds = next_due - time.monotonic()
                if wait_seconds > 0:
                    if self._stop_event.wait(min(wait_seconds, 0.5)):
                        return
                    continue

                snapshot = self.frame_store.snapshot()
                if snapshot is None or snapshot.metadata.sequence == self._last_sequence:
                    snapshot = self.frame_store.wait_for_new(self._last_sequence, 0.5)
                    if snapshot is None:
                        continue

                sequence = snapshot.metadata.sequence
                with self._lock:
                    if self._last_sequence:
                        self._skipped_frames += max(0, sequence - self._last_sequence - 1)
                    self._busy = True
                started = time.monotonic()
                try:
                    result = self._analyzer(snapshot.jpeg)
                    error = None
                except Exception as exc:
                    result = None
                    error = str(exc)
                duration_ms = int((time.monotonic() - started) * 1000)
                self._rate.mark()
                with self._lock:
                    self._busy = False
                    self._analyzed_frames += 1
                    self._last_sequence = sequence
                    self._last_duration_ms = duration_ms
                    self._last_analyzed_at_ms = int(time.time() * 1000)
                    self._last_error = error
                    if result is not None:
                        self._latest_result = result
                        self._latest_result_sequence = sequence
                        self._latest_result_at_ms = self._last_analyzed_at_ms
                # Analysis is CPU-heavy and may spend long stretches in native
                # OpenCV code. Keep a full sampling interval after completion
                # so HTTP/status and video-decode threads always get breathing
                # room even when one inference is slower than the target rate.
                next_due = time.monotonic() + interval
                if error and self._stop_event.wait(max(0.0, min(5.0, next_due - time.monotonic()))):
                    return
        finally:
            with self._lock:
                self._busy = False
                self._running = False


FRAME_STORE = FrameStore()
VIDEO_FRAME_STORE = LatestVideoFrameStore()
VIDEO_RECEIVER: VideoStreamReceiver | None = None
PREVIEW_WORKER: PreviewWorker | None = None
RECOGNITION_WORKER: RecognitionWorker | None = None
CONFIGURED_UDP_HOST = DEFAULT_UDP_HOST
CONFIGURED_UDP_PORT = DEFAULT_UDP_PORT


def json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def parse_positive_int(value: str | None) -> int:
    try:
        return max(0, int(value or "0"))
    except ValueError:
        return 0


def decode_frame_body(content_type: str, body: bytes) -> tuple[bytes, dict[str, object]]:
    if content_type.startswith("application/json"):
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("JSON 请求体无法解析") from exc
        if not isinstance(payload, dict):
            raise ValueError("JSON 请求体必须是对象")
        image = payload.get("image")
        if not isinstance(image, str) or not image:
            raise ValueError("JSON 中缺少 image")
        encoded = image.split(",", 1)[1] if "," in image else image
        try:
            jpeg = base64.b64decode(encoded, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise ValueError("image 不是有效的 Base64") from exc
        return jpeg, payload
    return body, {}


def is_jpeg(data: bytes) -> bool:
    return len(data) >= 4 and data[:2] == b"\xff\xd8" and data[-2:] == b"\xff\xd9"


def current_status() -> dict[str, object]:
    jpeg, metadata = FRAME_STORE.get()
    now_ms = int(time.time() * 1000)
    if VIDEO_RECEIVER is not None:
        stream = VIDEO_RECEIVER.status()
    else:
        stream = {
            "source": metadata.source if jpeg is not None else "udp_video",
            "streamConnected": False,
            "decoderRunning": False,
            "dependencyAvailable": None,
            "inputFps": 0.0,
            "receiveFps": 0.0,
            "decodeFps": 0.0,
            "receivedPackets": 0,
            "decodedFrames": 0,
            "decodeErrors": 0,
            "reconnects": 0,
            "idleTimeouts": 0,
            "lastReceiveAtMs": None,
            "lastDecodeAtMs": None,
            "lastError": None,
            "listenHost": CONFIGURED_UDP_HOST,
            "listenPort": CONFIGURED_UDP_PORT,
            "inputUrl": udp_input_url(CONFIGURED_UDP_HOST, CONFIGURED_UDP_PORT),
            **VIDEO_FRAME_STORE.stats(),
        }
    preview = (
        PREVIEW_WORKER.status()
        if PREVIEW_WORKER is not None
        else {
            "enabled": False,
            "running": False,
            "busy": False,
            "targetFps": 0.0,
            "outputFps": 0.0,
            "maxConcurrency": 1,
            "queueCapacity": 0,
            "encodedFrames": 0,
            "skippedFrames": 0,
            "encodeErrors": 0,
            "lastSequence": 0,
            "lastDurationMs": None,
            "lastError": None,
        }
    )
    preview_buffer = FRAME_STORE.stats()
    stream["preview"] = preview
    stream["previewFps"] = preview["outputFps"]
    stream["previewReplacedFrames"] = preview_buffer["replacedFrames"]
    recognition = (
        RECOGNITION_WORKER.status()
        if RECOGNITION_WORKER is not None
        else {
            "enabled": False,
            "running": False,
            "busy": False,
            "targetFps": 0.0,
            "analysisFps": 0.0,
            "maxConcurrency": 1,
            "queueCapacity": 0,
            "analyzedFrames": 0,
            "skippedFrames": 0,
            "lastSequence": 0,
            "lastDurationMs": None,
            "lastAnalyzedAtMs": None,
            "lastError": None,
            "hasAnalysis": False,
            "latestAnalysisSequence": 0,
            "latestAnalysisAtMs": None,
        }
    )
    return {
        "ok": True,
        "has_frame": jpeg is not None,
        "source": stream["source"],
        "streamConnected": stream["streamConnected"],
        "inputFps": stream["inputFps"],
        "receiveFps": stream["receiveFps"],
        "decodeFps": stream["decodeFps"],
        "frame": asdict(metadata),
        "age_ms": (
            max(0, now_ms - metadata.received_at_ms)
            if metadata.received_at_ms
            else None
        ),
        "stream": stream,
        "preview": preview,
        "recognition": recognition,
    }


def latest_analysis_payload() -> dict[str, object]:
    if RECOGNITION_WORKER is None:
        return {
            "ok": True,
            "has_analysis": False,
            "frame_sequence": 0,
            "analyzed_at_ms": None,
            "age_ms": None,
            "analysis": None,
        }
    return RECOGNITION_WORKER.latest_analysis()


class DemoHandler(BaseHTTPRequestHandler):
    server_version = "RokidCameraDemo/2.0"

    def log_message(self, format: str, *args: object) -> None:
        print(f"[{self.log_date_time_string()}] {self.client_address[0]} {format % args}")

    def _send_bytes(
        self,
        status: HTTPStatus | int,
        body: bytes,
        content_type: str,
        *,
        cache_control: str = "no-store",
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache_control)
        self.send_header("Access-Control-Allow-Origin", "*")
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_json(self, status: HTTPStatus | int, payload: object) -> None:
        self._send_bytes(status, json_bytes(payload), "application/json; charset=utf-8")

    def _read_body(self) -> bytes:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise ValueError("缺少 Content-Length")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValueError("Content-Length 无效") from exc
        if length <= 0:
            raise ValueError("请求体为空")
        if length > MAX_FRAME_BYTES:
            raise OverflowError(f"图片超过 {MAX_FRAME_BYTES // (1024 * 1024)}MB 限制")
        return self.rfile.read(length)

    def _serve_static(self, relative_path: str) -> None:
        allowed = {
            "viewer.html",
            "capture.html",
            "styles.css",
            "viewer.js",
            "capture.js",
        }
        if relative_path not in allowed:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        file_path = STATIC_ROOT / relative_path
        if not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type == "application/javascript":
            content_type += "; charset=utf-8"
        self._send_bytes(
            HTTPStatus.OK,
            file_path.read_bytes(),
            content_type,
            cache_control="no-cache",
        )

    def _serve_mjpeg(self) -> None:
        boundary = "rokid-frame"
        self.send_response(HTTPStatus.OK)
        self.send_header(
            "Content-Type",
            f"multipart/x-mixed-replace; boundary={boundary}",
        )
        self.send_header("Cache-Control", "no-store")
        self.send_header("Pragma", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        if self.command == "HEAD":
            return

        sequence = 0
        try:
            while True:
                snapshot = FRAME_STORE.wait_for_new(sequence, timeout=15.0)
                if snapshot is None:
                    continue
                sequence = snapshot.metadata.sequence
                header = (
                    f"--{boundary}\r\n"
                    "Content-Type: image/jpeg\r\n"
                    f"Content-Length: {len(snapshot.jpeg)}\r\n"
                    f"X-Frame-Sequence: {sequence}\r\n\r\n"
                ).encode("ascii")
                self.wfile.write(header)
                self.wfile.write(snapshot.jpeg)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
            return

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, X-Device-Name, X-Frame-Width, X-Frame-Height",
        )
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/viewer.html")
            self.end_headers()
            return
        if path == "/api/health":
            status = current_status()
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "service": "rokid-camera-link-demo",
                    "source": status["source"],
                    "streamConnected": status["streamConnected"],
                },
            )
            return
        if path == "/api/config":
            lan_ip = guess_lan_ip()
            http_port = self.server.server_port
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "source": "udp_video",
                    "lan_ip": lan_ip,
                    "port": http_port,
                    "udp_host": CONFIGURED_UDP_HOST,
                    "udp_port": CONFIGURED_UDP_PORT,
                    "stream_url": f"udp://{lan_ip}:{CONFIGURED_UDP_PORT}",
                    "preview_url": f"http://{lan_ip}:{http_port}/api/stream.mjpg",
                    "capture_url": f"http://{lan_ip}:{http_port}/capture.html",
                    "upload_url": f"http://{lan_ip}:{http_port}/api/frame",
                },
            )
            return
        if path == "/api/status":
            self._send_json(HTTPStatus.OK, current_status())
            return
        if path == "/api/analysis/latest":
            self._send_json(HTTPStatus.OK, latest_analysis_payload())
            return
        if path == "/api/frame.jpg":
            jpeg, metadata = FRAME_STORE.get()
            if jpeg is None:
                self._send_json(
                    HTTPStatus.NOT_FOUND,
                    {"ok": False, "error": "尚未收到视频帧"},
                )
                return
            self._send_bytes(
                HTTPStatus.OK,
                jpeg,
                "image/jpeg",
                extra_headers={
                    "X-Frame-Sequence": str(metadata.sequence),
                    "X-Received-At-Ms": str(metadata.received_at_ms),
                    "X-Frame-Source": metadata.source,
                },
            )
            return
        if path == "/api/stream.mjpg":
            self._serve_mjpeg()
            return
        relative_path = path.removeprefix("/")
        self._serve_static(relative_path)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path not in {"/api/frame", "/api/analyze"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            body = self._read_body()
            content_type = self.headers.get("Content-Type", "application/octet-stream")
            jpeg, payload = decode_frame_body(content_type, body)
            if len(jpeg) > MAX_FRAME_BYTES:
                raise OverflowError(
                    f"解码后图片超过 {MAX_FRAME_BYTES // (1024 * 1024)}MB 限制"
                )
            if not is_jpeg(jpeg):
                raise ValueError("请求体不是有效的 JPEG 图片")
            device_name = str(
                payload.get("device_name")
                or self.headers.get("X-Device-Name")
                or "unknown-device"
            )
            width = parse_positive_int(
                str(payload.get("width") or self.headers.get("X-Frame-Width") or "0")
            )
            height = parse_positive_int(
                str(payload.get("height") or self.headers.get("X-Frame-Height") or "0")
            )
            metadata = FRAME_STORE.put(
                jpeg,
                device_name=device_name,
                client_ip=self.client_address[0],
                width=width,
                height=height,
                source="http_jpeg",
            )
            if path == "/api/analyze":
                analysis = analyze_jpeg(jpeg)
                self._send_json(
                    HTTPStatus.OK,
                    {"ok": True, "frame": asdict(metadata), **analysis},
                )
            else:
                self._send_json(HTTPStatus.ACCEPTED, {"ok": True, "frame": asdict(metadata)})
        except OverflowError as exc:
            self._send_json(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                {"ok": False, "error": str(exc)},
            )
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
        except RuntimeError as exc:
            self._send_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"ok": False, "error": str(exc)},
            )
        except Exception as exc:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": f"服务器处理失败：{exc}"},
            )


class DemoHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def guess_lan_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 9))
        return str(sock.getsockname()[0])
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rokid 眼镜 UDP MPEG-TS/H.264 视频接收服务"
    )
    parser.add_argument("--host", default="0.0.0.0", help="HTTP 监听地址")
    parser.add_argument("--port", type=int, default=9088, help="HTTP 监听端口")
    parser.add_argument(
        "--udp-host",
        default=DEFAULT_UDP_HOST,
        help="UDP MPEG-TS 监听地址",
    )
    parser.add_argument(
        "--udp-port",
        type=int,
        default=DEFAULT_UDP_PORT,
        help="UDP MPEG-TS 监听端口",
    )
    parser.add_argument(
        "--preview-fps",
        type=float,
        default=10.0,
        help="浏览器 JPEG 预览上限 FPS",
    )
    parser.add_argument(
        "--recognition-fps",
        type=float,
        default=DEFAULT_RECOGNITION_FPS,
        help="后台识别上限 FPS，设为 0 可关闭",
    )
    parser.add_argument(
        "--stream-stale-seconds",
        type=float,
        default=DEFAULT_STREAM_STALE_SECONDS,
        help="超过该时长未解码到帧即认为视频断开",
    )
    parser.add_argument(
        "--jpeg-quality",
        type=int,
        default=82,
        help="浏览器预览 JPEG 质量",
    )
    args = parser.parse_args()

    global CONFIGURED_UDP_HOST, CONFIGURED_UDP_PORT
    global VIDEO_RECEIVER, PREVIEW_WORKER, RECOGNITION_WORKER
    CONFIGURED_UDP_HOST = args.udp_host
    CONFIGURED_UDP_PORT = args.udp_port
    VIDEO_RECEIVER = VideoStreamReceiver(
        VIDEO_FRAME_STORE,
        host=args.udp_host,
        port=args.udp_port,
        stale_after_seconds=max(0.5, args.stream_stale_seconds),
    )
    PREVIEW_WORKER = PreviewWorker(
        VIDEO_FRAME_STORE,
        FRAME_STORE,
        target_fps=args.preview_fps,
        jpeg_quality=args.jpeg_quality,
    )
    RECOGNITION_WORKER = RecognitionWorker(
        FRAME_STORE,
        target_fps=args.recognition_fps,
    )

    httpd = DemoHTTPServer((args.host, args.port), DemoHandler)
    VIDEO_RECEIVER.start()
    PREVIEW_WORKER.start()
    RECOGNITION_WORKER.start()
    lan_ip = guess_lan_ip()
    print()
    print("Rokid Camera Link 视频接收服务已启动")
    print(f"电脑监看页面：http://127.0.0.1:{args.port}/")
    print(f"眼镜推流目标：udp://{lan_ip}:{args.udp_port}")
    print(
        "视频格式：MPEG-TS / H.264，"
        f"预览上限：{max(0.0, args.preview_fps):g} FPS，"
        f"识别上限：{max(0.0, args.recognition_fps):g} FPS"
    )
    print("按 Ctrl+C 停止。")
    print()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止视频接收服务...")
    finally:
        RECOGNITION_WORKER.stop()
        PREVIEW_WORKER.stop()
        VIDEO_RECEIVER.stop()
        httpd.server_close()


if __name__ == "__main__":
    main()
