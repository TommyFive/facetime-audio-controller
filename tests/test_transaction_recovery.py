"""Concurrency and crash recovery tests (no actual FaceTime or HID clicks)."""
import importlib.util
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import facetime_txn as txn

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,str(ROOT/path))
    value=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value
ui=module("test_face_ui","nanokvm-call-ui.py")
prio=module("test_face_priority","facetime-priority.py")

class IsolatedJournal(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base=pathlib.Path(self.temp.name)
        changes={
            "ROOT":base,"CALL_LOCK":base/"call.lock","UI_LOCK":base/"ui.lock",
            "JOURNAL_LOCK":base/"journal.lock","JOURNAL":base/"journal.json"}
        patcher=patch.multiple(txn,**changes)
        patcher.start()
        self.addCleanup(patcher.stop)
    def test_new_run_and_durable_history(self):
        self.assertEqual(txn.snapshot()["stage"],"IDLE")
        one,previous=txn.start()
        txn.update(one["run_id"],"RECOVERY_REQUIRED")
        two,previous=txn.start()
        self.assertEqual(previous["stage"],"RECOVERY_REQUIRED")
        self.assertEqual(two["previous_run_id"],one["run_id"])
        self.assertTrue(txn.needs_recovery(previous))
    def test_nonblocking_call_lock(self):
        with txn.lockfile(txn.CALL_LOCK):
            with self.assertRaisesRegex(RuntimeError,"LOCK_BUSY"):
                with txn.lockfile(txn.CALL_LOCK):pass
        with txn.lockfile(txn.CALL_LOCK):
            pass
    def test_priority_hangup_can_interrupt_during_call_lock(self):
        with txn.lockfile(txn.CALL_LOCK):
            one,_=txn.start()
            txn.update(one["run_id"],"PLAYING")
            result=txn.interrupt("hangup")
            self.assertTrue(result["active"])
            with self.assertRaises(txn.Interrupted):
                txn.check(one["run_id"])
            # Independent UI mutex is usable even while call mutex held.
            with txn.action_locked(timeout=.2):pass
    def test_pending_cancel_interrupts_confirmation(self):
        one,_=txn.start()
        txn.update(one["run_id"],"CONFIRMING")
        self.assertTrue(txn.interrupt("cancel-pending")["active"])
        with self.assertRaises(txn.Interrupted):
            txn.check(one["run_id"])
    def test_cancel_does_not_end_active_speech(self):
        one,_=txn.start()
        txn.update(one["run_id"],"PLAYING")
        result=txn.interrupt("cancel-pending")
        self.assertTrue(result.get("refused"))
        txn.check(one["run_id"])
    def test_process_crash_releases_file_lock(self):
        code=("import os,fcntl,sys;f=os.open(sys.argv[1],os.O_CREAT|os.O_RDWR,0o600);"
              "fcntl.flock(f,fcntl.LOCK_EX);os._exit(0)")
        subprocess.run([sys.executable,"-c",code,str(txn.CALL_LOCK)],check=True,timeout=8)
        with txn.lockfile(txn.CALL_LOCK): pass
    def test_emergency_bypasses_call_lock(self):
        one,_=txn.start()
        txn.update(one["run_id"],"PLAYING")
        with txn.lockfile(txn.CALL_LOCK),\
             patch.object(prio,"locked",return_value=True),\
             patch.object(prio,"invoke",return_value=0) as action,\
             patch.object(prio.time,"sleep",return_value=None):
            self.assertEqual(prio.priority_action("hangup",8),0)
            self.assertEqual(action.call_count,2)
        self.assertTrue(txn.snapshot()["interrupt"])

class RecoveryCardSafety(unittest.TestCase):
    def state(self,kind,n=0,verified=False):
        buttons=[{"x":.95,"y":.09+i*.13,
                  "center_px":[1825,105+i*141]} for i in range(n)]
        return {"status":kind,"count":n,"badge_count":n,
                "all_pending_verified":verified,"red_count":0,
                "buttons":buttons,"width":1920,"height":1080}
    def test_duplicate_group_dismissed_with_one_gray_click(self):
        group=self.state("MULTIPLE",3,True)
        empty=self.state("NONE")
        it=iter([group,group,group,empty])
        clicks=[]
        with patch.object(ui,"capture",side_effect=lambda *args:next(it)),\
             patch.object(ui,"gray_cancel_color",return_value=(.95,.44)),\
             patch.object(ui,"click_once",side_effect=lambda *args:clicks.append(args)),\
             patch.object(ui.time,"sleep",return_value=None):
            self.assertTrue(ui.clear_pending_cards(None,None,"/tmp"))
        self.assertEqual(len(clicks),1)
        self.assertIn("RECOVERY_CANCEL",clicks[0])
    def test_ambiguous_group_never_clicked(self):
        group=self.state("MULTIPLE",2,False)
        with patch.object(ui,"capture",return_value=group),\
             patch.object(ui,"click_once") as click:
            with self.assertRaisesRegex(RuntimeError,"RECOVERY_REFUSED"):
                ui.clear_pending_cards(None,None,"/tmp")
            click.assert_not_called()
    def test_active_call_is_not_dismissed_as_pending(self):
        active=self.state("ACTIVE")
        with patch.object(ui,"capture",return_value=active),\
             patch.object(ui,"click_once") as click:
            with self.assertRaisesRegex(RuntimeError,"RECOVERY_REFUSED"):
                ui.clear_pending_cards(None,None,"/tmp")
            click.assert_not_called()

if __name__=="__main__":unittest.main()
