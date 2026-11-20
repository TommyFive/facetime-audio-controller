"""Permission checker regressions: read-only behavior, both GUI modes, TCC diagnostics."""
import importlib.util
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("facetime_permissions",ROOT/"facetime-permissions.py")
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def complete(code=0,out="",err=""):
    return subprocess.CompletedProcess([],code,out,err)

class FaceTimePermissionTests(unittest.TestCase):
    def test_unlocked_accessibility_granted(self):
        with patch.object(module.subprocess,"run",side_effect=[
            complete(out="GUI_UNLOCKED\n"),complete(out="4\n")]) as run:
            result=module.probe()
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"],"PERMISSIONS_OK")
        self.assertIn("osascript",run.call_args.args[0][0])
        self.assertNotIn("click",str(run.call_args))

    def test_unlocked_accessibility_denied(self):
        with patch.object(module.subprocess,"run",side_effect=[
            complete(out="GUI_UNLOCKED\n"),
            complete(1,err="osascript hat keine Berechtigung für den Hilfszugriff. (-25211)")]):
            result=module.probe()
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"],"ACCESSIBILITY_PERMISSION_DENIED")
        self.assertIn("System Settings",result["message"])

    def test_kvm_python_resolves_repository_and_installed_layouts(self):
        with tempfile.TemporaryDirectory() as t:
            root = pathlib.Path(t)
            repo = root / "projects" / "facetime-audio-controller"
            local_python = repo / ".venv/bin/python"
            local_python.parent.mkdir(parents=True)
            local_python.write_text("python")
            self.assertEqual(module.kvm_python_for(repo), local_python)
            installed_scripts = root / "scripts"
            installed_scripts.mkdir()
            expected = installed_scripts / ".venv/bin/python"
            self.assertEqual(module.kvm_python_for(installed_scripts), expected)

    def test_locked_nano_kvm_success(self):
        with patch.object(module,"KVM_PYTHON",ROOT/"facetime-permissions.py"), \
             patch.object(module,"KVM",ROOT/"facetime-permissions.py"), \
             patch.object(module.subprocess,"run",side_effect=[
                 complete(out="GUI_LOCKED\n"),complete(out='KVM_UI_RESULT {"status":"NONE"}\n')]):
            result=module.probe()
        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"],"GUI_LOCKED")

    def test_locked_kvm_denied(self):
        with patch.object(module,"KVM_PYTHON",ROOT/"facetime-permissions.py"), \
             patch.object(module,"KVM",ROOT/"facetime-permissions.py"), \
             patch.object(module.subprocess,"run",side_effect=[
                 complete(out="GUI_LOCKED\n"),complete(75,err="unauthorized")]):
            self.assertEqual(module.probe()["code"],"NANOKVM_ACCESS_DENIED")

    def test_unknown_gui_state_fails_closed(self):
        with patch.object(module.subprocess,"run",return_value=complete(75,out="GUI_UNKNOWN\n")):
            self.assertEqual(module.probe()["code"],"GUI_STATE_UNKNOWN")

    def test_timeout_fails_closed(self):
        with patch.object(module.subprocess,"run",side_effect=subprocess.TimeoutExpired("check",8)):
            self.assertEqual(module.probe()["code"],"PERMISSION_CHECK_TIMEOUT")

    def test_does_not_issue_calls_or_write_permissions(self):
        source=(ROOT/"facetime-permissions.py").read_text()
        self.assertNotIn("tccutil",source)
        self.assertNotIn("facetime-audio://",source)
        self.assertNotIn("AudioToolbox",source)
        controller=(ROOT/"facetime-call-fast.py").read_text()
        self.assertNotIn("AUDIO_ROUTE_PREFLIGHT_START",controller)
        self.assertIn('str(DIR/"facetime-permissions.py")',controller)
