#!/usr/bin/env bash
# setup_usb.sh — Prepare a wired USB connection between the Mac and the
# Samsung tablet so the Android app can reach the Mac server.
#
# Requirements on the Mac:
#   • ADB (Android Debug Bridge) installed:  brew install android-platform-tools
#   • USB debugging enabled on the tablet
#   • The Mac and tablet connected via USB cable
#
# Usage:
#   bash scripts/setup_usb.sh [port]
#
# The optional [port] argument overrides the default port 8080.

set -euo pipefail

PORT="${1:-8080}"

echo "==> Checking for ADB …"
if ! command -v adb &>/dev/null; then
  echo "  ERROR: adb not found. Install it with:  brew install android-platform-tools"
  exit 1
fi

echo "==> Waiting for a connected device …"
adb wait-for-device

DEVICE=$(adb devices | awk 'NR==2 {print $1}')
echo "  Device: ${DEVICE}"

echo "==> Setting up reverse port forwarding (tablet:${PORT} → mac:${PORT}) …"
adb reverse "tcp:${PORT}" "tcp:${PORT}"
echo "  Done."

echo ""
echo "==> Next steps:"
echo "  1. Start the Mac server:         python mac/server.py --display 2"
echo "  2. Open the MacScreen app on your tablet."
echo "  3. In the app settings choose 'USB (ADB)' mode and port ${PORT}."
echo "  4. Tap 'Connect'."
echo ""
echo "  Tip: to stream your primary display use --display 1."
echo "  Tip: for a true extended desktop, set up a virtual display first:"
echo "       https://github.com/waydabber/BetterDisplay (free tier supports virtual displays)"
