"""Privacy gate synthetic detection, no live identifiers in the repository."""
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("privacy_gate",ROOT/"tools/privacy-check.py")
gate=importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

class PrivacyGateTests(unittest.TestCase):
    def test_example_identity_is_safe(self):
        self.assertFalse(gate.scan("example",'recipient="friend@example.invalid"'))

    def test_non_example_address_is_detected(self):
        value="person"+"@"+"domain.test"
        self.assertTrue(gate.scan("sample",value))

    def test_bearer_token_is_detected(self):
        value="Bearer "+"A"*40
        self.assertTrue(gate.scan("sample",value))

    def test_private_key_pem_is_detected(self):
        value="-----BEGIN "+"PRIVATE KEY-----"
        self.assertTrue(gate.scan("sample",value))

    def test_github_pat_is_detected(self):
        value="gh"+"p_"+"A"*40
        self.assertTrue(gate.scan("sample",value))

    def test_macos_home_path_is_detected(self):
        value="/Users/"+ "someone/config"
        self.assertTrue(gate.scan("sample",value))
if __name__=="__main__":unittest.main()
