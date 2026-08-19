from __future__ import annotations

import base64
import json
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


JPEG_1X1 = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////"
    "2wBDAf//////////////////////////////////////////////////////////////////////////////////////"
    "wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAf/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/"
    "9oADAMBAAIQAxAAAAF//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABBQJ//8QAFBEBAAAAAAAAAAAAAAAA"
    "AAAAAP/aAAgBAwEBPwF//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAgEBPwF//8QAFBABAAAAAAAAAAAAAAAA"
    "AAAAAP/aAAgBAQAGPwJ//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPyF//9oADAMBAAIAAwAAABD/xAAU"
    "EQEAAAAAAAAAAAAAAAAAAAAA/9oACAEDAQE/EF//xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAECAQE/EF//xAAU"
    "EAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAE/EF//2Q=="
)


def wait_until(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        server.FRAME_STORE = server.FrameStore()
        server.VIDEO_FRAME_STORE = server.LatestVideoFrameStore()
        server.VIDEO_RECEIVER = None
        server.PREVIEW_WORKER = None
        server.RECOGNITION_WORKER = None
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.DemoHandler)
        cls.base_url = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)

    def read_json(self, path: str) -> tuple[int, dict[str, object]]:
        with urllib.request.urlopen(self.base_url + path, timeout=3) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_health_and_static_pages(self) -> None:
        status, payload = self.read_json("/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        status, config = self.read_json("/api/config")
        self.assertEqual(status, 200)
        self.assertIn("/capture.html", config["capture_url"])
        with urllib.request.urlopen(self.base_url + "/viewer.html", timeout=3) as response:
            html = response.read().decode("utf-8")
        self.assertIn("Rokid Camera Link", html)

    def test_rejects_non_jpeg(self) -> None:
        request = urllib.request.Request(
            self.base_url + "/api/frame",
            data=b"not-a-jpeg",
            method="POST",
            headers={"Content-Type": "image/jpeg"},
        )
        with self.assertRaises(urllib.error.HTTPError) as context:
            urllib.request.urlopen(request, timeout=3)
        self.assertEqual(context.exception.code, 400)

    def test_accepts_raw_jpeg_and_serves_latest_frame(self) -> None:
        request = urllib.request.Request(
            self.base_url + "/api/frame",
            data=JPEG_1X1,
            method="POST",
            headers={
                "Content-Type": "image/jpeg",
                "X-Device-Name": "unit-test-camera",
                "X-Frame-Width": "1",
                "X-Frame-Height": "1",
            },
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(response.status, 202)
        self.assertTrue(payload["ok"])

        _, status = self.read_json("/api/status")
        self.assertTrue(status["has_frame"])
        self.assertEqual(status["frame"]["device_name"], "unit-test-camera")

        with urllib.request.urlopen(self.base_url + "/api/frame.jpg", timeout=3) as response:
            self.assertEqual(response.read(), JPEG_1X1)

    def test_accepts_existing_project_style_json(self) -> None:
        image = "data:image/jpeg;base64," + base64.b64encode(JPEG_1X1).decode("ascii")
        body = json.dumps(
            {
                "image": image,
                "width": 1,
                "height": 1,
                "device_name": "json-camera",
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + "/api/frame",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["frame"]["device_name"], "json-camera")

    def test_latest_analysis_endpoint_returns_background_result(self) -> None:
        analysis = {
            "foods": [{"name": "米饭", "estimated_weight_g": 120}],
            "quality": {"overall": 0.8},
            "guidance": "测试完成",
            "analyzer": "test",
            "model_name": "test",
        }
        worker = server.RecognitionWorker(
            server.FRAME_STORE,
            target_fps=50,
            analyzer=lambda jpeg: analysis,
        )
        server.RECOGNITION_WORKER = worker
        worker.start()
        try:
            server.FRAME_STORE.put(
                JPEG_1X1,
                device_name="unit-test-camera",
                client_ip="127.0.0.1",
                width=1,
                height=1,
            )
            self.assertTrue(
                wait_until(lambda: worker.status()["hasAnalysis"]),
                worker.status(),
            )
            status, payload = self.read_json("/api/analysis/latest")
            self.assertEqual(status, 200)
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["has_analysis"])
            self.assertGreater(payload["frame_sequence"], 0)
            self.assertIsInstance(payload["analyzed_at_ms"], int)
            self.assertGreaterEqual(payload["age_ms"], 0)
            self.assertEqual(payload["analysis"], analysis)
        finally:
            worker.stop()
            server.RECOGNITION_WORKER = None

    def test_analyze_endpoint_returns_shared_recognition_shape(self) -> None:
        original = server.analyze_jpeg
        server.analyze_jpeg = lambda jpeg: {
            "foods": [{"name": "白米饭", "estimated_weight_g": 120}],
            "quality": {"overall": 0.8},
            "guidance": "测试完成",
            "analyzer": "test",
            "model_name": "test",
        }
        try:
            request = urllib.request.Request(
                self.base_url + "/api/analyze",
                data=JPEG_1X1,
                method="POST",
                headers={
                    "Content-Type": "image/jpeg",
                    "X-Device-Name": "Rokid-RV101",
                },
            )
            with urllib.request.urlopen(request, timeout=3) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(response.status, 200)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["foods"][0]["name"], "白米饭")
            self.assertEqual(payload["frame"]["device_name"], "Rokid-RV101")
        finally:
            server.analyze_jpeg = original


class LatestOnlyStoreTest(unittest.TestCase):
    def test_jpeg_store_replaces_instead_of_queueing(self) -> None:
        store = server.FrameStore()
        for index in range(3):
            store.put(
                JPEG_1X1,
                device_name="test",
                client_ip="127.0.0.1",
                width=1,
                height=1,
                source_sequence=index + 1,
            )
        snapshot = store.snapshot()
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.metadata.sequence, 3)
        self.assertEqual(snapshot.metadata.source_sequence, 3)
        self.assertEqual(
            store.stats(),
            {
                "capacity": 1,
                "totalFrames": 3,
                "replacedFrames": 2,
                "queuedFrames": 1,
            },
        )

    def test_decoded_store_keeps_only_latest_object(self) -> None:
        store = server.LatestVideoFrameStore()
        frames = [object(), object(), object()]
        for frame in frames:
            store.put(frame, width=1280, height=720)
        snapshot = store.snapshot()
        self.assertIsNotNone(snapshot)
        self.assertIs(snapshot.video_frame, frames[-1])
        self.assertEqual(snapshot.metadata.sequence, 3)
        self.assertEqual(store.stats()["replacedFrames"], 2)
        self.assertEqual(store.stats()["capacity"], 1)


