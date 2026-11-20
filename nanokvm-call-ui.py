#!/usr/bin/env python3
"""Conservative FaceTime lockscreen controller over direct Tailscale NanoKVM MCP.

Exactly one validated card, matching target OCR, stable geometry and one click.
No blind retries. On confirmation timeout cancel a uniquely verified pending
card; if the state is unknown, fail closed. Red hangup requires a unique active
call. A sole verified held call can be resumed, then hung up.
"""
import argparse
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

from PIL import Image
import facetime_txn as txn

RUN_ID=os.environ.get('FACETIME_TXN_RUN_ID') or None

ROOT=pathlib.Path(__file__).resolve().parent
WAKE=ROOT/"facetime-display-wake.py"

def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,ROOT/filename)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def log(message):
    print(f"KVM_UI time={time.time():.3f} {message}",flush=True)

def wake():
    p=subprocess.run(["/usr/bin/python3",str(WAKE),"--ensure-awake"],
                     capture_output=True,text=True,timeout=33)
    if p.returncode:
        raise RuntimeError("DISPLAY_NOT_READY "+(p.stderr or p.stdout)[-120:])
    log("DISPLAY_READY "+p.stdout.strip().replace("\n","; "))

def capture(bridge,detector,tmp,name):
    txn.verify_action_allowed(RUN_ID)
    path=pathlib.Path(tmp)/(name+".jpg")
    roi=pathlib.Path(tmp)/(name+"-roi.jpg")
    bridge.screenshot(str(path),quality=95)
    state=detector.inspect(str(path),str(roi),require_ocr=True)
    txn.verify_action_allowed(RUN_ID)
    log(f"IMAGE status={state['status']} pending={state.get('count')} red={state.get('red_count')} "
        f"badges={state.get('badge_count')} target={state.get('target_verified')}")
    return state

def position(state,which):
    key={"SINGLE":"buttons","ACTIVE":"red_buttons","UNAVAILABLE":"buttons"}[which]
    arr=state.get(key,[])
    return arr[0] if len(arr)==1 else None

def stable(s1,s2,kind,tolerance=.007):
    if s1["status"]!=kind or s2["status"]!=kind:
        return False
    a=position(s1,kind);b=position(s2,kind)
    return bool(a and b and abs(a["x"]-b["x"])<tolerance and
                abs(a["y"]-b["y"])<tolerance and
                s1.get("target_verified") and s2.get("target_verified") and
                (kind!="UNAVAILABLE" or (s1.get("unavailable_verified") and
                                          s2.get("unavailable_verified"))))

def ensure_none(bridge,detector,tmp):
    for index in range(2):
        s=capture(bridge,detector,tmp,"preflight-"+str(index))
        if s["status"]!="NONE":
            raise RuntimeError("EXISTING_FACETIME_UI "+s["status"]+
                               "; no new FaceTime URL")
        if not index:time.sleep(.8)
    log("PREFLIGHT_CLEAR two_frames=true")

def click_once(bridge,x,y,action):
    txn.verify_action_allowed(RUN_ID)
    reply=bridge.click(x,y)
    if reply.get("isError") or reply.get("ok") is False:
        raise RuntimeError(action+"_MCP_CLICK_UNCONFIRMED; DO_NOT_RETRY")
    log(action+f"_CLICK_SENT x={x:.6f} y={y:.6f} count=1")
    return True

def gray_cancel_color(path,button):
    x,y=button["center_px"]
    with Image.open(path) as photo:
        im=photo.convert("RGB")
        yy=y+int(im.height*.043)
        if not (190<=x<im.width-35 and 0<=yy<im.height):
            raise RuntimeError("CANCEL_OUTSIDE_FRAME")
        left=im.getpixel((x-24,yy))
        right=im.getpixel((x+24,yy))
        card=im.getpixel((x-165,yy))
        center=im.getpixel((x,yy))
        pill_sides_agree=sum(abs(a-b) for a,b in zip(left,right))<66
        pill_vs_card=sum(abs(a-b) for a,b in zip(left,card))>48
        x_glyph_contrast=sum(abs(a-b) for a,b in zip(center,left))>65
    if not (pill_sides_agree and pill_vs_card and x_glyph_contrast):
        raise RuntimeError("CANCEL_PILL_OR_X_NOT_VERIFIED")
    return x/im.width, yy/im.height

