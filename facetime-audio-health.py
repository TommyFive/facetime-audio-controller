#!/usr/bin/env python3
"""Fail-closed short CoreAudio/Loopback output preflight; never initiates a call.

Exercise actual AudioToolbox playback, NOT ffmpeg's device enumeration alone.
Output is silent synthetic PCM; successful completion does not prove handset audio.
"""
import argparse
import json
import pathlib
import re
import subprocess
import time

from facetime_runtime import executable
from facetime_runtime import audio_device
FFMPEG = executable("ffmpeg")
DEVICE_PATTERN = re.compile(r"\[(\d+)\]\s+"+re.escape(audio_device())+r"\b")

def find_device():
    result = subprocess.run(
        [FFMPEG, "-hide_banner", "-nostdin", "-f", "lavfi",
         "-i", "anullsrc=r=48000:cl=stereo", "-t", "0.01",
         "-f", "audiotoolbox", "-list_devices", "true", "-"],
        text=True, capture_output=True, timeout=10)
    matches = DEVICE_PATTERN.findall(result.stderr)
    if len(matches) != 1:
        raise RuntimeError("LOOPBACK_DEVICE_NOT_UNIQUE")
    return matches[0]

def check(device, timeout=8):
    device = str(device)
    if not device.isdecimal() or len(device) > 4:
        raise ValueError("Invalid audio device index")
    if timeout < 2 or timeout > 20:
        raise ValueError("Invalid audio test timeout")
    start = time.monotonic()
    cmd = [FFMPEG, "-hide_banner", "-nostdin", "-loglevel", "error",
           "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
           "-t", "0.25", "-ac", "2", "-ar", "48000",
           "-f", "audiotoolbox", "-audio_device_index", device, "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        ok = r.returncode == 0
        code = "AUDIO_ROUTE_OK" if ok else "AUDIO_ROUTE_FAILED"
    except subprocess.TimeoutExpired:
        ok = False
        code = "AUDIO_ROUTE_HUNG"
    except OSError:
        ok = False
        code = "AUDIO_TOOL_UNAVAILABLE"
    return {"ok": ok, "code": code, "elapsed_seconds": round(time.monotonic()-start, 2),
            "device": audio_device()}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--device-index")
    parser.add_argument("--timeout", type=int, default=8)
    args = parser.parse_args()
    try:
        index = args.device_index or find_device()
        result = check(index, args.timeout)
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        result = {"ok": False, "code": "AUDIO_DEVICE_ENUMERATION_FAILED",
                  "details": type(error).__name__}
    print(json.dumps(result, sort_keys=True), flush=True)
    raise SystemExit(0 if result["ok"] else 75)