class RateMetricsTest(unittest.TestCase):
    def test_recent_window_rate_and_expiry(self) -> None:
        now = [0.0]
        rate = server.RollingRate(2.0, clock=lambda: now[0])
        for tick in range(11):
            now[0] = tick / 10
            rate.mark()
        self.assertAlmostEqual(rate.rate(now=1.0), 10.0, places=4)
        self.assertEqual(rate.rate(now=3.1), 0.0)

    def test_stream_metrics_report_receive_and_decode_rates(self) -> None:
        now = [0.0]
        metrics = server.StreamMetrics(clock=lambda: now[0])
        metrics.set_running(True)
        for tick in range(11):
            now[0] = tick / 10
            metrics.mark_receive()
            metrics.mark_decode()
        status = metrics.snapshot(stale_after_seconds=1.0)
        self.assertTrue(status["streamConnected"])
        self.assertAlmostEqual(status["receiveFps"], 10.0, places=2)
        self.assertAlmostEqual(status["decodeFps"], 10.0, places=2)
        self.assertEqual(status["inputFps"], status["decodeFps"])
        now[0] = 3.0
        self.assertFalse(metrics.snapshot(stale_after_seconds=1.0)["streamConnected"])


class FakeReader:
    def __init__(self, frame_count: int = 3) -> None:
        self.frame_count = frame_count
        self.started = threading.Event()
        self.closed = False

    def events(self, stop_event: threading.Event):
        self.started.set()
        for _ in range(self.frame_count):
            yield server.ReaderEvent.packet()
            yield server.ReaderEvent.frame(object(), 1280, 720)
        while not stop_event.wait(0.01):
            pass

    def close(self) -> None:
        self.closed = True


