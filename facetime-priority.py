#!/usr/bin/env python3
"""Priority FaceTime controls; bypass the outgoing-call mutex by design.

--hangup / --cancel-pending request cooperative interruption of an ongoing
call, then operate through a separate bounded NanoKVM UI mutex. Nothing
force-deletes flock files or sets an ambiguous call state to IDLE.
"""
import argparse
import importlib.util
import tempfile
import os
import pathlib
import signal
import subprocess
import sys
import time

import facetime_txn as txn
import facetime_runtime as runtime
if runtime.recipient(): os.environ["FACETIME_RECIPIENT"]=runtime.recipient()

DIR=pathlib.Path(__file__).resolve().parent
SCRIPT=str(DIR/"facetime-call.sh")
GUI=str(DIR/"facetime-gui-session.py")
KVM_PY=str(DIR/".venv/bin/python")
KVM_UI=str(DIR/"nanokvm-call-ui.py")
AX=str(DIR/"facetime-ax-control.applescript")
TTS_RENDER=str(DIR/"facetime-tts.py")
FFMPEG=runtime.executable("ffmpeg")

def log(*args):
    print("PRIORITY",*args,flush=True)

def locked():
    p=subprocess.run(["/usr/bin/python3",GUI],capture_output=True,
                     text=True,timeout=10,check=True)
    value=p.stdout.strip()
    if value not in ("GUI_LOCKED","GUI_UNLOCKED"):
        raise RuntimeError("UNRECOGNIZED_GUI_STATE; refusing GUI action")
    return value=="GUI_LOCKED"

