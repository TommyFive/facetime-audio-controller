#!/bin/sh
# Read-only status inspection; no FaceTime call.
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec /usr/bin/python3 "$SCRIPT_DIR/facetime_tunnel_service.py" status
