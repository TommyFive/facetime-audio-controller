#!/usr/bin/env python3
"""NanoKVM MCP client over direct Tailscale HTTPS (never SSH at runtime).

The existing NanoKVM bearer is provisioned once into a FileVault-protected
macOS file with owner-only access. Never print, log, or commit credentials.
TLS certificate verification and fixed Tailscale hostname are mandatory.
"""
import argparse
import base64
import json
import os
import pathlib
import re
import stat
import sys
import tempfile
import urllib.error
import urllib.request

import facetime_runtime as runtime
ENDPOINT = runtime.nanokvm_endpoint()
AUTH_FILE = runtime.kvm_auth_file()
INIT = {
    "jsonrpc":"2.0","id":100,"method":"initialize",
    "params":{"protocolVersion":"2025-03-26","capabilities":{},
              "clientInfo":{"name":"facetime-nanokvm-https","version":"2.0"}}
}

def _auth():
    folder = AUTH_FILE.parent
    for path in (folder, AUTH_FILE):
        st=os.stat(path,follow_symlinks=False)
        if not (stat.S_ISDIR(st.st_mode) if path==folder else stat.S_ISREG(st.st_mode)):
            raise RuntimeError("AUTH_PATH_NOT_REGULAR")
        if st.st_uid != os.getuid() or st.st_mode & 0o077:
            raise RuntimeError("AUTH_PERMISSIONS_UNSAFE")
    value=AUTH_FILE.read_text(encoding="ascii").strip()
    if not re.fullmatch(r"Bearer [A-Za-z0-9_.~+/-]{20,250}=*",value):
        raise RuntimeError("AUTH_FORMAT_INVALID")
    return value

def _decode(response):
    if not response:
        return {}
    body=response.decode("utf-8")
    if body.lstrip().startswith("{"):
        return json.loads(body)
    events=[]
    for line in body.splitlines():
        if line.startswith("data: "):
            raw=line[6:].strip()
            if raw and raw != "[DONE]":
                events.append(json.loads(raw))
    if not events:
        raise RuntimeError("NO_VALID_MCP_RESPONSE")
    return events[-1]

def call(method,params=None,tool=None,timeout=20):
    if not ENDPOINT:raise RuntimeError("NANOKVM_NOT_CONFIGURED")
    header={"Authorization":_auth(),"Content-Type":"application/json",
            "Accept":"application/json, text/event-stream"}
    session=None
    def request(payload):
        nonlocal session
        h=dict(header)
        if session:
            h["Mcp-Session-Id"]=session
        req=urllib.request.Request(ENDPOINT,data=json.dumps(payload,separators=(",",":")).encode("utf-8"),headers=h,method="POST")
        # urllib validates DNS hostname and certificate chain automatically.
        try:
            with urllib.request.urlopen(req,timeout=timeout) as resp:
                session=resp.headers.get("Mcp-Session-Id",session)
                return _decode(resp.read())
        except urllib.error.HTTPError as err:
            raise RuntimeError(f"MCP_HTTP_{err.code}") from None
        except urllib.error.URLError as err:
            # Never put complete request headers in exception text.
            raise RuntimeError("MCP_NETWORK_FAILURE_"+type(err.reason).__name__) from None
    init=request(INIT)
    if init.get("error"):
        raise RuntimeError("MCP_INIT_ERROR")
    try:
        request({"jsonrpc":"2.0","method":"notifications/initialized"})
    except RuntimeError:
        pass
    result=request({"jsonrpc":"2.0","id":1,"method":method,"params":params or {}})
    if result.get("error"):
        code=result["error"].get("code","unknown")
        raise RuntimeError("MCP_JSONRPC_ERROR_"+str(code))
    out=result.get("result") or {}
    if out.get("isError") is True:
        raise RuntimeError("MCP_TOOL_ERROR")
    if method=="tools/list":
        return {"tools":[t.get("name") for t in out.get("tools",[])]}
    if tool=="screenshot":
        images=[x for x in out.get("content",[]) if
                x.get("type")=="image" and x.get("mimeType")=="image/jpeg"]
        if len(images)!=1:raise RuntimeError("MCP_SCREENSHOT_COUNT_"+str(len(images)))
        return {"jpegBase64":images[0]["data"]}
    # Do not accidentally print arbitrary MCP tool output.
    return {"ok":True,"isError":False}

def screenshot(filepath,quality=80):
    reply=call("tools/call",{"name":"screenshot","arguments":{"quality":quality,"timeoutMs":15000}},"screenshot",timeout=23)
    raw=base64.b64decode(reply["jpegBase64"],validate=True)
    if len(raw)<1024 or not raw.startswith(b"\xff\xd8") or not raw.endswith(b"\xff\xd9"):
        raise RuntimeError("MCP_SCREENSHOT_INVALID")
    path=pathlib.Path(filepath)
    flags=os.O_WRONLY|os.O_CREAT|os.O_TRUNC|getattr(os,"O_NOFOLLOW",0)
    fd=os.open(path,flags,0o600)
    with os.fdopen(fd,"wb") as handle:
        os.fchmod(handle.fileno(),0o600)
        handle.write(raw)
    return len(raw)

def click(x,y):
    if not (0<=x<=1 and 0<=y<=1):raise ValueError("Coordinates require normalized [0,1]")
    return call("tools/call",{"name":"click_mouse",
         "arguments":{"button":"left","clicks":1,"mode":"absolute",
                      "coordinateSpace":"content","x":float(x),"y":float(y)}},
         "click_mouse",timeout=18)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("action",choices=["tools","screenshot","click"])
    ap.add_argument("--out")
    ap.add_argument("--quality",type=int,default=80)
    ap.add_argument("--x",type=float)
    ap.add_argument("--y",type=float)
    args=ap.parse_args()
    if args.action=="tools":
        print(json.dumps(call("tools/list")))
    elif args.action=="screenshot":
        if not args.out:ap.error("--out required")
        print("SCREENSHOT_BYTES",screenshot(args.out,args.quality))
    else:
        if args.x is None or args.y is None:ap.error("--x and --y required")
        print(json.dumps(click(args.x,args.y)))
if __name__=="__main__":
    try:main()
    except Exception as err:
        print("NANOKVM_ERROR",str(err),file=sys.stderr)
        sys.exit(75)
