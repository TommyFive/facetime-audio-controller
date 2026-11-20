"""Linux-safe MiniMax model allowlist and API payload regression tests.

Does not require FFmpeg, macOS, audio devices, or a network API key.
"""
import importlib.util
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("facetime_tts_models", ROOT/"facetime-tts.py")
tts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tts)

class Response:
    status=200
    def __init__(self,raw):
        self.raw=raw
    def __enter__(self):
        return self
    def __exit__(self,*args):
        return False
    def read(self,_amount):
        return self.raw

class TTSModelTests(unittest.TestCase):
    def setUp(self):
        self.config=json.loads((ROOT/"tts-config.json").read_text())
        self.assertIn(self.config["minimax"]["model"],("speech-2.8-turbo","speech-2.8-hd"))

    def test_two_models_only(self):
        for name in ("speech-2.8-turbo","speech-2.8-hd"):
            with self.subTest(model=name):
                self.config["minimax"]["model"]=name
                self.assertEqual(tts.config_load_data(self.config)["minimax"]["model"],name)
        self.config["minimax"]["model"]="speech-unknown"
        with self.assertRaisesRegex(tts.TTSError,"config_minimax_model_invalid"):
            tts.config_load_data(self.config)

    def test_hd_effective_limit_cannot_exceed_provider_cap(self):
        self.config["minimax"]["model"]="speech-2.8-hd"
        self.config["minimax"]["max_characters_by_model"]["speech-2.8-hd"]=10000
        self.assertEqual(tts.max_text_characters(self.config,"minimax"),5000)
        self.config["minimax"]["model"]="speech-2.8-turbo"
        self.assertEqual(tts.max_text_characters(self.config,"minimax"),10000)

    def test_both_models_sent_in_api_payload(self):
        # A fake ID3 frame is sufficient to test the request contract,
        # without requiring FFmpeg or a live service.
        body=json.dumps({"base_resp":{"status_code":0},
                         "data":{"audio":(b"ID3"+b"0"*1500).hex(),"status":2}}).encode()
        for name in ("speech-2.8-turbo","speech-2.8-hd"):
            with self.subTest(model=name), tempfile.TemporaryDirectory() as folder:
                self.config["minimax"]["model"]=name
                seen=[]
                def fake_urlopen(req,timeout):
                    seen.append(json.loads(req.data.decode()))
                    return Response(body)
                with patch.object(tts,"read_key",return_value="synthetic-key"), \
                     patch.object(tts.urllib.request,"urlopen",side_effect=fake_urlopen):
                    tts.request_minimax("Hallo.",self.config["minimax"],
                                      pathlib.Path(folder)/"audio.mp3")
                self.assertEqual(seen[0]["model"],name)
                self.assertEqual(seen[0]["voice_setting"]["voice_id"],"German_FriendlyMan")
                self.assertEqual(seen[0]["voice_setting"]["speed"],1.1)
                self.assertEqual(seen[0]["voice_setting"]["pitch"],0)
                self.assertEqual(seen[0]["language_boost"],"German")

if __name__=="__main__":
    unittest.main()
