#!/bin/zsh
# FaceTime Audio controller for one owner-owned, fixed FaceTime identity on macOS 27.2.
# macOS GUI via AX in NotificationCenter; voice via Rogue Amoeba Loopback Audio.
# Fail closed if target identity, call state, or action is not unique.
set -euo pipefail

readonly TARGET="$(/usr/bin/python3 "$(dirname "$0")/facetime_runtime.py" recipient)"
export FACETIME_RECIPIENT="$TARGET"
readonly AUDIO_DEVICE="$(/usr/bin/python3 "$(dirname "$0")/facetime_runtime.py" audio-device)"
readonly DIR="${0:A:h}"
readonly TTS="$DIR/facetime-say.sh"
readonly AX="$DIR/facetime-ax-control.applescript"
readonly GUI_CHECK="$DIR/facetime-gui-session.py"
readonly FAST_HELPER="$DIR/facetime-call-fast.py"
readonly DISPLAY_WAKE_HELPER="$DIR/facetime-display-wake.py"
readonly KVM_UI="$DIR/nanokvm-call-ui.py"
readonly PRIORITY="$DIR/facetime-priority.py"
readonly KVM_PYTHON="$DIR/.venv/bin/python"

usage() {
  cat <<'USAGE'
Usage:
  facetime-call.sh --call [options] "Text"       # fast call + verified hangup
  facetime-call.sh --dial [options]             # confirm but do not speak
  facetime-call.sh --confirm [--timeout 20]     # AX/KVM, cancel pending on timeout
  facetime-call.sh --hangup [--timeout 24]      # AX/KVM verified red hangup
  facetime-call.sh --cancel-pending             # PRIORITY: cancel verified pending cards
  facetime-call.sh --recover                    # bounded preflight cleanup (no call)
  facetime-call.sh --speak [TTS options] "Text" # TTS into Loopback
  facetime-call.sh --status                     # state: GUI / lockscreen
  facetime-call.sh --dry-run
  facetime-call.sh --help

  --hangup and --cancel-pending bypass the outgoing call mutex and
  interrupt a running call. Other write operations use an exclusive lock.

Options for --call and --dial:
  --confirm-timeout SECONDS  (4..120; default 20)
  --answer-timeout SECONDS   (5..180; default 60; applies to --call)
  --hangup-timeout SECONDS   (5..60; default 24; applies to --call)

TTS options for --call and --speak:
  --tts-provider minimax|macos    (default: minimax; macOS fallback)
  --tts-speed NUMBER             (0.5..2.0; default 1.1)
  --tts-volume NUMBER            (0.01..10; default 1.0)
  --tts-pitch INTEGER            (-12..12; default 0)
  --tts-voice VOICE_ID           (default: German_FriendlyMan)

The script automatically detects whether the desktop is locked.
No FACETIME_NO_ACCESSIBILITY_CHECK or FACETIME_ENABLE_UNATTENDED required.
If the display is OFF, it is woken before a FaceTime or AX UI action.
Locked screen: direct NanoKVM MCP over Tailscale HTTPS; OCR + stable
screenshot ROI. Confirm exactly one outgoing card, then play fast TTS
and click exactly one verified red hangup button after speech.
If confirmation times out, cancel only target-verified pending gray cards.
Old duplicate pending cards are cleared before a new call with a bounded
recovery budget and a stable empty-screen check.
Multiple active/held/unknown cards => no unsafe clicks.
Unlocked desktop: AX confirms and hangs up automatically.
No simultaneous FaceTime calls. All normal write operations share a
nonblocking call mutex. Hangup/cancel use a priority interruption path.
Only target-verified pending cards are closed during bounded recovery;
hidden queued requests cannot be ruled out. OCR is supplemental and is
not an authenticated Apple call identity.
USAGE
}

preflight() {
  [[ -n "$TARGET" ]] || { print -u2 "RECIPIENT_NOT_CONFIGURED"; return 78; }
  [[ -x "$TTS" ]] || { print -u2 "ERROR: TTS missing or not executable: $TTS"; return 70; }
  [[ -f "$AX" ]] || { print -u2 "ERROR: AX script missing: $AX"; return 70; }
  [[ -d /System/Applications/FaceTime.app ]] || { print -u2 "ERROR: FaceTime missing"; return 69; }
  /usr/bin/say -a '?' 2>&1 | /usr/bin/grep -Fq "$AUDIO_DEVICE" || {
    print -u2 "ERROR: $AUDIO_DEVICE is not available"; return 69
  }
  /usr/sbin/system_profiler SPAudioDataType -detailLevel mini |
    /usr/bin/grep -A 12 -F "$AUDIO_DEVICE:" |
    /usr/bin/grep -Fq 'Default Input Device: Yes' || {
      print -u2 "ERROR: macOS default input is not $AUDIO_DEVICE"; return 69
    }
  print -r -- "PREFLIGHT_OK target=$TARGET audio=$AUDIO_DEVICE"
}

