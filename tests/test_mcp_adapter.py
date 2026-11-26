"""Safety tests for stdio MCP facade; no real calls or speech."""
import importlib.util
import pathlib
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("facetime_mcp_module", ROOT / "facetime-mcp-server.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class MCPAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = pathlib.Path(self.tmp.name)
        self.patches = [
            patch.object(module, "STATE_DIR", root),
            patch.object(module, "RUNS", root / "requests.json"),
            patch.object(module, "LOCK", root / "requests.lock"),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def test_fixed_target_no_recipient_argument(self):
        import inspect
        self.assertNotIn("recipient", inspect.signature(module.facetime_call.fn if hasattr(module.facetime_call, "fn") else module.facetime_call).parameters)

    def test_max_lifecycle_budget_and_verified_completion(self):
        import subprocess
        budget = module.call_timeout_seconds(20, 60, 24)
        self.assertEqual(budget, 1745)
        self.assertLess(budget, 1900)
        output = ("TTS_RENDER_READY provider=minimax requested=minimax fallback=False\n"
                  "CONNECTED event=2026-11-20T10:01:00\n"
                  "PLAY_START\nPLAY_END seconds=310.1\nHANGUP_OK\nCALL_COMPLETED")
        with patch.object(module, "_run_bounded",
                          return_value=subprocess.CompletedProcess(["controller"], 0, output, "")):
            r = module._exec("call", ["--call","fixture"], budget)
        self.assertTrue(r["ok"])
        self.assertEqual(r["state"], "call_terminated")
        self.assertTrue(r["call_connected_observed"])
        self.assertTrue(r["hangup_verified"])
        self.assertEqual(r["tts_provider_used"], "minimax")

    def test_invalid_id_no_execution(self):
        with patch.object(module, "_exec") as run:
            with self.assertRaises(ValueError):
                module.facetime_call(message="hello", request_id="../bad")
            run.assert_not_called()

    def test_long_briefing_supported_and_bounded(self):
        message = "Guten Morgen. " * 120  # > 1,200 chars, under HD's 5,000 cap
        with patch.object(module, "_exec", return_value={"state":"call_terminated","ok":True}) as run:
            result = module.facetime_call(message, "morning-briefing-20261120")
        self.assertTrue(result["ok"])
        self.assertEqual(run.call_count, 1)
        args, kwargs = run.call_args
        self.assertEqual(args[0], "call")
        self.assertIn(message, args[1])
        self.assertGreater(args[2], 1200)

    def test_too_long_message_no_execution(self):
        with patch.object(module, "_exec") as run:
            with self.assertRaisesRegex(ValueError, "text_exceeds_provider_model_limit"):
                module.facetime_call(message="X"*8001, request_id="morning-briefing-20261120")
            run.assert_not_called()

    def test_invalid_message_no_execution(self):
        with patch.object(module, "_exec") as run:
            with self.assertRaises(ValueError):
                module.facetime_call(message="\x00", request_id="case-0001")
            run.assert_not_called()

    def test_duplicate_same_id_suppressed(self):
        def succeed(*args, **kw):
            return module._result("call", ok=True, state="completed_by_controller", request_id=kw.get("request_id"))
        with patch.object(module, "_exec", side_effect=succeed) as run:
            first = module.facetime_call("hi", "case-0001")
            second = module.facetime_call("hi", "case-0001")
        self.assertTrue(first["ok"])
        self.assertEqual(second["code"], "DUPLICATE_REQUEST")
        self.assertEqual(run.call_count, 1)

    def test_request_id_conflict(self):
        with patch.object(module, "_exec", return_value={"state":"test","ok":True}) as run:
            module.facetime_call("hi", "case-0001")
            out = module.facetime_call("different", "case-0001")
            self.assertEqual(out["code"], "REQUEST_ID_CONFLICT")
            self.assertEqual(run.call_count, 1)

    def test_timeout_does_not_claim_success(self):
        import subprocess
        with patch.object(module, "_run_bounded", side_effect=subprocess.TimeoutExpired("test", 1)):
            result = module._exec("status", ["--status"], 1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CONTROLLER_TIMEOUT")
        self.assertEqual(result["state"], "timeout_unknown")

    def test_redact_token(self):
        r = module._result("test", ok=True, state="done", output="STATE=OK\nAuthorization: Bearer 123\napi_key=secret")
        self.assertEqual(r["controller_output"], "STATE=OK")

    def test_health_rejects_missing_accessibility(self):
        import subprocess
        import sys
        response=subprocess.CompletedProcess([],75,
            '{"ok":false,"code":"ACCESSIBILITY_PERMISSION_DENIED",'
            '"mode":"GUI_UNLOCKED","message":"Grant Accessibility"}\n',"")
        with patch.object(module,"CONTROLLER",pathlib.Path(sys.executable)), \
             patch.object(module,"_run_bounded",return_value=response):
            health=module.facetime_health()
        self.assertFalse(health["ok"])
        self.assertFalse(health["permissions_ok"])
        self.assertEqual(health["permissions_code"],"ACCESSIBILITY_PERMISSION_DENIED")
        self.assertNotIn("audio_route_ok",health)

    def test_invalid_tts(self):
        with self.assertRaises(ValueError):
            module.facetime_speak("hello", speed=3.0)

if __name__ == "__main__":
    unittest.main()
