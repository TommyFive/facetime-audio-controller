#!/bin/zsh
# One-way FaceTime TTS output to Loopback Audio (Rogue Amoeba).
# Does not modify default audio devices, start/end calls, or install drivers.
set -euo pipefail
if (( $# == 0 )); then
  print -u2 "Usage: facetime-say.sh 'Nachricht'"
  exit 64
fi
message="$*"
if [[ -z "${message//[[:space:]]/}" ]]; then
  print -u2 "Error: message is empty"
  exit 64
fi
audio_device=$(/usr/bin/python3 "$(dirname "$0")/facetime_runtime.py" audio-device) || exit 75
if ! /usr/bin/say -a '?' 2>&1 | /usr/bin/grep -Fq "$audio_device"; then
  print -u2 "Error: configured audio device is not available"
  exit 69
fi
exec /usr/bin/say -v Anna -r 165 -a "$audio_device" -- "$message"
