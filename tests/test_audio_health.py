"""No-call audio route diagnostics; no real audio stream reaches FaceTime."""
import importlib.util
import pathlib
import subprocess
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("ft_audio_health",ROOT/"facetime-audio-health.py")
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class AudioRouteHealthTests(unittest.TestCase):
    def test_success(self):
        with patch.object(mod.subprocess,"run",return_value=subprocess.CompletedProcess([],0)) as run:
            result=mod.check("2",8)
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"],"AUDIO_ROUTE_OK")
        self.assertIn("audiotoolbox",run.call_args.args[0])
        self.assertIn("anullsrc=r=48000:cl=stereo",run.call_args.args[0])
    def test_hang(self):
        with patch.object(mod.subprocess,"run",side_effect=subprocess.TimeoutExpired(["ffmpeg"],8)):
            result=mod.check("2",8)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"],"AUDIO_ROUTE_HUNG")
    def test_failure(self):
        with patch.object(mod.subprocess,"run",return_value=subprocess.CompletedProcess([],1)):
            self.assertEqual(mod.check("2",8)["code"],"AUDIO_ROUTE_FAILED")
    def test_reject_unsafe_device(self):
        with patch.object(mod.subprocess,"run") as run:
            with self.assertRaises(ValueError):
                mod.check("2; rm -rf /")
            run.assert_not_called()
    def test_find_device(self):
        stderr="[0] Speaker\n[2] Loopback Audio, com.rogueamoeba.Loopback\n"
        result=subprocess.CompletedProcess([],0,"",stderr)
        with patch.object(mod.subprocess,"run",return_value=result):
            self.assertEqual(mod.find_device(),"2")
