"""Regression for unlocked AX state parsing, with zero real calls."""
import pathlib
import subprocess
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]

class UnlockedShellStatusTests(unittest.TestCase):
    def test_status_stdout_is_machine_readable(self):
        script=(ROOT/"facetime-call.sh").read_text()
        part=script.split("status() {",1)[1].split("\nrequest_dial() {",1)[0]
        self.assertIn("ensure_display_awake >&2",part)
        self.assertIn('print -r -- "$output"',part)

    def test_state_protocol_ignores_display_chatter(self):
        script=(ROOT/"facetime-call.sh").read_text()
        self.assertIn('case "$before" in',script)
        self.assertIn('STATE=NO_CALL_UI*)',script)
        self.assertNotIn("ensure_display_awake || return $?\n  # Transient AX",script)
