"""Safety tests for lockscreen hangup and confirmation cancellation; no real HID."""
import importlib.util
import pathlib
import unittest
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("nanokvm_call_ui_tests",ROOT/"nanokvm-call-ui.py")
ui=importlib.util.module_from_spec(spec);spec.loader.exec_module(ui)
class FakeBridge:
    def __init__(self):self.clicks=[]
    def click(self,x,y):self.clicks.append((x,y));return {"ok":True}
def make(kind,button=(.963,.179)):
    return {
        "status":kind,"count":1 if kind=="SINGLE" else 0,
        "target_verified":True,"held_verified":kind=="HELD",
        "badge_count":1 if kind!="NONE" else 0,
        "red_count":1 if kind=="ACTIVE" else 0,
        "badges":[{"center_px":[1444,140]}] if kind!="NONE" else [],
        "red_buttons":[{"x":button[0],"y":button[1]}] if kind=="ACTIVE" else [],
        "buttons":[{"x":.9513,"y":.1023,"center_px":[1826,110]}] if kind=="SINGLE" else [],
        "width":1920,"height":1080
    }
class HangupPolicy(unittest.TestCase):
    def drive(self,frames,mode="hangup",expect=None):
        device=FakeBridge()
        it=iter(frames)
        with patch.object(ui,"capture",side_effect=lambda *args:next(it)),\
             patch.object(ui.time,"sleep",return_value=None):
            if expect:
                with self.assertRaisesRegex(RuntimeError,expect):
                    getattr(ui,mode)(device,None,"/tmp")
            else:
                self.assertTrue(getattr(ui,mode)(device,None,"/tmp"))
        return device.clicks
    def test_active_hangup_one_click(self):
        self.assertEqual(len(self.drive([make("ACTIVE")]*3+[make("NONE")])),1)
    def test_held_resume_then_hangup_two_distinct_clicks(self):
        clicks=self.drive([make("HELD")]*2+[make("ACTIVE")]*3+[make("NONE")])
        self.assertEqual(len(clicks),2)
        self.assertNotEqual(clicks[0],clicks[1])
    def test_multiple_cards_never_clicked(self):
        self.assertEqual(self.drive([make("MULTIPLE")],expect="HANGUP_REFUSED_STATE"),[])
    def test_unknown_call_never_clicked(self):
        self.assertEqual(self.drive([make("ACTIVE_OR_HELD")],expect="HANGUP_REFUSED_STATE"),[])
    def test_wrong_target_never_clicked(self):
        f=make("ACTIVE");f["target_verified"]=False
        self.assertEqual(self.drive([f],expect="HANGUP_REFUSED_STATE"),[])
    def test_red_button_moved_never_clicked(self):
        self.assertEqual(self.drive([make("ACTIVE"),make("ACTIVE",(.91,.179))],
                                    expect="HANGUP_RED_BUTTON_NOT_STABLE"),[])
    def test_cancel_unique_pending_one_click(self):
        dev=FakeBridge()
        frame=[make("SINGLE")]*3+[make("NONE")]
        itr=iter(frame)
        with patch.object(ui,"capture",side_effect=lambda *args:next(itr)),\
             patch.object(ui,"gray_cancel_color",return_value=(.9513,.145)),\
             patch.object(ui.time,"sleep",return_value=None):
            self.assertTrue(ui.cancel_pending(dev,None,"/tmp"))
        self.assertEqual(len(dev.clicks),1)
    def test_cancel_ambiguous_no_click(self):
        self.assertEqual(self.drive([make("MULTIPLE")],mode="cancel_pending",
                                    expect="CANCEL_REFUSED"),[])
    def test_confirmation_timeout_invokes_cancel_without_green_click(self):
        device=FakeBridge()
        # The configured deadline has already elapsed when checking the loop.
        with patch.object(ui.time,"monotonic",side_effect=[100.0,200.0]),\
             patch.object(ui,"cancel_pending",return_value=True) as cancel:
            with self.assertRaisesRegex(RuntimeError,"CONFIRM_TIMEOUT"):
                ui.confirm(device,None,"/tmp",deadline_s=.1,
                           fast_return=True,cancel_on_timeout=True)
        cancel.assert_called_once()
        self.assertEqual(device.clicks,[])
if __name__=="__main__":unittest.main()
