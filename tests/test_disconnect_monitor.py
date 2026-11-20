"""Real CallServices fixture and simulated remote disconnect cleanup; no dial."""
import datetime as dt
import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("facetime_disconnect_runner",ROOT/"facetime-call-fast.py")
import sys
sys.path.insert(0,str(ROOT))
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class DisconnectMonitorTests(unittest.TestCase):
    def test_callservices_event_parser_identifies_remote_hangup(self):
        fixture=(
            "2026-11-20 13:09:56.272 Df callservicesd Posting "
            "TUCallCenterCallConnectedNotification with object <private>\n"
            "2026-11-20 13:10:12.247 Df callservicesd Setting disconnected "
            "reason to remote hangup because ended reason is 2\n"
        )
        result=subprocess.CompletedProcess([],0,fixture,"")
        with patch.object(mod,"run",return_value=(result,0.1)):
            events,_=mod.events_since("2026-11-20 13:09:56")
        self.assertEqual([kind for _,kind in events],["connected","disconnected"])

    def test_audio_playback_aborts_on_remote_disconnect(self):
        class FakeProcess:
            pid=13579
            returncode=None
            killed=False
            def communicate(self,timeout=None):
                if self.killed:return ("","")
                raise subprocess.TimeoutExpired("ffmpeg",timeout)
            def poll(self):return -15 if self.killed else None
        p=FakeProcess()
        connected=dt.datetime.now()-dt.timedelta(seconds=4)
        with patch.object(mod.subprocess,"Popen",return_value=p) as spawn,\
             patch.object(mod,"events_since",return_value=([(dt.datetime.now(),"disconnected")],0.01)),\
             patch.object(mod.txn,"check"),\
             patch.object(mod.os,"killpg",side_effect=lambda *args:setattr(p,"killed",True)) as kill,\
             patch.object(mod,"log"):
            with self.assertRaisesRegex(RuntimeError,"CALL_DISCONNECTED_DURING_PLAYBACK"):
                mod.guarded([mod.FFMPEG,"-nostdin"],120,"test-run","Loopback TTS",
                            connection_since=connected)
        self.assertTrue(spawn.call_args.kwargs["start_new_session"])
        kill.assert_called_once()

if __name__=="__main__":unittest.main()
