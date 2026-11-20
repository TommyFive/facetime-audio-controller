#!/usr/bin/env python3
"""Detached, persistent FaceTime MCP request worker.

A new OS process group survives the agent's 90s RPC timeout. Only a stable
request id, not call text, appears in process arguments. Audio/call/cleanup
remain owned by the controller. Results are written atomically.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

from facetime_runtime import state_dir
STATE=state_dir()/"mcp/async"
CONTROLLER=Path(__file__).resolve().parent/"facetime-call.sh"
MAX_RUNTIME=1680
def path(request_id): return STATE/(request_id+".json")
def load(request_id): return json.loads(path(request_id).read_text())
def atomic(request_id, data):
    STATE.mkdir(mode=0o700,parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix=".state-",dir=STATE)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,"w") as out:
            json.dump(data,out,sort_keys=True)
            out.flush()
            os.fsync(out.fileno())
        os.replace(name,path(request_id))
    finally:
        if os.path.exists(name):os.unlink(name)
def update(request_id, **fields):
    data=load(request_id)
    data.update(fields, updated_at=time.time())
    atomic(request_id,data)
def cleanup(reason):
    """Priority hangup verifies the actual fixed-recipient screen, never blind UI clicks."""
    try:
        r=subprocess.run([str(CONTROLLER),"--hangup","--timeout","24"],
                         capture_output=True,text=True,timeout=85,
                         env={**os.environ,"PATH":"/usr/bin:/bin:/usr/sbin:/sbin"})
        return dict(attempted=True,verified=r.returncode==0,
                    exit_code=r.returncode,reason=reason)
    except (OSError,subprocess.TimeoutExpired) as exc:
        return dict(attempted=True,verified=False,reason=reason,error=type(exc).__name__)
def run(request_id):
    data=load(request_id)
    input_path=STATE/(request_id+".input")
    payload=json.loads(input_path.read_text())
    input_path.unlink()
    args=payload["args"]
    started=time.monotonic()
    log_path=STATE/(request_id+".log")
    proc=None
    try:
        with log_path.open("w") as log:
            os.chmod(log_path,0o600)
            proc=subprocess.Popen([str(CONTROLLER),*args],
                                  stdin=subprocess.DEVNULL,stdout=log,
                                  stderr=subprocess.STDOUT,start_new_session=True,
                                  cwd=CONTROLLER.parent,
                                  env={**os.environ,"PATH":"/usr/bin:/bin:/usr/sbin:/sbin"})
            update(request_id,state="running",worker_pid=os.getpid(),
                   controller_pid=proc.pid,controller_pgid=proc.pid,
                   started_at=time.time(),deadline_at=time.time()+MAX_RUNTIME)
            known_run=None
            while proc.poll() is None:
                if known_run is None:
                    try:
                        journal=json.loads((state_dir()/"journal.json").read_text())
                        if journal.get("started_at",0)>=data.get("created_at",0)-5 and journal.get("pid") and journal.get("stage") not in ("DONE","IDLE"):
                            known_run=journal.get("run_id")
                            update(request_id,controller_run_id=known_run)
                    except (OSError,ValueError):pass
                if time.monotonic()-started>MAX_RUNTIME:
                    raise TimeoutError("CONTROLLER_WALLCLOCK_TIMEOUT")
                time.sleep(2)
            rc=proc.returncode
        raw=log_path.read_text(errors="replace")
        call_started="DIAL_REQUESTED" in raw or "CONNECTED event=" in raw
        completed=(rc==0 and "PLAY_END" in raw and "HANGUP_OK" in raw
                   and "CALL_COMPLETED" in raw and "CONNECTED event=" in raw)
        provider=None
        for value in ("minimax","macos"):
            if "TTS_RENDER_READY provider="+value in raw: provider=value
        fallback="fallback=True" in raw
        if completed:
            update(request_id,state="call_terminated",ok=True,
                   hangup_verified=True,call_connected_observed=True,
                   tts_provider_used=provider,tts_fallback=fallback,
                   completed_at=time.time(),controller_exit=rc)
        else:
            # The controller may have failed to hang up; do not assume its exit
            # closes a live call. Recheck via verified priority hangup.
            remediate=cleanup("controller_incomplete") if call_started else dict(attempted=False)
            update(request_id,state="controller_failed",ok=False,
                   hangup_verified=bool(remediate.get("verified")),
                   call_connected_observed="CONNECTED event=" in raw,
                   tts_provider_used=provider,tts_fallback=fallback,
                   controller_exit=rc,cleanup=remediate,completed_at=time.time(),
                   error="CONTROLLER_INCOMPLETE")
    except BaseException as exc:
        if proc is not None and proc.poll() is None:
            try:os.killpg(proc.pid,signal.SIGTERM)
            except ProcessLookupError:pass
            try:proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:os.killpg(proc.pid,signal.SIGKILL)
                except ProcessLookupError:pass
        remediate=cleanup(type(exc).__name__)
        update(request_id,state="failed",ok=False,completed_at=time.time(),
               hangup_verified=bool(remediate.get("verified")),
               cleanup=remediate,error=type(exc).__name__)
        raise
def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("request_id")
    args=parser.parse_args()
    run(args.request_id)
if __name__=="__main__": main()
