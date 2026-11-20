#!/usr/bin/env python3
"""Read last macOS pmset display on/off transition and wake only when OFF.
No unlock, no persistent macOS changes, no FaceTime URL requests.
"""
import argparse
import datetime as dt
import os
import re
import subprocess
import sys
import time

EVENT = re.compile(r'^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) [+-]\d{4} Notification\s+Display is turned (on|off)\b')
TIMEOUT = 12

def state():
    p = subprocess.run(['/usr/bin/pmset','-g','log'], capture_output=True,
                       text=True,timeout=TIMEOUT)
    if p.returncode:
        raise RuntimeError('pmset returned ' + str(p.returncode))
    matches = [m for line in p.stdout.splitlines() if (m:=EVENT.search(line))]
    if not matches:
        raise RuntimeError('no display on/off events in pmset log')
    event = matches[-1]
    when = dt.datetime.strptime(event.group(1), '%Y-%m-%d %H:%M:%S')
    age = (dt.datetime.now()-when).total_seconds()
    if age < -120:
        raise RuntimeError('last display power transition is in the future: '+str(round(age)))
    return event.group(2).upper(),event.group(1),age

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--status',action='store_true')
    parser.add_argument('--ensure-awake',action='store_true')
    args=parser.parse_args()
    if args.status==args.ensure_awake:
        parser.error('select --status or --ensure-awake')
    before,when,age=state()
    print(f'DISPLAY_BEFORE={before} last_transition={when} age_seconds={age:.0f}',flush=True)
    if args.status or before=='ON':
        print('DISPLAY_READY already_on' if before=='ON' else 'DISPLAY_OFF',flush=True)
        return 0
    # macOS -u declares user activity and wakes the display without unlocking it.
    # Hold for 30s as a detached subprocess to cover notification rendering.
    subprocess.Popen(['/usr/bin/caffeinate','-u','-t','30'],stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                     start_new_session=True,close_fds=True)
    print('DISPLAY_WAKE_REQUESTED method=caffeinate-u hold_seconds=30',flush=True)
    deadline=time.monotonic()+9
    observed=False
    while time.monotonic()<deadline:
        time.sleep(.40)
        current,when2,age2=state()
        if current=='ON':
            observed=True
            break
    if not observed:
        print('ERROR: display did not report ON; no FaceTime request permitted',file=sys.stderr)
        return 75
    # Allow lockscreen notification surfaces / NanoKVM display rendering to settle.
    time.sleep(2.5)
    after,_,_=state()
    if after!='ON':
        print('ERROR: display turned OFF again; no FaceTime request permitted',file=sys.stderr)
        return 75
    print('DISPLAY_READY woken=1 settle_seconds=2.5',flush=True)
    return 0
if __name__=='__main__':
    try:sys.exit(main())
    except (subprocess.TimeoutExpired,RuntimeError) as error:
        print('ERROR: display state unknown: '+str(error),file=sys.stderr)
        sys.exit(75)
