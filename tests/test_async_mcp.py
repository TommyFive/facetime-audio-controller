"""Offline async MCP, config limits and watchdog tests: no FaceTime calls."""
import importlib.util
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch,MagicMock

ROOT=pathlib.Path(__file__).resolve().parents[1]
def load(filename,alias):
    spec=importlib.util.spec_from_file_location(alias, ROOT/filename)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
mcp=load("facetime-mcp-server.py","facetime_mcp_async_test")
tts=load("facetime-tts.py","facetime_tts_limits_test")
worker=load("facetime_async_worker.py","facetime_async_worker_test")
watchdog=load("facetime-async-watchdog.py","facetime_async_watchdog_test")

class AsyncTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder=pathlib.Path(tmp.name)
        self.patches=[
            patch.object(mcp,"ASYNC_DIR",self.folder),
            patch.object(mcp,"STATE_DIR",self.folder),
            patch.object(mcp,"RUNS",self.folder/"requests.json"),
            patch.object(mcp,"LOCK",self.folder/"requests.lock")
        ]
        for p in self.patches:p.start();self.addCleanup(p.stop)

    def test_start_returns_immediately_reuses_id_and_does_not_dial_in_agent_process(self):
        with patch.object(mcp.subprocess,"Popen") as spawn:
            spawn.return_value.pid=12345
            start=mcp.facetime_call_start("Hallo <#1#> Test!","async-test-0001")
            self.assertTrue(start["ok"])
            self.assertEqual(start["state"],"starting")
            self.assertEqual(spawn.call_count,1)
            self.assertEqual(spawn.call_args.args[0][-1],"async-test-0001")
            status=mcp.facetime_call_status("async-test-0001")
            self.assertEqual(status["state"],"starting")
            again=mcp.facetime_call_start("Hallo <#1#> Test!","async-test-0001")
            self.assertEqual(again["state"],"starting")
            self.assertEqual(spawn.call_count,1)
            changed=mcp.facetime_call_start("different","async-test-0001")
            self.assertEqual(changed["code"],"REQUEST_ID_CONFLICT")

    def test_active_async_prevents_second_call(self):
        with patch.object(mcp.subprocess,"Popen") as spawn:
            spawn.return_value.pid=12345
            mcp.facetime_call_start("hello","async-test-0001")
            out=mcp.facetime_call_start("hello","async-test-0002")
            self.assertEqual(out["code"],"ASYNC_CALL_IN_PROGRESS")
            self.assertEqual(spawn.call_count,1)

    def test_oversize_hd_rejected_without_spawn(self):
        with patch.object(mcp.subprocess,"Popen") as spawn:
            with self.assertRaisesRegex(ValueError,"text_exceeds_provider_model_limit"):
                mcp.facetime_call_start("X"*5001,"async-test-0001")
            spawn.assert_not_called()

    def test_cancel_rejects_unrelated_transaction(self):
        state={"request_id":"async-test-0040","state":"running","ok":False,
               "controller_run_id":"expected-transaction"}
        mcp._async_path("async-test-0040").write_text(json.dumps(state))
        journal=self.folder/"controller-journal.json"
        journal.write_text(json.dumps({
            "run_id":"another-transaction","stage":"PLAYING",
            "url_may_have_been_sent":True}))
        with patch.object(mcp,"CONTROLLER_JOURNAL",journal),             patch.object(mcp,"_exec") as call:
            result=mcp.facetime_call_cancel("async-test-0040")
        self.assertEqual(result["code"],"REQUEST_NOT_CURRENT_CALL")
        call.assert_not_called()

    def test_wait_timeout_returns_running_without_redial(self):
        data={"request_id":"async-test-0001","state":"running","ok":False}
        mcp._async_path("async-test-0001").write_text(json.dumps(data))
        result=mcp.facetime_call_wait("async-test-0001",1)
        self.assertEqual(result["state"],"running")
        self.assertFalse(result["ok"])

class TTSLimitTests(unittest.TestCase):
    def test_both_model_boundaries(self):
        cfg=tts.config_load(ROOT/"tts-config.json")
        self.assertEqual(cfg["minimax"]["max_characters_by_model"]["speech-2.8-turbo"],10000)
        self.assertEqual(cfg["minimax"]["max_characters_by_model"]["speech-2.8-hd"],5000)
        for model,cap in [("speech-2.8-turbo",10000),("speech-2.8-hd",5000)]:
            cfg["minimax"]["model"]=model
            tts.validate_text_length("x"*cap,cfg,"minimax")
            with self.assertRaisesRegex(tts.TTSError,"text_exceeds_provider_model_limit"):
                tts.validate_text_length("x"*(cap+1),cfg,"minimax")

    def test_optional_macos_cap(self):
        cfg=tts.config_load(ROOT/"tts-config.json")
        tts.validate_text_length("x"*15000,cfg,"macos")
        cfg["macos"]["max_characters"]=2000
        with self.assertRaisesRegex(tts.TTSError,"text_exceeds_provider_model_limit"):
            tts.validate_text_length("x"*2001,cfg,"macos")

    def test_invalid_config_cap(self):
        cfg=tts.config_load(ROOT/"tts-config.json")
        cfg["minimax"]["max_characters_by_model"]["speech-2.8-hd"]=True
        with self.assertRaisesRegex(tts.TTSError,"config_max_characters_by_model_invalid"):
            tts.config_load_data(cfg)