gui_state() {
  /usr/bin/python3 "$GUI_CHECK"
}
require_gui_unlocked() {
  local state
  state=$(gui_state) || {
    print -u2 -- "ERROR: cannot verify macOS GUI state: $state"
    return 75
  }
  if [[ "$state" != GUI_UNLOCKED ]]; then
    print -u2 "ERROR: Mac desktop locked; AX UI action unavailable. Use NanoKVM manually."
    return 77
  fi
}

ensure_display_awake() {
  /usr/bin/python3 "$DISPLAY_WAKE_HELPER" --ensure-awake || {
    print -u2 "ERROR: display not ready; GUI action not attempted."
    return 75
  }
}

status() {
  local gui
  gui=$(gui_state) || {
    print -u2 -- "ERROR: macOS GUI state unavailable: $gui"
    return 75
  }
  if [[ "$gui" == GUI_LOCKED ]]; then
    print -r -- "STATE=SCREEN_LOCKED target=$TARGET (using NanoKVM MCP visual state)"
    if [[ -x "$KVM_PYTHON" ]]; then
      "$KVM_PYTHON" "$KVM_UI" inspect
      return $?
    fi
    print -u2 -- "ERROR: NanoKVM image runtime unavailable; call state unknown"
    return 75
  fi
  # status is a machine-readable STATE= protocol; do not include display
  # diagnostics on stdout or AX dial_auto() will mistake NO_CALL_UI for
  # an unknown/unsafe state. Display wake remains fail-closed.
  ensure_display_awake >&2 || return $?
  # Transient AX element errors must not abort ongoing calls.
  local attempt output
  for attempt in {1..5}; do
    if output=$(/usr/bin/osascript "$AX" status 2>&1); then
      if [[ "$output" != STATE=TRANSIENT_UI* ]]; then
        print -r -- "$output"
        return 0
      fi
    elif [[ "$output" != *"-1719"* && "$output" != *"Ungültiger Index"* && "$output" != *"TRANSIENT_UI"* ]]; then
      print -u2 -- "ERROR: FaceTime status: $output"
      return 75
    fi
    /bin/sleep 0.15
  done
  print -u2 "ERROR: FaceTime status transient for five attempts"
  return 75
}

request_dial() {
  preflight
  ensure_display_awake || return $?
  # Fixed target, FaceTime Audio URL. macOS always displays a user call prompt.
  /usr/bin/open -a FaceTime "facetime-audio://${TARGET}"
  print -r -- "DIAL_REQUESTED target=$TARGET type=FaceTime-Audio (no connection verified)"
}

confirm_call() {
  ensure_display_awake || return $?
  require_gui_unlocked || return $?
  local attempt result
  for attempt in {1..12}; do
    if result=$(/usr/bin/osascript "$AX" confirm 2>&1); then
      print -r -- "$result"
      return 0
    fi
    if [[ "$result" == *"NO_MATCHING_CALL_CARD"* || "$result" == *"TRANSIENT_UI"* || "$result" == *"-1719"* ]]; then
      /bin/sleep 0.5
      continue
    fi
    print -u2 -- "ERROR: AX confirmation not completed: $result"
    return 75
  done
  print -u2 -- "ERROR: no uniquely matching FaceTime prompt detected after 12 checks. No additional call requested. Inspect --status and use --confirm if visible."
  return 75
}

dial_auto() {
  # An explicit --dial-auto invocation authorizes ONE outbound request.
  # First try to reuse an already pending prompt, so repeated invocations
  # do not create another prompt for the same target.
  local before again
  before=$(status) || return $?
  case "$before" in
    STATE=SCREEN_LOCKED*)
      print -u2 "ERROR: macOS GUI is locked; unlock Mac mini before FaceTime automation."
      return 77 ;;
    STATE=PENDING_CONFIRMATION*)
      print -r -- "PENDING_PROMPT_FOUND: confirming existing FaceTime Audio request; no new dial."
      confirm_call || return $?
      ;;
    STATE=NO_CALL_UI*)
      # NO_CALL_UI is not a definitive idle signal. Inspect a second time;
      # if the pending prompt becomes visible, reuse it.
      /bin/sleep 0.5
      again=$(status) || return $?
      case "$again" in
        STATE=PENDING_CONFIRMATION*)
          print -r -- "PENDING_PROMPT_FOUND: confirming existing FaceTime Audio request; no new dial."
          confirm_call || return $? ;;
        STATE=NO_CALL_UI*)
          print -r -- "NO_CALL_UI observed twice. Sending exactly one explicitly requested FaceTime Audio URL."
          request_dial
          confirm_call || return $? ;;
        *)
          print -u2 -- "ERROR: unsafe FaceTime state on recheck: $again; no new call requested."
          return 75 ;;
      esac
      ;;
    *)
      print -u2 -- "ERROR: existing call, multiple prompts, or uncertain FaceTime state: $before; no new call requested."
      return 75 ;;
  esac
  print -r -- "DIAL_AUTO_OK: AX confirmation clicked; remote answer not yet verified."
}