def cancel_pending(bridge,detector,tmp,reason="manual"):
    # Never cancel if there are multiple cards, an active call, or uncertain OCR.
    first=capture(bridge,detector,tmp,"cancel-first")
    if first["status"]=="NONE":
        log("CANCEL_NOTHING_VISIBLE hidden_queue_not_excluded=true")
        return False
    if first["status"]!="SINGLE":
        raise RuntimeError("CANCEL_REFUSED_STATE="+first["status"])
    time.sleep(.4)
    second=capture(bridge,detector,tmp,"cancel-verify")
    if not stable(first,second,"SINGLE"):
        raise RuntimeError("CANCEL_CARD_NOT_STABLE; NO_CLICK")
    third=capture(bridge,detector,tmp,"cancel-preclick")
    if not stable(second,third,"SINGLE"):
        raise RuntimeError("CANCEL_CARD_CHANGED; NO_CLICK")
    gray=gray_cancel_color(pathlib.Path(tmp)/"cancel-preclick.jpg",
                           third["buttons"][0])
    log(f"CANCEL_{reason.upper()} target_verified=true")
    click_once(bridge,*gray,"CANCEL")
    time.sleep(1)
    final=capture(bridge,detector,tmp,"cancel-post")
    if final["status"]!="NONE":
        raise RuntimeError("CANCEL_NOT_VERIFIED state="+final["status"]+"; NO_MORE_CLICKS")
    log("PENDING_CANCELLED_VERIFIED")
    return True

def dismiss_unavailable(bridge,detector,tmp):
    """Dismiss a unique, OCR-confirmed fixed-recipient unavailable card.

    No green phone click, no speculative click on ambiguous UI, no retry
    after sending the gray-X click. Verify the card is gone on two frames.
    """
    first=capture(bridge,detector,tmp,"unavailable-first")
    if (first.get("status")!="UNAVAILABLE" or
        not first.get("unavailable_verified") or
        not first.get("target_verified") or
        first.get("count")!=1 or first.get("red_count")!=0):
        raise RuntimeError("UNAVAILABLE_CARD_NOT_VERIFIED; NO_CLICK")
    time.sleep(.4)
    second=capture(bridge,detector,tmp,"unavailable-second")
    if not stable(first,second,"UNAVAILABLE"):
        raise RuntimeError("UNAVAILABLE_CARD_NOT_STABLE; NO_CLICK")
    third=capture(bridge,detector,tmp,"unavailable-preclick")
    if not stable(second,third,"UNAVAILABLE"):
        raise RuntimeError("UNAVAILABLE_CARD_CHANGED; NO_CLICK")
    gray=gray_cancel_color(pathlib.Path(tmp)/"unavailable-preclick.jpg",
                           third["buttons"][0])
    log("UNAVAILABLE_CARD_VERIFIED target=true count=1")
    click_once(bridge,*gray,"UNAVAILABLE_DISMISS")
    time.sleep(.65)
    after=capture(bridge,detector,tmp,"unavailable-post")
    if after.get("status")!="NONE":
        raise RuntimeError("UNAVAILABLE_DISMISS_UNVERIFIED state="+after.get("status","unknown")+"; NO_MORE_CLICKS")
    time.sleep(.7)
    second_empty=capture(bridge,detector,tmp,"unavailable-post-quiet")
    if second_empty.get("status")!="NONE":
        raise RuntimeError("UNAVAILABLE_DISMISS_NOT_QUIET; NO_MORE_CLICKS")
    log("UNAVAILABLE_DISMISSED_VERIFIED two_frames=true")
    return True


def verified_pending(state):
    return (state.get("status") in ("SINGLE","MULTIPLE")
            and state.get("all_pending_verified") is True
            and state.get("red_count")==0
            and state.get("count",0)>=1
            and state.get("count")==state.get("badge_count"))