class WatchdogTests(unittest.TestCase):
    def test_safe_noop_without_active_async_job(self):
        with tempfile.TemporaryDirectory() as dir:
            with patch.object(watchdog,"STATE",pathlib.Path(dir)):
                self.assertEqual(watchdog.check(),[])

    def test_no_unrelated_call_hangup(self):
        with tempfile.TemporaryDirectory() as dir:
            path=pathlib.Path(dir)
            sample={"request_id":"async-watch-0001","state":"running",
                "worker_pid":-1,"started_at":0,"deadline_at":1,
                "controller_run_id":"owned-transaction"}
            (path/"async-watch-0001.json").write_text(json.dumps(sample))
            with patch.object(watchdog,"STATE",path),\
                 patch.object(watchdog,"JOURNAL",path/"journal.json"),\
                 patch.object(watchdog,"atomic",side_effect=lambda key,value:(path/(key+".json")).write_text(json.dumps(value))),\
                 patch.object(watchdog.subprocess,"run") as hangup:
                (path/"journal.json").write_text(json.dumps({"run_id":"another-call","stage":"PLAYING","url_may_have_been_sent":True}))
                outcome=watchdog.check()
                self.assertEqual(len(outcome),1)
                hangup.assert_not_called()
                self.assertEqual(json.loads((path/"async-watch-0001.json").read_text())["state"],"recovery_required")

    def test_dead_worker_matching_controller_transaction_triggers_verified_hangup(self):
        import subprocess
        with tempfile.TemporaryDirectory() as directory:
            folder=pathlib.Path(directory)
            sample={"request_id":"async-watch-0003","state":"running",
                    "worker_pid":-1,"started_at":0,"deadline_at":1,
                    "controller_run_id":"matching-transaction"}
            (folder/"async-watch-0003.json").write_text(json.dumps(sample))
            (folder/"journal.json").write_text(json.dumps({
                "run_id":"matching-transaction","stage":"HANGING_UP",
                "url_may_have_been_sent":True}))
            with patch.object(watchdog,"STATE",folder),                 patch.object(watchdog,"JOURNAL",folder/"journal.json"),                 patch.object(watchdog,"atomic",side_effect=lambda key,value:(folder/(key+".json")).write_text(json.dumps(value))),                 patch.object(watchdog.subprocess,"run",return_value=subprocess.CompletedProcess([],0,"","")) as hangup:
                found=watchdog.check()
            self.assertEqual(len(found),1)
            self.assertTrue(found[0][2])
            hangup.assert_called_once()
            outcome=json.loads((folder/"async-watch-0003.json").read_text())
            self.assertEqual(outcome["state"],"watchdog_recovered")
            self.assertTrue(outcome["hangup_verified"])

    def test_stalled_hangup_is_recovered_even_with_live_worker(self):
        import subprocess,time
        with tempfile.TemporaryDirectory() as directory:
            folder=pathlib.Path(directory)
            sample={"request_id":"async-watch-0004","state":"running",
                    "worker_pid":99999,"started_at":time.time()-100,
                    "deadline_at":time.time()+1000,
                    "controller_run_id":"owned-hangup-stall"}
            (folder/"async-watch-0004.json").write_text(json.dumps(sample))
            (folder/"journal.json").write_text(json.dumps({
                "run_id":"owned-hangup-stall","stage":"HANGING_UP",
                "updated_at":time.time()-130,
                "url_may_have_been_sent":True}))
            with patch.object(watchdog,"STATE",folder),                 patch.object(watchdog,"JOURNAL",folder/"journal.json"),                 patch.object(watchdog,"alive",return_value=True),                 patch.object(watchdog,"atomic",side_effect=lambda key,value:(folder/(key+".json")).write_text(json.dumps(value))),                 patch.object(watchdog.subprocess,"run",return_value=subprocess.CompletedProcess([],0,"","")) as hangup:
                result=watchdog.check()
            self.assertEqual(result[0][1],"hangup_stalled")
            self.assertTrue(result[0][2])
            hangup.assert_called_once()

if __name__=="__main__":unittest.main()
