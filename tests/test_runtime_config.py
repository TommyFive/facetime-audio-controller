"""Per-user settings must be independent and fail closed without credentials."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import facetime_runtime as cfg

class RuntimeConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file=Path(self.tmp.name)/"config.json"
        self.file.write_text("{}")
        self.file.chmod(0o600)
        self.env=patch.dict(os.environ,{"FACETIME_CONFIG":str(self.file),
                  "FACETIME_RECIPIENT":"","FACETIME_NANOKVM_ENDPOINT":""})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_no_default_recipient(self):
        self.assertEqual(cfg.recipient(),"")
        with self.assertRaisesRegex(RuntimeError,"RECIPIENT_NOT_CONFIGURED"):
            cfg.require_recipient()
        self.assertEqual(cfg.nanokvm_endpoint(),"")

    def test_configured_recipient(self):
        self.file.write_text(json.dumps({"facetime":{"recipient":"friend@example.invalid"},
                    "audio":{"device":"Loopback Audio"},"nanokvm":{"endpoint":""}}))
        self.assertEqual(cfg.require_recipient(),"friend@example.invalid")

    def test_bad_recipient_refused(self):
        self.file.write_text(json.dumps({"facetime":{"recipient":"unsafe user"}}))
        with self.assertRaisesRegex(RuntimeError,"RECIPIENT_NOT_CONFIGURED"):
            cfg.require_recipient()

    def test_private_endpoint_must_be_https(self):
        self.file.write_text(json.dumps({"nanokvm":{"endpoint":"http://example.invalid/api/mcp"}}))
        with self.assertRaisesRegex(RuntimeError,"NANOKVM_ENDPOINT_INVALID"):
            cfg.nanokvm_endpoint()

    def test_symlink_config_rejected(self):
        original=Path(self.tmp.name)/"original.json"
        original.write_text("{}")
        self.file.unlink()
        self.file.symlink_to(original)
        with self.assertRaisesRegex(RuntimeError,"CONFIG_UNSAFE_FILE"):
            cfg.load()

    def test_invalid_json_rejected(self):
        self.file.write_text("{")
        with self.assertRaisesRegex(RuntimeError,"CONFIG_INVALID"):
            cfg.load()
if __name__=="__main__":unittest.main()
