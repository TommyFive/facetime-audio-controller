#!/usr/bin/env python3
"""Guided, non-destructive FaceTime Controller configuration planning.

Importing this module has no side effects. Secret material is never put in a
command line, output or tracked source, and the wizard itself writes nothing.
"""
from __future__ import annotations
import copy
import getpass
import json
import os
from pathlib import Path
import re
import stat
import sys

MODELS={"turbo":"speech-2.8-turbo","hd":"speech-2.8-hd"}
ENDPOINTS={"international":"https://api.minimax.io/v1/t2a_v2",
           "china":"https://api.minimaxi.com/v1/t2a_v2"}
SAFE_VOICE=re.compile(r"[A-Za-z0-9_() \-]{3,100}")
SAFE_DEVICE=re.compile(r"[A-Za-z0-9_. ()+-]{1,100}")
SAFE_RECIPIENT=re.compile(r"(?:[^\s@]+@[^\s@]+\.[^\s@]+|\+[1-9][0-9]{5,15})")
SAFE_KVM=re.compile(r"https://[A-Za-z0-9.-]+(?::[0-9]{2,5})?/api/mcp")

def prompt(message,default=""):
    suffix=f" [{default}]" if default else ""
    result=input(f"{message}{suffix}: ").strip()
    return result if result else str(default)

def choose(title,options,default):
    print("\n"+title)
    for i,(value,label) in enumerate(options,1):
        print(f"  {i}) {label}"+(" (default)" if value==default else ""))
    while True:
        val=prompt("Selection",str(1+next(i for i,(v,_) in enumerate(options) if v==default)))
        if val.isdigit() and 1<=int(val)<=len(options):
            return options[int(val)-1][0]
        if val in {v for v,_ in options}:return val
        print("Invalid option. Please choose one of the listed values.")

def yesno(question,default=False):
    suffix="Y/n" if default else "y/N"
    while True:
        value=input(f"{question} [{suffix}]: ").strip().lower()
        if not value:return default
        if value in ("y","yes"):return True
        if value in ("n","no"):return False
        print("Please enter y or n.")

def floating(message,default,minimum,maximum):
    while True:
        raw=prompt(message,str(default))
        try:value=float(raw)
        except ValueError:print("A number is required.");continue
        if minimum<=value<=maximum:return value
        print(f"Value must be between {minimum} and {maximum}.")

def integer(message,default,minimum,maximum):
    while True:
        raw=prompt(message,str(default))
        try:value=int(raw)
        except ValueError:print("An integer is required.");continue
        if minimum<=value<=maximum:return value
        print(f"Value must be between {minimum} and {maximum}.")

def load_existing(path:Path):
    if not path.exists():return None
    if path.is_symlink() or not path.is_file():raise RuntimeError("Unsafe existing config file")
    info=path.stat()
    if info.st_uid!=os.getuid() or info.st_mode&0o077:raise RuntimeError("Config must be owned by this user and mode 0600")
    content=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(content,dict):raise RuntimeError("Config must be a JSON object")
    return content

def secret_source(path:Path):
    info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:
        raise RuntimeError("Secret input must be an owner-owned regular file with mode 0600")
    return path.read_bytes()

