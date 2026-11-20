"""No-call lifecycle regressions: long speech must finish before verified hangup."""
import contextlib
import datetime as dt
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location("facetime_long_lifecycle",ROOT/"facetime-call-fast.py")
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class LongLifecycleTests(unittest.TestCase):
    def run_controller(self, fail_playback=False):
        log_lines=[]
        stages=[]
        playback_timeouts=[]
        hangups=[]
        def fake_guarded(command, timeout, run_id, label, env=None, connection_since=None):
            if command[0]==sys.executable and command[1].endswith("facetime-permissions.py"):
                return json.dumps({"ok":True,"mode":"GUI_UNLOCKED"}), 0.1
            if command[0]==sys.executable and command[1].endswith("facetime-tts.py"):
                output=Path(command[command.index("--output")+1])
                output.write_bytes(b"FORM"+b"a"*2000)
                return json.dumps({"ok":True,"provider":"minimax","requested":"minimax",
                    "fallback":False,"fallback_reason":"none","model":"speech-2.8-hd",
                    "voice":"German_FriendlyMan","speed":1.1,"audio_seconds":310.0}),0.1
            if command[0]=="/usr/bin/python3" and command[1].endswith("facetime-display-wake.py"):
                return "DISPLAY_READY",0.1
            if command[0]==mod.SCRIPT and "--_dial-ax" in command:
                return "DIAL_REQUESTED",0.1
            if command[0]==mod.FFMPEG and "-audio_device_index" in command:
                playback_timeouts.append(timeout)
                if fail_playback:raise RuntimeError("synthetic_stalled_playback")
                return "",310.0
            if command[0]==mod.SCRIPT and "--_hangup-ax" in command:
                hangups.append(True)
                return "HANGUP_OK",0.1
            raise AssertionError("Unexpected controller call: "+str(command[:3]))
        with patch.object(mod.txn,"lockfile",return_value=contextlib.nullcontext()), \
             patch.object(mod.txn,"start",return_value=({"run_id":"unit-test-run"},{"stage":"DONE"})), \
             patch.object(mod.txn,"check",return_value={}), \
             patch.object(mod.txn,"update",side_effect=lambda runid,stage,**kwargs: stages.append(stage)), \
             patch.object(mod,"call_state",return_value="GUI_UNLOCKED"), \
             patch.object(mod,"output_device",return_value="3"), \
             patch.object(mod,"ensure_input"), \
             patch.object(mod,"unavailable_popup_state",return_value=False), \
             patch.object(mod,"connected_at_or_after",return_value=(dt.datetime.now(),0.01)), \
             patch.object(mod,"guarded",side_effect=fake_guarded), \
             patch.object(mod,"log",side_effect=log_lines.append):
            if fail_playback:
                with self.assertRaisesRegex(RuntimeError,"synthetic_stalled_playback"):
                    mod.main(["This is an offline long-call lifecycle test."])
            else:
                self.assertEqual(mod.main(["This is an offline long-call lifecycle test."]),0)
        return stages,playback_timeouts,hangups,log_lines

    def test_310_second_audio_finishes_and_hangs_up(self):
        stages,timeouts,hangups,logs=self.run_controller()
        self.assertEqual(timeouts,[325])
        self.assertEqual(hangups,[True])
        self.assertEqual(stages[-1],"DONE")
        self.assertTrue(any("PLAY_END" in line for line in logs))
        self.assertTrue(any("HANGUP_OK" in line for line in logs))
        self.assertTrue(any("CALL_COMPLETED" in line for line in logs))

    def test_stalled_playback_attempts_verified_cleanup(self):
        stages,timeouts,hangups,logs=self.run_controller(fail_playback=True)
        self.assertEqual(timeouts,[325])
        self.assertEqual(hangups,[True])
        self.assertEqual(stages[-1],"RECOVERY_REQUIRED")
        self.assertTrue(any("CALL_ERROR" in line for line in logs))
        self.assertTrue(any("HANGUP_OK" in line for line in logs))
        self.assertFalse(any("CALL_COMPLETED" in line for line in logs))


if __name__=="__main__":
    unittest.main()
