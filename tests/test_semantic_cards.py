"""Offline mixed-notification regression tests."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from test_nanokvm_controller import det,ui,sample
from PIL import ImageDraw

def scan(kind,exact=True):
    return dict(verified=True,exact_target=exact,pending=kind=="PENDING",
                unavailable=kind=="UNAVAILABLE",active_text=kind=="ACTIVE",
                held=False,resume=False)

class SemanticTests(unittest.TestCase):
    def classify(self,kinds,exact=True):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"test.jpg";sample(len(kinds)).save(p,quality=96)
            with patch.object(det,"card_ocr",side_effect=[scan(k,exact) for k in kinds]):
                return det.inspect(str(p),require_ocr=True)
    def test_pending_above_unavailable(self):
        s=self.classify(["PENDING","UNAVAILABLE"])
        self.assertEqual(s["status"],"MIXED_PENDING")
        self.assertEqual(s["pending_buttons"],[s["buttons"][0]])
    def test_pending_below_unavailable(self):
        s=self.classify(["UNAVAILABLE","PENDING"])
        self.assertEqual(s["status"],"MIXED_PENDING")
        self.assertEqual(s["pending_buttons"],[s["buttons"][1]])
    def test_two_pending_refused(self):
        self.assertEqual(self.classify(["PENDING","PENDING"])["status"],"MULTIPLE")
    def test_fuzzy_only_refused(self):
        self.assertEqual(self.classify(["PENDING","UNAVAILABLE"],False)["status"],"MULTIPLE")
    def test_unknown_label_refused(self):
        self.assertEqual(self.classify(["PENDING","UNKNOWN"])["status"],"MULTIPLE")
    def test_stale_only(self):
        self.assertEqual(self.classify(["UNAVAILABLE","UNAVAILABLE"])["status"],"STALE_ONLY")
    def test_three_frames_click_only_pending(self):
        for kinds in (["PENDING","UNAVAILABLE"],["UNAVAILABLE","PENDING"]):
            s=self.classify(kinds)
            b=s["pending_buttons"][0]
            with patch.object(ui,"capture",return_value=s),patch.object(ui.time,"sleep"),patch.object(ui,"click_once") as click:
                self.assertTrue(ui.confirm(None,None,"/tmp"))
                click.assert_called_once_with(None,b["x"],b["y"],"CONFIRM")
    def test_two_pending_never_click(self):
        s=self.classify(["PENDING","PENDING"])
        with patch.object(ui,"capture",return_value=s),patch.object(ui,"click_once") as click:
            with self.assertRaisesRegex(RuntimeError,"MULTIPLE"): ui.confirm(None,None,"/tmp")
            click.assert_not_called()
    def test_mixed_active_hangup_only_red(self):
        s=dict(status="MIXED_ACTIVE",target_verified=True,active_buttons=[dict(x=.96,y=.18)])
        with patch.object(ui,"capture",side_effect=[s,s,s,dict(status="UNAVAILABLE")]),patch.object(ui.time,"sleep"),patch.object(ui,"require_idle_call_center") as idle,patch.object(ui,"click_once") as click:
            self.assertTrue(ui.hangup(None,None,"/tmp"))
            click.assert_called_once_with(None,.96,.18,"HANGUP")
            idle.assert_called_once()
