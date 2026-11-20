"""Synthetic safety tests: no network, real calls, keys or mouse events."""
import importlib.util
import pathlib
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image, ImageDraw

ROOT=pathlib.Path(__file__).resolve().parents[1]
def load(name,file):
    spec=importlib.util.spec_from_file_location(name,ROOT/file)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj
det=load("detector_test","nanokvm-popup-detector.py")
ui=load("controller_test","nanokvm-call-ui.py")

def sample(cards=0,held=False,extra_held=False):
    img=Image.new("RGB",(1920,1080),(28,34,124));d=ImageDraw.Draw(img)
    for i in range(cards):
        y=75+i*141
        d.rounded_rectangle((1380,y,1896,y+114),radius=23,fill=(46,38,109))
        d.rounded_rectangle((1776,y+18,1877,y+53),radius=17,fill=(65,245,103))
        d.rounded_rectangle((1776,y+65,1877,y+99),radius=16,fill=(224,228,244))
        d.rounded_rectangle((1434,y+67,1454,y+87),radius=4,fill=(56,235,105))
    if held or extra_held:
        y=75+cards*141 if extra_held else 75
        d.rounded_rectangle((1380,y,1896,y+95),radius=23,fill=(46,38,109))
        d.rounded_rectangle((1434,y+57,1454,y+77),radius=4,fill=(56,235,105))
    return img

class ImageDetection(unittest.TestCase):
    def inspect(self,*args):
        with tempfile.TemporaryDirectory() as tmp:
            file=pathlib.Path(tmp)/"sample.jpg"
            sample(*args).save(file,quality=95)
            return det.inspect(str(file))
    def test_empty(self): self.assertEqual(self.inspect()["status"],"NONE")
    def test_single(self):
        result=self.inspect(1)
        self.assertEqual(result["status"],"SINGLE")
        self.assertEqual(result["count"],1)
    def test_two(self): self.assertEqual(self.inspect(2)["status"],"MULTIPLE")
    def test_three(self): self.assertEqual(self.inspect(3)["status"],"MULTIPLE")
    def test_held(self): self.assertEqual(self.inspect(0,True)["status"],"ACTIVE_OR_HELD")
    def test_active_red_button(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=pathlib.Path(tmp)/"active.jpg"
            image=sample(0,True)
            draw=ImageDraw.Draw(image)
            draw.ellipse((1823,167,1877,220),fill=(224,11,35))
            image.save(file,quality=96)
            state=det.inspect(str(file))
        self.assertEqual(state["status"],"ACTIVE")
        self.assertEqual(state["red_count"],1)
        self.assertAlmostEqual(state["red_buttons"][0]["x"],.963,places=2)
    def test_pending_plus_held(self):
        self.assertEqual(self.inspect(1,False,True)["status"],"AMBIGUOUS_EXISTING_CALL")

class ClickPolicy(unittest.TestCase):
    def state(self,kind,x=.9513,y=.1023):
        return {"status":kind,"count":1 if kind=="SINGLE" else 2 if kind=="MULTIPLE" else 0,
                "buttons":[{"x":x,"y":y}] if kind=="SINGLE" else [],
                "target_verified":True,
                "width":1920,"height":1080}
    def run_case(self,frames,pattern=None):
        class FakeBridge:
            def __init__(self):self.clicks=[]
            def click(self,x,y):self.clicks.append((x,y));return {"isError":False}
        bridge=FakeBridge()
        it=iter(frames)
        with patch.object(ui,"capture",side_effect=lambda *args: next(it)),\
             patch.object(ui.time,"sleep",return_value=None):
            if pattern:
                with self.assertRaisesRegex(RuntimeError,pattern):
                    ui.confirm(bridge,None,"/tmp",deadline_s=3,fast_return=True)
            else:
                self.assertTrue(ui.confirm(bridge,None,"/tmp",deadline_s=3,fast_return=True))
        return bridge.clicks
    def test_multiple_no_click(self):
        self.assertEqual(self.run_case([self.state("MULTIPLE")],"MULTIPLE"),[])
    def test_held_no_click(self):
        self.assertEqual(self.run_case([self.state("ACTIVE_OR_HELD")],"CONFIRM_REFUSED"),[])
    def test_stable_one_click(self):
        self.assertEqual(len(self.run_case([self.state("SINGLE")]*3)),1)
    def test_movement_requires_fresh_stable_frames(self):
        # A moving lockscreen card must not be clicked at its old location.
        # It may be clicked once after three fresh target-verified frames settle.
        moving=self.state("SINGLE",x=.91)
        clicks=self.run_case([self.state("SINGLE"),moving,moving,moving])
        self.assertEqual(clicks,[(.91,.1023)])
    def test_third_frame_multiple_refuses(self):
        self.assertEqual(self.run_case([self.state("SINGLE")]*2+[self.state("MULTIPLE")],"CONFIRM_PRECLICK_CHANGED"),[])

if __name__=="__main__":unittest.main()
