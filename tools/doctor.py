#!/usr/bin/env python3
"""Read-only setup checks; never dials or clicks FaceTime controls."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import facetime_runtime as rt

def main():
    parser=argparse.ArgumentParser(description="Read-only FaceTime Controller setup doctor")
    parser.add_argument("--permissions",action="store_true",
                        help="Probe effective macOS Accessibility/Automation or NanoKVM access; no calls")
    args=parser.parse_args()
    checks=[]
    def check(name,ok,detail):
        checks.append({"check":name,"ok":bool(ok),"detail":detail})
    check("macOS",sys.platform=="darwin","A graphical macOS session is required.")
    cf=rt.config_path()
    check("private config",cf.is_file() and not cf.is_symlink() and (cf.stat().st_mode&0o077)==0 if cf.exists() else False,
          "Owner-only JSON configuration.")
    try:
        rt.require_recipient()
        check("recipient",True,"Fixed FaceTime recipient configured (value hidden).")
    except RuntimeError:
        check("recipient",False,"Configure a valid fixed recipient.")
    ffmpeg=rt.executable("ffmpeg")
    check("FFmpeg",bool(shutil.which("ffmpeg") or Path(ffmpeg).is_file()),"FFmpeg available.")
    ocr=ROOT/".bin/facetime-vision-ocr"
    check("Vision OCR",ocr.is_file() and os.access(ocr,os.X_OK),"Compiled local OCR helper.")
    try:
        import mcp
        import PIL
        check("Python dependencies",True,"MCP SDK and Pillow available.")
    except ImportError:
        check("Python dependencies",False,"Run installer with dependency installation.")
    tc=rt.tts_config_file(ROOT/"tts-config.json")
    try:
        j=json.loads(tc.read_text())
        check("TTS settings",j.get("provider") in ("macos","minimax"),"Provider settings present.")
        if j.get("provider")=="minimax":
            key=rt.minimax_key_file()
            check("MiniMax credential",key.is_file() and (key.stat().st_mode&0o077)==0 if key.exists() else False,
                  "Owner-only API key (local fallback remains available).")
    except (OSError,ValueError):
        check("TTS settings",False,"Provider configuration invalid.")
    if rt.nanokvm_endpoint():
        key=rt.kvm_auth_file()
        check("NanoKVM credential",key.is_file() and (key.stat().st_mode&0o077)==0 if key.exists() else False,
              "Optional locked-screen bearer credential.")
    if sys.platform=="darwin":
        try:
            p=subprocess.run(["/usr/bin/say","-a","?"],capture_output=True,text=True,timeout=12)
            check("Loopback device",p.returncode==0 and rt.audio_device() in (p.stdout+p.stderr),
                  "Rogue Amoeba Loopback must also be the default input microphone.")
        except (OSError,subprocess.TimeoutExpired):
            check("Loopback device",False,"Cannot enumerate audio devices.")
        try:
            p=subprocess.run(["/usr/sbin/system_profiler","SPAudioDataType","-detailLevel","mini"],
                             capture_output=True,text=True,timeout=25)
            lines=p.stdout.splitlines()
            index=next((i for i,line in enumerate(lines) if line.strip()==rt.audio_device()+":"),-1)
            block="\n".join(lines[index:index+16]) if index>=0 else ""
            check("default microphone",p.returncode==0 and "Default Input Device: Yes" in block,
                  "Configured virtual audio device must be the default macOS input.")
        except (OSError,subprocess.TimeoutExpired):
            check("default microphone",False,"Cannot verify macOS default input.")
    if args.permissions and sys.platform=="darwin":
        try:
            result=subprocess.run([sys.executable,str(ROOT/"facetime-permissions.py")],
                                  capture_output=True,text=True,timeout=35)
            data=json.loads(result.stdout)
            check("automation permissions",result.returncode==0 and data.get("ok") is True,
                  str(data.get("code","UNKNOWN"))+": "+str(data.get("message","")))
        except (OSError,ValueError,subprocess.TimeoutExpired):
            check("automation permissions",False,"Permission probe failed; verify the invoking process TCC privileges.")
        # Optional KVM must also work when the GUI is currently unlocked.
        if rt.nanokvm_endpoint():
            try:
                kvm=subprocess.run([sys.executable,str(ROOT/"nanokvm-call-ui.py"),"inspect"],
                                   capture_output=True,text=True,timeout=35)
                check("NanoKVM screenshot access",kvm.returncode==0 and "KVM_UI_RESULT " in kvm.stdout,
                      "Read-only NanoKVM MCP visual probe (no click or call).")
            except (OSError,subprocess.TimeoutExpired):
                check("NanoKVM screenshot access",False,"KVM screenshot probe unavailable or timed out.")
    print(json.dumps({"ok":all(x["ok"] for x in checks),"checks":checks},indent=2))
    return 0 if all(x["ok"] for x in checks) else 2
if __name__=="__main__":sys.exit(main())