def invoke(cmd,timeout,run_id=None):
    env=dict(os.environ)
    if run_id:env["FACETIME_TXN_RUN_ID"]=run_id
    p=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                       text=True,start_new_session=True,env=env)
    try:
        started=time.monotonic()
        while True:
            if run_id:txn.check(run_id)
            if time.monotonic()-started>timeout:
                raise subprocess.TimeoutExpired(cmd,timeout)
            try:
                out,err=p.communicate(timeout=.3)
                break
            except subprocess.TimeoutExpired:continue
        if p.returncode:
            raise RuntimeError("ACTION_EXIT_"+str(p.returncode)+" "+(err or out)[-280:])
        if out:print(out,end="",flush=True)
        return 0
    except BaseException:
        if p.poll() is None:
            try:os.killpg(p.pid,signal.SIGTERM)
            except ProcessLookupError:pass
            try:p.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                try:os.killpg(p.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                p.communicate(timeout=2)
        raise

def priority_action(action,timeout):
    # In contrast to normal operations, call.lock is NEVER acquired here.
    try:
        before=txn.interrupt(action)
    except RuntimeError as error:
        # Emergency hangup must still be available if journal is damaged.
        # The UI action mutex and visual checks remain mandatory.
        before={"active":False,"stage":"UNKNOWN"}
        log("JOURNAL_UNAVAILABLE_PROCEED_WITH_SAFE_EMERGENCY_UI",str(error)[:80])
    if before.get("refused"):
        raise RuntimeError("CANCEL_NOT_ALLOWED_DURING_ACTIVE_CALL stage="+
                           str(before["stage"])+"; use --hangup")
    log("INTERRUPT_SENT",action,"active_transaction="+str(before["active"]))
    with txn.lockfile(txn.ROOT/"priority.lock",timeout=25):
        # Let the outgoing runner see the interrupt and cancel its own
        # in-flight NanoKVM helper before the emergency action's UI lock.
        if before["active"]:time.sleep(.35)
        if locked():
            if action=="hangup":
                invoke([KVM_PY,KVM_UI,"hangup","--timeout",str(timeout)],
                       timeout+55)
                # Validate the UI stays clear, or safely clean a late pending
                # request that emerged after the first screenshot.
                invoke([KVM_PY,KVM_UI,"recover"],55)
            else:
                invoke([KVM_PY,KVM_UI,"recover"],55)
        else:
            if action=="hangup":
                invoke(["/usr/bin/osascript",AX,"hangup"],25)
            else:
                invoke(["/usr/bin/osascript",AX,"cancel-pending"],25)
        log("ACTION_COMPLETE",action,"call_lock_not_required=true")
        return 0

def manual_confirm(timeout):
    # Confirm is *not* priority. It must not race with --call or --dial.
    with txn.lockfile(txn.CALL_LOCK):
        entry,previous=txn.start()
        run_id=entry["run_id"]
        try:
            txn.update(run_id,"CONFIRMING")
            if locked():
                invoke([KVM_PY,KVM_UI,"confirm","--timeout",str(timeout),
                        "--fast-return"],timeout+45,run_id=run_id)
            else:
                invoke(["/usr/bin/osascript",AX,"confirm"],25,run_id=run_id)
            txn.update(run_id,"RECOVERY_REQUIRED",
                       last_error="Manual confirm may result in active outgoing call")
            return 0
        except txn.Interrupted:
            txn.update(run_id,"INTERRUPTED")
            raise
        except Exception as exc:
            txn.update(run_id,"RECOVERY_REQUIRED",last_error=str(exc)[:180])
            raise

def manual_recover():
    with txn.lockfile(txn.CALL_LOCK):
        entry,previous=txn.start()
        rid=entry["run_id"]
        try:
            txn.update(rid,"RECOVERING")
            if locked():
                invoke([KVM_PY,KVM_UI,"recover"],70,run_id=rid)
            else:
                status=subprocess.run([SCRIPT,"--status"],capture_output=True,text=True,timeout=15)
                if status.returncode or "STATE=NO_CALL_UI" not in status.stdout:
                    raise RuntimeError("UNLOCKED_RECOVERY_NOT_IDLE")
            txn.update(rid,"DONE",recovered=True)
            log("RECOVERY_VERIFIED_IDLE")
            return 0
        except Exception as err:
            txn.update(rid,"RECOVERY_REQUIRED",last_error=str(err)[:180])
            raise

def standalone_speak(message,args):
    """Use the same configurable TTS path as --call, without initiating a call."""
    with txn.lockfile(txn.CALL_LOCK):
        record,previous=txn.start()
        run_id=record["run_id"]
        try:
            with tempfile.TemporaryDirectory(prefix="facetime-speak-") as folder:
                audio=str(pathlib.Path(folder)/"voice.aiff")
                render_args=[sys.executable,TTS_RENDER,"--output",audio,"--text",message]
                for flag,value in (("--provider",args.tts_provider),
                                   ("--speed",args.tts_speed),
                                   ("--volume",args.tts_volume),
                                   ("--pitch",args.tts_pitch),
                                   ("--voice",args.tts_voice)):
                    if value is not None:render_args.extend((flag,str(value)))
                txn.update(run_id,"PLAYING")
                invoke(render_args,110,run_id=run_id)
                spec=importlib.util.spec_from_file_location(
                    "facetime_fast_audio_device",DIR/"facetime-call-fast.py")
                module=importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                device=module.output_device()
                module.ensure_input()
                invoke([FFMPEG,"-hide_banner","-nostdin","-loglevel","error",
                        "-i",audio,"-ac","2","-ar","48000","-f","audiotoolbox",
                        "-audio_device_index",device,"-"],180,run_id=run_id)
            txn.update(run_id,"DONE")
            return 0
        except txn.Interrupted:
            txn.update(run_id,"INTERRUPTED")
            raise
        except Exception as error:
            txn.update(run_id,"RECOVERY_REQUIRED",last_error=str(error)[:160])
            raise

def main():
    p=argparse.ArgumentParser()
    p.add_argument("action",choices=["hangup","cancel-pending","confirm","recover","speak"])
    p.add_argument("--timeout",type=float,default=None)
    p.add_argument("--tts-provider",choices=("minimax","macos"))
    p.add_argument("--tts-speed",type=float)
    p.add_argument("--tts-volume",type=float)
    p.add_argument("--tts-pitch",type=int)
    p.add_argument("--tts-voice")
    p.add_argument("text",nargs="*")
    args=p.parse_intermixed_args()
    seconds=args.timeout if args.timeout is not None else (24 if args.action=="hangup" else 20)
    if not 3<=seconds<=120:p.error("timeout must be 3..120")
    if args.action=="speak":
        if not " ".join(args.text).strip():p.error("speak needs nonempty text")
        return standalone_speak(" ".join(args.text),args)
    if args.text:p.error("no message arguments accepted")
    if args.action=="confirm":
        return manual_confirm(seconds)
    if args.action=="recover":
        return manual_recover()
    return priority_action(args.action,seconds)

if __name__=="__main__":
    try:sys.exit(main())
    except Exception as exc:
        log("ERROR",str(exc)[:360])
        sys.exit(75)
