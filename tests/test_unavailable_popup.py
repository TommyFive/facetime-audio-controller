"""No-call regression checks for a recipient-unavailable FaceTime notification."""
import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import os
os.environ.setdefault("FACETIME_RECIPIENT", "test-recipient@example.invalid")
ROOT = Path(__file__).resolve().parents[1]
FAST = ROOT / "facetime-call-fast.py"
AX = ROOT / "facetime-ax-control.applescript"

spec = importlib.util.spec_from_file_location("unavailable_fast", FAST)
fast = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fast)
fast.TARGET="test-recipient@example.invalid"

server_spec = importlib.util.spec_from_file_location("unavailable_mcp", ROOT / "facetime-mcp-server.py")
server = importlib.util.module_from_spec(server_spec)
server_spec.loader.exec_module(server)


class UnavailableNotificationTests(unittest.TestCase):
    def test_ax_requires_unique_fixed_target_and_exact_unavailable_label(self):
        source = AX.read_text()
        self.assertIn('dd is "ist nicht verfügbar"', source)
        self.assertIn('targetCount is 1 and nUnavailable is 1', source)
        self.assertIn('nCall is 1 and nCancel is 1 and nEnd is 0', source)
        self.assertIn('detectedState to "UNAVAILABLE"', source)
        self.assertIn('if (count of results) is not 1 or (count of unavailableActions) is not 1', source)
        self.assertIn('click (item 1 of unavailableActions)', source)
        self.assertIn('NOT_ONE_UNAVAILABLE_CARD: no action taken', source)

    def test_status_match_requires_exact_target(self):
        good = subprocess.CompletedProcess([], 0,
            "STATE=UNAVAILABLE target=test-recipient@example.invalid label=\n", "")
        wrong_target = subprocess.CompletedProcess([], 0,
            "STATE=UNAVAILABLE target=other@example.invalid label=\n", "")
        with patch.object(fast.subprocess, "run", return_value=good):
            self.assertTrue(fast.unavailable_popup_state())
        with patch.object(fast.subprocess, "run", return_value=wrong_target):
            self.assertFalse(fast.unavailable_popup_state())

    def test_ax_probe_failure_does_not_count_as_unavailable(self):
        with patch.object(fast.subprocess, "run",
                          side_effect=subprocess.TimeoutExpired("osascript", 6)):
            self.assertFalse(fast.unavailable_popup_state())

    def test_dismiss_requires_a_verified_empty_ui(self):
        with patch.object(fast.txn, "check"), patch.object(
            fast, "guarded", side_effect=[
                ("UNAVAILABLE_DISMISS_CLICK_SENT", 0.2),
                ("STATE=UNAVAILABLE target=test-recipient@example.invalid", 0.2),
                ("STATE=NO_CALL_UI target=test-recipient@example.invalid", 0.2)
            ]) as guarded, patch.object(fast.time, "sleep"):
            fast.dismiss_unavailable_popup("fake-run")
        self.assertEqual(guarded.call_count, 3)
        self.assertEqual(guarded.call_args_list[0].args[0][-1], "dismiss-unavailable")

    def test_dismiss_fails_closed_if_ui_remains(self):
        with patch.object(fast.txn, "check"), patch.object(
            fast, "guarded", side_effect=[
                ("UNAVAILABLE_DISMISS_CLICK_SENT", 0.2),
                *[("STATE=UNAVAILABLE target=test-recipient@example.invalid", 0.2)]*4
            ]), patch.object(fast.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "UNAVAILABLE_DISMISS_UNVERIFIED"):
                fast.dismiss_unavailable_popup("fake-run")

    def test_mcp_returns_explicit_unavailable_code(self):
        response = subprocess.CompletedProcess(
            ["controller"], 75,
            "CALL_UNAVAILABLE_DETECTED\nCALL_UNAVAILABLE_DISMISSED\nERROR CALL_UNAVAILABLE",
            "")
        with patch.object(server, "_run_bounded", return_value=response):
            result = server._exec("call", ["--call", "example"], 10)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CALL_UNAVAILABLE")
        self.assertEqual(result["state"], "recipient_unavailable")


if __name__ == "__main__":
    unittest.main()