def clear_pending_cards(bridge,detector,tmp,max_clicks=3):
    """Remove visible old pending cards, including a verified multi-card group.

    At most three gray clicks; require validated target and pending-state OCR on
    EACH card. A gray click may dismiss the entire notification group.
    """
    for attempt in range(max_clicks+1):
        first=capture(bridge,detector,tmp,f"clear-{attempt}-first")
        if first["status"]=="NONE":
            log("PENDING_CARDS_CLEAR")
            return True
        if not verified_pending(first):
            raise RuntimeError("RECOVERY_REFUSED_STATE="+first["status"]+"; NO_CLICK")
        if attempt>=max_clicks:
            raise RuntimeError("RECOVERY_CLICK_BUDGET_EXHAUSTED")
        time.sleep(.45)
        second=capture(bridge,detector,tmp,f"clear-{attempt}-verify")
        if not verified_pending(second) or second["count"]!=first["count"]:
            raise RuntimeError("RECOVERY_CARDS_NOT_STABLE; NO_CLICK")
        # Check chosen bottom card is the SAME across the two frames.
        old=first["buttons"][-1];new=second["buttons"][-1]
        if abs(old["x"]-new["x"])>.008 or abs(old["y"]-new["y"])>.008:
            raise RuntimeError("RECOVERY_CARD_MOVED; NO_CLICK")
        third=capture(bridge,detector,tmp,f"clear-{attempt}-preclick")
        if not verified_pending(third) or third["count"]!=second["count"]:
            raise RuntimeError("RECOVERY_CHANGED_BEFORE_CLICK; NO_CLICK")
        last=third["buttons"][-1]
        if abs(last["x"]-new["x"])>.008 or abs(last["y"]-new["y"])>.008:
            raise RuntimeError("RECOVERY_TARGET_MOVED; NO_CLICK")
        gray=gray_cancel_color(pathlib.Path(tmp)/f"clear-{attempt}-preclick.jpg",last)
        log(f"RECOVERY_CANCEL_GRAY attempt={attempt+1} count={third['count']}")
        click_once(bridge,*gray,"RECOVERY_CANCEL")
        time.sleep(1)
        after=capture(bridge,detector,tmp,f"clear-{attempt}-after")
        if after["status"]=="NONE":
            log("RECOVERY_ALL_CARDS_CLEARED")
            return True
        if not verified_pending(after) or after["count"]>=third["count"]:
            raise RuntimeError("RECOVERY_NO_MONOTONIC_REDUCTION; NO_MORE_CLICKS")
    return False

def stable_quiescence(bridge,detector,tmp,seconds=3.5):
    """Wait out delayed NotificationCenter rendering, not just one empty frame."""
    deadline=time.monotonic()+seconds
    index=0
    while True:
        state=capture(bridge,detector,tmp,f"quiet-{index}")
        if state["status"]!="NONE":
            raise RuntimeError("RECOVERY_NOT_QUIET="+state["status"])
        index+=1
        if time.monotonic()>=deadline and index>=3:
            break
        time.sleep(.8)
    log(f"QUIESCENT_EMPTY frames={index} duration_seconds={seconds}")
    return True

def recover(bridge,detector,tmp):
    first=capture(bridge,detector,tmp,"recover-initial")
    if first["status"]=="PENDING_RENDERING":
        for n in range(4):
            time.sleep(.55)
            first=capture(bridge,detector,tmp,f"recover-render-{n}")
            if first["status"]!="PENDING_RENDERING":break
    if first["status"]=="UNAVAILABLE":
        dismiss_unavailable(bridge,detector,tmp)
    elif first["status"]!="NONE":
        clear_pending_cards(bridge,detector,tmp,max_clicks=3)
    stable_quiescence(bridge,detector,tmp,seconds=3.5)
    log("RECOVERY_IDLE_VERIFIED")
    return True

