#!/usr/bin/env python3
"""Single user-facing CLI for the FaceTime controller.

This is a pure argument router, not a second implementation of calling,
diagnostics or usage accounting. Never construct a shell command with user
supplied text. Replace the current process so signals and exit codes flow
unchanged to the original controller/doctor/stats entrypoint.
"""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
COMMANDS = {
    "call": ("facetime-call.sh", "--call"),
    "speak": ("facetime-call.sh", "--speak"),
    "status": ("facetime-call.sh", "--status"),
    "hangup": ("facetime-call.sh", "--hangup"),
    "cancel-pending": ("facetime-call.sh", "--cancel-pending"),
    "recover": ("facetime-call.sh", "--recover"),
    "confirm": ("facetime-call.sh", "--confirm"),
    "dial": ("facetime-call.sh", "--dial"),
    "dry-run": ("facetime-call.sh", "--dry-run"),
    "doctor": ("tools/doctor.py",),
    "stats": ("tools/usage.py",),
}

HELP = """FaceTime Controller - unified local CLI

Usage:
  facetime-controller call [TTS options] "text"    Make one FaceTime Audio call
  facetime-controller speak [TTS options] "text"   Render and play speech (no call)
  facetime-controller status                       Inspect call/GUI status
  facetime-controller stats [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--json]
                                                   Local privacy-safe usage report
  facetime-controller doctor [--permissions]      Read-only system diagnostics
  facetime-controller hangup [--timeout SECONDS]  Priority hangup
  facetime-controller cancel-pending               Priority cancel
  facetime-controller recover                      Safe recovery
  facetime-controller confirm [--timeout SECONDS] Confirm pending UI
  facetime-controller dial [options]              Advanced dial-only mode
  facetime-controller dry-run                     Check prerequisites
  facetime-controller help                        This help message

Legacy 'facetime-call' and 'facetime-controller-doctor' commands are supported.
MCP tools and the secure tunnel are unaffected by this local CLI router.
"""

def dispatch(argv):
    if not argv or argv[0] in ("help", "--help", "-h"):
        if len(argv) > 1:
            print("Unexpected arguments to help.", file=sys.stderr)
            return 64
        print(HELP, end="")
        return 0
    name, *extra = argv
    if name not in COMMANDS:
        print(f"Unknown FaceTime Controller command: {name!r}. Use 'help'.",
              file=sys.stderr)
        return 64
    target, *pre_args = COMMANDS[name]
    target_path = ROOT / target
    if not target_path.is_file():
        print("FaceTime Controller component missing.", file=sys.stderr)
        return 70
    if target.endswith(".py"):
        executable = sys.executable
        arguments = [executable, str(target_path), *extra]
    else:
        executable = str(target_path)
        arguments = [executable, *pre_args, *extra]
    os.execv(executable, arguments)
    return 70


def main():
    return dispatch(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
