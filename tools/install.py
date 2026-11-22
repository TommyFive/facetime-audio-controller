#!/usr/bin/env python3
"""Safe, per-user macOS installer and maintenance for FaceTime Audio Controller.

All changes are under user-owned paths. No sudo, no FaceTime calls.
The optional Watchdog LaunchAgent belongs exclusively to this package.
"""
from __future__ import annotations
import argparse
import getpass
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import time
import venv
import tempfile
import shlex
# Permit safe importlib-based loading by the unit suite, not just CLI execution.
sys.path.insert(0,str(Path(__file__).resolve().parent))
import setup_wizard
import openclaw_integration

ROOT=Path(__file__).resolve().parents[1]
LABEL="com.facetime-controller.async-watchdog"
PACKAGE="facetime-controller"
SOURCE_FILES=[
    "facetime_runtime.py","facetime-call.sh","facetime-call-fast.py",
    "facetime-ax-control.applescript","facetime-gui-session.py",
    "facetime-display-wake.py","facetime-permissions.py",
    "facetime-audio-health.py","facetime-vision-ocr.swift",
    "facetime-tts.py","facetime-say.sh","facetime_txn.py","facetime_usage.py",
    "facetime-priority.py","facetime-mcp-server.py",
    "facetime-async-watchdog.py","facetime_async_worker.py","nanokvm-mcp-bridge.py",
    "nanokvm-popup-detector.py","nanokvm-call-ui.py",
    "tts-config.json","requirements.txt",
]
TOOLS=["provision-nanokvm-auth.py","facetime_tunnel_service.py",
       "install-tunnel.sh","uninstall-tunnel.sh","status-tunnel.sh",
       "doctor.py","usage.py","cli.py",
       "install.py","setup_wizard.py","openclaw_integration.py"]

def run(*command,**opts):
    return subprocess.run(list(map(str,command)),check=True,**opts)

