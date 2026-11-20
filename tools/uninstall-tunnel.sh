#!/bin/sh
# Remove only the dedicated FaceTime tunnel LaunchAgent.
# Preserves runtime credentials, profile, logs and existing tunnel services.
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec /usr/bin/python3 "$SCRIPT_DIR/facetime_tunnel_service.py" uninstall
