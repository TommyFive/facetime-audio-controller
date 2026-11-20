#!/usr/bin/env python3
"""Independent launchd watchdog for detached FaceTime MCP jobs.

Runs every 30s even when OpenClaw/the MCP transport disconnects. Fail closed:
hangup only when a matching, unfinished controller transaction is recorded.
"""
import json
import os
from pathlib import Path
import subprocess
import time
from facetime_async_worker import STATE,CONTROLLER,atomic

from facetime_runtime import state_dir
JOURNAL=state_dir()/"journal.json"
ACTIVE={"DIAL_REQUESTED","CONFIRMING","WAITING_ANSWER","PLAYING",
        "HANGING_UP","PREFLIGHT","RECOVERING"}
def alive(pid):
    if not isinstance(pid,int) or pid<=0:return False
    try:os.kill(pid,0)
    except ProcessLookupError:return False
    except PermissionError:return True
    # A zombie still responds to kill(pid, 0), but cannot supervise a call.
    try:
        p=subprocess.run(["/bin/ps","-p",str(pid),"-o","state="],
                         capture_output=True,text=True,timeout=3)
        state=p.stdout.strip()
        return p.returncode==0 and bool(state) and not state.startswith(("Z","X"))
    except (OSError,subprocess.TimeoutExpired):
        return True  # fail closed on uncertain process inspection

def check():
    if not STATE.exists():return []
    results=[]
    for file in sorted(STATE.glob("*.json")):
        try:
            item=json.loads(file.read_text())
            if item.get("state") not in ("running","starting"):continue
            now=time.time()
            expired=now>item.get("deadline_at",now+1)
            gone=not alive(item.get("worker_pid"))
            request_id=item.get("request_id")
            journal=json.loads(JOURNAL.read_text())
            stalled_hangup=(journal.get("stage")=="HANGING_UP"
                            and journal.get("run_id")==item.get("controller_run_id")
                            and now-journal.get("updated_at",now)>90)
            if not expired and not gone and not stalled_hangup:continue
            if gone and not stalled_hangup and now-item.get("started_at",now)<15:continue
            # Do not interrupt an unrelated user-initiated call.
            owned=(journal.get("stage") in ACTIVE|{"RECOVERY_REQUIRED"}
                   and isinstance(item.get("controller_run_id"),str)
                   and journal.get("run_id")==item["controller_run_id"]
                   and journal.get("url_may_have_been_sent") is True)
            verified=False
            reason=("hangup_stalled" if stalled_hangup else
                    "deadline_exceeded" if expired else "worker_disappeared")
            if owned:
                # Re-check transaction ownership immediately before mutating
                # FaceTime, to avoid interfering with a newer unrelated call.
                fresh=json.loads(JOURNAL.read_text())
                if fresh.get("run_id")!=item["controller_run_id"]:
                    owned=False
                else:
                    r=subprocess.run([str(CONTROLLER),"--hangup","--timeout","24"],
                                     timeout=85,capture_output=True,text=True)
                    verified=r.returncode==0
            # Re-read immediately before writing to avoid downgrading a completed job.
            current=json.loads(file.read_text())
            if current.get("state") not in ("running","starting"):continue
            current.update(state="watchdog_recovered" if verified else "recovery_required",
                           ok=False,hangup_verified=verified,
                           error=reason,completed_at=time.time(),
                           updated_at=time.time(),watchdog_owned_transaction=owned)
            atomic(request_id,current)
            results.append((request_id,reason,verified))
        except Exception as exc:
            # Fail closed and leave a verifiable log entry rather than pretending success.
            results.append((file.stem,type(exc).__name__,False))
    return results
if __name__=="__main__":
    for item in check():print(*item,flush=True)