def private_write(path:Path,data:bytes,overwrite=False):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if path.parent.name=="secrets":path.parent.chmod(0o700)
    if path.is_symlink():raise RuntimeError("Refusing symlink configuration: "+str(path))
    if path.exists() and not overwrite:return False
    import tempfile
    fd,tmp=tempfile.mkstemp(prefix=".facetime-",dir=str(path.parent))
    try:
        with os.fdopen(fd,"wb") as file:
            os.fchmod(file.fileno(),0o600)
            file.write(data);file.flush();os.fsync(file.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    return True

def paths(args):
    home=Path.home()
    base=Path(args.prefix).expanduser() if args.prefix else home/".local/share/facetime-controller"
    cfg=Path(os.environ.get("FACETIME_CONFIG_DIR",str(home/".config/facetime-controller"))).expanduser()
    return dict(base=base,versions=base/"versions",current=base/"current",
                config=cfg,bin=Path(os.environ.get("FACETIME_BIN_DIR",str(home/".local/bin"))).expanduser(),
                launchagent=home/"Library/LaunchAgents"/(LABEL+".plist"),
                log=Path(os.environ.get("FACETIME_STATE_DIR",str(home/".local/state/facetime-controller"))).expanduser()/"watchdog.log")

def requirements():
    if sys.platform!="darwin":
        raise RuntimeError("Installation is supported only on macOS")
    if sys.version_info<(3,11):
        raise RuntimeError("Python 3.11+ required (install Homebrew Python and retry)")
    if not Path("/System/Applications/FaceTime.app").exists():
        raise RuntimeError("FaceTime application missing")
    if not shutil.which("ffmpeg") and not Path("/opt/homebrew/bin/ffmpeg").exists():
        raise RuntimeError("FFmpeg missing; install it first using: brew install ffmpeg")
    if not shutil.which("swiftc") and not Path("/usr/bin/swiftc").exists():
        raise RuntimeError("Swift compiler not available; install Xcode Command Line Tools")
    if not os.access(Path.home(),os.W_OK):
        raise RuntimeError("HOME is not writable")

def recipient_check(value:str):
    return bool(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",value) or re.fullmatch(r"\+[1-9][0-9]{5,15}",value))

def write_settings(settings,p):
    """Update only private config/credentials and retain previous bytes for safe rollback."""
    originals={}
    files={p["config"]/"config.json":json.dumps(settings["core"],indent=2,ensure_ascii=False).encode()+b"\n",
           p["config"]/"tts.json":json.dumps(settings["tts"],indent=2,ensure_ascii=False).encode()+b"\n"}
    if settings["secret"]:
        files[p["config"]/"secrets/minimax.json"]=json.dumps(
            {"minimaxApiKey":settings["secret"]}).encode()+b"\n"
    if settings["nanokvm_secret"]:
        source=Path(settings["nanokvm_secret"]).expanduser()
        files[p["config"]/"secrets/nanokvm-authorization"]=source.read_bytes().strip()+b"\n"
    try:
        for file,data in files.items():
            if file.exists() and file.read_bytes()==data:continue
            originals[file]=file.read_bytes() if file.exists() else None
            private_write(file,data,overwrite=True)
        p["config"].chmod(0o700)
    except Exception:
        restore_settings(originals)
        raise
    return originals

def restore_settings(originals):
    for path,previous in reversed(list(originals.items())):
        if previous is None:path.unlink(missing_ok=True)
        else:private_write(path,previous,overwrite=True)

def test_minimax_no_call(current,settings):
    """Explicit optional paid provider test; does not dial FaceTime."""
    spec=__import__("importlib.util",fromlist=["spec_from_file_location"])
    module_spec=spec.spec_from_file_location("facetime_tts_installer",current/"facetime-tts.py")
    renderer=spec.module_from_spec(module_spec)
    module_spec.loader.exec_module(renderer)
    with tempfile.TemporaryDirectory(prefix="facetime-install-tts-") as tmp:
        target=Path(tmp)/"test.aiff"
        try:
            result=renderer.render("This is a short installation test.",settings["tts"],target,provider="minimax")
        except renderer.TTSError as exc:
            raise RuntimeError("MiniMax TTS verification failed: "+exc.code) from None
        if result.get("fallback") or result.get("provider")!="minimax":
            raise RuntimeError("MiniMax TTS verification used fallback; API key/model was not verified")
    print("MiniMax TTS API verified without placing a FaceTime call.")

def copy_source(dst:Path):
    dst.mkdir(parents=True,exist_ok=False)
    for name in SOURCE_FILES:
        source=ROOT/name
        if not source.is_file():raise RuntimeError("Missing source: "+name)
        shutil.copy2(source,dst/name)
    (dst/"tools").mkdir()
    for name in TOOLS:
        shutil.copy2(ROOT/"tools"/name,dst/"tools"/name)
    for name in ("facetime-call.sh","facetime-say.sh"):
        (dst/name).chmod(0o755)

def create_venv(dst:Path,skip_deps:bool):
    venv.EnvBuilder(with_pip=not skip_deps).create(dst/".venv")
    python=dst/".venv/bin/python"
    if not skip_deps:
        run(python,"-m","pip","install","--disable-pip-version-check","-r",dst/"requirements.txt")
    return python

def compile_ocr(dst:Path):
    binary=dst/".bin/facetime-vision-ocr"
    binary.parent.mkdir(exist_ok=True)
    swift=shutil.which("swiftc") or "/usr/bin/swiftc"
    run(swift,dst/"facetime-vision-ocr.swift","-o",binary)
    binary.chmod(0o700)

def wrapper(path:Path,current:Path,command:str):
    """Create a shell launcher; quote argv tokens individually (also with spaces)."""
    executable=([str(current/".venv/bin/python"),str(current/command)]
                if command.endswith(".py") else [str(current/command)])
    contents="#!/bin/sh\nexec "+" ".join(shlex.quote(part) for part in executable)+' "$@"\n'
    if path.is_symlink():
        raise RuntimeError("Refusing symlink wrapper: "+str(path))
    if path.exists() and not path.is_file():
        raise RuntimeError("Cannot overwrite non-file wrapper")
    if path.exists() and str(current) not in path.read_text():
        raise RuntimeError("Refusing to overwrite unrelated existing command: "+str(path))
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(contents)
    path.chmod(0o755)

def mcp_example(current,p):
    data={"mcp":{"servers":{"facetime-controller":openclaw_integration.definition(current)}}}
    private_write(p["config"]/"openclaw-mcp-snippet.json",
                  (json.dumps(data,indent=2)+"\n").encode(),True)

def plist(current,p):
    return plistlib.dumps({
        "Label":LABEL,
        "ProgramArguments":[str(current/".venv/bin/python"),str(current/"facetime-async-watchdog.py")],
        "WorkingDirectory":str(current),"RunAtLoad":True,
        "StartInterval":30,"Umask":0o077,
        "StandardOutPath":str(p["log"]),
        "StandardErrorPath":str(p["log"])
    })

def install_agent(current,p):
    file=p["launchagent"]
    file.parent.mkdir(parents=True,exist_ok=True)
    p["log"].parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    p["log"].parent.chmod(0o700)
    if p["log"].is_symlink():raise RuntimeError("Refusing symlink watchdog log")
    previous=file.read_bytes() if file.exists() else None
    if previous:
        try:
            if plistlib.loads(previous).get("Label")!=LABEL:
                raise RuntimeError("Conflicting LaunchAgent at "+str(file))
        except (plistlib.InvalidFileException,ValueError):
            raise RuntimeError("Existing LaunchAgent cannot be inspected")
    service=f"gui/{os.getuid()}/{LABEL}"
    subprocess.run(["/bin/launchctl","bootout",service],capture_output=True)
    file.write_bytes(plist(current,p))
    try:
        run("/bin/launchctl","bootstrap",f"gui/{os.getuid()}",file)
    except Exception:
        if previous:file.write_bytes(previous)
        else:file.unlink(missing_ok=True)
        if previous:subprocess.run(["/bin/launchctl","bootstrap",f"gui/{os.getuid()}",str(file)],capture_output=True)
        raise

def install(args):
    p=paths(args)
    print("Install base:",p["base"])
    print("User config:",p["config"])
    if args.dry_run:
        print("DRY RUN: no configuration, service or FaceTime changes.")
        return 0
    requirements()
    settings=setup_wizard.plan(args,p,ROOT)
    if settings["integration"]:
        # Refuse missing/incompatible OpenClaw before touching any configuration.
        binary=openclaw_integration.command_location(args.openclaw_cli)
        available=openclaw_integration.cmd(binary,"mcp","--help")
        if available.returncode or "set" not in (available.stdout+available.stderr):
            raise RuntimeError("OpenClaw native MCP registry is unavailable; install a compatible version first")
        existing=openclaw_integration.cmd(binary,"mcp","show","facetime-controller","--json")
        if existing.returncode==0 and not args.replace_openclaw_mcp:
            raise RuntimeError("FaceTime MCP is already registered. Replacing it requires --replace-openclaw-mcp and confirmation")
        if existing.returncode==0 and not args.non_interactive:
            if not setup_wizard.yesno("Replace existing OpenClaw FaceTime MCP entry after protected backup?",False):
                raise RuntimeError("OpenClaw MCP replacement cancelled")
    stamp=time.strftime("%Y%m%d-%H%M%S")+"-"+str(os.getpid())
    new=p["versions"]/stamp
    if new.exists():raise RuntimeError("Version destination collision")
    p["versions"].mkdir(parents=True,exist_ok=True)
    current=p["current"]
    old=os.readlink(current) if current.is_symlink() else None
    if current.exists() and not current.is_symlink():
        raise RuntimeError("Existing installation is not a symlink; refusing overwrite")
    originals={}
    switched=False
    try:
        copy_source(new)
        create_venv(new,args.skip_deps)
        compile_ocr(new)
        run(new/".venv/bin/python","-m","compileall","-q",new)
        if not args.skip_deps:
            run(new/".venv/bin/python",ROOT/"tests/mcp_protocol_smoke.py",cwd=ROOT)
        originals=write_settings(settings,p)
        if settings["needs_tts_check"]:
            if args.skip_deps:raise RuntimeError("Cannot test TTS without installed dependencies")
            test_minimax_no_call(new,settings)
        link=p["base"]/".current-next"
        if link.exists() or link.is_symlink():link.unlink()
        link.symlink_to(Path("versions")/new.name)
        os.replace(link,current)
        switched=True
        wrapper(p["bin"]/"facetime-controller",current,"tools/cli.py")
        wrapper(p["bin"]/"facetime-call",current,"facetime-call.sh")
        wrapper(p["bin"]/"facetime-controller-doctor",current,"tools/doctor.py")
        mcp_example(current,p)
        if settings["watchdog"]:
            install_agent(current,p)
        elif p["launchagent"].exists():
            # Disabling the product watchdog during an upgrade is intentional.
            remove_agent(p)
        integration_issue=None
        if settings["integration"]:
            try:
                report=openclaw_integration.integrate(current,p["config"],
                    cli_path=args.openclaw_cli,replace=args.replace_openclaw_mcp,
                    openclaw_config=args.openclaw_config)
                print("OpenClaw registered. Existing Gateway not restarted.")
                print("OpenClaw backup:",report["backup"] or "(no config file at expected location)")
                if not args.skip_deps:
                    openclaw_integration.verify_no_call(args.openclaw_cli)
                    print("OpenClaw MCP discovery passed (no call made).")
            except (OSError,RuntimeError,subprocess.TimeoutExpired) as exc:
                # OpenClaw's CLI may have committed the registration before a
                # subsequent doctor/probe failed. Never roll back the installed
                # binary to a broken pointer that OpenClaw may now reference.
                integration_issue=str(exc)
    except Exception:
        if switched:
            if old:
                tmp=p["base"]/".current-rollback"
                if tmp.is_symlink():tmp.unlink()
                tmp.symlink_to(old)
                os.replace(tmp,current)
            else:current.unlink(missing_ok=True)
        if originals:restore_settings(originals)
        # Do not delete version directory or overwrite the user's existing
        # OpenClaw configuration: preserve evidence and let user inspect recovery.
        raise
    print("Installed:",current)
    print("Lockscreen mode:","NanoKVM-assisted" if settings["nanokvm"] else "UNLOCKED SESSION ONLY")
    print("Speech provider:",settings["tts"]["provider"])
    print("Watchdog:", "enabled" if settings["watchdog"] else "disabled")
    print("MCP integration:", "OpenClaw registered" if settings["integration"] else "local stdio available; not registered")
    print("No actual FaceTime calls were placed.")
    print("=== Readiness (read-only) ===")
    doctor=[str(current/".venv/bin/python"),str(current/"tools/doctor.py")]
    if settings["permissions"] or settings["nanokvm"]:doctor.append("--permissions")
    result=subprocess.run(doctor,capture_output=True,text=True,timeout=80)
    if result.stdout:print(result.stdout)
    if result.returncode and not args.non_interactive and settings["permissions"]:
        print("\nPermissions/setup incomplete. For an unlocked desktop, allow Terminal/your MCP client")
        print("under System Settings > Privacy & Security > Accessibility and Automation.")
        print("For locked operation, validate NanoKVM TLS, bearer and screen geometry.")
        print("Confirm FaceTime sign-in manually; the installer cannot reliably prove it from a read-only probe.")
        for _ in range(2):
            if not setup_wizard.yesno("Recheck permissions after correcting settings?",False):break
            result=subprocess.run(doctor,capture_output=True,text=True,timeout=80)
            if result.stdout:print(result.stdout)
            if not result.returncode:break
    if result.returncode or integration_issue:
        if integration_issue:print("OPENCLAW_INTEGRATION_NEEDS_ATTENTION:",integration_issue)
        if result.stderr:print("DOCTOR_FAILED:",result.stderr.splitlines()[-1][:240])
        print("INSTALL_COMPLETE_BUT_NOT_READY: correct the reported issues and rerun facetime-controller-doctor --permissions.")
        return 2
    if not settings["permissions"]:
        print("INSTALL_OFFLINE_CHECKS_PASSED: GUI/Automation permissions were not probed; an authorized live E2E test remains separate.")
    else:
        print("INSTALL_READINESS_CHECKS_PASSED: no-call checks passed; an authorized live E2E test remains separate.")
    return 0

def remove_agent(p):
    file=p["launchagent"]
    if not file.exists():return
    old=plistlib.loads(file.read_bytes())
    if old.get("Label")!=LABEL:
        raise RuntimeError("Unexpected LaunchAgent; refusing to remove it")
    subprocess.run(["/bin/launchctl","bootout",f"gui/{os.getuid()}/{LABEL}"],
                   capture_output=True)
    file.unlink()

def uninstall(args):
    p=paths(args)
    if args.dry_run:
        print("Would remove this package's LaunchAgent, wrappers and active symlink; preserve config/state.")
        return 0
    service=f"gui/{os.getuid()}/{LABEL}"
    remove_agent(p)
    for name in ("facetime-controller","facetime-call","facetime-controller-doctor"):
        file=p["bin"]/name
        if file.is_file() and str(p["current"]) in file.read_text():file.unlink()
    if p["current"].is_symlink():p["current"].unlink()
    print("Uninstalled service and entrypoints. Package versions, state, config and secrets retained.")
    if args.purge:
        if not args.yes:raise RuntimeError("Purging config/state requires explicit --yes")
        shutil.rmtree(p["config"],ignore_errors=True)
        shutil.rmtree(p["base"],ignore_errors=True)
        print("Purged package files and config; state intentionally retained for audit.")
    return 0

def main():
    parser=argparse.ArgumentParser(description="FaceTime Audio Controller per-user macOS installer")
    parser.add_argument("action",nargs="?",default="install",choices=("install","uninstall"))
    parser.add_argument("--prefix")
    parser.add_argument("--recipient")
    parser.add_argument("--tts-provider",choices=("macos","minimax"),default=None)
    parser.add_argument("--minimax-model",choices=("turbo","hd"))
    parser.add_argument("--minimax-region",choices=("international","china"))
    parser.add_argument("--minimax-key-file",help="Owner-only local 0600 JSON with minimaxApiKey")
    parser.add_argument("--tts-voice")
    parser.add_argument("--tts-speed",type=float)
    parser.add_argument("--tts-volume",type=float)
    parser.add_argument("--tts-pitch",type=int)
    parser.add_argument("--max-characters",type=int)
    parser.add_argument("--macos-rate",type=int)
    parser.add_argument("--macos-max-characters",type=int)
    parser.add_argument("--audio-device")
    parser.add_argument("--nanokvm",action=argparse.BooleanOptionalAction,default=None)
    parser.add_argument("--accept-unlocked-only",action="store_true",
                        help="Confirm that no-NanoKVM unattended calls need an unlocked GUI")
    parser.add_argument("--openclaw",action=argparse.BooleanOptionalAction,default=None)
    parser.add_argument("--openclaw-cli")
    parser.add_argument("--openclaw-config")
    parser.add_argument("--replace-openclaw-mcp",action="store_true")
    parser.add_argument("--reconfigure",action="store_true")
    parser.add_argument("--test-tts",action="store_true",
                        help="Optional no-call API validation; may incur MiniMax fees")
    parser.add_argument("--check-permissions",action="store_true",
                        help="Read-only active GUI permission and optional KVM checks")
    parser.add_argument("--nanokvm-endpoint")
    parser.add_argument("--nanokvm-auth-file")
    parser.add_argument("--non-interactive",action="store_true")
    parser.add_argument("--watchdog",action=argparse.BooleanOptionalAction,default=None)
    parser.add_argument("--skip-deps",action="store_true",help="For isolated installer tests only: not a working MCP installation")
    parser.add_argument("--dry-run",action="store_true")
    parser.add_argument("--purge",action="store_true")
    parser.add_argument("--yes",action="store_true")
    args=parser.parse_args()
    try:return install(args) if args.action=="install" else uninstall(args)
    except (OSError,RuntimeError,subprocess.CalledProcessError,ValueError) as exc:
        print("INSTALL_ERROR:",type(exc).__name__,str(exc),file=sys.stderr)
        return 1
if __name__=="__main__":sys.exit(main())
