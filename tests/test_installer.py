"""Installer safety and configuration tests; no app installation or FaceTime calls."""
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("facetime_installer",ROOT/"tools/install.py")
installer=importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)

class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)

    def test_recipient_validation(self):
        self.assertTrue(installer.recipient_check("friend@example.invalid"))
        # German regulator-reserved drama number (Berlin +49 30 23125 000).
        self.assertTrue(installer.recipient_check("+493023125000"))
        for bad in ("","someone","https://example.invalid","user name","@invalid"):
            self.assertFalse(installer.recipient_check(bad))

    def test_private_write_is_non_destructive(self):
        target=self.base/"private/settings.json"
        self.assertTrue(installer.private_write(target,b'{"a":1}\n'))
        self.assertEqual(stat.S_IMODE(target.stat().st_mode),0o600)
        self.assertFalse(installer.private_write(target,b"changed"))
        self.assertEqual(target.read_bytes(),b'{"a":1}\n')
        self.assertTrue(installer.private_write(target,b"changed",overwrite=True))

    def test_refuse_symlink_to_other_user_file(self):
        source=self.base/"source.json";source.write_text("important")
        dest=self.base/"settings.json";dest.symlink_to(source)
        with self.assertRaises(RuntimeError):
            installer.private_write(dest,b"secret",overwrite=True)
        self.assertEqual(source.read_text(),"important")

    def test_wrapper_uses_managed_python_for_doctor(self):
        current=self.base/"facetime-controller/current"
        dest=self.base/"bin/facetime-controller-doctor"
        installer.wrapper(dest,current,"tools/doctor.py")
        text=dest.read_text()
        self.assertIn("/current/.venv/bin/python",text)
        self.assertIn("/current/tools/doctor.py",text)

    def test_refuse_overwriting_unrelated_command(self):
        current=self.base/"facetime-controller/current"
        dest=self.base/"bin/facetime-call"
        dest.parent.mkdir()
        dest.write_text("#!/bin/sh\necho unrelated\n")
        with self.assertRaises(RuntimeError):
            installer.wrapper(dest,current,"facetime-call.sh")

    def test_dry_run_changes_nothing(self):
        prefix=self.base/"package"
        proc=subprocess.run([sys.executable,str(ROOT/"tools/install.py"),
                             "install","--prefix",str(prefix),"--dry-run","--non-interactive"],
                            capture_output=True,text=True,timeout=12)
        self.assertEqual(proc.returncode,0,proc.stderr)
        self.assertFalse(prefix.exists())
if __name__=="__main__":unittest.main()
