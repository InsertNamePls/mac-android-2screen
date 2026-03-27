#!/usr/bin/env bash
# setup_wifi.sh — Print the Mac's local IP address(es) so you can enter one
# in the Android app for a Wi-Fi connection.
#
# Requirements:
#   • Both the Mac and the Samsung tablet must be on the same Wi-Fi network.
#   • The firewall on the Mac must allow incoming connections on the chosen port
#     (macOS prompts automatically when the Python server first runs).
#
# Usage:
#   bash scripts/setup_wifi.sh [port]

set -euo pipefail

PORT="${1:-8080}"

echo "==> Mac local IP address(es):"
# List all IPv4 addresses that are not loopback.
ifconfig | awk '/inet / && !/127\.0\.0\.1/ {print "  " $2}'

echo ""
echo "==> Next steps:"
echo "  1. Start the Mac server:"
echo "       python mac/server.py --display 2"
echo "  2. Open the MacScreen app on your tablet."
echo "  3. In the app settings choose 'Wi-Fi' mode."
echo "  4. Enter the Mac IP address above and port ${PORT}."
echo "  5. Tap 'Connect'."
echo ""
echo "  Tip: for lower latency and a more stable connection use USB mode instead."
