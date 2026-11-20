#!/usr/bin/env python3
"""FaceTime lockscreen visual state classifier. No mouse operations.

Color/shape ROI detection (green confirm, red hangup, FaceTime green badges)
and optional macOS Vision OCR on small private per-card crops.
Unknown UI => fail closed; 1920x1080 capture is the validated layout.
"""
import argparse
from collections import deque
import json
import os
import pathlib
import re
import subprocess
import tempfile
import unicodedata

from PIL import Image

import facetime_runtime as runtime
TARGET = runtime.recipient()
_SCRIPT_DIR=pathlib.Path(__file__).resolve().parent
_LOCAL_OCR=_SCRIPT_DIR/".bin/facetime-vision-ocr"
OCR_BINARY=_LOCAL_OCR

def components(roi,predicate):
    pix=roi.load();w,h=roi.size
    mask=bytearray(w*h)
    for y in range(h):
        off=y*w
        for x in range(w):
            if predicate(*pix[x,y]): mask[off+x]=1
    seen=bytearray(w*h)
    for i in range(len(mask)):
        if not mask[i] or seen[i]:continue
        q=[i];seen[i]=1
        xmin=w;xmax=0;ymin=h;ymax=0;area=0
        while q:
            z=q.pop();x=z%w;y=z//w;area+=1
            xmin=min(xmin,x);xmax=max(xmax,x)
            ymin=min(ymin,y);ymax=max(ymax,y)
            for n in (z-1 if x>0 else -1,z+1 if x<w-1 else -1,
                      z-w if y>0 else -1,z+w if y<h-1 else -1):
                if n>=0 and mask[n] and not seen[n]:
                    seen[n]=1;q.append(n)
        yield xmin,ymin,xmax,ymax,area

def card_ocr(rgb,y):
    """OCR a bounded single-card region; return flags only, never transcript."""
    if not OCR_BINARY.is_file() or not os.access(OCR_BINARY,os.X_OK):
        return {"verified":False,"pending":False,"held":False,"resume":False,"active_text":False,"unavailable":False}
    w,h=rgb.size
    crop=rgb.crop((int(w*.724),max(0,y-74),min(w,int(w*.991)),min(h,y+64)))
    with tempfile.TemporaryDirectory(prefix="ft-vision-") as temp:
        path=pathlib.Path(temp)/"card.jpg"
        crop=crop.resize((crop.width*2,crop.height*2),Image.Resampling.LANCZOS)
        crop.save(path,format="JPEG",quality=95)
        os.chmod(path,0o600)
        try:
            p=subprocess.run([str(OCR_BINARY),str(path)],
                             capture_output=True,text=True,timeout=5)
        except (subprocess.TimeoutExpired,OSError):
            return {"verified":False,"pending":False,"held":False,"resume":False,"active_text":False}
    if p.returncode:
        return {"verified":False,"pending":False,"held":False,"resume":False,"active_text":False}
    lines=[x.lower().strip() for x in p.stdout.splitlines()]
    compact=[re.sub(r"\s+","",x) for x in lines]
    from difflib import SequenceMatcher
    def normalize(value):
        return re.sub(r"[^a-z0-9]","",value.lower())
    # Diacritics and OCR variants: "verfügbar", "verfugbar", "verfuegbar".
    def normalized_label(value):
        folded=unicodedata.normalize("NFKD",value.lower().replace("ß","ss"))
        folded=re.sub(r"[^a-z0-9]","",folded)
        return folded.replace("ue","u")
    unavailable_text=("istnichtverfugbar" in normalized_label(" ".join(lines)))
    expected=normalize(TARGET)
    target_like=bool(expected) and any(len(normalize(line))>=10 and
        SequenceMatcher(None,normalize(line),expected).ratio()>=.82 for line in lines)
    held=any(SequenceMatcher(None,normalize(x),"angehalten").ratio()>=.78 for x in lines)
    resume=any("fort" in normalize(x) for x in lines) or any(
        SequenceMatcher(None,x,"fortsetzen").ratio()>=.70 for x in compact)
    return {
        "verified":target_like,
        "pending":any("anrufenklicken" in normalize(x) or
                      SequenceMatcher(None,normalize(x),"zumanrufenklicken").ratio()>=.72 for x in lines),
        "held":held,
        "resume":resume,
        "active_text":any("facetimeaudio" in normalize(x) for x in lines),
        "unavailable":unavailable_text
    }

def cancel_pill_shape(rgb,cx,cy):
    """Match gray/purple cancel pill in BOTH macOS light and dark lockscreen.

    Sample two background pixels away from center X. Depending on wallpaper
    and transparency the center glyph is BLACK or WHITE; neither brightness
    of center nor theme color is a safe indicator.
    """
    w,h=rgb.size
    x=int(cx);y=int(cy)
    if not (180<=x<w-36 and 0<=y<h and x>175):
        return False
    left=rgb.getpixel((x-24,y))
    right=rgb.getpixel((x+24,y))
    card=rgb.getpixel((x-165,y))
    similar=sum(abs(a-b) for a,b in zip(left,right))<66
    distinct=sum(abs(a-b) for a,b in zip(left,card))>48
    return similar and distinct

