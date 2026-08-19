"""End-to-end smoke test for the Rokid video-stream control entry.

Run through scripts/with_server.py with HEALTH_DB_PATH pointing to a disposable
database. The test uses the locally installed Microsoft Edge executable.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from playwright.sync_api import sync_playwright
from werkzeug.security import generate_password_hash


APP_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.environ["HEALTH_DB_PATH"])
SCREENSHOT_PATH = APP_ROOT.parent / ".browser-smoke.png"
BASE_URL = os.environ.get("HEALTH_TEST_BASE_URL", "http://127.0.0.1:5000").rstrip("/")


def seed_test_user() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO users
                (phone, password_hash, role, nickname, supervisor_code, supervisee_code)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "13800000000",
                generate_password_hash("CodexTest1"),
                "supervisee",
                "浏览器测试",
                "TESTSUP1",
                "TESTSUB1",
            ),
        )


seed_test_user()

console_errors: list[str] = []
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        headless=True,
        executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    )
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    page.add_init_script(
        """
        window.RokidGlasses = {
            requestAuthorizationAndConnect: function() {},
            ensure: function() {},
            install: function() {},
            start: function() {},
            stop: function() {},
            status: function() {},
            setServerUrl: function() { return true; },
            getServerUrl: function() { return 'http://192.168.1.100:9088'; },
            getState: function() {
                return JSON.stringify({
                    control_ready: true,
                    streamer_apk_embedded: true,
                    streamer_installed: true,
                    streamer_installing: false,
                    streaming: false,
                    streamer_status: {state: 'idle', actualFps: 30, width: 1280, height: 720},
                    message: '浏览器视频流控制测试'
                });
            }
        };
        """
    )
    page.on(
        "console",
        lambda message: console_errors.append(message.text)
        if message.type == "error" and "Failed to load resource" not in message.text
        else None,
    )
    page.goto(f"{BASE_URL}/login")
    page.wait_for_load_state("networkidle")
    page.locator("#tab-password input[name=phone]").fill("13800000000")
    page.locator("#tab-password input[name=password]").fill("CodexTest1")
    page.locator("#tab-password button[type=submit]").click()
    page.wait_for_url("**/goal")
    page.goto(f"{BASE_URL}/recognition")
    page.wait_for_load_state("networkidle")
    assert page.locator("#rokidControls").is_visible()
    assert page.locator("#rokidStartButton").is_enabled()
    assert page.locator("#rokidActualFps").text_content() == "30.0"
    assert page.locator("#rokidResolution").text_content() == "1280×720"
    assert "眼镜拍照" not in page.content()
    assert "开始低频采集" not in page.content()
    assert not console_errors, console_errors
    page.screenshot(path=str(SCREENSHOT_PATH), full_page=True)
    print("browser smoke: PASS")
    browser.close()
