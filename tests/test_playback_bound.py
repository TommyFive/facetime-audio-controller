"""No-call safety regression for AudioToolbox completion timeouts."""
import importlib.util
import pathlib
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("ft_fast",ROOT/"facetime-call-fast.py")
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class PlaybackTimeoutTests(unittest.TestCase):
    def test_bounded_short_speech(self):
        self.assertEqual(mod.playback_timeout_seconds(1.3), 16)
    def test_long_speech_has_proportional_timeout(self):
        self.assertEqual(mod.playback_timeout_seconds(23.35), 38)
    def test_upper_bound(self):
        self.assertEqual(mod.playback_timeout_seconds(300), 315)
        self.assertEqual(mod.playback_timeout_seconds(1200), 1215)
    def test_invalid(self):
        for value in (0, -1, 1200.1, "nan"):
            with self.assertRaises(ValueError):
                mod.playback_timeout_seconds(value)
