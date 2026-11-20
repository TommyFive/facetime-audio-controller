#!/usr/bin/env python3
"""Persistent FaceTime transaction journal and priority interrupt protocol.

Two separate locks:
 - call.lock: exclusive for a complete outgoing call, auto released by OS
 - ui.lock: bounded, exclusive around screenshot/verification/HID operations

Emergency manual hangup/cancel NEVER acquires call.lock. It signals the current
call through the journal then acquires ui.lock for its own safe interaction.
The journal persists incomplete transactions for later bounded recovery.
"""
import contextlib
import fcntl
import json
import os
import pathlib
import tempfile
import time
import uuid

from facetime_runtime import state_dir
ROOT = state_dir()
CALL_LOCK=ROOT/"call.lock"
UI_LOCK=ROOT/"ui.lock"
JOURNAL_LOCK=ROOT/"journal.lock"
JOURNAL=ROOT/"journal.json"
ACTIVE_STAGES=frozenset({
    "STARTING","PREFLIGHT","DIAL_REQUESTED","CONFIRMING",
    "WAITING_ANSWER","PLAYING","HANGING_UP","CANCELLING","RECOVERING"})
FINAL_STAGES=frozenset({"IDLE","DONE","INTERRUPTED","RECOVERY_REQUIRED"})

class Interrupted(Exception):
    pass

def setup():
    ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(ROOT,0o700)

@contextlib.contextmanager
def lockfile(path, timeout=None):
    setup()
    fd=os.open(str(path),os.O_CREAT|os.O_RDWR|getattr(os,"O_NOFOLLOW",0),0o600)
    os.fchmod(fd,0o600)
    try:
        start=time.monotonic()
        while True:
            try:
                fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if timeout is None:
                    raise RuntimeError("LOCK_BUSY:"+path.name)
                if time.monotonic()-start>timeout:
                    raise RuntimeError("LOCK_TIMEOUT:"+path.name)
                time.sleep(.12)
        yield
    finally:
        os.close(fd)  # kernel releases lock even after SIGKILL

def read():
    setup()
    if not JOURNAL.exists():return {"stage":"IDLE"}
    try:
        value=json.loads(JOURNAL.read_text())
        if not isinstance(value,dict) or "stage" not in value:
            raise ValueError("invalid journal")
        return value
    except (ValueError,OSError) as exc:
        raise RuntimeError("JOURNAL_INVALID; manual inspection required") from exc

def _write(record):
    setup()
    fd,name=tempfile.mkstemp(prefix=".journal-",dir=str(ROOT))
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,"w") as file:
            json.dump(record,file,sort_keys=True,separators=(",",":"))
            file.flush();os.fsync(file.fileno())
        os.replace(name,JOURNAL)
    finally:
        if os.path.exists(name):os.unlink(name)

def snapshot():
    with lockfile(JOURNAL_LOCK,timeout=4):
        return read()

def start():
    with lockfile(JOURNAL_LOCK,timeout=4):
        previous=read()
        run_id=uuid.uuid4().hex
        record={"run_id":run_id,"stage":"STARTING","pid":os.getpid(),
                "started_at":time.time(),"updated_at":time.time(),
                "previous_stage":previous.get("stage","IDLE"),
                "previous_run_id":previous.get("run_id"),
                "interrupt":None}
        _write(record)
        return record,previous

def update(run_id,stage,**fields):
    if stage not in ACTIVE_STAGES|FINAL_STAGES:
        raise ValueError("invalid stage")
    with lockfile(JOURNAL_LOCK,timeout=4):
        state=read()
        if state.get("run_id")!=run_id:
            raise Interrupted("Run ownership was superseded")
        state.update(fields)
        state["stage"]=stage
        state["updated_at"]=time.time()
        _write(state)
        return state

def interrupt(action):
    if action not in ("hangup","cancel-pending"):
        raise ValueError("unsupported interrupt")
    with lockfile(JOURNAL_LOCK,timeout=4):
        state=read()
        active=state.get("stage") in ACTIVE_STAGES
        if action=="cancel-pending" and active and state.get("stage") not in (
                "STARTING","PREFLIGHT","DIAL_REQUESTED","CONFIRMING","RECOVERING"):
            return {"active":False,"refused":True,"stage":state.get("stage"),
                    "run_id":state.get("run_id")}
        if active:
            state["interrupt"]={"action":action,"run_id":state["run_id"],
                                "time":time.time(),"nonce":uuid.uuid4().hex}
            _write(state)
        return {"active":active,"stage":state.get("stage"),"run_id":state.get("run_id") if active else None}

def check(run_id):
    state=read()
    if state.get("run_id")!=run_id:
        raise Interrupted("Transaction owner changed")
    request=state.get("interrupt")
    if request and request.get("run_id")==run_id:
        raise Interrupted("PRIORITY_"+request.get("action","unknown").upper())
    return state

def verify_action_allowed(run_id):
    if run_id:
        check(run_id)

def pid_alive(pid):
    if not isinstance(pid,int) or pid<=0:return False
    try:os.kill(pid,0);return True
    except ProcessLookupError:return False
    except PermissionError:return True

def needs_recovery(previous):
    stage=previous.get("stage","IDLE")
    if stage in ("IDLE","DONE"):return False
    # Even a successful manual interruption may leave hidden queued FaceTime UI.
    return True

def action_locked(timeout=35):
    return lockfile(UI_LOCK,timeout=timeout)
