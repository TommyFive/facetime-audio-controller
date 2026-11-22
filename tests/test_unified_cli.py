"""Unified CLI and installer wrapper regression tests; no calls or external APIs."""
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

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("facetime_unified_cli", ROOT/"tools/cli.py")
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)
spec2 = importlib.util.spec_from_file_location("facetime_installer_cli", ROOT/"tools/install.py")
installer = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(installer)


class UnifiedCLITests(unittest.TestCase):
    def test_legacy_calls_use_original_shell_entrypoint(self):
        for command, expected in (("call", "--call"), ("speak", "--speak"),
                                  ("status", "--status"), ("hangup", "--hangup"),
                                  ("dry-run", "--dry-run"), ("cancel-pending", "--cancel-pending")):
            with self.subTest(command=command), patch.object(cli.os, "execv") as execute:
                cli.dispatch([command, "--flag", "sample with spaces"])
                executable, argv = execute.call_args.args
                self.assertEqual(executable, str(ROOT/"facetime-call.sh"))
                self.assertEqual(argv[1:], [expected, "--flag", "sample with spaces"])

    def test_doctor_and_stats_use_existing_modules(self):
        for command, filename in (("doctor", "doctor.py"), ("stats", "usage.py")):
            with self.subTest(command=command), patch.object(cli.os, "execv") as execute:
                cli.dispatch([command, "--json"])
                executable, argv = execute.call_args.args
                self.assertEqual(executable, sys.executable)
                self.assertEqual(argv, [sys.executable, str(ROOT/"tools"/filename), "--json"])

    def test_help_unknown_and_no_extra_arguments(self):
        self.assertEqual(cli.dispatch([]), 0)
        self.assertEqual(cli.dispatch(["help"]), 0)
        self.assertEqual(cli.dispatch(["help", "unexpected"]), 64)
        self.assertEqual(cli.dispatch(["nonexistent"]), 64)

    def test_stats_cli_real_exec_no_call_and_no_transcripts(self):
        with tempfile.TemporaryDirectory() as folder:
            proc=subprocess.run([sys.executable,str(ROOT/"tools/cli.py"),"stats","--json"],
                env={**os.environ,"FACETIME_USAGE_DIR":folder},capture_output=True,
                text=True,timeout=15)
            self.assertEqual(proc.returncode,0,proc.stderr)
            report=json.loads(proc.stdout)
            self.assertEqual(report["minimax_total"]["attempts"],0)
            self.assertEqual(set(report["minimax_by_model"]),
                             {"speech-2.8-hd","speech-2.8-turbo"})
            self.assertEqual(report["calls"],0)

    def test_installer_package_includes_all_router_targets(self):
        with tempfile.TemporaryDirectory() as folder:
            dest=Path(folder)/"package"
            installer.copy_source(dest)
            for name in ("tools/cli.py","tools/usage.py","tools/doctor.py",
                         "facetime_usage.py","facetime-call.sh"):
                self.assertTrue((dest/name).is_file(),name)

    def test_wrapper_executes_python_and_passes_exact_args_with_spaced_paths(self):
        with tempfile.TemporaryDirectory(prefix="face time cli wrapper ") as folder:
            base=Path(folder)
            current=base/"facetime controller/current"
            python=current/".venv/bin/python"
            python.parent.mkdir(parents=True)
            python.symlink_to(sys.executable)
            module=current/"tools/cli.py"
            module.parent.mkdir(parents=True)
            module.write_text("import json,sys;print(json.dumps(sys.argv[1:]))\n")
            binary=base/"bin/facetime-controller"
            installer.wrapper(binary,current,"tools/cli.py")
            self.assertEqual(stat.S_IMODE(binary.stat().st_mode),0o755)
            proc=subprocess.run([str(binary),"stats","--json","an argument with spaces"],
                capture_output=True,text=True,timeout=12)
            self.assertEqual(proc.returncode,0,proc.stderr)
            self.assertEqual(json.loads(proc.stdout),["stats","--json","an argument with spaces"])

    def test_wrapper_rejects_unrelated_and_symlink(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder)
            symlink=base/"controller"
            target=base/"target"
            target.write_text("unrelated")
            symlink.symlink_to(target)
            with self.assertRaisesRegex(RuntimeError,"symlink"):
                installer.wrapper(symlink,base/"current","tools/cli.py")
            self.assertEqual(target.read_text(),"unrelated")

if __name__=="__main__":
    unittest.main()