def inspect(path,save_roi=None,require_ocr=False):
    with Image.open(path) as original:
        rgb=original.convert("RGB")
    w,h=rgb.size
    if (w,h)!=(1920,1080):
        return {"status":"UNSUPPORTED_SIZE","width":w,"height":h,"buttons":[],"red_buttons":[],
                "badge_count":0,"count":0,"target_verified":False}
    left=int(w*.73);top=int(h*.055);right=int(w*.995);bottom=int(h*.69)
    roi=rgb.crop((left,top,right,bottom))
    if save_roi:
        roi.save(save_roi,format="JPEG",quality=90)
        os.chmod(save_roi,0o600)
    buttons=[];badges=[];reds=[]
    for a,b,c,d,area in components(roi,lambda r,g,bl: g>=175 and r<145 and bl<183 and
                                   g>r*1.6 and g>bl*1.42):
        cw=c-a+1;ch=d-b+1;cx=left+(a+c)/2;cy=top+(b+d)/2
        if 12<=cw<=32 and 12<=ch<=32 and 100<=area<=700 and cx<w*.81:
            badges.append({"center_px":[round(cx),round(cy)],"green_pixels":area})
        if 55<=cw<=150 and 19<=ch<=58 and area>=850 and cx>w*.88:
            ax=int(cx-w*.12);ay=int(cy);bx=int(cx);by=int(cy+h*.043)
            if not (0<=ax<w and 0<=bx<w and 0<=by<h):continue
            ar,ag,ab=rgb.getpixel((ax,ay))
            if not (ar<175 and ag<170 and ab<215 and
                    cancel_pill_shape(rgb,cx,by)):
                continue
            buttons.append({"bbox_px":[left+a,top+b,left+c,top+d],
                            "center_px":[round(cx),round(cy)],
                            "x":round(cx/w,6),"y":round(cy/h,6),"green_pixels":area})
    for a,b,c,d,area in components(roi,lambda r,g,bl: r>148 and r>g*1.42 and
                                    r>bl*1.24 and g<140 and bl<155):
        cw=c-a+1;ch=d-b+1;cx=left+(a+c)/2;cy=top+(b+d)/2
        if 38<=cw<=78 and 36<=ch<=78 and 750<=area<=5200 and cx>w*.89:
            reds.append({"bbox_px":[left+a,top+b,left+c,top+d],
                         "center_px":[round(cx),round(cy)],
                         "x":round(cx/w,6),"y":round(cy/h,6),"red_pixels":area})
    buttons.sort(key=lambda a:a["y"])
    badges.sort(key=lambda a:a["center_px"][1])
    reds.sort(key=lambda a:a["y"])
    count=len(buttons);badge_count=len(badges);red_count=len(reds)
    scans=[card_ocr(rgb,b["center_px"][1]) for b in badges] if require_ocr else []
    target_ok=(len(scans)==badge_count and badge_count>0 and all(s["verified"] for s in scans))
    held_ok=target_ok and badge_count==1 and scans[0]["held"] and scans[0]["resume"]
    pending_ok=target_ok and badge_count==1 and scans[0]["pending"]
    all_pending=(target_ok and count>0 and badge_count==count and red_count==0
                 and all(s["pending"] and not s["held"] for s in scans))
    unavailable_ok=(require_ocr and target_ok and badge_count==1 and
                    count==1 and red_count==0 and scans[0].get("unavailable")
                    and not scans[0].get("pending") and not scans[0].get("held"))
    # A held card without OCR certainty must NEVER become a hangup target.
    if count>1 or red_count>1:
        status="MULTIPLE"
    elif unavailable_ok:
        status="UNAVAILABLE"
    elif count==1 and red_count==0 and badge_count==1:
        status="SINGLE" if not require_ocr or pending_ok else "UNKNOWN_PENDING_CARD"
    elif count==0 and red_count==1 and badge_count==1:
        status="ACTIVE" if not require_ocr or target_ok else "UNKNOWN_ACTIVE_CALL"
    elif count==0 and red_count==0 and badge_count==1:
        if require_ocr and held_ok:
            status="HELD"
        elif require_ocr and target_ok and scans[0]["pending"]:
            # FaceTime card text may render before the green phone pill.
            # Treat only an OCR-verified pending label as transition.
            status="PENDING_RENDERING"
        else:
            status="ACTIVE_OR_HELD"
    elif count==0 and red_count==0 and badge_count==0:
        status="NONE"
    else:
        status="AMBIGUOUS_EXISTING_CALL"
    return {"status":status,"count":count,"red_count":red_count,"badge_count":badge_count,
            "width":w,"height":h,"roi_px":[left,top,right,bottom],
            "buttons":buttons,"red_buttons":reds,"badges":badges,
            "target_verified":target_ok,"held_verified":held_ok,
            "unavailable_verified":unavailable_ok,
            "all_pending_verified":all_pending,"ocr_checked":require_ocr}

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("jpeg");ap.add_argument("--crop-output")
    ap.add_argument("--ocr",action="store_true")
    args=ap.parse_args()
    print(json.dumps(inspect(args.jpeg,args.crop_output,args.ocr),sort_keys=True))
