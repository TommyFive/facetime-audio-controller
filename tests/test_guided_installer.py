"""Guided installer/upgrade planning tests. No real calls, API requests or host modifications."""
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    value=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value
wizard=module("facetime_setup_wizard","tools/setup_wizard.py")
installer=module("facetime_guided_installer","tools/install.py")
integration=module("facetime_openclaw_integration","tools/openclaw_integration.py")

def args(**overrides):
    params=dict(non_interactive=True,reconfigure=False,recipient="tester@example.invalid",
        tts_provider="macos",minimax_model=None,minimax_region=None,minimax_key_file=None,
        tts_voice=None,tts_speed=None,tts_volume=None,tts_pitch=None,max_characters=None,
        macos_rate=None,macos_max_characters=None,audio_device=None,nanokvm=None,nanokvm_endpoint=None,
        nanokvm_auth_file=None,accept_unlocked_only=False,openclaw=None,openclaw_cli=None,openclaw_config=None,replace_openclaw_mcp=False,watchdog=None,
        test_tts=False,check_permissions=False)
    params.update(overrides)
    return SimpleNamespace(**params)

class SetupPlanningTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        self.cfg=self.base/"cfg"
        self.p={"config":self.cfg}

    def test_explicit_unlocked_only_acknowledgment_is_required(self):
        with self.assertRaisesRegex(RuntimeError,"accept-unlocked-only"):
            wizard.plan(args(),self.p,ROOT)
        self.assertFalse(self.cfg.exists())

    def test_unlocked_cli_only_default(self):
        result=wizard.plan(args(accept_unlocked_only=True),self.p,ROOT)
        self.assertFalse(result["integration"])
        self.assertFalse(result["watchdog"])
        self.assertEqual(result["core"]["facetime"]["recipient"],"tester@example.invalid")
        self.assertEqual(result["tts"]["provider"],"macos")

    def test_paid_tts_check_requires_minimax(self):
        with self.assertRaisesRegex(RuntimeError,"requires MiniMax"):
            wizard.plan(args(tts_provider="macos",test_tts=True,accept_unlocked_only=True),self.p,ROOT)

    def test_fresh_provider_without_flag_defaults_to_private_macos(self):
        result=wizard.plan(args(tts_provider=None,accept_unlocked_only=True),self.p,ROOT)
        self.assertEqual(result["tts"]["provider"],"macos")

    def test_hd_or_turbo_and_models_caps(self):
        secret=self.base/"key.json"
        secret.write_text(json.dumps({"minimaxApiKey":"A"*45}))
        secret.chmod(0o600)
        for model,cap in (("turbo",10000),("hd",5000)):
            with self.subTest(model=model):
                setup=wizard.plan(args(tts_provider="minimax",minimax_model=model,
                    minimax_key_file=str(secret),max_characters=cap,accept_unlocked_only=True),self.p,ROOT)
                mm=setup["tts"]["minimax"]
                self.assertEqual(mm["model"],"speech-2.8-"+model)
                self.assertEqual(mm["max_characters_by_model"][mm["model"]],cap)
                self.assertEqual(setup["secret"],"A"*45)
        with self.assertRaisesRegex(RuntimeError,"Maximum characters"):
            wizard.plan(args(tts_provider="minimax",minimax_model="hd",
                minimax_key_file=str(secret),max_characters=6000,accept_unlocked_only=True),self.p,ROOT)

    def test_conflicting_provider_options_are_rejected(self):
        with self.assertRaisesRegex(RuntimeError,"MiniMax-specific options"):
            wizard.plan(args(tts_provider="macos",minimax_model="hd",accept_unlocked_only=True),self.p,ROOT)
        with self.assertRaisesRegex(RuntimeError,"NanoKVM endpoint/credential"):
            wizard.plan(args(tts_provider="macos",nanokvm=False,
                             nanokvm_endpoint="https://kvm.example.invalid/api/mcp",
                             accept_unlocked_only=True),self.p,ROOT)
        with self.assertRaisesRegex(RuntimeError,"OpenClaw configuration options"):
            wizard.plan(args(tts_provider="macos",openclaw=False,
                             replace_openclaw_mcp=True,accept_unlocked_only=True),self.p,ROOT)

    def test_missing_minimax_key_blocks_install(self):
        with self.assertRaisesRegex(RuntimeError,"no owner-only API key"):
            wizard.plan(args(tts_provider="minimax",accept_unlocked_only=True),self.p,ROOT)

    def test_nano_requires_endpoint_and_token(self):
        with self.assertRaisesRegex(RuntimeError,"authorized HTTPS"):
            wizard.plan(args(nanokvm=True),self.p,ROOT)
        token=self.base/"nanokvm-auth"
        token.write_text("Bearer "+"X"*55+"\n");token.chmod(0o600)
        result=wizard.plan(args(nanokvm=True,nanokvm_endpoint="https://kvm.example.invalid/api/mcp",
                                nanokvm_auth_file=str(token),openclaw=False),self.p,ROOT)
        self.assertTrue(result["nanokvm"])
        self.assertFalse(result["watchdog"])
        token.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError,"mode 0600"):
            wizard.plan(args(nanokvm=True,nanokvm_endpoint="https://kvm.example.invalid/api/mcp",
                             nanokvm_auth_file=str(token)),self.p,ROOT)

    def test_existing_config_can_be_updated_without_destroying_other_settings(self):
        self.cfg.mkdir()
        old={"facetime":{"recipient":"friend@example.invalid"},"audio":{"device":"Loopback Audio"},
             "nanokvm":{"endpoint":""},"reserved":{"future":"retain"}}
        (self.cfg/"config.json").write_text(json.dumps(old));(self.cfg/"config.json").chmod(0o600)
        setup=wizard.plan(args(recipient="friend@example.invalid",tts_provider="macos",
                               accept_unlocked_only=True,audio_device="Loopback Audio"),self.p,ROOT)
        self.assertEqual(setup["core"]["reserved"]["future"],"retain")
        self.assertFalse(setup["nanokvm"])

    def test_same_installation_credentials_are_private_and_rollback(self):
        result=wizard.plan(args(accept_unlocked_only=True),self.p,ROOT)
        saved=installer.write_settings(result,self.p)
        target=self.cfg/"config.json"
        self.assertEqual(stat.S_IMODE(target.stat().st_mode),0o600)
        self.assertEqual(json.loads(target.read_text())["facetime"]["recipient"],"tester@example.invalid")
        installer.restore_settings(saved)
        self.assertFalse(target.exists())
        self.assertFalse((self.cfg/"tts.json").exists())

    def test_interactive_setup_prompts_for_all_major_features(self):
        # Fresh interactive setup, MiniMax Turbo and unlocked-only, no OpenClaw.
        user_inputs=iter(["friend@example.invalid","", "2","1","1","","","","","","n","y","n","n","y","n"])
        with patch("builtins.input",side_effect=lambda *_:next(user_inputs)),\
             patch.object(wizard.getpass,"getpass",return_value="B"*45) as key:
            result=wizard.plan(args(non_interactive=False,recipient=None,tts_provider=None),self.p,ROOT)
        self.assertEqual(result["core"]["facetime"]["recipient"],"friend@example.invalid")
        self.assertEqual(result["tts"]["provider"],"minimax")
        self.assertEqual(result["tts"]["minimax"]["model"],"speech-2.8-turbo")
        self.assertEqual(result["secret"],"B"*45)
        key.assert_called_once()

class OpenClawMCPRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.cli=self.root/"openclaw"
        self.cli.write_text("#!/bin/sh\nexit 0\n");self.cli.chmod(0o700)
        self.config=self.root/"openclaw.json"
        self.config.write_text('{"some":"unrelated"}');self.config.chmod(0o600)

    def test_safe_native_stdio_definition(self):
        d=integration.definition(self.root/"current")
        self.assertIn("facetime_call_start",d["toolFilter"]["include"])
        self.assertNotIn("facetime_call",d["toolFilter"]["include"])
        self.assertEqual(d["codex"]["defaultToolsApprovalMode"],"prompt")
        self.assertEqual(d["requestTimeoutMs"],60000)

    def test_existing_server_is_not_overwritten_without_explicit_replace(self):
        result=SimpleNamespace(returncode=0,stdout="set add doctor show",stderr="")
        with patch.object(integration,"cmd",return_value=result):
            with self.assertRaisesRegex(RuntimeError,"already registered"):
                integration.integrate(self.root/"current",self.root/"private",
                    cli_path=str(self.cli),openclaw_config=str(self.config),replace=False)

    def test_registration_via_native_cli_backs_up_all_config(self):
        def response(_binary,*argv,**kwargs):
            if argv[0:2]==("mcp","show"):
                return SimpleNamespace(returncode=1,stdout="",stderr="")
            return SimpleNamespace(returncode=0,stdout="set doctor facetime_call_start facetime_health",stderr="")
        with patch.object(integration,"cmd",side_effect=response) as cmd:
            result=integration.integrate(self.root/"current",self.root/"private",
                cli_path=str(self.cli),openclaw_config=str(self.config))
        backup=Path(result["backup"])
        self.assertEqual(backup.read_bytes(),self.config.read_bytes())
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode),0o600)
        commands=[call.args[1:3] for call in cmd.call_args_list]
        self.assertIn(("mcp","set"),commands)
        self.assertIn(("mcp","doctor"),commands)

if __name__=="__main__":
    unittest.main()
