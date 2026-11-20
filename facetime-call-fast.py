#!/usr/bin/env python3
"""Fast one-shot FaceTime Audio + TTS.

GUI unlocked: call via the existing AX-controlled internal mode, verify via CallServices,
then auto-hangup via AX.
GUI locked: reconcile stale cards, issue exactly one FaceTime URL,
visually confirm via NanoKVM MCP, trigger pre-rendered Loopback TTS after
CallServices connects, and verify NanoKVM hangup. Manual priority hangup
and cancel interrupt the normal runner without waiting for call.lock.
"""
import argparse
import json
import datetime as dt
import os
import pathlib
import re
import signal
import facetime_txn as txn
import subprocess
import sys
import tempfile
import time

import facetime_runtime as runtime
DIR = pathlib.Path(__file__).resolve().parent
SCRIPT = str(DIR / "facetime-call.sh")
GUI_CHECK = str(DIR / "facetime-gui-session.py")
FFMPEG = runtime.executable("ffmpeg")
DISPLAY_WAKE_HELPER = str(DIR / "facetime-display-wake.py")
KVM_UI = str(DIR / "nanokvm-call-ui.py")
# Support both the repository entry point and the copied scripts layout.
_REPO_KVM_PYTHON = DIR / ".venv/bin/python"
KVM_PYTHON = str(_REPO_KVM_PYTHON if _REPO_KVM_PYTHON.is_file() else pathlib.Path(sys.executable))
TTS_RENDERER = str(DIR / "facetime-tts.py")
TARGET = runtime.recipient()
if TARGET: os.environ["FACETIME_RECIPIENT"]=TARGET
PRED = ('process == "callservicesd" AND (eventMessage CONTAINS[c] '
        '"TUCallCenterCallConnectedNotification" OR eventMessage CONTAINS[c] '
        '"callDisconnected(withReason:)" OR eventMessage CONTAINS[c] '
        '"Setting disconnected reason")')
LOG_PATTERN = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+)")
DEVICE_PATTERN = re.compile(r"\[(\d+)\]\s+"+re.escape(runtime.audio_device())+",")

def log(msg):
    print(dt.datetime.now().astimezone().isoformat(timespec="milliseconds") + " " + msg,
          flush=True)

def run(command, timeout):
    begin = time.monotonic()
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    return result, time.monotonic()-begin

def checked(command, timeout, label):
    result, duration = run(command, timeout)
    if result.returncode:
        raise RuntimeError(f"{label}: rc={result.returncode} {(result.stderr or result.stdout)[:280]}")
    return result, duration

def events_since(start_second):
    result, duration = run([
        "/usr/bin/log", "show", "--start", start_second, "--style", "compact",
        "--predicate", PRED
    ], 9)
    if result.returncode:
        raise RuntimeError("CallServices log query failed: " + result.stderr[:220])
    items = []
    for line in result.stdout.splitlines():
        match = LOG_PATTERN.match(line)
        if not match:
            continue
        if "Posting TUCallCenterCallConnectedNotification" in line:
            kind = "connected"
        elif ("Analytics: callDisconnected(withReason:)" in line
              or "Setting disconnected reason" in line):
            kind = "disconnected"
        else:
            continue
        try:
            stamp = dt.datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S.%f")
        except ValueError:
            continue
        items.append((stamp, kind))
    return items, duration

def call_state():
    result, duration = checked(["/usr/bin/python3", GUI_CHECK], 8, "GUI check")
    state = result.stdout.strip()
    if state not in ("GUI_LOCKED", "GUI_UNLOCKED"):
        raise RuntimeError("Unknown GUI state: "+state)
    return state

def output_device():
    result, duration = run([
        FFMPEG, "-hide_banner", "-nostdin", "-f", "lavfi", "-i",
        "anullsrc=r=48000:cl=stereo", "-t", "0.01",
        "-f", "audiotoolbox", "-list_devices", "true", "-"
    ], 10)
    matches = DEVICE_PATTERN.findall(result.stderr)
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one configured CoreAudio output, got {matches}")
    return matches[0]

def ensure_input():
    result, duration = checked([
        "/usr/sbin/system_profiler", "SPAudioDataType", "-detailLevel", "mini"
    ], 15, "audio input preflight")
    section = result.stdout.split(runtime.audio_device()+":",1)
    if len(section) != 2 or "Default Input Device: Yes" not in section[1][:600]:
        raise RuntimeError("Configured audio device is not macOS default microphone input")

