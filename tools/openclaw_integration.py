#!/usr/bin/env python3
"""Optional, explicit native OpenClaw MCP registry integration.

Never edits OpenClaw config JSON manually. Its supported CLI owns the mutation.
Never restarts/stops production Gateway. Never launches a FaceTime call.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import time

NAME="facetime-controller"
TOOL_FILTER=[
    "facetime_capabilities","facetime_health","facetime_status",
    "facetime_call_start","facetime_call_wait","facetime_call_status",
    "facetime_call_cancel","facetime_hangup","facetime_speak",
]
# Exclude the legacy synchronous call by default to prevent long RPC timeouts.
def definition(current:Path):
    return dict(command=str(current/".venv/bin/python"),
                args=[str(current/"facetime-mcp-server.py")],
                cwd=str(current),enabled=True,
                requestTimeoutMs=60000,connectionTimeoutMs=15000,
                toolFilter={"include":TOOL_FILTER},
                supportsParallelToolCalls=False,
                codex={"defaultToolsApprovalMode":"prompt"})

def command_location(explicit=None):
    path=explicit or shutil.which("openclaw")
    if not path or not Path(path).is_file():
        raise RuntimeError("OpenClaw CLI not found. Install OpenClaw or supply --openclaw-cli with its absolute executable path")
    return str(Path(path).expanduser().resolve())

def cmd(binary,*args,timeout=25):
    p=subprocess.run([binary,*args],capture_output=True,text=True,timeout=timeout)
    return p

def backup_settings(destination:Path,source:Path):
    if not source.exists():return None
    info=source.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid():
        raise RuntimeError("OpenClaw config must be owned by the current user and not a symlink")
    destination.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    destination.parent.chmod(0o700)
    fd=os.open(destination,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,"wb") as f:f.write(source.read_bytes())
    return destination

def integrate(current:Path,config_dir:Path,*,cli_path=None,replace=False,openclaw_config=None):
    binary=command_location(cli_path)
    help_result=cmd(binary,"mcp","--help")
    if help_result.returncode!=0 or "set" not in (help_result.stdout+help_result.stderr):
        raise RuntimeError("This OpenClaw CLI does not support the native 'openclaw mcp set' registry")
    show=cmd(binary,"mcp","show",NAME,"--json")
    already=show.returncode==0
    if already and not replace:
        raise RuntimeError("MCP server already registered; use --replace-openclaw-mcp after inspecting the existing entry")
    config_path=Path(openclaw_config or os.environ.get("OPENCLAW_CONFIG_PATH",str(Path.home()/".openclaw/openclaw.json"))).expanduser()
    stamp=time.strftime("%Y%m%d-%H%M%S")
    backup=backup_settings(config_dir/"backups"/("openclaw-"+stamp+".json5"),config_path)
    payload=json.dumps(definition(current),separators=(",",":"))
    result=cmd(binary,"mcp","set",NAME,payload,timeout=30)
    if result.returncode!=0:
        raise RuntimeError("OpenClaw rejected the MCP registry entry (existing configuration unchanged or needs manual verification)")
    static=cmd(binary,"mcp","doctor",NAME,timeout=30)
    if static.returncode!=0:
        # Do not overwrite shared OpenClaw configuration or unconditionally
        # delete a pre-existing registration. Leave a documented repair path.
        raise RuntimeError("OpenClaw MCP entry saved, but doctor rejected it; inspect the backed-up config before correcting")
    report={"installed":True,"server":NAME,"backup":str(backup) if backup else None,
            "gateway_restarted":False,"notes":"OpenClaw manages hot-reload; start a new agent session before testing tool discovery."}
    return report

def verify_no_call(cli_path=None):
    binary=command_location(cli_path)
    result=cmd(binary,"mcp","probe",NAME,"--json",timeout=50)
    # Probe opens an MCP connection and enumerates tools, never calls them.
    if result.returncode!=0 or "facetime_call_start" not in result.stdout or "facetime_health" not in result.stdout:
        raise RuntimeError("OpenClaw MCP tool discovery incomplete. Check invoking user/session and the server tool filter.")
    return True
