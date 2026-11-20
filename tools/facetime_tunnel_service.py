#!/usr/bin/env python3
"""Manage the dedicated FaceTime Secure MCP Tunnel LaunchAgent.

Never writes or reads secret contents. Never calls FaceTime.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

LABEL = "com.openai.tunnel-client.facetime-mcp"
PROFILE = "facetime-mcp"
TUNNEL_ID = os.environ.get("FACETIME_TUNNEL_ID", "")
CLIENT = Path(__import__("shutil").which("tunnel-client") or "/opt/homebrew/bin/tunnel-client")


def paths(home: Path) -> dict[str, Path]:
    base = home / ".config" / "tunnel-client"
    return {
        "config": base / f"{PROFILE}.yaml",
        "secret": base / "secrets" / "facetime-control-plane.key",
        "url": base / "facetime-health.url",
        "plist": home / "Library" / "LaunchAgents" / f"{LABEL}.plist",
        "logs": home / "Library" / "Logs" / "facetime-mcp-tunnel",
        "project": Path(__file__).resolve().parents[1],
    }


def service() -> str:
    return f"gui/{os.getuid()}/{LABEL}"


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=check, timeout=20)


def plist(home: Path) -> bytes:
    p = paths(home)
    spec = {
        "Label": LABEL,
        "ProgramArguments": [
            str(CLIENT), "run", "--profile", PROFILE,
            "--health.url-file", str(p["url"]),
            "--log.level", "warn",
        ],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 15,
        "WorkingDirectory": str(p["project"]),
        "StandardOutPath": str(p["logs"] / "stdout.log"),
        "StandardErrorPath": str(p["logs"] / "stderr.log"),
        "Umask": 0o077,
        "EnvironmentVariables": {
            "HOME": str(home),
            "USER": os.environ.get("USER", home.name),
            "PATH": "/opt/homebrew/opt/node@24/bin:/opt/homebrew/bin:/usr/bin:/bin",
        },
    }
    return plistlib.dumps(spec, sort_keys=True)


def secure_file(p: Path, label: str) -> None:
    if p.is_symlink() or not p.is_file():
        raise RuntimeError(f"{label} missing or symlink: {p}")
    st = p.stat()
    if st.st_uid != os.getuid() or (st.st_mode & 0o077):
        raise RuntimeError(f"{label} must belong to current user and forbid group/other access: {p}")


def validate(home: Path) -> None:
    p = paths(home)
    if sys.platform != "darwin":
        raise RuntimeError("launchd installation requires macOS")
    if not CLIENT.is_file() or not os.access(CLIENT, os.X_OK):
        raise RuntimeError(f"tunnel-client not executable: {CLIENT}")
    secure_file(p["config"], "Tunnel profile")
    secure_file(p["secret"], "Runtime credential")
    python = p["project"] / ".venv" / "bin" / "python"
    target = p["project"] / "facetime-mcp-server.py"
    if not os.access(python, os.X_OK) or not target.is_file():
        raise RuntimeError("FaceTime Python MCP server or virtualenv missing")
    profile_text = p["config"].read_text()
    if not TUNNEL_ID or TUNNEL_ID not in profile_text or str(p["secret"]) not in profile_text:
        raise RuntimeError("FaceTime tunnel profile does not reference expected tunnel ID/secret path")
    if str(python) not in profile_text or str(target) not in profile_text:
        raise RuntimeError("FaceTime stdio command differs from expected production paths")
    # Proactively reject an extra manually launched daemon to avoid two pollers.
    proc = run("/bin/ps", "-axo", "command", check=False)
    matches = [line for line in proc.stdout.splitlines()
               if "tunnel-client run --profile facetime-mcp" in line
               and "facetime_tunnel_service.py" not in line]
    if matches:
        raise RuntimeError("An existing foreground facetime-mcp tunnel is running. Stop it with Ctrl+C first.")


def local_url(home: Path) -> str | None:
    f = paths(home)["url"]
    if f.is_symlink() or not f.is_file() or f.stat().st_uid != os.getuid():
        return None
    url = f.read_text().strip()
    if not url.startswith("http://127.0.0.1:"):
        return None
    return url.rstrip("/")


def readiness(home: Path) -> tuple[bool, str]:
    url = local_url(home)
    if not url:
        return False, "Health URL is not yet available"
    try:
        with urlopen(url + "/readyz", timeout=4) as r:
            return r.status == 200, f"readyz HTTP {r.status}"
    except (URLError, TimeoutError, OSError) as e:
        return False, f"readyz unavailable ({type(e).__name__})"


def install(home: Path) -> int:
    validate(home)
    p = paths(home)
    if p["plist"].exists() or p["plist"].is_symlink():
        raise RuntimeError(f"Existing LaunchAgent will not be overwritten: {p['plist']}")
    current = run("/bin/launchctl", "print", service(), check=False)
    if current.returncode == 0:
        raise RuntimeError("LaunchAgent is already loaded. Refusing conflicting installation.")
    p["plist"].parent.mkdir(parents=True, exist_ok=True)
    p["logs"].mkdir(parents=True, exist_ok=True, mode=0o700)
    p["logs"].chmod(0o700)
    for name in ("stdout.log", "stderr.log"):
        log = p["logs"] / name
        if log.is_symlink():
            raise RuntimeError(f"Refusing symlinked log file: {log}")
        fd = os.open(log, os.O_CREAT | os.O_APPEND | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        log.chmod(0o600)
    p["url"].unlink(missing_ok=True) if not p["url"].is_symlink() else None
    if p["url"].is_symlink():
        raise RuntimeError("Refusing symlinked health URL path")
    data = plist(home)
    tmp = p["plist"].with_suffix(".plist.pending")
    if tmp.exists() or tmp.is_symlink():
        raise RuntimeError("Temporary LaunchAgent path already exists")
    try:
        with tmp.open("xb") as f:
            f.write(data)
        tmp.chmod(0o600)
        run("/usr/bin/plutil", "-lint", str(tmp))
        os.replace(tmp, p["plist"])
        result = run("/bin/launchctl", "bootstrap", f"gui/{os.getuid()}", str(p["plist"]), check=False)
        if result.returncode:
            raise RuntimeError(f"launchctl bootstrap failed: {result.stderr.strip()}")
    except Exception:
        tmp.unlink(missing_ok=True)
        run("/bin/launchctl", "bootout", service(), check=False)
        p["plist"].unlink(missing_ok=True)
        raise
    print(f"LaunchAgent installed: {LABEL}")
    for _ in range(20):
        ok, detail = readiness(home)
        if ok:
            print("READY:", detail)
            return 0
        time.sleep(1)
    print("Launched, but readiness not confirmed; inspect local logs and tunnel permissions.")
    return 2


def status(home: Path) -> int:
    p = paths(home)
    r = run("/bin/launchctl", "print", service(), check=False)
    print("LaunchAgent loaded:", r.returncode == 0)
    print("Plist installed:", p["plist"].is_file())
    ok, reason = readiness(home)
    print("Tunnel ready:", ok, reason)
    print("Health URL:", local_url(home) or "(not available)")
    return 0 if r.returncode == 0 and ok else 2


def uninstall(home: Path) -> int:
    p = paths(home)
    if p["plist"].is_symlink():
        raise RuntimeError("Refusing symlinked LaunchAgent")
    if p["plist"].is_file():
        old = plistlib.loads(p["plist"].read_bytes())
        if old.get("Label") != LABEL:
            raise RuntimeError("LaunchAgent file has an unexpected label")
    active = run("/bin/launchctl", "print", service(), check=False)
    if active.returncode == 0:
        stopped = run("/bin/launchctl", "bootout", service(), check=False)
        if stopped.returncode != 0:
            raise RuntimeError("launchctl bootout failed; preserving plist for safe retry: " + stopped.stderr.strip())
        if run("/bin/launchctl", "print", service(), check=False).returncode == 0:
            raise RuntimeError("LaunchAgent still loaded; refusing to delete plist")
    p["plist"].unlink(missing_ok=True)
    if p["url"].is_symlink():
        raise RuntimeError("Refusing symlinked health URL path")
    p["url"].unlink(missing_ok=True)
    print("FaceTime tunnel LaunchAgent removed.")
    print("Tunnel profile, secret, logs, OpenClaw and other services preserved.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "status", "uninstall", "print-plist"))
    args = parser.parse_args()
    try:
        home = Path.home()
        if args.action == "print-plist":
            sys.stdout.buffer.write(plist(home))
            return 0
        if args.action == "install":
            return install(home)
        if args.action == "status":
            return status(home)
        return uninstall(home)
    except (OSError, subprocess.TimeoutExpired, RuntimeError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
