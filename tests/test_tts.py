"""MiniMax 2.8 Turbo/HD / macOS TTS safety and fallback tests.

No external network, FaceTime URL, outgoing call or Loopback audio in this suite.
Valid synthetic MP3 is made locally with the already installed FFmpeg.
"""
import importlib.util
import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

ROOT=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("facetime_tts_module",ROOT/"facetime-tts.py")
tts=importlib.util.module_from_spec(spec)
spec.loader.exec_module(tts)

class FakeResponse:
    status=200
    def __init__(self,body):self.body=body
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def read(self,amount):return self.body

class TTSTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture=tempfile.TemporaryDirectory(prefix="facetime-unit-audio-")
        cls.valid_mp3=pathlib.Path(cls.fixture.name)/"synthetic.mp3"
        subprocess.run([(__import__("shutil").which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"),"-nostdin","-v","error","-y",
            "-f","lavfi","-i","sine=frequency=440:duration=0.8",
            "-codec:a","libmp3lame","-q:a","6",str(cls.valid_mp3)],
            check=True,timeout=18)
        assert cls.valid_mp3.stat().st_size>1000
    @classmethod
    def tearDownClass(cls):cls.fixture.cleanup()
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="facetime-unit-run-")
        self.addCleanup(self.temp.cleanup)
        self.config=tts.config_load(ROOT/"tts-config.json")
        self.path=pathlib.Path(self.temp.name)/"result.aiff"
        # Linux CI lacks macOS /usr/bin/say. Retain real say coverage on macOS,
        # but use local synthetic AIFF when validating fallback semantics on Linux.
        if sys.platform != "darwin":
            mock=patch.object(tts,"render_macos",side_effect=self.synthetic_local_tts)
            mock.start()
            self.addCleanup(mock.stop)

    def synthetic_local_tts(self,text,settings,path):
        subprocess.run([shutil.which("ffmpeg"),"-nostdin","-v","error","-y",
                        "-f","lavfi","-i","sine=frequency=440:duration=0.8",
                        "-ar","48000","-ac","2","-c:a","pcm_s16be",
                        "-f","aiff",str(path)],check=True,timeout=20)
        pathlib.Path(path).chmod(0o600)
        return tts.verify_aiff(path)
    def mock_mp3(self,text,settings,target):
        shutil.copyfile(self.valid_mp3,target)
        return target.stat().st_size
    def test_default_provider_and_voice(self):
        self.assertEqual(self.config["provider"],"minimax")
        self.assertEqual(self.config["fallback_provider"],"macos")
        self.assertIn(self.config["minimax"]["model"],("speech-2.8-turbo","speech-2.8-hd"))
        self.assertEqual(self.config["minimax"]["voice_id"],"German_FriendlyMan")
        self.assertEqual(self.config["minimax"]["language_boost"],"German")
        self.assertEqual(self.config["minimax"]["speed"],1.1)
        self.assertEqual(self.config["minimax"]["pitch"],0)
        self.assertEqual(self.config["minimax"]["volume"],1.0)
    def test_both_minimax_models_accepted(self):
        for model in ("speech-2.8-turbo", "speech-2.8-hd"):
            with self.subTest(model=model):
                self.config["minimax"]["model"]=model
                validated=tts.config_load_data(self.config)
                self.assertEqual(validated["minimax"]["model"],model)

    def test_unknown_model_rejected_before_api_request(self):
        self.config["minimax"]["model"]="speech-3.0-unknown"
        with patch.object(tts,"request_minimax") as upstream:
            with self.assertRaisesRegex(tts.TTSError,"config_minimax_model_invalid"):
                tts.render("Hallo Test.",self.config,self.path)
        upstream.assert_not_called()

    def test_hd_model_selection_renders_correct_metadata(self):
        self.config["minimax"]["model"]="speech-2.8-hd"
        observed=[]
        def record(text,settings,target):
            observed.append(settings["model"])
            return self.mock_mp3(text,settings,target)
        with patch.object(tts,"request_minimax",side_effect=record):
            result=tts.render("Hallo Test.",self.config,self.path)
        self.assertEqual(observed,["speech-2.8-hd"])
        self.assertEqual(result["model"],"speech-2.8-hd")
        self.assertEqual(result["provider"],"minimax")
        self.assertFalse(result["fallback"])

    def test_hd_api_request_payload(self):
        self.config["minimax"]["model"]="speech-2.8-hd"
        data={"data":{"audio":self.valid_mp3.read_bytes().hex(),"status":2},
              "base_resp":{"status_code":0}}
        observed=[]
        def fake_urlopen(req,timeout):
            observed.append(json.loads(req.data))
            return FakeResponse(json.dumps(data).encode())
        with patch.object(tts,"read_key",return_value="synthetic-credential-not-secret"),\
             patch.object(tts.urllib.request,"urlopen",side_effect=fake_urlopen):
            tts.request_minimax("Hallo.",self.config["minimax"],
                pathlib.Path(self.temp.name)/"hd.mp3")
        self.assertEqual(observed[0]["model"],"speech-2.8-hd")
        self.assertEqual(observed[0]["voice_setting"]["speed"],1.1)

    def test_hd_network_error_falls_back_to_macos(self):
        self.config["minimax"]["model"]="speech-2.8-hd"
        with patch.object(tts,"request_minimax",side_effect=tts.TTSError("network_timeout")):
            result=tts.render("Hallo Test.",self.config,self.path)
        self.assertEqual(result["provider"],"macos")
        self.assertEqual(result["fallback_reason"],"network_timeout")

    def test_valid_minimax_audio_to_aiff(self):
        with patch.object(tts,"request_minimax",side_effect=self.mock_mp3):
            info=tts.render("Hallo, Test.",self.config,self.path)
        self.assertEqual(info["provider"],"minimax")
        self.assertFalse(info["fallback"])
        self.assertTrue(self.path.read_bytes().startswith(b"FORM"))
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode),0o600)
    def test_macos_override_bypasses_minimax(self):
        with patch.object(tts,"request_minimax") as upstream:
            info=tts.render("Hallo Test.",self.config,self.path,provider="macos")
            upstream.assert_not_called()
        self.assertEqual(info["provider"],"macos")
        self.assertEqual(info["requested"],"macos")
        self.assertFalse(info["fallback"])
    def test_network_timeout_triggers_fallback(self):
        with patch.object(tts,"request_minimax",side_effect=tts.TTSError("network_timeout")):
            info=tts.render("Hallo Test.",self.config,self.path)
        self.assertEqual(info["provider"],"macos")
        self.assertEqual(info["requested"],"minimax")
        self.assertTrue(info["fallback"])
        self.assertEqual(info["fallback_reason"],"network_timeout")
        self.assertGreater(info["audio_seconds"],0)
    def test_missing_key_triggers_fallback(self):
        with patch.object(tts,"read_key",side_effect=tts.TTSError("key_unavailable")):
            info=tts.render("Hallo Test.",self.config,self.path)
        self.assertTrue(info["fallback"])
        self.assertEqual(info["fallback_reason"],"key_unavailable")
    def test_corrupt_minimax_mp3_triggers_fallback(self):
        def corrupt(_text,_settings,target):
            target.write_bytes(b"not-an-mp3"*1000)
            return target.stat().st_size
        with patch.object(tts,"request_minimax",side_effect=corrupt):
            info=tts.render("Hallo Test.",self.config,self.path)
        self.assertEqual(info["provider"],"macos")
        self.assertTrue(info["fallback"])
        self.assertEqual(info["fallback_reason"],"audio_convert_failed")
    def test_config_rejects_unsafe_endpoint(self):
        self.config["minimax"]["endpoint"]="https://example.org/audio"
        with self.assertRaisesRegex(tts.TTSError,"endpoint_not_allowlisted"):
            tts.config_load_data(self.config)
    def test_speed_and_pitch_validation(self):
        with self.assertRaisesRegex(tts.TTSError,"config_speed_invalid"):
            tts.render("Text",self.config,self.path,speed=3.0)
        with self.assertRaisesRegex(tts.TTSError,"config_pitch_invalid"):
            tts.render("Text",self.config,self.path,pitch=20)
    def test_override_speed_and_voice(self):
        calls=[]
        def record(_text,settings,target):
            calls.append((settings["speed"],settings["voice_id"],settings["pitch"]))
            return self.mock_mp3(_text,settings,target)
        with patch.object(tts,"request_minimax",side_effect=record):
            tts.render("Test",self.config,self.path,speed=1.25,voice="German_PlayfulMan",pitch=-2)
        self.assertEqual(calls,[(1.25,"German_PlayfulMan",-2)])
    def test_api_request_payload_and_hex(self):
        data={"data":{"audio":self.valid_mp3.read_bytes().hex(),"status":2},
              "base_resp":{"status_code":0}}
        obj=FakeResponse(json.dumps(data).encode())
        observed=[]
        def fake_urlopen(req,timeout):
            observed.append((req,timeout))
            return obj
        with patch.object(tts,"read_key",return_value="synthetic-credential-not-secret"),\
             patch.object(tts.urllib.request,"urlopen",side_effect=fake_urlopen):
            file=pathlib.Path(self.temp.name)/"response.mp3"
            n=tts.request_minimax("Ein Test.",self.config["minimax"],file)
        self.assertGreater(n,1000)
        request,timeout=observed[0]
        self.assertEqual(request.full_url,"https://api.minimax.io/v1/t2a_v2")
        payload=json.loads(request.data)
        self.assertEqual(payload["model"],self.config["minimax"]["model"])
        self.assertEqual(payload["voice_setting"]["voice_id"],"German_FriendlyMan")
        self.assertEqual(payload["voice_setting"]["speed"],1.1)
        self.assertEqual(payload["voice_setting"]["vol"],1.0)
        self.assertEqual(payload["voice_setting"]["pitch"],0)
        self.assertEqual(payload["language_boost"],"German")
        self.assertEqual(payload["output_format"],"hex")
    def test_http_auth_error_causes_mac_fallback(self):
        def denied(req,timeout):
            error=urllib.error.HTTPError(req.full_url,401,"Unauthorized",{},None)
            error.close()
            raise error
        with patch.object(tts,"read_key",return_value="synthetic-credential-not-secret"),\
             patch.object(tts.urllib.request,"urlopen",side_effect=denied):
            info=tts.render("Hallo Test.",self.config,self.path)
        self.assertEqual(info["fallback_reason"],"http_401")
        self.assertEqual(info["provider"],"macos")
    def test_invalid_audio_header_causes_fallback(self):
        data={"data":{"audio":(b"invalid audio content"*500).hex(),"status":2},
              "base_resp":{"status_code":0}}
        with patch.object(tts,"read_key",return_value="synthetic-credential-not-secret"),\
             patch.object(tts.urllib.request,"urlopen",return_value=FakeResponse(json.dumps(data).encode())):
            info=tts.render("Hallo Test.",self.config,self.path)
        self.assertTrue(info["fallback"])
        self.assertEqual(info["fallback_reason"],"audio_invalid_mp3")
    def test_no_secret_in_provider_metadata(self):
        with patch.object(tts,"request_minimax",side_effect=tts.TTSError("http_401")):
            info=tts.render("Hallo Test.",self.config,self.path)
        self.assertNotIn("Authorization",json.dumps(info))
        self.assertNotIn("minimaxApiKey",json.dumps(info))
    def test_untrusted_config_missing_fails_without_call(self):
        with self.assertRaisesRegex(tts.TTSError,"config_unavailable"):
            tts.config_load(pathlib.Path(self.temp.name)/"does-not-exist.json")