def plan(args,p,root:Path):
    interactive=not args.non_interactive
    config_file=p["config"]/"config.json"
    tts_file=p["config"]/"tts.json"
    old_config=load_existing(config_file)
    old_tts=load_existing(tts_file)
    core=copy.deepcopy(old_config or {})
    speech=copy.deepcopy(old_tts or json.loads((root/"tts-config.json").read_text()))
    existing=bool(old_config)
    print("\n=== FaceTime Audio Controller Setup ===")
    print("Existing settings will be displayed without revealing secrets and preserved unless explicitly changed.")
    if existing and interactive:
        reconfigure=yesno("Update existing settings?",False)
    else:reconfigure=not existing or bool(args.reconfigure)
    if existing and args.reconfigure:reconfigure=True

    current=core.get("facetime",{}).get("recipient","")
    if not isinstance(current,str):raise RuntimeError("Invalid existing recipient")
    if args.recipient:
        destination=args.recipient
        if existing and destination!=current and not (args.reconfigure or reconfigure):
            raise RuntimeError("Changing recipient requires --reconfigure")
    elif interactive and reconfigure:
        destination=prompt("Fixed FaceTime recipient (Apple ID email or E.164 phone)",current)
    else:destination=current
    if not isinstance(destination,str) or not SAFE_RECIPIENT.fullmatch(destination):
        raise RuntimeError("A valid fixed FaceTime recipient is required")
    core.setdefault("facetime",{})["recipient"]=destination
    if existing and current and destination!=current and interactive:
        if not yesno("Recipient changed. This changes who will receive real calls. Confirm?",False):
            raise RuntimeError("Recipient change cancelled")

    current_audio=core.get("audio",{}).get("device","Loopback Audio")
    audio=args.audio_device or (prompt("Virtual audio device name",current_audio) if interactive and reconfigure else current_audio)
    if not isinstance(audio,str) or not SAFE_DEVICE.fullmatch(audio):
        raise RuntimeError("Invalid audio device name")
    core.setdefault("audio",{})["device"]=audio

    old_provider=speech.get("provider","macos") if old_tts else "macos"
    provider=args.tts_provider or (choose("Speech provider",[("macos","macOS local speech (no cloud/API key)"),("minimax","MiniMax cloud speech (API key required)")],old_provider) if interactive and reconfigure else old_provider)
    if provider not in ("macos","minimax"):raise RuntimeError("Invalid TTS provider")
    speech["provider"]=provider
    if provider=="macos" and args.test_tts:
        raise RuntimeError("--test-tts requires MiniMax, and may incur API charges")
    if provider=="macos" and (args.minimax_model or args.minimax_region or args.minimax_key_file
                              or args.max_characters is not None):
        raise RuntimeError("MiniMax-specific options cannot be used with macOS local speech")
    if provider=="minimax" and (args.macos_rate is not None or args.macos_max_characters is not None):
        raise RuntimeError("macOS-specific speech options cannot be used with MiniMax")
    if provider=="minimax":
        mm=speech["minimax"]
        default_model=next((key for key,value in MODELS.items() if mm.get("model")==value),"turbo")
        selected=args.minimax_model or (choose("MiniMax model",[("turbo","Speech 2.8 Turbo - maximum 10,000 characters"),("hd","Speech 2.8 HD - maximum 5,000 characters")],default_model) if interactive and reconfigure else default_model)
        mm["model"]=MODELS[selected]
        region=args.minimax_region or (choose("MiniMax account region",[("international","International (api.minimax.io)"),("china","China mainland (api.minimaxi.com)")],next((r for r,v in ENDPOINTS.items() if v==mm.get("endpoint")),"international")) if interactive and reconfigure else next((r for r,v in ENDPOINTS.items() if v==mm.get("endpoint")),"international"))
        mm["endpoint"]=ENDPOINTS[region]
        mm["voice_id"]=args.tts_voice or (prompt("Voice ID",mm.get("voice_id","German_FriendlyMan")) if interactive and reconfigure else mm.get("voice_id","German_FriendlyMan"))
        mm["speed"]=args.tts_speed if args.tts_speed is not None else floating("Speech speed",mm.get("speed",1.1),.5,2.0) if interactive and reconfigure else mm.get("speed",1.1)
        mm["volume"]=args.tts_volume if args.tts_volume is not None else floating("Volume",mm.get("volume",1),.01,10) if interactive and reconfigure else mm.get("volume",1)
        mm["pitch"]=args.tts_pitch if args.tts_pitch is not None else integer("Pitch",mm.get("pitch",0),-12,12) if interactive and reconfigure else mm.get("pitch",0)
        if not SAFE_VOICE.fullmatch(mm["voice_id"]):raise RuntimeError("Invalid MiniMax voice ID")
        cap=10000 if selected=="turbo" else 5000
        override=args.max_characters if args.max_characters is not None else integer("Maximum characters for selected model",min(mm.get("max_characters_by_model",{}).get(mm["model"],cap),cap),1,cap) if interactive and reconfigure else min(mm.get("max_characters_by_model",{}).get(mm["model"],cap),cap)
        if not (isinstance(override,int) and 1<=override<=cap):
            raise RuntimeError(f"Maximum characters must be 1..{cap} for the selected model")
        mm.setdefault("max_characters_by_model",{})[mm["model"]]=override
    else:
        mac=speech["macos"]
        mac["voice"]=args.tts_voice or (prompt("macOS voice",mac.get("voice","Anna")) if interactive and reconfigure else mac.get("voice","Anna"))
        mac["rate"]=args.macos_rate if args.macos_rate is not None else integer("macOS speech rate",mac.get("rate",165),80,400) if interactive and reconfigure else mac.get("rate",165)
        if args.macos_max_characters is not None:
            if not 1<=args.macos_max_characters<=100000:raise RuntimeError("macOS character limit must be 1..100000")
            mac["max_characters"]=args.macos_max_characters
        elif interactive and reconfigure:
            current_cap=mac.get("max_characters")
            response=prompt("macOS max characters (empty means no model-specific cap)",
                            str(current_cap) if current_cap is not None else "")
            if response:
                try:cap=int(response)
                except ValueError:raise RuntimeError("macOS character limit must be an integer")
                if not 1<=cap<=100000:raise RuntimeError("macOS character limit must be 1..100000")
                mac["max_characters"]=cap
            else:mac["max_characters"]=None

    prev_endpoint=core.get("nanokvm",{}).get("endpoint","")
    nano_opt=args.nanokvm if args.nanokvm is not None else (yesno("Use NanoKVM for calls while the Mac is locked?",bool(prev_endpoint)) if interactive and reconfigure else bool(prev_endpoint))
    if not nano_opt and (args.nanokvm_endpoint or args.nanokvm_auth_file):
        raise RuntimeError("NanoKVM endpoint/credential specified while NanoKVM is disabled")
    endpoint=(args.nanokvm_endpoint or prev_endpoint) if nano_opt else ""
    if nano_opt and interactive and reconfigure and not args.nanokvm_endpoint:
        endpoint=prompt("Authorized NanoKVM HTTPS MCP endpoint, ending /api/mcp",endpoint)
    if nano_opt and (not isinstance(endpoint,str) or not SAFE_KVM.fullmatch(endpoint)):
        raise RuntimeError("NanoKVM requires an authorized HTTPS endpoint ending /api/mcp")
    core.setdefault("nanokvm",{})["endpoint"]=endpoint
    if not nano_opt:
        print("\nIMPORTANT: Without NanoKVM, unattended FaceTime UI control works ONLY while the Mac session remains unlocked.")
        print("An automatic lock can prevent or interrupt scheduled calls. Never disable the macOS lock screen automatically.")
        accepted=args.accept_unlocked_only or (yesno("Accept unlocked-session-only operation?",False) if interactive else False)
        if not accepted:raise RuntimeError("Explicit --accept-unlocked-only is required without NanoKVM")

    integration=args.openclaw if args.openclaw is not None else (yesno("Register MCP server with installed OpenClaw?",False) if interactive and reconfigure else False)
    if not integration and (args.openclaw_cli or args.replace_openclaw_mcp or args.openclaw_config):
        raise RuntimeError("OpenClaw configuration options specified while OpenClaw integration is disabled")
    agent_file=p.get("launchagent")
    watchdog_default=bool(integration or (agent_file and agent_file.is_file()))
    watchdog=args.watchdog if args.watchdog is not None else (yesno("Enable independent 30-second async hangup watchdog?",watchdog_default) if interactive and reconfigure else watchdog_default)
    if integration and not watchdog:
        print("WARNING: Disabling the watchdog removes detached-worker crash recovery. Do not rely on unattended calls.")
        if interactive and not yesno("Continue without watchdog?",False):raise RuntimeError("Watchdog is recommended for unattended MCP calls")
    print("MCP stdio server is started on demand by OpenClaw; no always-running MCP daemon is required.")

    from importlib.util import spec_from_file_location,module_from_spec
    if str(root) not in sys.path:sys.path.insert(0,str(root))
    spec=spec_from_file_location("facetime-tts-setup-validator",root/"facetime-tts.py")
    validation=module_from_spec(spec);spec.loader.exec_module(validation)
    validation.config_load_data(speech)

    secret=None
    source=args.minimax_key_file
    if source:
        raw=secret_source(Path(source).expanduser())
        try:secret=json.loads(raw.decode())["minimaxApiKey"]
        except (UnicodeError,KeyError,ValueError,TypeError):raise RuntimeError("Invalid MiniMax key source JSON")
    elif provider=="minimax" and interactive and reconfigure:
        secret_file=p["config"]/"secrets/minimax.json"
        if not secret_file.exists() or yesno("Replace existing MiniMax API key?",False):
            secret=getpass.getpass("MiniMax API key (hidden, leave blank to keep existing): ").strip()
            if not secret:secret=None
    if secret is not None and (not isinstance(secret,str) or len(secret)<30 or "\n" in secret or "\r" in secret):
        raise RuntimeError("MiniMax key must be a single line of at least 30 characters")
    if provider=="minimax" and not secret:
        existing_key=p["config"]/"secrets/minimax.json"
        if existing_key.is_file():
            raw=secret_source(existing_key)
            try:
                key=json.loads(raw.decode("utf-8")).get("minimaxApiKey")
            except (ValueError,TypeError,UnicodeError) as exc:
                raise RuntimeError("Existing MiniMax key file is invalid") from exc
            if not isinstance(key,str) or len(key)<30 or "\n" in key or "\r" in key:
                raise RuntimeError("Existing MiniMax key file is invalid")
        else:raise RuntimeError("MiniMax selected but no owner-only API key was provided")

    kvm_secret=args.nanokvm_auth_file
    if nano_opt and interactive and reconfigure and not kvm_secret:
        if not (p["config"]/"secrets/nanokvm-authorization").exists():
            kvm_secret=prompt("Existing local NanoKVM bearer file (0600)", "")
    if nano_opt and kvm_secret:
        kvm_secret=str(Path(kvm_secret).expanduser())
        raw=secret_source(Path(kvm_secret))
        if not raw.strip().startswith(b"Bearer ") or b"\n" in raw.strip() or len(raw)>300:
            raise RuntimeError("NanoKVM authorization must be a valid Bearer token")
    if nano_opt and not kvm_secret:
        existing_bearer=p["config"]/"secrets/nanokvm-authorization"
        if not existing_bearer.is_file():
            raise RuntimeError("NanoKVM requires a local 0600 bearer file")
        raw=secret_source(existing_bearer).strip()
        if not raw.startswith(b"Bearer ") or b"\n" in raw or len(raw)>300:
            raise RuntimeError("Existing NanoKVM bearer file is invalid")
    if interactive and not yesno("\nSave these settings and install (no phone call will be placed)?",True):
        raise RuntimeError("Installation cancelled")

    return dict(core=core,tts=speech,secret=secret,nanokvm_secret=kvm_secret,
                integration=bool(integration),watchdog=bool(watchdog),nanokvm=bool(nano_opt),
                needs_tts_check=bool(args.test_tts or (interactive and provider=="minimax" and yesno("Validate MiniMax with a short paid/no-call speech API test?",False))),
                permissions=bool(args.check_permissions or interactive))
