"""Focused process-group timeout regression tests; never invoke FaceTime."""
import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("facetime_timeout_module", ROOT / "facetime-mcp-server.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BoundedRunnerTests(unittest.TestCase):
    def test_timeout_terminates_process_group(self):
        class FakeProcess:
            pid = 12345
            returncode = -15
            count = 0

            def communicate(self, timeout=None):
                self.count += 1
                if self.count == 1:
                    raise subprocess.TimeoutExpired("fake", timeout)
                return ("", "")

        proc = FakeProcess()
        with patch.object(module.subprocess, "Popen", return_value=proc) as spawn, \
             patch.object(module.os, "killpg") as killpg:
            with self.assertRaises(subprocess.TimeoutExpired):
                module._run_bounded(["/usr/bin/true"], timeout=1)
        self.assertTrue(spawn.call_args.kwargs["start_new_session"])
        killpg.assert_called_once_with(12345, module.signal.SIGTERM)
        self.assertEqual(proc.count, 2)

    def test_escalates_when_graceful_stop_does_not_exit(self):
        class FakeProcess:
            pid = 54321
            returncode = -9
            count = 0

            def communicate(self, timeout=None):
                self.count += 1
                if self.count <= 2:
                    raise subprocess.TimeoutExpired("fake", timeout)
                return ("", "")

        proc = FakeProcess()
        with patch.object(module.subprocess, "Popen", return_value=proc), \
             patch.object(module.os, "killpg") as killpg:
            with self.assertRaises(subprocess.TimeoutExpired):
                module._run_bounded(["/usr/bin/true"], timeout=1)
        self.assertEqual([c.args[1] for c in killpg.call_args_list],
                         [module.signal.SIGTERM, module.signal.SIGKILL])

    def test_success_preserves_output_and_exit_code(self):
        result = module._run_bounded(
            ["/usr/bin/env", "python3", "-c", "print('ok')"],
            timeout=5
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "ok")


if __name__ == "__main__":
    unittest.main()
