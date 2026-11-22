"""Privacy-safe usage journal tests: offline, no calls, no MiniMax credentials."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import facetime_usage as usage

spec = importlib.util.spec_from_file_location("facetime_usage_tts_test", ROOT / "facetime-tts.py")
tts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tts)

class FakeResponse:
    status = 200
    def __init__(self, body):
        self.body = json.dumps(body).encode()
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, _limit):
        return self.body


def add_call(oid, outcome="completed", connected=True):
    usage.append(
        "call_result", operation_id=oid, outcome=outcome,
        dial_requested=True, connected=connected, playback_completed=connected,
        hangup_verified=connected, elapsed_seconds=12.5,
        connected_seconds=8.0 if connected else None,
        playback_seconds=7.0 if connected else None)


class UsageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ft-usage-test-")
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {"FACETIME_USAGE_DIR": self.temp.name}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("FACETIME_USAGE_ID", None)

    def test_fixed_schema_rejects_text_and_identity(self):
        with self.assertRaises(ValueError):
            usage.append("call_result", operation_id=usage.operation_id(), message="Sensitive words")
        with self.assertRaises(ValueError):
            usage.append("tts_render", operation_id=usage.operation_id(),
                         requested_provider="macos", provider="macos",
                         endpoint="local_macos", model="macos",
                         input_characters=8, audio_seconds=2.5,
                         elapsed_seconds=0.4, fallback=False,
                         recipient="test@example.invalid")
        self.assertFalse(usage.journal_path().exists())

    def test_concurrent_atomic_append_and_file_permissions(self):
        ids = [usage.operation_id() for _ in range(60)]
        with ThreadPoolExecutor(max_workers=12) as pool:
            list(pool.map(add_call, ids))
        events = usage.read_events()
        self.assertEqual(len(events), 60)
        self.assertEqual(set(row["operation_id"] for row in events), set(ids))
        self.assertEqual(usage.journal_path().stat().st_mode & 0o777, 0o600)
        self.assertEqual(usage.journal_path().parent.stat().st_mode & 0o777, 0o700)

    def test_symlink_file_is_refused(self):
        outside = Path(self.temp.name) / "outside.txt"
        outside.write_text("SAFE")
        usage.journal_path().symlink_to(outside)
        with self.assertRaises(OSError):
            add_call(usage.operation_id())
        self.assertEqual(outside.read_text(), "SAFE")

    def test_real_http_contract_only_provider_usage_metadata(self):
        payload = {
            "base_resp": {"status_code": 0},
            "extra_info": {"usage_characters": 19},
            "data": {"status": 2, "audio": (b"ID3" + b"0" * 1500).hex()},
        }
        conf = tts.config_load(ROOT / "tts-config.json")["minimax"]
        oid = usage.operation_id()
        with patch.dict(os.environ, {"FACETIME_USAGE_ID": oid}), \
             patch.object(tts, "read_key", return_value="synthetic"), \
             patch.object(tts.urllib.request, "urlopen", return_value=FakeResponse(payload)):
            target = Path(self.temp.name) / "audio.mp3"
            tts.request_minimax("SECRET_MESSAGE_SHOULD_NOT_APPEAR", conf, target)
        events = usage.read_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event"], "minimax_request")
        self.assertEqual(events[0]["result"], "generated")
        self.assertEqual(events[0]["usage_characters"], 19)
        self.assertEqual(events[0]["input_characters"], 32)
        self.assertEqual(events[0]["operation_id"], oid)
        self.assertNotIn("SECRET_MESSAGE", usage.journal_path().read_text())

    def test_provider_network_failure_is_not_falsely_billed(self):
        conf = tts.config_load(ROOT / "tts-config.json")["minimax"]
        with patch.object(tts, "read_key", return_value="synthetic"), \
             patch.object(tts.urllib.request, "urlopen", side_effect=urllib.error.URLError("synthetic")):
            with self.assertRaises(tts.TTSError):
                tts.request_minimax("Test", conf, Path(self.temp.name) / "nothing.mp3")
        report = usage.summarize(usage.read_events())
        self.assertEqual(report["minimax_generated"], 0)
        self.assertEqual(report["minimax_requests"], 1)
        self.assertEqual(report["minimax_usage_unknown"], 1)

    def test_local_fallback_recorded_as_separate_render_lane(self):
        config = tts.config_load(ROOT / "tts-config.json")
        message = "PRIVATE_MESSAGE_DO_NOT_LOG"
        def fake_macos(_text, _config, path):
            Path(path).write_bytes(b"FORM" + b"0" * 2000)
            return 3.75
        with patch.object(tts, "request_minimax", side_effect=tts.TTSError("network_timeout")), \
             patch.object(tts, "render_macos", side_effect=fake_macos):
            result = tts.render(message, config, Path(self.temp.name) / "output.aiff")
        self.assertTrue(result["fallback"])
        self.assertEqual(result["provider"], "macos")
        rows = usage.read_events()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["endpoint"], "local_macos")
        self.assertEqual(rows[0]["model"], "macos")
        self.assertTrue(rows[0]["fallback"])
        self.assertEqual(rows[0]["audio_seconds"], 3.75)
        self.assertEqual(rows[0]["input_characters"], len(message))
        self.assertNotIn(message, usage.journal_path().read_text())

    def test_direct_macos_is_not_fallback(self):
        config = tts.config_load(ROOT / "tts-config.json")
        def fake_macos(_text, _config, path):
            Path(path).write_bytes(b"FORM" + b"0" * 2000)
            return 2.5
        with patch.object(tts, "render_macos", side_effect=fake_macos), \
             patch.object(tts, "request_minimax") as remote:
            tts.render("Local only", config, Path(self.temp.name) / "local.aiff", provider="macos")
        remote.assert_not_called()
        obj = usage.read_events()[0]
        self.assertFalse(obj["fallback"])
        self.assertEqual(obj["requested_provider"], "macos")

    def test_generation_counted_without_successful_call(self):
        oid = usage.operation_id()
        usage.append("tts_render", operation_id=oid,
                     requested_provider="minimax", provider="minimax",
                     endpoint="api.minimax.io", model="speech-2.8-hd",
                     input_characters=100, audio_seconds=30,
                     elapsed_seconds=2.3, fallback=False)
        add_call(oid, outcome="failed", connected=False)
        report = usage.summarize(usage.read_events())
        self.assertEqual(report["rendered_count"], 1)
        self.assertEqual(report["rendered_audio_seconds"], 30)
        self.assertEqual(report["calls_not_connected"], 1)
        self.assertEqual(report["calls_completed"], 0)

    def test_summary_separates_regions_model_and_fallback(self):
        for endpoint in ("api.minimax.io", "api.minimaxi.com"):
            usage.append("minimax_request", operation_id=usage.operation_id(),
                         endpoint=endpoint, model="speech-2.8-turbo",
                         input_characters=11, usage_characters=12,
                         result="generated", elapsed_seconds=0.2)
        usage.append("tts_render", operation_id=usage.operation_id(),
                     requested_provider="minimax", provider="macos",
                     endpoint="local_macos", model="macos", fallback=True,
                     input_characters=11, audio_seconds=4, elapsed_seconds=1)
        report = usage.summarize(usage.read_events())
        self.assertEqual(report["minimax_usage_characters_known"], 24)
        self.assertEqual(report["minimax_generated"], 2)
        self.assertEqual(len(report["by_api"]), 2)
        self.assertIn("local_macos / macos / fallback", report["by_render"])

    def test_cli_json_is_aggregate_only(self):
        add_call(usage.operation_id())
        proc = subprocess.run([sys.executable, str(ROOT / "tools" / "usage.py"), "--json"],
                              capture_output=True, text=True, timeout=10, check=True)
        info = json.loads(proc.stdout)
        self.assertEqual(info["calls"], 1)
        self.assertNotIn("operation_id", proc.stdout)
        self.assertNotIn("timestamp", proc.stdout)


if __name__ == "__main__":
    unittest.main()