def connected_at_or_after(start_exact):
    # CallServices logs are system-wide, not authenticated to the target.
    # Correlate by a fresh time window and exactly one outgoing request.
    since = start_exact.strftime("%Y-%m-%d %H:%M:%S")
    events, duration = events_since(since)
    fresh = [(t,k) for t,k in events if t >= start_exact]
    if not fresh:
        return None, duration
    if fresh[-1][1] == "disconnected":
        raise RuntimeError("Call disconnected before TTS")
    new_connections = [t for t,k in fresh if k == "connected"]
    return (new_connections[-1] if new_connections else None), duration

def unavailable_popup_state(timeout=6):
    """Observe the exact fixed-recipient unavailable card, without interacting."""
    try:
        proc = subprocess.run(
            ["/usr/bin/osascript", str(DIR/"facetime-ax-control.applescript"), "status"],
            capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        return False
    return (proc.returncode == 0 and
            proc.stdout.strip().startswith("STATE=UNAVAILABLE target="+TARGET+" "))


def dismiss_unavailable_popup(run_id):
    """Close only one verified unavailable card, then observe its disappearance."""
    guarded(["/usr/bin/osascript", str(DIR/"facetime-ax-control.applescript"),
             "dismiss-unavailable"], 12, run_id, "AX unavailable dismissal")
    for _ in range(4):
        txn.check(run_id)
        status, _ = guarded([SCRIPT, "--status"], 12, run_id,
                            "AX unavailable dismissal verification")
        if "STATE=NO_CALL_UI" in status:
            return
        time.sleep(.35)
    raise RuntimeError("UNAVAILABLE_DISMISS_UNVERIFIED")


def locked_unavailable_popup_state(run_id):
    """Read-only NanoKVM OCR probe; unknown states never mean unavailable."""
    try:
        output,_=guarded([KVM_PYTHON,KVM_UI,"inspect"],22,run_id,
                         "NanoKVM unavailable status",
                         env={"FACETIME_TXN_RUN_ID":run_id})
        for line in output.splitlines():
            if line.startswith("KVM_UI_RESULT "):
                result=json.loads(line.removeprefix("KVM_UI_RESULT "))
                return (result.get("status")=="UNAVAILABLE" and
                        result.get("target_verified") is True and
                        result.get("unavailable_verified") is True and
                        result.get("count")==1 and result.get("red_count")==0)
    except (RuntimeError, subprocess.TimeoutExpired, ValueError, OSError):
        return False
    return False


def dismiss_locked_unavailable_popup(run_id):
    """One guarded NanoKVM gray-X click; require verified two-frame disappearance."""
    kvm(["dismiss-unavailable"],30,"NanoKVM unavailable dismissal",run_id)


def options_parse(argv):
    parser=argparse.ArgumentParser(
        description="FaceTime fast TTS with automatic locked-screen NanoKVM confirmation and hangup")
    parser.add_argument("--dial-only",action="store_true",
                        help="Request/confirm the call but do not speak or auto-hangup")
    parser.add_argument("--confirm-timeout",type=float,
                        default=float(os.environ.get("FACETIME_CONFIRM_TIMEOUT","20")),
                        help="Seconds pending confirmation may remain (default 20)")
    parser.add_argument("--answer-timeout",type=float,
                        default=float(os.environ.get("FACETIME_ANSWER_TIMEOUT","60")),
                        help="Seconds to wait for recipient to answer (default 60)")
    parser.add_argument("--hangup-timeout",type=float,
                        default=float(os.environ.get("FACETIME_HANGUP_TIMEOUT","24")),
                        help="Seconds allowed for verified red-button hangup (default 24)")
    parser.add_argument("--tts-provider",choices=("minimax","macos"),default=None,
                        help="TTS provider; default from tts-config.json (minimax)")
    parser.add_argument("--tts-speed",type=float,default=None,
                        help="MiniMax speed 0.5..2; default 1.1")
    parser.add_argument("--tts-volume",type=float,default=None,
                        help="MiniMax volume 0.01..10; default 1.0")
    parser.add_argument("--tts-pitch",type=int,default=None,
                        help="MiniMax pitch -12..12; default 0")
    parser.add_argument("--tts-voice",default=None,
                        help="MiniMax voice id; default German_FriendlyMan")
    parser.add_argument("text",nargs="*",help="Text spoken after connection")
    opt=parser.parse_args(argv)
    if not 4<=opt.confirm_timeout<=120:parser.error("--confirm-timeout must be 4..120")
    if not 5<=opt.answer_timeout<=180:parser.error("--answer-timeout must be 5..180")
    if not 5<=opt.hangup_timeout<=60:parser.error("--hangup-timeout must be 5..60")
    if opt.tts_speed is not None and not .5<=opt.tts_speed<=2.0:
        parser.error("--tts-speed must be 0.5..2.0")
    if opt.tts_volume is not None and not .01<=opt.tts_volume<=10:
        parser.error("--tts-volume must be 0.01..10")
    if opt.tts_pitch is not None and not -12<=opt.tts_pitch<=12:
        parser.error("--tts-pitch must be -12..12")
    if not opt.dial_only and not " ".join(opt.text).strip():
        parser.error("nonempty TTS message required")
    return opt


def guarded(command, timeout, run_id, label, env=None, connection_since=None):
    """Cancelable subprocess. A priority interrupt aborts before next UI step.

    new_session gives the subprocess group a bounded kill path; no shell.
    """
    txn.check(run_id)
    begin=time.monotonic()
    opts=dict(os.environ)
    if env:opts.update(env)
    proc=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                          text=True,env=opts,start_new_session=True)
    last_connection_check=0.0
    consecutive_log_failures=0
    try:
        while True:
            txn.check(run_id)
            # During long audio, confirm the remote call is still connected.
            # Without this, local FFmpeg completion could masquerade as
            # successful handset-side delivery after an early remote hangup.
            if connection_since is not None and time.monotonic()-last_connection_check>=5:
                last_connection_check=time.monotonic()
                try:
                    events,_=events_since(connection_since.strftime("%Y-%m-%d %H:%M:%S"))
                    consecutive_log_failures=0
                    if any(kind=="disconnected" and stamp>=connection_since
                           for stamp,kind in events):
                        log("CALL_DISCONNECTED_DURING_PLAYBACK")
                        raise RuntimeError("CALL_DISCONNECTED_DURING_PLAYBACK")
                except RuntimeError as exc:
                    if "CALL_DISCONNECTED_DURING_PLAYBACK" in str(exc):
                        raise
                    consecutive_log_failures+=1
                    log("PLAYBACK_CALLSERVICES_RETRY "+str(exc)[:95])
                    if consecutive_log_failures>=3:
                        raise RuntimeError("PLAYBACK_CALLSERVICES_UNAVAILABLE") from exc
            remaining=timeout-(time.monotonic()-begin)
            if remaining<=0:
                raise subprocess.TimeoutExpired(command,timeout)
            try:
                stdout,stderr=proc.communicate(timeout=min(.25,remaining))
                break
            except subprocess.TimeoutExpired:
                continue
        if proc.returncode:
            raise RuntimeError(f"{label}: rc={proc.returncode} {(stderr or stdout)[-280:]}")
        return stdout,time.monotonic()-begin
    except BaseException:
        if proc.poll() is None:
            try:os.killpg(proc.pid,signal.SIGTERM)
            except ProcessLookupError:pass
            try:proc.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                try:os.killpg(proc.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                proc.communicate(timeout=3)
        raise

def kvm(args, timeout, label, run_id):
    output,seconds=guarded([KVM_PYTHON,KVM_UI]+args,timeout,run_id,label,
                           env={"FACETIME_TXN_RUN_ID":run_id})
    for line in output.splitlines():
        if any(mark in line for mark in
                ("PREFLIGHT_CLEAR","CONFIRM_CLICK_SENT","CONFIRM_SENT_FAST",
                 "PENDING_CANCELLED_VERIFIED","RECOVERY_ALL_CARDS_CLEARED",
                 "RECOVERY_IDLE_VERIFIED","QUIESCENT_EMPTY",
                 "HANGUP_CLICK_SENT","HANGUP_VERIFIED","HANGUP_ALREADY_CLEAR",
                 "HANGUP_CANCELLED_PENDING_INSTEAD","RESUME_HELD_CLICK_SENT",
                 "UNAVAILABLE_CARD_VERIFIED","UNAVAILABLE_DISMISS_CLICK_SENT",
                 "UNAVAILABLE_DISMISSED_VERIFIED")):
            log(line)
    return seconds

def playback_timeout_seconds(audio_seconds):
    """Bound stalled AudioToolbox playback to rendered speech duration plus cleanup margin."""
    seconds=float(audio_seconds)
    # The renderer accepts verified AIFF durations up to 1200 seconds.
    # Never truncate a legitimate long briefing at the former 180s cap.
    if not (0 < seconds <= 1200):
        raise ValueError("invalid rendered audio duration")
    return min(1215, max(15, int(seconds + 15)))


def main(args):
    opt=options_parse(args)
    runtime.require_recipient()
    if not opt.dial_only and not pathlib.Path(FFMPEG).is_file():
        raise RuntimeError("FFmpeg unavailable")
    # Acquire BEFORE any FaceTime-changing operation. This lock is never
    # acquired by --hangup/--cancel-pending.
    with txn.lockfile(txn.CALL_LOCK):
        record,previous=txn.start()
        run_id=record["run_id"]
        state=None
        started=False
        confirmed=False
        successful=False
        error=None
        cleanup_error=None
        priority_interrupt=False
        unavailable_dismissed=False
        try:
            state=call_state()
            if state=="GUI_LOCKED" and not pathlib.Path(KVM_PYTHON).is_file():
                raise RuntimeError("NanoKVM Pillow runtime missing")
            log(f"CALL_START run_id={run_id[:12]} "
                f"mode={'LOCKED_NANOKVM_HTTPS' if state=='GUI_LOCKED' else 'UNLOCKED_AX'} "
                f"previous={previous.get('stage','IDLE')} "
                f"confirm_timeout={opt.confirm_timeout:g}s answer_timeout={opt.answer_timeout:g}s")
            # Check permission in the same execution context, BEFORE rendering
            # and BEFORE issuing any FaceTime URL. Do not play silent audio.
            permission_output,_=guarded(
                [sys.executable,str(DIR/"facetime-permissions.py")],
                33,run_id,"FaceTime automation permissions")
            try:
                permission=json.loads(permission_output.strip().splitlines()[-1])
            except (ValueError,IndexError,TypeError) as exc:
                raise RuntimeError("PERMISSION_CHECK_INVALID") from exc
            if permission.get("ok") is not True or permission.get("mode") != state:
                raise RuntimeError("PERMISSION_CHECK_FAILED")
            log("PERMISSIONS_OK mode="+state)
            with tempfile.TemporaryDirectory(prefix="facetime-call-fast-") as folder:
                audio=str(pathlib.Path(folder)/"voice.aiff")
                device=None
                if not opt.dial_only:
                    txn.check(run_id)
                    tts_args=[sys.executable,TTS_RENDERER,"--output",audio,
                              "--text"," ".join(opt.text)]
                    for flag,value in (
                        ("--provider",opt.tts_provider),
                        ("--speed",opt.tts_speed),
                        ("--volume",opt.tts_volume),
                        ("--pitch",opt.tts_pitch),
                        ("--voice",opt.tts_voice)):
                        if value is not None:tts_args.extend([flag,str(value)])
                    log("TTS_RENDER_START")
                    # Cancellable subprocess: emergency --hangup/--cancel-pending
                    # can interrupt API rendering as well as active TTS playback.
                    stdout,duration=guarded(tts_args,110,run_id,"TTS renderer")
                    try:
                        info=json.loads(stdout.splitlines()[-1])
                        if not info.get("ok") or info["provider"] not in ("minimax","macos"):
                            raise ValueError("provider failed")
                    except (IndexError,KeyError,ValueError,TypeError) as exc:
                        raise RuntimeError("TTS renderer returned invalid metadata") from exc
                    if not pathlib.Path(audio).is_file() or pathlib.Path(audio).stat().st_size<1500:
                        raise RuntimeError("TTS rendered empty audio")
                    log(f"TTS_RENDER_READY provider={info['provider']} "
                        f"requested={info['requested']} fallback={info['fallback']} "
                        f"reason={info['fallback_reason']} "
                        f"model={info['model']} voice={info['voice']} "
                        f"speed={info['speed']} "
                        f"audio_seconds={info['audio_seconds']} "
                        f"render_seconds={duration:.3f}")
                    device=output_device()
                    ensure_input()
                txn.update(run_id,"PREFLIGHT")
                if state=="GUI_LOCKED":
                    # Reconcile old pending cards BEFORE opening a new URL,
                    # regardless of stale journal stage, with a fixed budget
                    # and stable empty-screen quiescence.
                    txn.update(run_id,"RECOVERING",
                               previous_stage=previous.get("stage","IDLE"))
                    kvm(["recover"],55,"NanoKVM bounded recovery",run_id)
                    txn.update(run_id,"PREFLIGHT")
                else:
                    txn.check(run_id)
                    if txn.needs_recovery(previous):
                        # AX state is a snapshot, not proof that the old call ended.
                        status,elapsed=guarded([SCRIPT,"--status"],15,run_id,"AX recovery status")
                        if "STATE=NO_CALL_UI" not in status:
                            raise RuntimeError("UNLOCKED_GUI_RECOVERY_REQUIRED "+status[-120:])
                output,seconds=guarded(
                    ["/usr/bin/python3",DISPLAY_WAKE_HELPER,"--ensure-awake"],30,
                    run_id,"display preflight")
                for line in output.strip().splitlines():log("DISPLAY "+line)
                # Journal the intent BEFORE issuing a side effect: interruption
                # after this point may require recovery even on URL failure.
                txn.update(run_id,"DIAL_REQUESTED",url_may_have_been_sent=True)
                started=True
                dial_start=dt.datetime.now()
                log("DIAL_START")
                if state=="GUI_LOCKED":
                    guarded(["/usr/bin/open","-a","FaceTime",f"facetime-audio://{TARGET}"],
                            13,run_id,"FaceTime URL request")
                    log("DIAL_REQUESTED")
                    txn.update(run_id,"CONFIRMING")
                    kvm(["confirm","--timeout",str(opt.confirm_timeout),"--fast-return"],
                        opt.confirm_timeout+45,"NanoKVM unique-card confirmation",run_id)
                    confirmed=True
                    log("KVM_CONFIRM_OK")
                else:
                    # This internal command checks the active transaction token
                    # and never starts a separate outgoing call transaction.
                    guarded([SCRIPT,"--_dial-ax"],28,run_id,"AX confirmed dial",
                            env={"FACETIME_INTERNAL_RUN_ID":run_id})
                    confirmed=True
                    log("DIAL_REQUESTED")
                if opt.dial_only:
                    log("DIAL_ONLY_CONFIRMED: external hangup required")
                else:
                    txn.update(run_id,"WAITING_ANSWER")
                    deadline=time.monotonic()+opt.answer_timeout
                    detected=None
                    failures=0
                    last_unavailable_check=0.0
                    while time.monotonic()<deadline:
                        txn.check(run_id)
                        # The declined/unanswered result has a verified AX card:
                        # do not keep polling CallServices for the full timeout.
                        if time.monotonic()-last_unavailable_check>=2:
                            last_unavailable_check=time.monotonic()
                            # The unlocked AX and locked NanoKVM paths are
                            # independent, both requiring exact target/UI proof.
                            unavailable=(unavailable_popup_state() if state=="GUI_UNLOCKED"
                                         else locked_unavailable_popup_state(run_id))
                            if unavailable:
                                log("CALL_UNAVAILABLE_DETECTED")
                                if state=="GUI_LOCKED":
                                    dismiss_locked_unavailable_popup(run_id)
                                else:
                                    dismiss_unavailable_popup(run_id)
                                unavailable_dismissed=True
                                log("CALL_UNAVAILABLE_DISMISSED")
                                raise RuntimeError("CALL_UNAVAILABLE; unavailable popup dismissed")
                        try:
                            detected,elapsed=connected_at_or_after(dial_start)
                            failures=0
                        except RuntimeError as err:
                            if "disconnected before TTS" in str(err):
                                # CallServices disconnect may precede the
                                # NotificationCenter unavailable notification.
                                # Allow a short bounded window to identify it.
                                for _ in range(3 if state=="GUI_LOCKED" else 6):
                                    txn.check(run_id)
                                    unavailable=(unavailable_popup_state() if state=="GUI_UNLOCKED"
                                                 else locked_unavailable_popup_state(run_id))
                                    if unavailable:
                                        log("CALL_UNAVAILABLE_DETECTED")
                                        if state=="GUI_LOCKED":
                                            dismiss_locked_unavailable_popup(run_id)
                                        else:
                                            dismiss_unavailable_popup(run_id)
                                        unavailable_dismissed=True
                                        log("CALL_UNAVAILABLE_DISMISSED")
                                        raise RuntimeError("CALL_UNAVAILABLE; unavailable popup dismissed")
                                    time.sleep(.4)
                                raise
                            failures+=1
                            if failures>=5:raise
                            log("CALLSERVICES_RETRY "+str(err)[:100])
                            time.sleep(.25)
                            continue
                        if detected:
                            log(f"CONNECTED event={detected.isoformat(timespec='milliseconds')} "
                                f"recognition_lag={(dt.datetime.now()-detected).total_seconds():.3f}s")
                            break
                        time.sleep(.15)
                    if not detected:
                        unavailable=(unavailable_popup_state() if state=="GUI_UNLOCKED"
                                     else locked_unavailable_popup_state(run_id))
                        if unavailable:
                            log("CALL_UNAVAILABLE_DETECTED")
                            if state=="GUI_LOCKED":
                                dismiss_locked_unavailable_popup(run_id)
                            else:
                                dismiss_unavailable_popup(run_id)
                            unavailable_dismissed=True
                            log("CALL_UNAVAILABLE_DISMISSED")
                            raise RuntimeError("CALL_UNAVAILABLE; unavailable popup dismissed")
                        raise RuntimeError("ANSWER_TIMEOUT; verified cleanup required")
                    txn.check(run_id)
                    txn.update(run_id,"PLAYING")
                    log("PLAY_START")
                    _,duration=guarded([FFMPEG,"-hide_banner","-nostdin","-loglevel",
                        "error","-i",audio,"-ac","2","-ar","48000","-f",
                        "audiotoolbox","-audio_device_index",device,"-"],
                        playback_timeout_seconds(info["audio_seconds"]),run_id,"Loopback TTS",
                        connection_since=detected)
                    log(f"PLAY_END seconds={duration:.3f}")
                successful=True
        except txn.Interrupted as exc:
            priority_interrupt=True
            error=exc
            log("PRIORITY_INTERRUPT "+str(exc))
        except Exception as exc:
            error=exc
            log("CALL_ERROR "+str(exc)[:280])
        finally:
            if started and not opt.dial_only and not priority_interrupt and not unavailable_dismissed:
                try:
                    txn.check(run_id)
                    txn.update(run_id,"HANGING_UP")
                    log("HANGUP_START")
                    if state=="GUI_LOCKED":
                        kvm(["hangup","--timeout",str(opt.hangup_timeout)],
                            opt.hangup_timeout+36,"NanoKVM verified hangup",run_id)
                    else:
                        guarded([SCRIPT,"--_hangup-ax"],34,run_id,"AX hangup",
                                env={"FACETIME_INTERNAL_HANGUP":run_id})
                    log("HANGUP_OK")
                except txn.Interrupted as exc:
                    priority_interrupt=True
                    error=error or exc
                    log("PRIORITY_INTERRUPT_DURING_CLEANUP "+str(exc))
                except Exception as exc:
                    cleanup_error=exc
                    log("HANGUP_UNVERIFIED "+str(exc)[:200])
            # Another priority operation may have completed while this runner
            # was canceling. Never claim success until a fresh visual preflight
            # on the next call; interrupted runs always trigger reconciliation.
            stage=("INTERRUPTED" if priority_interrupt else
                   "DONE" if unavailable_dismissed and cleanup_error is None else
                   "RECOVERY_REQUIRED" if (error or cleanup_error or
                                          (opt.dial_only and started)) else "DONE")
            try:
                txn.update(run_id,stage,
                           last_error=str(error or cleanup_error or "")[:190],
                           last_finished_at=time.time())
            except txn.Interrupted:
                # Emergency client may have already started a later run.
                pass
        if error:
            if cleanup_error:
                raise RuntimeError(str(error)+"; cleanup="+str(cleanup_error))
            raise error
        if cleanup_error:raise RuntimeError("Verified hangup failed: "+str(cleanup_error))
        if priority_interrupt:raise txn.Interrupted("Priority action interrupted outgoing call")
        log("DIAL_CONFIRMED" if opt.dial_only else "CALL_COMPLETED")
        return 0

if __name__=="__main__":
    try:sys.exit(main(sys.argv[1:]))
    except (subprocess.TimeoutExpired,Exception) as exc:
        log("ERROR "+str(exc)[:350])
        sys.exit(75)
