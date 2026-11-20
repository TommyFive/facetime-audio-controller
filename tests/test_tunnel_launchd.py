"""Portable unit checks for the FaceTime tunnel launchd configuration.

These tests do not connect to OpenAI, launch processes or use FaceTime.
"""
import importlib.util
from pathlib import Path
import plistlib
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "facetime_tunnel_service", ROOT / "tools" / "facetime_tunnel_service.py"
)
svc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(svc)


class TunnelLaunchdTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "test-user"

    def test_plist_launches_only_named_profile(self):
        result = plistlib.loads(svc.plist(self.home))
        args = result["ProgramArguments"]
        self.assertEqual(args[:4], [str(svc.CLIENT), "run", "--profile", "facetime-mcp"])
        self.assertEqual(result["Label"], svc.LABEL)
        self.assertEqual(result["RunAtLoad"], True)
        self.assertIs(result["KeepAlive"], True)
        self.assertEqual(result["Umask"], 0o077)
        self.assertEqual(result["ThrottleInterval"], 15)
        self.assertIn("--health.url-file", args)
        self.assertIn("--log.level", args)
        self.assertIn("warn", args)
        self.assertNotIn("sk-", repr(result))
        self.assertNotIn("API_KEY", repr(result))
        self.assertNotIn("facetime_call", repr(result))

    def test_paths_isolate_new_tunnel_from_existing_ones(self):
        paths = svc.paths(self.home)
        self.assertEqual(paths["config"].name, "facetime-mcp.yaml")
        self.assertEqual(paths["secret"].name, "facetime-control-plane.key")
        self.assertEqual(paths["plist"].name, svc.LABEL + ".plist")
        self.assertNotIn("ssh-mcp", repr(paths))
        self.assertNotIn("browser-mcp", repr(paths))

    def test_health_url_rejects_external_addresses_and_symlinks(self):
        p = svc.paths(self.home)["url"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("http://0.0.0.0:8080")
        self.assertIsNone(svc.local_url(self.home))
        p.write_text("https://example.com")
        self.assertIsNone(svc.local_url(self.home))
        p.write_text("http://127.0.0.1:12345/")
        self.assertEqual(svc.local_url(self.home), "http://127.0.0.1:12345")
        p.unlink()
        target = p.parent / "target"
        target.write_text("http://127.0.0.1:12345")
        p.symlink_to(target)
        self.assertIsNone(svc.local_url(self.home))


if __name__ == "__main__":
    unittest.main()
