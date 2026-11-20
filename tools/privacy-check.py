#!/usr/bin/env python3
"""Public current-tree gate (full clean-history and artifact audit is separate)."""
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
TEXT_SUFFIXES={".md",".txt",".sh",".py",".applescript",".swift",".json",".toml",".yaml",".yml",".plist"}
FORBIDDEN=[
    ("absolute macOS home path",re.compile(r"/Users/[A-Za-z0-9._-]+")),
    ("tailnet-specific hostname",re.compile(r"\b[A-Za-z0-9.-]+\.ts\.net\b")),
    ("tunnel instance identifier",re.compile(r"\btunnel_[0-9a-f]{16,}\b",re.I)),
    ("hardcoded IPv4 private infrastructure",re.compile(r"\b100\.(?:[0-9]{1,3}\.){2}[0-9]{1,3}\b")),
    ("API key",re.compile(r"\b(?:sk|pk)-[A-Za-z0-9_-]{18,}\b")),
    ("GitHub personal access token",re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b")),
    ("GitHub fine-grained token",re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}\b")),
    ("AWS access key",re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("PEM private key",re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("JWT-like token",re.compile(r"\beyJ[A-Za-z0-9_-]{50,}\.[A-Za-z0-9_-]{30,}\.[A-Za-z0-9_-]{10,}\b")),
    ("Bearer credential",re.compile(r"\bBearer\s+[A-Za-z0-9_.~+/-]{30,}={0,2}\b")),
]
MAIL=re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
def scan(path,text):
    errors=[]
    for lineno,line in enumerate(text.splitlines(),1):
        for label,pat in FORBIDDEN:
            if pat.search(line):errors.append((lineno,label))
        for m in MAIL.finditer(line):
            if not m.group().lower().endswith("@example.invalid"):
                errors.append((lineno,"non-example email identity"))
    return errors
def main():
    tracked=subprocess.run(["git","ls-files","--cached","--others","--exclude-standard"],
                           cwd=ROOT,text=True,capture_output=True,check=True).stdout.splitlines()
    errors=[]
    for name in sorted(set(tracked)):
        f=ROOT/name
        if not f.is_file() or ".venv" in f.parts or "__pycache__" in f.parts:
            continue
        data=f.read_bytes()
        if b"\x00" in data:
            errors.append((name,0,"binary file in public current-tree audit"))
            continue
        try:
            content=data.decode("utf-8")
        except UnicodeDecodeError:
            errors.append((name,0,"non-UTF8 file in public current-tree audit"))
            continue
        for lineno,label in scan(name,content):
            errors.append((name,lineno,label))
    for name,line,label in errors:print(f"{name}:{line}: {label}",file=sys.stderr)
    if errors:print(f"PRIVACY_GATE_FAILED: {len(errors)} findings",file=sys.stderr);return 1
    print("PRIVACY_GATE_OK: current text tree contains no matching personal identifiers, leaked credentials or absolute user paths.")
    print("This check is current-tree only. Publish only from a verified new root commit and separately inspect release assets.")
    return 0
if __name__=="__main__":sys.exit(main())
