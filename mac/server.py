#!/usr/bin/env python3
"""
mac-android-2screen — Mac Server
Captures a Mac display and streams it as MJPEG over HTTP so a Samsung tablet
can display it as an extended monitor.  Touch events sent back by the Android
app are injected as mouse events on the captured display region.

Usage:
    python server.py [--display 2] [--port 8080] [--fps 30] [--quality 75]

Wired (USB) setup:
    adb reverse tcp:8080 tcp:8080
    python server.py --display 2

Wi-Fi setup:
    python server.py --display 2
    # Then enter your Mac's LAN IP in the Android app settings.
"""

import argparse
import io
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

try:
    import mss
except ImportError:
    raise SystemExit("Please install mss:  pip install -r requirements.txt")

try:
    from PIL import Image
except ImportError:
    raise SystemExit("Please install Pillow:  pip install -r requirements.txt")

try:
    import pyautogui
    _PYAUTOGUI = True
    pyautogui.FAILSAFE = False  # don't raise on corner-screen moves
except ImportError:  # pragma: no cover
    _PYAUTOGUI = False
    print("Warning: pyautogui not found — touch input will be ignored.")


# ---------------------------------------------------------------------------
# Globals shared between the capture thread and the HTTP handlers
# ---------------------------------------------------------------------------
_frame_lock = threading.Lock()
_current_frame: bytes | None = None
_monitor: dict | None = None  # mss monitor rect being captured

# Whitelist of recognised touch event types.
_VALID_EVENT_TYPES = frozenset({"down", "up", "move", "click", "rightclick", "scroll"})


class Config:
    port: int = 8080
    display_index: int = 1  # 1 = primary, 2 = second display, …
    fps: int = 30
    quality: int = 75  # JPEG quality 1–100


config = Config()


# ---------------------------------------------------------------------------
# Screen capture thread
# ---------------------------------------------------------------------------

def _capture_loop() -> None:
    """Continuously grab the selected monitor and store the latest JPEG frame."""
    global _current_frame, _monitor

    with mss.mss() as sct:
        monitors = sct.monitors  # monitors[0] = all, monitors[1] = primary, …
        total = len(monitors) - 1
        print(f"Detected {total} display(s):")
        for i, m in enumerate(monitors[1:], start=1):
            print(f"  [{i}] {m['width']}×{m['height']}  offset ({m['left']}, {m['top']})")

        idx = config.display_index
        if idx < 1 or idx >= len(monitors):
            print(f"Display index {idx} out of range — defaulting to 1 (primary).")
            idx = 1

        monitor = monitors[idx]
        _monitor = monitor
        print(f"\nCapturing display [{idx}]: {monitor['width']}×{monitor['height']}")

        frame_time = 1.0 / config.fps
        while True:
            t0 = time.monotonic()
            screenshot = sct.grab(monitor)
            img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=config.quality)
            with _frame_lock:
                _current_frame = buf.getvalue()
            elapsed = time.monotonic() - t0
            wait = frame_time - elapsed
            if wait > 0:
                time.sleep(wait)


# ---------------------------------------------------------------------------
# HTTP request handler
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    # Silence the default per-request log line; we do our own minimal logging.
    def log_message(self, fmt, *args):  # noqa: N802
        pass

    # ------------------------------------------------------------------
    def do_GET(self):  # noqa: N802
        path = urlparse(self.path).path
        if path == "/stream":
            self._stream()
        elif path == "/info":
            self._info()
        elif path in ("/", "/index.html"):
            self._index()
        else:
            self.send_error(404)

    def do_POST(self):  # noqa: N802
        path = urlparse(self.path).path
        if path == "/touch":
            self._touch()
        else:
            self.send_error(404)

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    # ------------------------------------------------------------------
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _index(self):
        html = b"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>mac-android-2screen</title>
<style>body{font-family:sans-serif;background:#111;color:#eee;margin:2em}
img{max-width:100%;border:1px solid #444}</style></head>
<body>
<h1>mac-android-2screen</h1>
<p>Stream: <code>/stream</code> &mdash; Info: <code>/info</code></p>
<img src="/stream" alt="screen stream">
</body></html>
"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self._cors()
        self.end_headers()
        self.wfile.write(html)

    def _info(self):
        mon = _monitor or {}
        payload = {
            "display": config.display_index,
            "fps": config.fps,
            "quality": config.quality,
            "width": mon.get("width"),
            "height": mon.get("height"),
        }
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache, no-store")
        self._cors()
        self.end_headers()

        frame_delay = 1.0 / config.fps
        try:
            while True:
                with _frame_lock:
                    frame = _current_frame
                if frame:
                    self.wfile.write(
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n"
                        + frame
                        + b"\r\n"
                    )
                    self.wfile.flush()
                time.sleep(frame_delay)
        except (BrokenPipeError, ConnectionResetError):
            pass  # client disconnected

    def _touch(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
            event_type: str = data["type"]       # "down" | "up" | "move" | "click" | "rightclick" | "scroll"
            norm_x: float = float(data["x"])     # 0.0 – 1.0
            norm_y: float = float(data["y"])     # 0.0 – 1.0
        except (json.JSONDecodeError, KeyError, ValueError):
            self.send_error(400, "Invalid JSON payload")
            return

        if event_type not in _VALID_EVENT_TYPES:
            self.send_error(400, "Unknown event type")
            return

        if _PYAUTOGUI and _monitor:
            mon = _monitor
            sx = int(mon["left"] + norm_x * mon["width"])
            sy = int(mon["top"] + norm_y * mon["height"])
            if event_type == "down":
                pyautogui.moveTo(sx, sy)
                pyautogui.mouseDown()
            elif event_type == "up":
                pyautogui.moveTo(sx, sy)
                pyautogui.mouseUp()
            elif event_type == "move":
                pyautogui.moveTo(sx, sy)
            elif event_type == "click":
                pyautogui.click(sx, sy)
            elif event_type == "rightclick":
                pyautogui.rightClick(sx, sy)
            elif event_type == "scroll":
                try:
                    clicks = int(data.get("amount", 0))
                except (TypeError, ValueError):
                    clicks = 0
                if clicks != 0:
                    pyautogui.scroll(clicks, x=sx, y=sy)

        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stream a Mac display to a Samsung tablet over USB/Wi-Fi."
    )
    parser.add_argument(
        "--display", type=int, default=Config.display_index,
        help="Display index to capture (1 = primary, 2 = second, …). "
             "Default: %(default)s",
    )
    parser.add_argument(
        "--port", type=int, default=Config.port,
        help="HTTP server port. Default: %(default)s",
    )
    parser.add_argument(
        "--fps", type=int, default=Config.fps,
        help="Target frames per second. Default: %(default)s",
    )
    parser.add_argument(
        "--quality", type=int, default=Config.quality,
        help="JPEG quality (1–100). Default: %(default)s",
    )
    args = parser.parse_args()

    config.display_index = args.display
    config.port = args.port
    config.fps = args.fps
    config.quality = args.quality

    capture_thread = threading.Thread(target=_capture_loop, daemon=True, name="capture")
    capture_thread.start()

    print("Waiting for first frame …", end="", flush=True)
    while _current_frame is None:
        time.sleep(0.05)
    print(" ready.")

    print(f"Server listening on http://0.0.0.0:{config.port}")
    print(f"  Stream  → http://localhost:{config.port}/stream")
    print(f"  Info    → http://localhost:{config.port}/info")
    print("Press Ctrl+C to stop.\n")

    server = HTTPServer(("", config.port), _Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == "__main__":
    main()