hangup() {
  ensure_display_awake || return $?
  require_gui_unlocked || return $?
  local outcome attempt observed
  for attempt in {1..5}; do
    if outcome=$(/usr/bin/osascript "$AX" hangup 2>&1); then
      print -r -- "$outcome"
      # Verify AFTER clicking; this check does not delay remote hangup.
      for attempt in {1..6}; do
        /bin/sleep 0.3
        observed=$(status 2>/dev/null) || continue
        if [[ "$observed" == STATE=NO_CALL_UI* ]]; then
          print -r -- "POST_HANGUP_$observed"
          return 0
        fi
      done
      print -u2 "WARNING: hangup clicked, but disconnection not yet verified"
      return 75
    fi
    if [[ "$outcome" != *"TRANSIENT_UI"* && "$outcome" != *"-1719"* ]]; then
      print -u2 -- "ERROR: hangup not performed: $outcome"
      return 75
    fi
    /bin/sleep 0.15
  done
  print -u2 "ERROR: hangup remained transient; no verified click"
  return 75
}

speak() {
  local message="$*"
  [[ -n "${message//[[:space:]]/}" ]] || { print -u2 "ERROR: empty speech"; return 64; }
  preflight
  "$TTS" "$message"
  print -r -- "TTS_FINISHED output=$AUDIO_DEVICE (remote delivery not verified)"
}

call_standard() {
  [[ -f "$FAST_HELPER" ]] || { print -u2 "ERROR: fast helper missing: $FAST_HELPER"; return 70; }
  /usr/bin/python3 "$FAST_HELPER" "$@"
}

mode="${1:---dry-run}"
if (( $# > 0 )); then shift; fi
case "$mode" in
  --help|-h)
    (( $# == 0 )) || { usage >&2; exit 64; }
    usage ;;
  --dry-run)
    (( $# == 0 )) || { usage >&2; exit 64; }
    preflight
    print -r -- "DRY_RUN_OK: no outgoing call or audio" ;;
  --status)
    (( $# == 0 )) || { usage >&2; exit 64; }
    status ;;
  --dial)
    /usr/bin/python3 "$FAST_HELPER" --dial-only "$@" ;;
  --_dial-ax)
    (( $# == 0 )) || { usage >&2; exit 64; }
    [[ -n "${FACETIME_INTERNAL_RUN_ID:-}" ]] || {
      print -u2 "ERROR: internal AX dial requires an active call transaction"; exit 77;
    }
    PYTHONPATH="$DIR" /usr/bin/python3 -c 'import facetime_txn,sys;facetime_txn.check(sys.argv[1])' "$FACETIME_INTERNAL_RUN_ID" || exit 75
    require_gui_unlocked || exit $?
    dial_auto ;;
  --_hangup-ax)
    (( $# == 0 )) || { usage >&2; exit 64; }
    [[ -n "${FACETIME_INTERNAL_HANGUP:-}" ]] || {
      print -u2 "ERROR: internal AX hangup requires an active call transaction"; exit 77;
    }
    PYTHONPATH="$DIR" /usr/bin/python3 -c 'import facetime_txn,sys;facetime_txn.check(sys.argv[1])' "$FACETIME_INTERNAL_HANGUP" || exit 75
    hangup ;;
  --confirm)
    if (( $# == 0 )); then
      /usr/bin/python3 "$PRIORITY" confirm
    elif [[ $# == 2 && "$1" == "--timeout" ]]; then
      /usr/bin/python3 "$PRIORITY" confirm --timeout "$2"
    else
      usage >&2; exit 64
    fi ;;
  --cancel-pending)
    (( $# == 0 )) || { usage >&2; exit 64; }
    /usr/bin/python3 "$PRIORITY" cancel-pending ;;
  --hangup)
    if (( $# == 0 )); then
      /usr/bin/python3 "$PRIORITY" hangup
    elif [[ $# == 2 && "$1" == "--timeout" ]]; then
      /usr/bin/python3 "$PRIORITY" hangup --timeout "$2"
    else
      usage >&2; exit 64
    fi ;;
  --speak)
    (( $# > 0 )) || { usage >&2; exit 64; }
    /usr/bin/python3 "$PRIORITY" speak "$@" ;;
  --recover)
    (( $# == 0 )) || { usage >&2; exit 64; }
    /usr/bin/python3 "$PRIORITY" recover ;;
  --call)
    (( $# > 0 )) || { usage >&2; exit 64; }
    call_standard "$@" ;;
  *)
    print -u2 "ERROR: unknown mode: $mode"
    usage >&2
    exit 64 ;;
esac
