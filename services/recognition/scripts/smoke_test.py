from __future__ import annotations

import base64
import io

import requests
from PIL import Image, ImageDraw


BASE = "http://127.0.0.1:8000"


def make_frame() -> str:
    image = Image.new("RGB", (640, 360), (36, 42, 38))
    draw = ImageDraw.Draw(image)
    draw.ellipse((120, 80, 520, 300), fill=(232, 235, 224))
    draw.ellipse((170, 125, 330, 250), fill=(238, 232, 195))
    draw.ellipse((340, 120, 470, 220), fill=(220, 150, 92))
    draw.ellipse((330, 220, 500, 285), fill=(70, 150, 80))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=82)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def main() -> None:
    session = requests.post(f"{BASE}/api/sessions", timeout=10).json()
    session_id = session["session_id"]
    token = session["token"]
    join = requests.post(
        f"{BASE}/api/sessions/{session_id}/join",
        json={"token": token, "device": {"platform": "android", "model": "smoke-test", "user_agent": "smoke-test"}},
        timeout=10,
    )
    join.raise_for_status()
    frame = requests.post(
        f"{BASE}/api/sessions/{session_id}/frames",
        json={"token": token, "image": make_frame(), "width": 640, "height": 360, "timestamp_ms": 1, "device_motion": {}},
        timeout=30,
    )
    frame.raise_for_status()
    state = frame.json()
    report = requests.post(f"{BASE}/api/sessions/{session_id}/finish", timeout=10)
    report.raise_for_status()
    print("session:", session_id)
    print("analyzer:", state["analyzer"], state["model_name"])
    print("foods:", [(food["name"], food["estimated_weight_g"]) for food in state["foods"]])
    print("overall quality:", state["measurement_quality"]["overall"])
    print("report total:", report.json()["meal_summary"])


if __name__ == "__main__":
    main()