def confirm(bridge,detector,tmp,deadline_s=20,fast_return=True,cancel_on_timeout=True):
    deadline=time.monotonic()+deadline_s
    previous=None
    render_started=None
    seq=0
    while time.monotonic()<deadline:
        now=capture(bridge,detector,tmp,f"pending-{seq}")
        seq+=1
        if now["status"] in ("MULTIPLE","AMBIGUOUS_EXISTING_CALL","ACTIVE","HELD",
                             "ACTIVE_OR_HELD","UNKNOWN_ACTIVE_CALL","UNAVAILABLE"):
            raise RuntimeError("CONFIRM_REFUSED_STATE="+now["status"]+"; NO_CLICK")
        if now["status"]=="UNSUPPORTED_SIZE":
            raise RuntimeError("UNSUPPORTED_DISPLAY_SIZE; NO_CLICK")
        if now["status"]=="SINGLE" and now.get("target_verified"):
            if previous is not None:
                if not stable(previous,now,"SINGLE"):
                    # NotificationCenter animates the first card into place.
                    # Reset stability; do not click until two fresh frames agree.
                    if now.get("status")!="SINGLE" or not now.get("target_verified"):
                        raise RuntimeError("PENDING_MOVED_OR_CHANGED; NO_CLICK")
                    log("PENDING_MOVED_REOBSERVE; NO_CLICK")
                    previous=now
                    time.sleep(.35)
                    continue
                final=capture(bridge,detector,tmp,"confirm-preclick")
                if not stable(now,final,"SINGLE"):
                    if final.get("status")=="SINGLE" and final.get("target_verified"):
                        log("CONFIRM_PRECLICK_MOVED_REOBSERVE; NO_CLICK")
                        previous=final
                        time.sleep(.35)
                        continue
                    raise RuntimeError("CONFIRM_PRECLICK_CHANGED; NO_CLICK")
                if time.monotonic()>=deadline:
                    log("CONFIRM_TIMEOUT_BEFORE_CLICK; attempting verified cancel")
                    if cancel_on_timeout:
                        cancel_pending(bridge,detector,tmp,reason="timeout")
                    raise RuntimeError("CONFIRM_TIMEOUT")
                target=final["buttons"][0]
                click_once(bridge,target["x"],target["y"],"CONFIRM")
                if fast_return:
                    log("CONFIRM_SENT_FAST caller_must_verify_CallServices=true")
                    return True
                time.sleep(1.2)
                after=capture(bridge,detector,tmp,"confirm-after")
                if after["status"]=="SINGLE":
                    raise RuntimeError("CONFIRM_CARD_STILL_PRESENT; NO_RETRY")
                if after["status"]=="MULTIPLE":
                    raise RuntimeError("CONFIRM_MULTIPLE_AFTER_CLICK; NO_RETRY")
                log("CONFIRM_POSTCLICK status="+after["status"])
                return True
            previous=now
        elif now["status"]=="PENDING_RENDERING":
            # FaceTime's app badge and text may be rendered before its green
            # control. Never click until the complete button is stable.
            if render_started is None:render_started=time.monotonic()
            if time.monotonic()-render_started>5:
                raise RuntimeError("PENDING_RENDERING_PERSISTENT; NO_CLICK")
            previous=None
        elif now["status"]=="UNKNOWN_PENDING_CARD":
            # OCR ambiguous: never choose the button; wait until timeout.
            previous=None
        else:
            render_started=None
            previous=None
        time.sleep(.35)
    log("CONFIRM_TIMEOUT expired="+str(deadline_s)+"s; cancel_if_unique="+str(cancel_on_timeout))
    if cancel_on_timeout:
        cancelled=cancel_pending(bridge,detector,tmp,reason="timeout")
        log("CONFIRM_TIMEOUT_CLEANUP cancelled="+str(cancelled))
    raise RuntimeError("CONFIRM_TIMEOUT; NO_CALL_CLICK")