class VideoReceiverLifecycleTest(unittest.TestCase):
    def test_fake_reader_lifecycle_and_status(self) -> None:
        store = server.LatestVideoFrameStore()
        reader = FakeReader()
        receiver = server.VideoStreamReceiver(
            store,
            reader_factory=lambda url: reader,
            reconnect_delay_seconds=0.01,
        )
        receiver.start()
        self.assertTrue(reader.started.wait(1))
        self.assertTrue(
            wait_until(lambda: receiver.status()["decodedFrames"] == 3),
            receiver.status(),
        )
        status = receiver.status()
        self.assertEqual(status["source"], "udp_video")
        self.assertTrue(status["streamConnected"])
        self.assertEqual(status["decodedFrames"], 3)
        self.assertEqual(status["receivedPackets"], 3)
        self.assertEqual(status["replacedFrames"], 2)
        self.assertEqual(status["latestSequence"], 3)

        receiver.stop()
        self.assertTrue(reader.closed)
        self.assertFalse(receiver.is_alive)
        self.assertFalse(receiver.status()["decoderRunning"])

    def test_missing_dependency_stops_without_reconnect_loop(self) -> None:
        class MissingReader:
            def events(self, stop_event: threading.Event):
                raise server.VideoDependencyError("install av")

            def close(self) -> None:
                pass

        receiver = server.VideoStreamReceiver(
            server.LatestVideoFrameStore(),
            reader_factory=lambda url: MissingReader(),
            reconnect_delay_seconds=0.01,
        )
        receiver.start()
        self.assertTrue(wait_until(lambda: not receiver.is_alive))
        status = receiver.status()
        self.assertFalse(status["dependencyAvailable"])
        self.assertIn("install av", status["lastError"])
        self.assertEqual(status["reconnects"], 0)

    def test_idle_udp_timeouts_do_not_create_a_reconnect_storm(self) -> None:
        attempts = 0

        class IdleReader:
            def events(self, stop_event: threading.Event):
                nonlocal attempts
                attempts += 1
                raise OSError(5, "I/O error")
                yield  # pragma: no cover - keep this method a generator

            def close(self) -> None:
                pass

        receiver = server.VideoStreamReceiver(
            server.LatestVideoFrameStore(),
            reader_factory=lambda url: IdleReader(),
            reconnect_delay_seconds=0.01,
            max_idle_retry_delay_seconds=0.04,
        )
        receiver.start()
        self.assertTrue(
            wait_until(lambda: receiver.status()["idleTimeouts"] >= 3),
            receiver.status(),
        )
        status = receiver.status()
        receiver.stop()

        self.assertEqual(status["reconnects"], 0)
        self.assertIsNone(status["lastError"])
        self.assertGreaterEqual(status["idleTimeouts"], 3)
        self.assertLess(attempts, 10)
        self.assertFalse(receiver.is_alive)

    def test_only_an_established_stream_counts_as_one_reconnect(self) -> None:
        attempts = 0

        class OneStreamThenIdleReader:
            def __init__(self, emit_frame: bool) -> None:
                self.emit_frame = emit_frame

            def events(self, stop_event: threading.Event):
                if self.emit_frame:
                    yield server.ReaderEvent.packet()
                    yield server.ReaderEvent.frame(object(), 1280, 720)
                    return
                raise OSError(5, "I/O error")
                yield  # pragma: no cover - keep this method a generator

            def close(self) -> None:
                pass

        def make_reader(url: str):
            nonlocal attempts
            attempts += 1
            return OneStreamThenIdleReader(emit_frame=attempts == 1)

        receiver = server.VideoStreamReceiver(
            server.LatestVideoFrameStore(),
            reader_factory=make_reader,
            reconnect_delay_seconds=0.01,
            max_idle_retry_delay_seconds=0.02,
        )
        receiver.start()
        self.assertTrue(
            wait_until(lambda: receiver.status()["idleTimeouts"] >= 2),
            receiver.status(),
        )
        status = receiver.status()
        receiver.stop()

        self.assertEqual(status["decodedFrames"], 1)
        self.assertEqual(status["reconnects"], 1)
        self.assertGreaterEqual(status["idleTimeouts"], 2)
        self.assertFalse(receiver.is_alive)

    def test_stop_calls_reader_close_and_unblocks_receiver(self) -> None:
        class CloseUnblocksReader:
            def __init__(self) -> None:
                self.started = threading.Event()
                self.closed = threading.Event()

            def events(self, stop_event: threading.Event):
                self.started.set()
                self.closed.wait(2)
                return
                yield  # pragma: no cover - keep this method a generator

            def close(self) -> None:
                self.closed.set()

        reader = CloseUnblocksReader()
        receiver = server.VideoStreamReceiver(
            server.LatestVideoFrameStore(),
            reader_factory=lambda url: reader,
        )
        receiver.start()
        self.assertTrue(reader.started.wait(1))
        started = time.monotonic()
        receiver.stop(timeout=1)

        self.assertLess(time.monotonic() - started, 0.5)
        self.assertTrue(reader.closed.is_set())
        self.assertFalse(receiver.is_alive)
        self.assertFalse(receiver.status()["decoderRunning"])


