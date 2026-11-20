#!/bin/sh
# Install the dedicated FaceTime Secure MCP Tunnel LaunchAgent.
# Only run after ending the foreground tunnel with Ctrl+C.
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec /usr/bin/python3 "$SCRIPT_DIR/facetime_tunnel_service.py" install
