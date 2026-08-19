"""HTTPS wrapper for the FastAPI video backend.

Run with:
    cd services/recognition
    python server_https.py

Requires cert.pem / key.pem in this directory (self-signed is fine):
    openssl req -x509 -newkey rsa:2048 -nodes -keyout key.pem -out cert.pem -days 365 -subj "/CN=nutritionglass"
"""
from __future__ import annotations

import uvicorn

from server import app

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        ssl_keyfile="key.pem",
        ssl_certfile="cert.pem",
        log_level="info",
    )
