#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
for candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys;sys.exit(sys.version_info < (3,11))' 2>/dev/null; then
    exec "$candidate" "$ROOT/tools/install.py" uninstall "$@"
  fi
done
echo "Python 3.11+ required" >&2
exit 1