class BoundedWorkerTest(unittest.TestCase):
    def test_preview_worker_skips_intermediate_decoded_frames(self) -> None:
        input_store = server.LatestVideoFrameStore()
        output_store = server.FrameStore()
        first_started = threading.Event()
        release_first = threading.Event()
        calls: list[object] = []

        def encoder(video_frame: object) -> bytes:
            calls.append(video_frame)
            if len(calls) == 1:
                first_started.set()
                release_first.wait(1)
            return JPEG_1X1

        first_frame = object()
        latest_frame = object()
        input_store.put(first_frame, width=1280, height=720)
        worker = server.PreviewWorker(
            input_store,
            output_store,
            target_fps=100,
            encoder=encoder,
        )
        worker.start()
        self.assertTrue(first_started.wait(1))
        for _ in range(18):
            input_store.put(object(), width=1280, height=720)
        input_store.put(latest_frame, width=1280, height=720)
        release_first.set()
        self.assertTrue(
            wait_until(lambda: worker.status()["encodedFrames"] >= 2),
            worker.status(),
        )
        worker.stop()

        self.assertEqual(calls, [first_frame, latest_frame])
        self.assertGreaterEqual(worker.status()["skippedFrames"], 18)
        snapshot = output_store.snapshot()
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.metadata.source_sequence, 20)
        self.assertEqual(worker.status()["queueCapacity"], 0)
        self.assertEqual(worker.status()["maxConcurrency"], 1)

    def test_recognition_worker_analyzes_first_and_latest_only(self) -> None:
        store = server.FrameStore()
        first_started = threading.Event()
        release_first = threading.Event()
        calls: list[bytes] = []

        def analyzer(jpeg: bytes) -> dict[str, object]:
            calls.append(jpeg)
            if len(calls) == 1:
                first_started.set()
                release_first.wait(1)
            return {
                "foods": [],
                "quality": {},
                "guidance": "",
                "analyzer": "test",
                "model_name": "test",
            }

        store.put(
            JPEG_1X1,
            device_name="test",
            client_ip="127.0.0.1",
            width=1,
            height=1,
        )
        worker = server.RecognitionWorker(store, target_fps=100, analyzer=analyzer)
        worker.start()
        self.assertTrue(first_started.wait(1))
        for _ in range(19):
            store.put(
                JPEG_1X1,
                device_name="test",
                client_ip="127.0.0.1",
                width=1,
                height=1,
            )
        release_first.set()
        self.assertTrue(
            wait_until(lambda: worker.status()["analyzedFrames"] >= 2),
            worker.status(),
        )
        worker.stop()

        self.assertEqual(len(calls), 2)
        status = worker.status()
        self.assertEqual(status["lastSequence"], 20)
        self.assertGreaterEqual(status["skippedFrames"], 18)
        self.assertEqual(status["queueCapacity"], 0)
        self.assertEqual(status["maxConcurrency"], 1)


if __name__ == "__main__":
    unittest.main()
