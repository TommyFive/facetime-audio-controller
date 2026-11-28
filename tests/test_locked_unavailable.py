"""Locked-screen FaceTime 'ist nicht verfügbar' safety tests. No real calls or clicks."""
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,ROOT/filename)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


det=load("unavailable_lockscreen_detector","nanokvm-popup-detector.py")
ui=load("unavailable_lockscreen_ui","nanokvm-call-ui.py")
fast=load("unavailable_lockscreen_fast","facetime-call-fast.py")
det.TARGET="test-recipient@example.invalid"
fast.TARGET="test-recipient@example.invalid"


def screenshot():
    img=Image.new("RGB",(1920,1080),(20,25,90))
    d=ImageDraw.Draw(img)
    d.rounded_rectangle((1380,75,1896,190),radius=23,fill=(42,42,119))
    d.rounded_rectangle((1434,142,1455,162),radius=4,fill=(56,230,104))
    d.rounded_rectangle((1776,93,1878,128),radius=17,fill=(56,240,109))
    d.rounded_rectangle((1776,139,1878,173),radius=17,fill=(70,92,169))
    d.line((1821,151,1831,161),fill=(247,247,254),width=3)
    d.line((1821,161,1831,151),fill=(247,247,254),width=3)
    return img


def classified_frame(x=.9513,y=.1023):
    return {"status":"UNAVAILABLE","count":1,"red_count":0,
            "badge_count":1,"buttons":[{"x":x,"y":y,"center_px":[round(x*1920),round(y*1080)]}],
            "target_verified":True,"unavailable_verified":True,"width":1920,"height":1080}


