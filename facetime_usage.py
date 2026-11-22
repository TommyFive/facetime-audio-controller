#!/usr/bin/env python3
"""Privacy-preserving, local FaceTime usage journal (no message bodies or identities).

One JSONL event is appended per MiniMax HTTP attempt, completed TTS render,
and completed call transaction. The schema is deliberately an explicit
allowlist: free-form text, credentials, paths and recipients cannot be logged.
"""
from __future__ import annotations

import datetime as dt
import fcntl
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import uuid

FILE_NAME = "usage.jsonl"
SCHEMA_VERSION = 1
EVENT_FIELDS = {
    "minimax_request": {
        "operation_id", "endpoint", "model", "input_characters",
        "usage_characters", "result", "elapsed_seconds",
    },
    "tts_render": {
        "operation_id", "requested_provider", "provider", "endpoint", "model",
        "input_characters", "audio_seconds", "elapsed_seconds", "fallback",
    },
    "call_result": {
        "operation_id", "outcome", "dial_requested", "connected",
        "playback_completed", "hangup_verified", "elapsed_seconds",
        "connected_seconds", "playback_seconds",
    },
}
PROVIDERS = {"minimax", "macos"}
ENDPOINTS = {"api.minimax.io", "api.minimaxi.com", "local_macos"}
MODELS = {"speech-2.8-turbo", "speech-2.8-hd", "macos"}
API_RESULTS = {"generated", "api_error", "network_error", "invalid_audio", "local_error"}
CALL_OUTCOMES = {"completed", "dial_only", "failed", "interrupted", "preflight_failed"}
MINIMAX_MODELS = ("speech-2.8-turbo", "speech-2.8-hd")


def _model_stats():
    return {"attempts":0, "generated_responses":0, "submitted_characters":0,
            "reported_usage_characters":0, "unknown_usage_attempts":0,
            "rendered_count":0, "rendered_characters":0, "rendered_audio_seconds":0.0}



def operation_id() -> str:
    candidate = os.environ.get("FACETIME_USAGE_ID", "")
    return candidate if re.fullmatch(r"[a-f0-9]{32}", candidate) else uuid.uuid4().hex


def journal_path() -> Path:
    default = Path.home() / ".local" / "state" / "facetime-controller"
    directory = Path(os.environ.get("FACETIME_USAGE_DIR", str(default))).expanduser()
    if not directory.is_absolute():
        raise ValueError("usage directory must be absolute")
    return directory / FILE_NAME


def _safe_seconds(value):
    if value is None:
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 100000:
        raise ValueError("invalid seconds")
    return round(float(value), 3)


def _safe_characters(value, nullable=False):
    if value is None and nullable:
        return None
    if type(value) is not int or not 0 <= value <= 10000000:
        raise ValueError("invalid character count")
    return value


def _build_event(kind: str, **fields) -> dict:
    if kind not in EVENT_FIELDS or set(fields) != EVENT_FIELDS[kind]:
        raise ValueError("usage event fields do not match fixed schema")
    if not re.fullmatch(r"[a-f0-9]{32}", fields["operation_id"]):
        raise ValueError("invalid operation identifier")
    if kind == "minimax_request":
        if fields["endpoint"] not in ENDPOINTS - {"local_macos"} or fields["model"] not in MODELS - {"macos"}:
            raise ValueError("unsupported model or endpoint")
        if fields["result"] not in API_RESULTS:
            raise ValueError("invalid API result")
        fields["input_characters"] = _safe_characters(fields["input_characters"])
        fields["usage_characters"] = _safe_characters(fields["usage_characters"], nullable=True)
        fields["elapsed_seconds"] = _safe_seconds(fields["elapsed_seconds"])
    elif kind == "tts_render":
        if fields["requested_provider"] not in PROVIDERS or fields["provider"] not in PROVIDERS:
            raise ValueError("unsupported provider")
        if fields["endpoint"] not in ENDPOINTS or fields["model"] not in MODELS:
            raise ValueError("unsupported endpoint or model")
        if fields["provider"] == "macos" and (fields["endpoint"] != "local_macos" or fields["model"] != "macos"):
            raise ValueError("invalid macOS render")
        if fields["provider"] == "minimax" and (fields["endpoint"] == "local_macos" or fields["model"] == "macos"):
            raise ValueError("invalid MiniMax render")
        if type(fields["fallback"]) is not bool:
            raise ValueError("invalid fallback")
        fields["input_characters"] = _safe_characters(fields["input_characters"])
        fields["audio_seconds"] = _safe_seconds(fields["audio_seconds"])
        fields["elapsed_seconds"] = _safe_seconds(fields["elapsed_seconds"])
    else:
        if fields["outcome"] not in CALL_OUTCOMES:
            raise ValueError("invalid call outcome")
        for key in ("dial_requested", "connected", "playback_completed", "hangup_verified"):
            if type(fields[key]) is not bool:
                raise ValueError("invalid call boolean")
        for key in ("elapsed_seconds", "connected_seconds", "playback_seconds"):
            fields[key] = _safe_seconds(fields[key])
    return {
        "version": SCHEMA_VERSION,
        "event": kind,
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds"),
        **fields,
    }


def _check_owner_mode(path: Path, directory: bool):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        raise OSError("usage path symlink is forbidden")
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise OSError("usage path type is invalid")
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise OSError("usage path has unsafe ownership/permissions")
    if not directory and info.st_nlink != 1:
        raise OSError("usage file must not be hardlinked")