class CLIOverrides(unittest.TestCase):
    @staticmethod
    def priority_module():
        import sys
        if str(ROOT) not in sys.path:
            sys.path.insert(0,str(ROOT))
        spec=importlib.util.spec_from_file_location("face_priority_test",ROOT/"facetime-priority.py")
        mod=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    def test_speak_flags_between_action_and_text(self):
        import sys
        p=self.priority_module()
        with patch.object(sys,"argv",["facetime-priority.py","speak","--tts-provider","macos","Hallo Test."]),\
             patch.object(p,"standalone_speak",return_value=0) as mocked:
            self.assertEqual(p.main(),0)
        self.assertEqual(mocked.call_args.args[0],"Hallo Test.")
        self.assertEqual(mocked.call_args.args[1].tts_provider,"macos")
    def test_speak_flags_after_text(self):
        import sys
        p=self.priority_module()
        with patch.object(sys,"argv",["facetime-priority.py","speak","Hallo Test.","--tts-speed","1.2"]),\
             patch.object(p,"standalone_speak",return_value=0) as mocked:
            self.assertEqual(p.main(),0)
        self.assertEqual(mocked.call_args.args[0],"Hallo Test.")
        self.assertEqual(mocked.call_args.args[1].tts_speed,1.2)

if __name__=="__main__":unittest.main()
