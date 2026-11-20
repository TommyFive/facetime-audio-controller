#!/usr/bin/env python3
"""Check whether the logged-in console user has an unlocked macOS GUI session.

Read-only IOKit state. Fail closed on unavailable/ambiguous session information.
"""
import os
import pwd
import plistlib
import subprocess
import sys

try:
    proc = subprocess.run(
        ["/usr/sbin/ioreg", "-n", "Root", "-d", "1", "-a"],
        capture_output=True, timeout=5, check=True
    )
    info = plistlib.loads(proc.stdout)
    candidates = [
        user for user in info.get("IOConsoleUsers", [])
        if isinstance(user, dict) and user.get("kCGSSessionOnConsoleKey") is True
    ]
    if len(candidates) != 1:
        print("GUI_UNKNOWN reason=no-single-console-session")
        sys.exit(75)
    user = candidates[0]
    if user.get("kCGSSessionUserNameKey") != pwd.getpwuid(os.getuid()).pw_name:
        print("GUI_UNKNOWN reason=other-console-user")
        sys.exit(75)
    if user.get("CGSSessionScreenIsLocked") is True or info.get("IOConsoleLocked") is True:
        print("GUI_LOCKED")
    elif user.get("kCGSessionLoginDoneKey") is True:
        print("GUI_UNLOCKED")
    else:
        print("GUI_UNKNOWN reason=login-not-complete")
        sys.exit(75)
except Exception as exc:
    print("GUI_UNKNOWN reason=" + type(exc).__name__)
    sys.exit(75)
