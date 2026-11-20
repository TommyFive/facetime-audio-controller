#!/usr/bin/env python3
"""Import an existing NanoKVM MCP bearer from a user-owned local file. No SSH."""
import argparse
import os
from pathlib import Path
import stat
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from facetime_runtime import kvm_auth_file

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("--from-file",required=True,type=Path)
args=parser.parse_args()
source=args.from_file
mode=source.lstat()
if not stat.S_ISREG(mode.st_mode) or mode.st_uid!=os.getuid() or mode.st_mode & 0o077:
    parser.error("input must be an owner-only regular file (0600)")
secret=source.read_bytes().strip()
if not secret.startswith(b"Bearer ") or b"\n" in secret or b"\r" in secret or not 30<len(secret)<300:
    parser.error("expected a pre-authorized Bearer credential")
dest=kvm_auth_file()
dest.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
dest.parent.chmod(0o700)
if dest.exists():parser.error("destination already exists; refusing to overwrite existing credential")
fd=os.open(str(dest),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
with os.fdopen(fd,"wb") as out:out.write(secret+b"\n")
print("Imported local NanoKVM authorization into an owner-only credential file.")