def append(kind: str, **fields) -> None:
    record = _build_event(kind, **fields)
    data = (json.dumps(record, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n").encode()
    if len(data) > 2048:
        raise ValueError("oversized usage event")
    path = journal_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _check_owner_mode(path.parent, directory=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        _check_owner_mode(path, directory=False)
        fcntl.flock(fd, fcntl.LOCK_EX)
        written = os.write(fd, data)
        if written != len(data):
            raise OSError("partial journal write")
        os.fsync(fd)
    finally:
        os.close(fd)


def record(kind: str, **fields) -> None:
    """Non-fatal telemetry: audio and call safety must not depend on disk logging."""
    try:
        append(kind, **fields)
    except (OSError, ValueError, TypeError) as exc:
        print("USAGE_JOURNAL_WARNING " + type(exc).__name__, file=sys.stderr, flush=True)


def read_events() -> list[dict]:
    path = journal_path()
    if not path.exists():
        return []
    _check_owner_mode(path.parent, directory=True)
    _check_owner_mode(path, directory=False)
    events = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            obj = json.loads(line)
            kind = obj.get("event")
            if (kind not in EVENT_FIELDS or obj.get("version") != SCHEMA_VERSION
                    or set(obj) != EVENT_FIELDS[kind] | {"version", "event", "timestamp"}):
                raise ValueError(f"invalid usage schema on line {line_number}")
            events.append(obj)
    return events


def summarize(events: list[dict], start_date=None, end_date=None) -> dict:
    """Aggregate safe metadata only; never expose an event's arbitrary contents."""
    summary = {
        "minimax_requests": 0, "minimax_generated": 0,
        "minimax_input_characters": 0, "minimax_usage_characters_known": 0,
        "minimax_usage_unknown": 0, "rendered_count": 0,
        "rendered_characters": 0, "rendered_audio_seconds": 0,
        "calls": 0, "calls_connected": 0, "calls_completed": 0,
        "calls_not_connected": 0, "calls_playback_completed": 0,
        "call_elapsed_seconds": 0, "by_render": {}, "by_api": {}, "by_outcome": {},
        "minimax_total": _model_stats(),
        "minimax_by_model": {model: _model_stats() for model in MINIMAX_MODELS},
    }
    def group(table, key):
        return table.setdefault(key, {"count": 0, "characters": 0, "audio_seconds": 0.0})
    for obj in events:
        date = obj["timestamp"][:10]
        if (start_date and date < start_date) or (end_date and date > end_date):
            continue
        kind = obj["event"]
        if kind == "minimax_request":
            summary["minimax_requests"] += 1
            summary["minimax_input_characters"] += obj["input_characters"]
            for stats in (summary["minimax_total"], summary["minimax_by_model"][obj["model"]]):
                stats["attempts"] += 1
                stats["submitted_characters"] += obj["input_characters"]
                if obj["result"] == "generated":
                    stats["generated_responses"] += 1
                if obj["usage_characters"] is None:
                    stats["unknown_usage_attempts"] += 1
                else:
                    stats["reported_usage_characters"] += obj["usage_characters"]
            key = obj["endpoint"] + " / " + obj["model"] + " / " + obj["result"]
            item = group(summary["by_api"], key)
            item["count"] += 1
            item["characters"] += obj["input_characters"]
            if obj["result"] == "generated":
                summary["minimax_generated"] += 1
            if obj["usage_characters"] is None:
                summary["minimax_usage_unknown"] += 1
            else:
                summary["minimax_usage_characters_known"] += obj["usage_characters"]
        elif kind == "tts_render":
            summary["rendered_count"] += 1
            summary["rendered_characters"] += obj["input_characters"]
            summary["rendered_audio_seconds"] += obj["audio_seconds"]
            if obj["provider"] == "minimax":
                for stats in (summary["minimax_total"], summary["minimax_by_model"][obj["model"]]):
                    stats["rendered_count"] += 1
                    stats["rendered_characters"] += obj["input_characters"]
                    stats["rendered_audio_seconds"] += obj["audio_seconds"]
            lane = "fallback" if obj["fallback"] else "direct"
            key = obj["endpoint"] + " / " + obj["model"] + " / " + lane
            item = group(summary["by_render"], key)
            item["count"] += 1
            item["characters"] += obj["input_characters"]
            item["audio_seconds"] += obj["audio_seconds"]
        elif kind == "call_result":
            summary["calls"] += 1
            summary["calls_connected"] += int(obj["connected"])
            summary["calls_completed"] += int(obj["outcome"] == "completed")
            summary["calls_not_connected"] += int(obj["dial_requested"] and not obj["connected"])
            summary["calls_playback_completed"] += int(obj["playback_completed"])
            summary["call_elapsed_seconds"] += obj["elapsed_seconds"]
            summary["by_outcome"][obj["outcome"]] = summary["by_outcome"].get(obj["outcome"], 0) + 1
    summary["rendered_audio_seconds"] = round(summary["rendered_audio_seconds"], 3)
    summary["call_elapsed_seconds"] = round(summary["call_elapsed_seconds"], 3)
    for item in summary["by_render"].values():
        item["audio_seconds"] = round(item["audio_seconds"], 3)
    for stats in (summary["minimax_total"], *summary["minimax_by_model"].values()):
        stats["rendered_audio_seconds"] = round(stats["rendered_audio_seconds"], 3)
    return summary