class DetectorTests(unittest.TestCase):
    def test_real_german_label_ocr_variants(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub=pathlib.Path(tmp)/"ocr"
            stub.write_text("stub")
            stub.chmod(0o700)
            for line in ("ist nicht verfügbar","ist nicht verfugbar","ist nicht verfuegbar"):
                with self.subTest(label=line),patch.object(det,"OCR_BINARY",stub),patch.object(
                        det.subprocess,"run",return_value=subprocess.CompletedProcess(
                            [],0,"test-recipient@example.invalid\n"+line+"\n","")):
                    ocr=det.card_ocr(screenshot(),152)
                    self.assertTrue(ocr["verified"])
                    self.assertTrue(ocr["unavailable"])
                    self.assertFalse(ocr["pending"])

    def test_available_text_never_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub=pathlib.Path(tmp)/"ocr"
            stub.write_text("stub")
            stub.chmod(0o700)
            with patch.object(det,"OCR_BINARY",stub),patch.object(
                    det.subprocess,"run",return_value=subprocess.CompletedProcess(
                        [],0,"test-recipient@example.invalid\nist verfügbar\n","")):
                self.assertFalse(det.card_ocr(screenshot(),152)["unavailable"])

    def classify(self,ocr):
        with tempfile.TemporaryDirectory() as tmp:
            img=pathlib.Path(tmp)/"screen.jpg"
            screenshot().save(img,quality=96)
            with patch.object(det,"card_ocr",return_value=ocr):
                return det.inspect(str(img),require_ocr=True)

    def test_single_exact_target_unavailable_is_recognized(self):
        frame=self.classify(dict(verified=True,pending=False,held=False,
                                 unavailable=True,resume=False,active_text=False))
        self.assertEqual(frame["status"],"UNAVAILABLE")
        self.assertTrue(frame["unavailable_verified"])
        self.assertEqual(frame["count"],1)

    def test_other_target_or_pending_call_cannot_be_dismissed(self):
        base=dict(verified=True,pending=False,held=False,
                  unavailable=True,resume=False,active_text=False)
        frame=self.classify({**base,"verified":False})
        self.assertNotEqual(frame["status"],"UNAVAILABLE")
        self.assertFalse(frame["unavailable_verified"])
        frame=self.classify({**base,"pending":True})
        self.assertNotEqual(frame["status"],"UNAVAILABLE")
        self.assertFalse(frame["unavailable_verified"])


class ClickSafetyTests(unittest.TestCase):
    def test_unique_unavailable_clicks_gray_x_once_then_two_empty_frames(self):
        class Bridge:
            def __init__(self):self.clicks=[]
            def click(self,x,y):
                self.clicks.append((x,y))
                return {"ok":True}
        bridge=Bridge()
        with patch.object(ui,"capture",side_effect=[
                classified_frame(),classified_frame(),classified_frame(),
                {"status":"NONE"},{"status":"NONE"}]),patch.object(
                ui,"gray_cancel_color",return_value=(.9513,.146)),patch.object(
                ui.time,"sleep",return_value=None):
            self.assertTrue(ui.dismiss_unavailable(bridge,None,"/tmp"))
        self.assertEqual(bridge.clicks,[(.9513,.146)])

    def test_expired_unavailable_card_requires_quiet_and_native_idle(self):
        with patch.object(ui,"capture",return_value={"status":"NONE"}), patch.object(ui,"stable_quiescence",return_value=True) as quiet, patch.object(ui,"require_idle_call_center") as idle, patch.object(ui,"click_once") as click:
            self.assertTrue(ui.dismiss_unavailable(None,None,"/tmp"))
            quiet.assert_called_once()
            idle.assert_called_once()
            click.assert_not_called()
    def test_expired_card_with_unverified_idle_fails_closed(self):
        with patch.object(ui,"capture",return_value={"status":"NONE"}), patch.object(ui,"stable_quiescence",return_value=True), patch.object(ui,"require_idle_call_center",side_effect=RuntimeError("BUSY")), patch.object(ui,"click_once") as click:
            with self.assertRaisesRegex(RuntimeError,"BUSY"):
                ui.dismiss_unavailable(None,None,"/tmp")
            click.assert_not_called()

    def test_ambiguous_target_never_clicked(self):
        class Bridge:
            def click(self,*args):raise AssertionError("No click permitted")
        for state in ({**classified_frame(),"target_verified":False},
                      {**classified_frame(),"status":"MULTIPLE"},
                      {**classified_frame(),"unavailable_verified":False}):
            with self.subTest(state=state["status"]),patch.object(
                    ui,"capture",return_value=state):
                with self.assertRaisesRegex(RuntimeError,"NOT_VERIFIED"):
                    ui.dismiss_unavailable(Bridge(),None,"/tmp")

    def test_unstable_coordinates_refuse_click(self):
        with patch.object(ui,"capture",side_effect=[
                classified_frame(),classified_frame(x=.91)]),patch.object(
                ui.time,"sleep",return_value=None):
            with self.assertRaisesRegex(RuntimeError,"NOT_STABLE"):
                ui.dismiss_unavailable(None,None,"/tmp")

    def test_failed_postclick_verification_never_retries(self):
        class Bridge:
            def __init__(self):self.clicks=[]
            def click(self,x,y):
                self.clicks.append((x,y))
                return {"ok":True}
        bridge=Bridge()
        with patch.object(ui,"capture",side_effect=[
                classified_frame(),classified_frame(),classified_frame(),
                classified_frame()]),patch.object(
                ui,"gray_cancel_color",return_value=(.9513,.146)),patch.object(
                ui.time,"sleep",return_value=None):
            with self.assertRaisesRegex(RuntimeError,"UNAVAILABLE_DISMISS_UNVERIFIED"):
                ui.dismiss_unavailable(bridge,None,"/tmp")
        self.assertEqual(len(bridge.clicks),1)

    def test_recovery_and_hangup_route_only_unavailable_to_guarded_dismissal(self):
        with patch.object(ui,"capture",return_value=classified_frame()),patch.object(
                ui,"dismiss_unavailable",return_value=True) as dismiss,patch.object(
                ui,"stable_quiescence",return_value=True):
            self.assertTrue(ui.recover(None,None,"/tmp"))
            self.assertTrue(ui.hangup(None,None,"/tmp"))
        self.assertEqual(dismiss.call_count,2)

    def test_confirmation_refuses_unavailable_without_redial(self):
        with patch.object(ui,"capture",return_value=classified_frame()):
            with self.assertRaisesRegex(RuntimeError,"CONFIRM_REFUSED_STATE=UNAVAILABLE"):
                ui.confirm(None,None,"/tmp",deadline_s=2)


class CallRunnerTests(unittest.TestCase):
    def test_locked_readonly_probe_requires_exact_verified_structure(self):
        frame=classified_frame()
        with patch.object(fast,"guarded",return_value=(
            "KVM_UI_RESULT "+json.dumps(frame),1.2)):
            self.assertTrue(fast.locked_unavailable_popup_state("fake-run"))
        frame["target_verified"]=False
        with patch.object(fast,"guarded",return_value=(
            "KVM_UI_RESULT "+json.dumps(frame),1.2)):
            self.assertFalse(fast.locked_unavailable_popup_state("fake-run"))

    def test_probe_failure_is_not_positive(self):
        with patch.object(fast,"guarded",side_effect=RuntimeError("NanoKVM down")):
            self.assertFalse(fast.locked_unavailable_popup_state("fake-run"))

    def test_locked_dismiss_uses_only_named_kvm_action(self):
        with patch.object(fast,"kvm") as kvm:
            fast.dismiss_locked_unavailable_popup("fake-run")
        self.assertEqual(kvm.call_args.args[0],["dismiss-unavailable"])


if __name__=="__main__":
    unittest.main()
