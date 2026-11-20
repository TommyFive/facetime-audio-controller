#!/usr/bin/env python3
"""Per-user configuration. Missing recipient always fails closed before dialing."""
import json
import os
from pathlib import Path
import re
import shutil

def config_dir():
    return Path(os.environ.get("FACETIME_CONFIG_DIR", str(Path.home()/".config/facetime-controller"))).expanduser()

def config_path():
    return Path(os.environ.get("FACETIME_CONFIG",str(config_dir()/"config.json"))).expanduser()

def load():
    path=config_path()
    if not path.exists():return {}
    if path.is_symlink() or not path.is_file():raise RuntimeError("CONFIG_UNSAFE_FILE")
    info=path.stat()
    if info.st_uid!=os.getuid() or info.st_mode&0o077:raise RuntimeError("CONFIG_UNSAFE_PERMISSIONS")
    try:data=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,ValueError) as exc:raise RuntimeError("CONFIG_INVALID") from exc
    if not isinstance(data,dict):raise RuntimeError("CONFIG_INVALID_ROOT")
    return data

def option(group,key,default=None):
    data=load().get(group,{})
    if not isinstance(data,dict):raise RuntimeError("CONFIG_INVALID_SECTION")
    return data.get(key,default)

def recipient():
    value=os.environ.get("FACETIME_RECIPIENT") or option("facetime","recipient","")
    if not isinstance(value,str):raise RuntimeError("RECIPIENT_INVALID")
    return value.strip()

def require_recipient():
    value=recipient()
    if not (re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",value) or re.fullmatch(r"\+[1-9][0-9]{5,15}",value)):
        raise RuntimeError("RECIPIENT_NOT_CONFIGURED_OR_INVALID")
    return value

def audio_device():
    value=option("audio","device","Loopback Audio")
    if not isinstance(value,str) or not 1<=len(value)<=100:raise RuntimeError("AUDIO_DEVICE_INVALID")
    return value

def state_dir():
    default=Path(os.environ.get("XDG_STATE_HOME",str(Path.home()/".local/state")))/"facetime-controller"
    return Path(os.environ.get("FACETIME_STATE_DIR",str(default))).expanduser()

def nanokvm_endpoint():
    url=os.environ.get("FACETIME_NANOKVM_ENDPOINT") or option("nanokvm","endpoint","")
    if not isinstance(url,str) or (url and not re.fullmatch(r"https://[A-Za-z0-9.-]+(?::[0-9]{2,5})?/api/mcp",url)):
        raise RuntimeError("NANOKVM_ENDPOINT_INVALID")
    return url

def kvm_auth_file():
    return Path(os.environ.get("FACETIME_NANOKVM_AUTH_FILE",str(config_dir()/"secrets/nanokvm-authorization"))).expanduser()

def minimax_key_file():
    return Path(os.environ.get("FACETIME_MINIMAX_KEY_FILE",str(config_dir()/"secrets/minimax.json"))).expanduser()

def tts_config_file(packaged):
    custom=os.environ.get("FACETIME_TTS_CONFIG")
    local=config_dir()/"tts.json"
    return Path(custom).expanduser() if custom else local if local.is_file() else Path(packaged)

def executable(name):
    found=shutil.which(name)
    if found:return found
    for folder in ("/opt/homebrew/bin","/usr/local/bin"):
        p=Path(folder)/name
        if p.is_file():return str(p)
    return name

if __name__=="__main__":
    import sys
    actions={"recipient":recipient,"audio-device":audio_device,"config-path":lambda:str(config_path()),"state-path":lambda:str(state_dir()),"nanokvm-endpoint":nanokvm_endpoint}
    if len(sys.argv)!=2 or sys.argv[1] not in actions:raise SystemExit(64)
    print(actions[sys.argv[1]]())
