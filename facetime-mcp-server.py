#!/usr/bin/env python3
"""Local stdio MCP adapter for the existing, fixed-recipient FaceTime controller.

No listening socket. This intentionally does not implement outbound recipient selection.
The existing shell controller remains the sole macOS automation and TTS executor.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import tempfile
import importlib.util
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from typing import Any

from mcp.server import MCPServer

ROOT = Path(__file__).resolve().parent
from facetime_runtime import state_dir,recipient
CONTROLLER = ROOT / "facetime-call.sh"
STATE_DIR = state_dir() / "mcp"
RUNS = STATE_DIR / "requests.json"
LOCK = STATE_DIR / "requests.lock"
mcp = MCPServer("facetime-controller")
ASYNC_DIR=STATE_DIR/"async"
ASYNC_WORKER=ROOT/"facetime_async_worker.py"
CONTROLLER_JOURNAL=state_dir()/"journal.json"
def _tts_module():
    spec=importlib.util.spec_from_file_location("facetime_tts_validation", ROOT/"facetime-tts.py")
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _result(action: str, *, ok: bool, state: str, code: str | None = None,
            output: str = "", elapsed: float = 0, request_id: str | None = None) -> dict[str, Any]:
    # Output is allowlisted controller diagnostics, never include environment or subprocess secrets.
    safe = "\n".join(line[:300] for line in output.splitlines() if
                     not re.search(r"(?i)(api.?key|authorization:|bearer |token=|password|secret)", line))
    target=recipient()
    if target:safe=safe.replace(target,"[configured-recipient]")
    return dict(action=action, ok=ok, state=state, code=code,
                controller_output=safe[-3000:], elapsed_seconds=round(elapsed, 2),
                request_id=request_id, timestamp=dt.datetime.now(dt.timezone.utc).isoformat())

def _run_bounded(cmd: list[str], *, timeout: int, **kwargs: Any) -> subprocess.CompletedProcess[str]:
    """Run a controller command with a bounded lifetime for its entire process group.

    A shell controller can spawn osascript/ffmpeg children. subprocess.run's
    timeout kills only the immediate shell, potentially leaving GUI children
    alive. Use a separate process group to terminate descendants as well.
    """
    proc = subprocess.Popen(cmd, start_new_session=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, **kwargs)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            proc.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.communicate(timeout=2)
        raise
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)


def _exec(action: str, args: list[str], timeout: int, request_id: str | None = None) -> dict[str, Any]:
    start = time.monotonic()
    try:
        p = _run_bounded([str(CONTROLLER), *args], timeout=timeout, cwd=ROOT,
                         env={**os.environ, "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"})
    except subprocess.TimeoutExpired:
        return _result(action, ok=False, state="timeout_unknown", code="CONTROLLER_TIMEOUT",
                       elapsed=time.monotonic()-start, request_id=request_id)
    except (OSError, ValueError):
        return _result(action, ok=False, state="execution_failed", code="CONTROLLER_UNAVAILABLE",
                       elapsed=time.monotonic()-start, request_id=request_id)
    combined = (p.stdout + "\n" + p.stderr).strip()
    # An exit-0 is not evidence of connection, speech delivery, or call termination.
    state = "completed_by_controller" if p.returncode == 0 else "controller_failed"
    code = None if p.returncode == 0 else f"CONTROLLER_EXIT_{p.returncode}"
    if "LOCK_BUSY" in combined:
        state, code = "busy", "LOCK_BUSY"
    elif "CALL_UNAVAILABLE" in combined:
        state, code = "recipient_unavailable", "CALL_UNAVAILABLE"
    if "ACCESSIBILITY_PERMISSION_DENIED" in combined or "-25211" in combined:
        state, code = "permission_denied", "ACCESSIBILITY_PERMISSION_DENIED"
    elif "NANOKVM_ACCESS_DENIED" in combined:
        state, code = "permission_denied", "NANOKVM_ACCESS_DENIED"
    elif "PERMISSION_CHECK" in combined or "ACCESSIBILITY_CHECK_FAILED" in combined:
        state, code = "permission_unavailable", "PERMISSION_CHECK_FAILED"
    if "AUDIO_ROUTE_HUNG" in combined:
        state, code = "audio_route_unavailable", "AUDIO_ROUTE_HUNG"
    elif "AUDIO_ROUTE_FAILED" in combined:
        state, code = "audio_route_unavailable", "AUDIO_ROUTE_FAILED"
    result = _result(action, ok=p.returncode == 0, state=state,
                     code=code, output=combined, elapsed=time.monotonic()-start,
                     request_id=request_id)
    result["observed_facetime_state"] = None
    result["tts_provider_used"] = None
    result["tts_fallback"] = None
    result["call_connected_observed"] = False
    result["hangup_verified"] = False
    if action == "status":
        status_match = re.search(r'KVM_UI_RESULT (\{[^\n]*\})', combined)
        if status_match:
            try:
                result["observed_facetime_state"] = json.loads(status_match.group(1)).get("status")
            except (ValueError, KeyError):
                pass
        else:
            ax_match = re.search(r'STATE=([A-Z_]+)', combined)
            if ax_match:
                result["observed_facetime_state"] = ax_match.group(1)
    if action == "call":
        provider_match = re.search(r'TTS_RENDER_READY provider=(minimax|macos).*?fallback=(True|False)', combined)
        if provider_match:
            result["tts_provider_used"] = provider_match.group(1)
            result["tts_fallback"] = provider_match.group(2) == "True"
        result["call_connected_observed"] = bool(re.search(r"\bCONNECTED event=", combined))
        result["hangup_verified"] = "HANGUP_OK" in combined
        if p.returncode == 0 and all((result["call_connected_observed"], result["hangup_verified"], "PLAY_END" in combined, "CALL_COMPLETED" in combined)):
            result["state"] = "call_terminated"
        elif p.returncode == 0:
            result["state"] = "success_unverified"
            result["code"] = "MISSING_LIFECYCLE_EVIDENCE"
            result["ok"] = False
    return result

def _validate_text(message: str, provider: str = "minimax") -> None:
    if not isinstance(message,str) or not message.strip():
        raise ValueError("Message must not be empty")
    if any(ord(c)<32 and c not in "\n\t" for c in message):
        raise ValueError("Message contains control characters")
    tts=_tts_module()
    config=tts.config_load(tts.CONFIG)
    try:tts.validate_text_length(message,config,provider)
    except tts.TTSError as exc:
        raise ValueError("TTS text rejected: "+exc.code) from None

def call_timeout_seconds(confirm_timeout: int, answer_timeout: int,
                         hangup_timeout: int) -> int:
    """Bound the entire controller lifetime, including long audio and hangup.

    Aligns with the renderer's 1200-second AIFF limit and the 1215-second
    playback watchdog. Every subprocess remains independently bounded.
    """
    return int(
        110  # MiniMax render and conversion
        + 55 + 30  # bounded NanoKVM recovery and display/preflight
        + confirm_timeout + 45  # confirmation / GUI allowance
        + answer_timeout + 30  # answer detection and CallServices retries
        + 1215  # verified maximum playback + 15-second watchdog
        + hangup_timeout + 36  # guarded hangup and visual verification
        + 60  # OS scheduling and MCP protocol overhead
    )

def _validate_id(request_id: str) -> None:
    if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{7,79}", request_id):
        raise ValueError("request_id must be 8..80 ASCII letters, digits, dots, hyphens or underscores")

def _validate_tts(speed: float, volume: float, pitch: int, provider: str) -> None:
    if provider not in {"minimax", "macos"}:
        raise ValueError("Unsupported TTS provider")
    if not (0.5 <= speed <= 2.0 and 0.01 <= volume <= 10.0 and -12 <= pitch <= 12):
        raise ValueError("Invalid TTS parameters")

def _journal(call):
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(STATE_DIR, 0o700)
    with open(LOCK, "a+", encoding="utf-8") as fh:
        os.chmod(LOCK, 0o600)
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            try:
                db = json.loads(RUNS.read_text()) if RUNS.exists() else {}
            except (ValueError, OSError):
                # Fail closed if durable request bookkeeping cannot be trusted.
                raise RuntimeError("IDEMPOTENCY_JOURNAL_UNREADABLE")
            now = time.time()
            db = {k:v for k,v in db.items() if now-v.get("created",now) < 86400}
            result, changed = call(db)
            if changed:
                tmp = STATE_DIR / ("requests." + str(os.getpid()) + ".tmp")
                fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w") as out:
                    json.dump(db, out, sort_keys=True)
                    out.flush()
                    os.fsync(out.fileno())
                os.replace(tmp, RUNS)
            return result
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

@mcp.tool()
def facetime_capabilities() -> dict[str, Any]:
    """Read safe local FaceTime MCP capabilities and operational constraints."""
    return dict(target="fixed_owner_identity", transport="stdio", controller="legacy_shell",
                call_modes=["call","call_start_status"], actions=["call","call_start","call_status","call_wait","call_cancel","status","hangup","speak","health"],
                tts_providers=["minimax", "macos"], default_speech_speed=1.1,
                duplicate_prevention="request_id durable 24-hour replay protection",
                limitations=["FaceTime state is not authenticated via Apple CallServices",
                             "External calls cannot be ruled out", "No dynamic recipients"])

@mcp.tool()
def facetime_health() -> dict[str, Any]:
    """Check actual OS automation permissions without playing audio or dialing."""
    exists = CONTROLLER.is_file()
    executable = os.access(CONTROLLER, os.X_OK)
    permission = {"ok": False, "code": "PERMISSION_CHECK_UNAVAILABLE",
                  "message": "Permission preflight helper unavailable."}
    if exists and executable:
        try:
            proc = _run_bounded([sys.executable, str(ROOT/"facetime-permissions.py")],
                                timeout=35, cwd=ROOT)
            permission = json.loads(proc.stdout.strip().splitlines()[-1])
            if proc.returncode != 0:
                permission["ok"] = False
        except (OSError, subprocess.TimeoutExpired, ValueError, IndexError, TypeError):
            permission = {"ok": False, "code": "PERMISSION_CHECK_UNAVAILABLE",
                          "message": "Permission preflight failed unexpectedly."}
    return dict(ok=bool(exists and executable and permission.get("ok")),
                controller_present=exists, executable=executable,
                permissions_ok=bool(permission.get("ok")),
                permissions_code=permission.get("code"),
                permissions_message=permission.get("message"),
                gui_mode=permission.get("mode"),
                sdk="mcp-python-2", transport="stdio")

@mcp.tool()
def facetime_status() -> dict[str, Any]:
    """Observe FaceTime and Mac GUI state without initiating a call."""
    return _exec("status", ["--status"], 45)

@mcp.tool()
def facetime_hangup(timeout: int = 24) -> dict[str, Any]:
    """Safely hang up the currently verified FaceTime call; does not dial."""
    if not 5 <= timeout <= 60:
        raise ValueError("timeout must be 5..60 seconds")
    return _exec("hangup", ["--hangup", "--timeout", str(timeout)], timeout + 20)

@mcp.tool()
def facetime_speak(message: str, provider: str = "minimax", speed: float = 1.1,
                   volume: float = 1.0, pitch: int = 0) -> dict[str, Any]:
    """Speak using the existing Loopback TTS route (MiniMax with macOS fallback)."""
    _validate_text(message,provider)
    _validate_tts(speed, volume, pitch, provider)
    return _exec("speak", ["--speak", "--tts-provider", provider,
                          "--tts-speed", str(speed), "--tts-volume", str(volume),
                          "--tts-pitch", str(pitch), message], 120)

@mcp.tool()
def facetime_call(message: str, request_id: str, provider: str = "minimax",
                  speed: float = 1.1, volume: float = 1.0, pitch: int = 0,
                  confirm_timeout: int = 20, answer_timeout: int = 60,
                  hangup_timeout: int = 24) -> dict[str, Any]:
    """Place exactly one call to the controller's FIXED owner recipient.

    This is a real outgoing FaceTime Audio call. request_id is mandatory and
    replay-protected; never generate another ID when retrying the same intent.
    Successful process exit is NOT independent handset-side audio verification.
    """
    _validate_text(message,provider)
    _validate_id(request_id)
    _validate_tts(speed, volume, pitch, provider)
    if not (4 <= confirm_timeout <= 120 and 5 <= answer_timeout <= 180 and 5 <= hangup_timeout <= 60):
        raise ValueError("Invalid timeout range")
    args = ["--call", "--tts-provider", provider, "--tts-speed", str(speed),
            "--tts-volume", str(volume), "--tts-pitch", str(pitch),
            "--confirm-timeout", str(confirm_timeout),
            "--answer-timeout", str(answer_timeout),
            "--hangup-timeout", str(hangup_timeout), message]
    if _async_path(request_id).exists():
        return _result("call",ok=False,state="duplicate_suppressed",
                       code="DUPLICATE_ASYNC_REQUEST",request_id=request_id)
    fingerprint = __import__("hashlib").sha256(json.dumps(args).encode()).hexdigest()
    def reserve(db):
        prior = db.get(request_id)
        if prior:
            if prior["fingerprint"] != fingerprint:
                return _result("call", ok=False, state="rejected", code="REQUEST_ID_CONFLICT",
                               request_id=request_id), False
            return _result("call", ok=False, state="duplicate_suppressed",
                           code="DUPLICATE_REQUEST", request_id=request_id), False
        db[request_id] = dict(created=time.time(), fingerprint=fingerprint,
                              state="reserved")
        return None, True
    previous = _journal(reserve)
    if previous is not None:
        return previous
    outcome = _exec("call", args,
                    call_timeout_seconds(confirm_timeout, answer_timeout, hangup_timeout),
                    request_id=request_id)
    # Conservative at-most-once: even if outcome failed, same ID is never re-dialed.
    def update(db):
        if request_id in db:
            db[request_id]["state"] = outcome["state"]
        return None, True
    _journal(update)
    return outcome

def _async_path(request_id: str) -> Path:
    return ASYNC_DIR/(request_id+".json")

def _async_status(request_id: str) -> dict[str, Any]:
    try:
        data=json.loads(_async_path(request_id).read_text())
    except FileNotFoundError:
        return _result("call_status",ok=False,state="not_found",
                       code="REQUEST_NOT_FOUND",request_id=request_id)
    except (ValueError,OSError):
        return _result("call_status",ok=False,state="unknown",
                       code="STATE_UNREADABLE",request_id=request_id)
    # No private speech text or API keys are persisted into status.
    return {key:data.get(key) for key in (
        "request_id","state","ok","started_at","updated_at","deadline_at",
        "completed_at","hangup_verified","call_connected_observed",
        "tts_provider_used","tts_fallback","error","cleanup","controller_exit")}

@mcp.tool()
def facetime_call_start(message: str, request_id: str, provider: str = "minimax",
                        speed: float = 1.1, volume: float = 1.0, pitch: int = 0,
                        confirm_timeout: int = 20, answer_timeout: int = 60,
                        hangup_timeout: int = 24) -> dict[str, Any]:
    """Start a detached, idempotent fixed-recipient call; returns immediately.

    Poll facetime_call_status to confirm playback, completion and verified
    hangup. Never retry with a different request ID after uncertain outcomes.
    """
    _validate_id(request_id)
    _validate_tts(speed,volume,pitch,provider)
    _validate_text(message,provider)
    if not (4 <= confirm_timeout <= 120 and 5 <= answer_timeout <= 180
            and 5 <= hangup_timeout <= 60):
        raise ValueError("Invalid timeout range")
    args=["--call","--tts-provider",provider,"--tts-speed",str(speed),
          "--tts-volume",str(volume),"--tts-pitch",str(pitch),
          "--confirm-timeout",str(confirm_timeout),
          "--answer-timeout",str(answer_timeout),
          "--hangup-timeout",str(hangup_timeout),message]
    fingerprint=hashlib.sha256(json.dumps(args).encode()).hexdigest()
    STATE_DIR.mkdir(mode=0o700,parents=True,exist_ok=True)
    ASYNC_DIR.mkdir(mode=0o700,parents=True,exist_ok=True)
    with open(LOCK,"a+",encoding="utf-8") as guard:
        os.chmod(LOCK,0o600)
        fcntl.flock(guard.fileno(),fcntl.LOCK_EX)
        try:
            result_path=_async_path(request_id)
            if result_path.exists():
                existing=json.loads(result_path.read_text())
                if existing.get("fingerprint") != fingerprint:
                    return _result("call_start",ok=False,state="rejected",
                                   code="REQUEST_ID_CONFLICT",request_id=request_id)
                return _async_status(request_id)
            # A previous synchronous MCP call can have reserved this ID.
            synchronous=json.loads(RUNS.read_text()) if RUNS.exists() else {}
            if request_id in synchronous:
                return _result("call_start",ok=False,state="duplicate_suppressed",
                               code="DUPLICATE_REQUEST",request_id=request_id)
            # Refuse another call while another async request is in progress.
            for file in ASYNC_DIR.glob("*.json"):
                try:
                    other=json.loads(file.read_text())
                    if other.get("state") in ("starting","running"):
                        return _result("call_start",ok=False,state="busy",
                                       code="ASYNC_CALL_IN_PROGRESS",request_id=request_id)
                except (ValueError,OSError):
                    return _result("call_start",ok=False,state="unknown",
                                   code="ASYNC_STATE_UNREADABLE",request_id=request_id)
            input_file=ASYNC_DIR/(request_id+".input")
            with input_file.open("x") as stream:
                os.chmod(input_file,0o600)
                json.dump({"args":args},stream)
                stream.flush()
                os.fsync(stream.fileno())
            record=dict(request_id=request_id,fingerprint=fingerprint,
                        state="starting",ok=False,created_at=time.time(),
                        updated_at=time.time(),started_at=time.time(),
                        deadline_at=time.time()+1680)
            fd,tmp=tempfile.mkstemp(prefix=".state-",dir=ASYNC_DIR)
            with os.fdopen(fd,"w") as out:
                os.fchmod(out.fileno(),0o600)
                json.dump(record,out)
                out.flush()
                os.fsync(out.fileno())
            os.replace(tmp,result_path)
            try:
                child=subprocess.Popen([sys.executable,str(ASYNC_WORKER),request_id],
                                       cwd=ROOT,stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                                       start_new_session=True,
                                       env={**os.environ,"PATH":"/usr/bin:/bin:/usr/sbin:/sbin"})
            except OSError:
                record.update(state="failed",error="ASYNC_WORKER_UNAVAILABLE",
                              completed_at=time.time())
                result_path.write_text(json.dumps(record))
                input_file.unlink(missing_ok=True)
                return _result("call_start",ok=False,state="failed",
                               code="ASYNC_WORKER_UNAVAILABLE",request_id=request_id)
            return dict(action="call_start",ok=True,state="starting",
                        request_id=request_id,worker_pid=child.pid,
                        poll_tool="facetime_call_status")
        finally:
            fcntl.flock(guard.fileno(),fcntl.LOCK_UN)

@mcp.tool()
def facetime_call_status(request_id: str) -> dict[str, Any]:
    """Read durable request state, independent of the initiating MCP session."""
    _validate_id(request_id)
    return _async_status(request_id)

@mcp.tool()
def facetime_call_wait(request_id: str, wait_seconds: int = 45) -> dict[str, Any]:
    """Wait at most 45 seconds for completion, safe under OpenClaw's 90s RPC limit.

    Poll again using the same ID while state is starting/running. Never redial.
    """
    _validate_id(request_id)
    if type(wait_seconds) is not int or not 1 <= wait_seconds <= 45:
        raise ValueError("wait_seconds must be 1..45")
    deadline=time.monotonic()+wait_seconds
    while True:
        result=_async_status(request_id)
        if result.get("state") not in ("starting","running"):
            return result
        if time.monotonic()>=deadline:
            return result
        time.sleep(min(1,deadline-time.monotonic()))

@mcp.tool()
def facetime_call_cancel(request_id: str) -> dict[str, Any]:
    """Cancel an active async call using guarded, target-verified priority hangup."""
    _validate_id(request_id)
    current=_async_status(request_id)
    if current.get("state") not in ("starting","running"):
        return current
    try:
        record=json.loads(_async_path(request_id).read_text())
        journal=json.loads(CONTROLLER_JOURNAL.read_text())
    except (OSError,ValueError):
        return _result("call_cancel",ok=False,state="unknown",
                       code="CONTROLLER_JOURNAL_UNAVAILABLE",request_id=request_id)
    # Never hang up an unrelated user's call based only on a stale request ID.
    if (not record.get("controller_run_id")
            or journal.get("run_id")!=record["controller_run_id"]
            or journal.get("url_may_have_been_sent") is not True
            or journal.get("stage") not in (
                "DIAL_REQUESTED","CONFIRMING","WAITING_ANSWER","PLAYING",
                "HANGING_UP","RECOVERY_REQUIRED")):
        return _result("call_cancel",ok=False,state="unknown",
                       code="REQUEST_NOT_CURRENT_CALL",request_id=request_id)
    outcome=_exec("hangup",["--hangup","--timeout","24"],85)
    return dict(action="call_cancel",ok=outcome.get("ok",False),
                request_id=request_id,state=outcome.get("state"),
                code=outcome.get("code"),controller_output=outcome.get("controller_output"))

if __name__ == "__main__":
    mcp.run(transport="stdio")
