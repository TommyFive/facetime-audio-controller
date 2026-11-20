"""Theme and transient FaceTime card image tests. No real calls or HID."""
import importlib.util
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image,ImageDraw
root=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
def load(name,file):
    s=importlib.util.spec_from_file_location(name,root/file)
    x=importlib.util.module_from_spec(s);s.loader.exec_module(x);return x
det=load("face_vision_theme","nanokvm-popup-detector.py")
ui=load("face_ui_theme","nanokvm-call-ui.py")
def image_sample(theme="dark",pending=True):
    img=Image.new("RGB",(1920,1080),(20,25,90))
    d=ImageDraw.Draw(img)
    d.rounded_rectangle((1380,75,1896,190),radius=23,fill=(42,42,119))
    d.rounded_rectangle((1434,142,1455,162),radius=4,fill=(56,230,104))
    if pending:
        d.rounded_rectangle((1776,93,1878,128),radius=17,fill=(56,240,109))
        col=(70,92,169) if theme=="dark" else (90,84,164)
        glyph=(4,0,0) if theme=="dark" else (247,247,254)
        d.rounded_rectangle((1776,139,1878,173),radius=17,fill=col)
        d.line((1821,151,1831,161),fill=glyph,width=3)
        d.line((1821,161,1831,151),fill=glyph,width=3)
    return img
class ThemeCases(unittest.TestCase):
    def classify(self,im,ocr=False):
        with tempfile.TemporaryDirectory() as folder:
            p=pathlib.Path(folder)/"frame.jpg"
            im.save(p,quality=96)
            if ocr:
                value={"verified":True,"pending":True,"held":False,
                       "resume":False,"active_text":False}
                with patch.object(det,"card_ocr",return_value=value):
                    return det.inspect(str(p),require_ocr=True)
            return det.inspect(str(p))
    def test_dark_gray_x_and_green_button(self):
        state=self.classify(image_sample("dark"))
        self.assertEqual(state["status"],"SINGLE")
    def test_light_gray_x_and_green_button(self):
        state=self.classify(image_sample("light"))
        self.assertEqual(state["status"],"SINGLE")
    def test_dark_cancel_click_color_confirmation(self):
        with tempfile.TemporaryDirectory() as folder:
            p=pathlib.Path(folder)/"frame.jpg"
            image_sample("dark").save(p,quality=96)
            x,y=ui.gray_cancel_color(p,{"center_px":[1827,111]})
            self.assertAlmostEqual(x,1827/1920,places=3)
            self.assertAlmostEqual(y,157/1080,places=3)
    def test_light_cancel_click_color_confirmation(self):
        with tempfile.TemporaryDirectory() as folder:
            p=pathlib.Path(folder)/"frame.jpg"
            image_sample("light").save(p,quality=96)
            x,y=ui.gray_cancel_color(p,{"center_px":[1827,111]})
            self.assertAlmostEqual(y,157/1080,places=3)
    def test_pending_text_before_green_control(self):
        state=self.classify(image_sample("dark",pending=False),ocr=True)
        self.assertEqual(state["status"],"PENDING_RENDERING")
    def test_transient_pending_render_then_one_confirm(self):
        pending={"status":"PENDING_RENDERING"}
        single={"status":"SINGLE","target_verified":True,
                "buttons":[{"x":.9513,"y":.1023}]}
        frames=iter([pending,single,single,single])
        clicks=[]
        with patch.object(ui,"capture",side_effect=lambda *a:next(frames)),\
             patch.object(ui,"click_once",side_effect=lambda *a:clicks.append(a)),\
             patch.object(ui.time,"sleep",return_value=None):
            self.assertTrue(ui.confirm(None,None,"/tmp",deadline_s=5,fast_return=True))
        self.assertEqual(len(clicks),1)
    def test_recovery_waits_for_pending_rendering(self):
        frames=iter([{"status":"PENDING_RENDERING"},{"status":"SINGLE"}])
        with patch.object(ui,"capture",side_effect=lambda *a:next(frames)),\
             patch.object(ui,"clear_pending_cards",return_value=True) as clear,\
             patch.object(ui,"stable_quiescence",return_value=True),\
             patch.object(ui.time,"sleep",return_value=None):
            self.assertTrue(ui.recover(None,None,"/tmp"))
            clear.assert_called_once()
if __name__=="__main__":unittest.main()