def hangup(bridge,detector,tmp,timeout=18,recover_held=True):
    deadline=time.monotonic()+timeout
    s=capture(bridge,detector,tmp,"hangup-first")
    if s["status"]=="NONE":
        log("HANGUP_ALREADY_CLEAR")
        return True
    if s["status"]=="PENDING_RENDERING":
        for n in range(4):
            time.sleep(.55)
            s=capture(bridge,detector,tmp,f"hangup-render-{n}")
            if s["status"]!="PENDING_RENDERING":break
    if s["status"]=="UNAVAILABLE":
        dismiss_unavailable(bridge,detector,tmp)
        log("HANGUP_UNAVAILABLE_DISMISSED")
        return True
    if verified_pending(s):
        clear_pending_cards(bridge,detector,tmp,max_clicks=3)
        log("HANGUP_CANCELLED_PENDING_INSTEAD")
        return True
    # A sole held call is not ended by the red phone button; first resume it.
    if s["status"]=="HELD" and recover_held and s.get("held_verified"):
        time.sleep(.45)
        again=capture(bridge,detector,tmp,"held-verify")
        if again["status"]!="HELD" or not again.get("held_verified") or (
            abs(again["badges"][0]["center_px"][1]-s["badges"][0]["center_px"][1])>8):
            raise RuntimeError("HELD_CARD_UNSTABLE; NO_CLICK")
        # The 'Fortsetzen' pill sits to the right of the unique badge, ~20px
        # above its center. Both screenshots must confirm the German held state.
        w=again["width"];h=again["height"]
        x=.943
        y=(again["badges"][0]["center_px"][1]-18)/h
        log("HELD_TARGET_VERIFIED; attempting single resume before hangup")
        click_once(bridge,x,y,"RESUME_HELD")
        # No second resume click. Wait for precisely one RED active call.
        active=None
        while time.monotonic()<deadline:
            time.sleep(.6)
            active=capture(bridge,detector,tmp,"resume-check")
            if active["status"]=="ACTIVE":
                break
            if active["status"] not in ("HELD","ACTIVE_OR_HELD"):
                raise RuntimeError("RESUME_UNEXPECTED_STATE="+active["status"]+"; NO_MORE_CLICKS")
        if not active or active["status"]!="ACTIVE":
            raise RuntimeError("HELD_RESUME_NOT_VERIFIED; NO_MORE_CLICKS")
        s=active
    if s["status"]!="ACTIVE" or not s.get("target_verified"):
        raise RuntimeError("HANGUP_REFUSED_STATE="+s["status"]+"; NO_CLICK")
    if time.monotonic()>=deadline:
        raise RuntimeError("HANGUP_DEADLINE_EXPIRED_BEFORE_CLICK")
    time.sleep(.3)
    nextstate=capture(bridge,detector,tmp,"hangup-second")
    if not stable(s,nextstate,"ACTIVE"):
        raise RuntimeError("HANGUP_RED_BUTTON_NOT_STABLE; NO_CLICK")
    final=capture(bridge,detector,tmp,"hangup-preclick")
    if not stable(nextstate,final,"ACTIVE") or time.monotonic()>=deadline:
        raise RuntimeError("HANGUP_PRECLICK_UNSAFE; NO_CLICK")
    r=final["red_buttons"][0]
    click_once(bridge,r["x"],r["y"],"HANGUP")
    # Do not re-click. Verify once+poll state; no other changes.
    while time.monotonic()<deadline:
        time.sleep(.75)
        after=capture(bridge,detector,tmp,"hangup-post")
        if after["status"]=="NONE":
            log("HANGUP_VERIFIED no_remaining_FaceTime_card=true")
            return True
        if after["status"]!="ACTIVE":
            raise RuntimeError("HANGUP_POSTCLICK_STATE="+after["status"]+
                               "; NOT_RETRYING")
    raise RuntimeError("HANGUP_SENT_BUT_NOT_VERIFIED; NOT_RETRYING")

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("action",choices=["inspect","preflight","recover","confirm","cancel-pending","hangup","dismiss-unavailable"])
    parser.add_argument("--timeout",type=float,default=None)
    parser.add_argument("--fast-return",action="store_true")
    parser.add_argument("--no-cancel-on-timeout",action="store_true")
    parser.add_argument("--no-recover-held",action="store_true")
    args=parser.parse_args()
    timeout=args.timeout if args.timeout is not None else (20 if args.action=="confirm" else 18)
    if not 3<=timeout<=180:parser.error("--timeout must be 3..180 seconds")
    bridge=load("nanokvm_https_mcp","nanokvm-mcp-bridge.py")
    detector=load("nanokvm_vision_detector","nanokvm-popup-detector.py")
    wake()
    with tempfile.TemporaryDirectory(prefix="facetime-kvm-ui-") as folder:
        if args.action=="inspect":
            s=capture(bridge,detector,folder,"inspect")
            print("KVM_UI_RESULT "+json.dumps(s,sort_keys=True))
            return 0
        # Separate short-lived UI mutex: DOES NOT hold the call mutex. Priority
        # hangup/cancel can interrupt the owner, then take this bounded lock.
        with txn.action_locked(timeout=45):
            if args.action=="preflight":
                ensure_none(bridge,detector,folder);return 0
            if args.action=="recover":
                recover(bridge,detector,folder);return 0
            if args.action=="confirm":
                confirm(bridge,detector,folder,timeout,args.fast_return,
                        not args.no_cancel_on_timeout);return 0
            if args.action=="cancel-pending":
                clear_pending_cards(bridge,detector,folder,max_clicks=3)
                return 0
            if args.action=="dismiss-unavailable":
                dismiss_unavailable(bridge,detector,folder)
                return 0
            if args.action=="hangup":
                hangup(bridge,detector,folder,timeout,not args.no_recover_held)
                return 0
    return 75

if __name__=="__main__":
    try:sys.exit(main())
    except Exception as err:
        log("ERROR "+str(err)[:360])
        sys.exit(75)
