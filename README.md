# mac-android-2screen

Use your Samsung tablet (or any Android device) as an **extended external
monitor** for your Mac — wired via USB or over Wi-Fi.

```
┌─────────────────────────────────┐       USB / Wi-Fi
│           Mac  (server)         │ ──────────────────►  Samsung Tablet
│  captures display, streams MJPEG│ ◄──────────────────  (Android app)
│  injects touch → mouse events   │       touch events
└─────────────────────────────────┘
```

---

## How it works

| Component | Location | Role |
|-----------|----------|------|
| **Mac server** | `mac/server.py` | Captures a display with `mss`, streams it as MJPEG over HTTP, and injects touch events received from the tablet as mouse events via `pyautogui`. |
| **Android app** | `android/` | Full-screen MJPEG viewer built with a `SurfaceView`. Forwards touch events to the server as normalised-coordinate JSON POST requests. Supports USB (ADB reverse) and Wi-Fi modes. |
| **Scripts** | `scripts/` | One-command USB/Wi-Fi setup helpers. |

---

## Requirements

### Mac
| Tool | Install |
|------|---------|
| Python 3.10+ | pre-installed on macOS 12+ |
| `mss` · `Pillow` · `pyautogui` | `pip install -r mac/requirements.txt` |
| ADB *(USB mode only)* | `brew install android-platform-tools` |

### Samsung Tablet (Android 8.0+)
- **USB Debugging** enabled — Settings → Developer options → USB debugging
- **MacScreen** APK installed (build with Android Studio or download a release)

### Extended display (recommended)
For a true drag-and-drop second monitor experience, create a virtual display on
your Mac that macOS treats as a physical second screen:

- **[BetterDisplay](https://github.com/waydabber/BetterDisplay)** (free tier) —
  create a virtual/dummy display at your tablet's resolution, then pass
  `--display 2` (or whatever index macOS assigns) to the server.
- Alternatively, stream any existing display with `--display 1` (primary).

---

## Wired setup (USB — recommended)

```bash
# 1. Connect the tablet via USB and accept the "Allow USB Debugging" prompt.

# 2. Set up ADB reverse port forwarding (tablet → Mac):
bash scripts/setup_usb.sh

# 3. Install Python dependencies (first time only):
pip install -r mac/requirements.txt

# 4. Start the Mac server (streaming display 2 at 30 fps):
python mac/server.py --display 2

# 5. Open the MacScreen app on the tablet.
#    In ⚙ Settings: choose "USB (ADB)" mode, port 8080, then tap Connect.
```

---

## Wi-Fi setup

```bash
# 1. Find your Mac's local IP:
bash scripts/setup_wifi.sh

# 2. Start the Mac server:
python mac/server.py --display 2

# 3. Open the MacScreen app on the tablet.
#    In ⚙ Settings: choose "Wi-Fi" mode, enter the Mac IP, tap Connect.
```

---

## Server options

```
python mac/server.py [options]

  --display N    Display index to capture (1=primary, 2=second, …)  [default: 1]
  --port N       HTTP server port                                    [default: 8080]
  --fps N        Target frames per second                            [default: 30]
  --quality N    JPEG quality 1–100 (lower = faster, less detail)   [default: 75]
```

You can also preview the stream in any browser: `http://localhost:8080/`

---

## Android app — building from source

1. Open the `android/` folder in **Android Studio Hedgehog (2023.1.1)** or newer.
2. Let Gradle sync and download dependencies.
3. Build → **Generate Signed APK** or run directly on the tablet via USB.

> **Minimum SDK:** Android 8.0 (API 26)  
> **Target SDK:** Android 14 (API 34)

---

## Project structure

```
mac-android-2screen/
├── mac/
│   ├── server.py            # MJPEG streaming server + touch event receiver
│   └── requirements.txt     # Python dependencies
├── android/
│   ├── settings.gradle.kts
│   ├── build.gradle.kts
│   ├── gradle/
│   │   ├── libs.versions.toml
│   │   └── wrapper/gradle-wrapper.properties
│   └── app/src/main/
│       ├── AndroidManifest.xml
│       ├── java/com/macscreen/client/
│       │   ├── MainActivity.kt        # Full-screen activity, settings dialog
│       │   ├── MjpegView.kt           # SurfaceView MJPEG renderer
│       │   ├── MjpegDecoder.kt        # Background MJPEG stream parser
│       │   └── TouchEventSender.kt    # Queued HTTP touch event forwarder
│       └── res/
│           ├── layout/activity_main.xml
│           └── values/{strings,themes}.xml
└── scripts/
    ├── setup_usb.sh         # ADB reverse port forwarding helper
    └── setup_wifi.sh        # Print Mac LAN IP for Wi-Fi mode
```

---

## Tips & troubleshooting

| Problem | Fix |
|---------|-----|
| Blank screen / "Error: Stream error" | Check the server is running and the port matches. For USB, re-run `setup_usb.sh`. |
| High latency | Lower `--fps` or `--quality`; use USB instead of Wi-Fi. |
| Touch misaligned | Ensure the tablet is in landscape orientation matching the streamed display. |
| `adb: command not found` | `brew install android-platform-tools` |
| `pyautogui` permission denied | macOS requires Accessibility permission: System Settings → Privacy & Security → Accessibility → add Terminal/Python. |
| Can't drag windows to tablet display | Use BetterDisplay to create a virtual display first; then assign it the tablet's resolution. |
