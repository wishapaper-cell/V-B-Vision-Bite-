from __future__ import annotations

import argparse
import base64
import json
import urllib.request


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


def main() -> None:
    parser = argparse.ArgumentParser(description="向独立 Demo 发送一张测试 JPEG")
    parser.add_argument("--url", default="http://127.0.0.1:9088/api/frame")
    args = parser.parse_args()

    request = urllib.request.Request(
        args.url,
        data=JPEG_1X1,
        method="POST",
        headers={
            "Content-Type": "image/jpeg",
            "X-Device-Name": "python-self-test",
            "X-Frame-Width": "1",
            "X-Frame-Height": "1",
        },
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        payload = json.loads(response.read().decode("utf-8"))
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
