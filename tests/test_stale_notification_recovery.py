"""Offline coverage for bounded, fail-closed notification recovery."""
import importlib.util
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location("stale_ui",ROOT/"nanokvm-call-ui.py")
ui=importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)

def card(**changes):
    state={"status":"SINGLE","count":1,"badge_count":1,"red_count":0,
           "target_verified":True,"all_pending_verified":True,
           "buttons":[{"x":.95,"y":.10,"center_px":[1824,108]}]}
    state.update(changes)
    return state

class Recovery(unittest.TestCase):
    def test_unchanged_verified_card_is_only_escalation_candidate(self):
        with patch.object(ui,"capture",return_value=card()), patch.object(ui,"gray_cancel_color",return_value=(.95,.14)), patch.object(ui,"click_once") as click, patch.object(ui.time,"sleep"):
            with self.assertRaises(ui.StalePendingCard):
                ui.clear_pending_cards(None,None,"/tmp")
            click.assert_called_once()

    def test_changed_card_not_escalated(self):
        moved=card(buttons=[{"x":.90,"y":.10,"center_px":[1728,108]}])
        with patch.object(ui,"capture",side_effect=[card(),card(),card(),moved]), patch.object(ui,"gray_cancel_color",return_value=(.95,.14)), patch.object(ui,"click_once"), patch.object(ui.time,"sleep"):
            with self.assertRaises(RuntimeError) as raised:
                ui.clear_pending_cards(None,None,"/tmp")
            self.assertNotIsInstance(raised.exception,ui.StalePendingCard)

    def test_recover_dispatches_once(self):
        with patch.object(ui,"capture",return_value=card()), patch.object(ui,"clear_pending_cards",side_effect=ui.StalePendingCard(card())), patch.object(ui,"reset_stale_notification") as reset:
            self.assertTrue(ui.recover(None,None,"/tmp"))
            reset.assert_called_once()

    def test_generic_recovery_error_never_escalates(self):
        with patch.object(ui,"capture",return_value=card()), patch.object(ui,"clear_pending_cards",side_effect=RuntimeError("unknown")), patch.object(ui,"reset_stale_notification") as reset:
            with self.assertRaises(RuntimeError):
                ui.recover(None,None,"/tmp")
            reset.assert_not_called()

    def test_owner_requires_eligible_prior_timeout_and_no_new_dial(self):
        valid={"stage":"RECOVERING","previous_stage":"RECOVERY_REQUIRED","notification_reset_eligible":True}
        with patch.object(ui,"RUN_ID","test"), patch.object(ui.os,"getuid",return_value=501), patch.object(ui.txn,"check",return_value=valid):
            ui.require_recovery_owner()
        for changes in [{"stage":"PLAYING"},{"previous_stage":"DONE"},{"notification_reset_eligible":False},{"url_may_have_been_sent":True}]:
            with self.subTest(changes=changes), patch.object(ui,"RUN_ID","test"), patch.object(ui.os,"getuid",return_value=501), patch.object(ui.txn,"check",return_value={**valid,**changes}):
                with self.assertRaises(RuntimeError):
                    ui.require_recovery_owner()

    @unittest.skipUnless(sys.platform=="darwin","native macOS SDK required")
    def test_swift_probe_typechecks(self):
        with tempfile.TemporaryDirectory() as folder:
            source=pathlib.Path(folder)/"CallStateProbe.swift"
            source.write_text(ui.CALL_STATE_PROBE)
            subprocess.run(["/usr/bin/swiftc","-typecheck",str(source)],
                           check=True,capture_output=True,text=True,timeout=45)

    def test_native_probe_fails_closed(self):
        for stdout,stderr,rc in [("BUSY","",0),("","",0),("IDLE","warning",0),("IDLE","",1)]:
            with self.subTest(stdout=stdout,stderr=stderr,rc=rc), patch.object(ui.sys,"platform","darwin"), patch.object(ui.subprocess,"run",return_value=subprocess.CompletedProcess([],rc,stdout,stderr)):
                with self.assertRaises(RuntimeError):
                    ui.require_idle_call_center()
        with patch.object(ui.sys,"platform","darwin"), patch.object(ui.subprocess,"run",return_value=subprocess.CompletedProcess([],0,"IDLE\n","")):
            ui.require_idle_call_center()

    def test_native_timeout_fails_closed(self):
        with patch.object(ui.sys,"platform","darwin"), patch.object(ui.subprocess,"run",side_effect=subprocess.TimeoutExpired("swift",12)):
            with self.assertRaises(RuntimeError):
                ui.require_idle_call_center()

    def test_busy_or_changed_card_prevents_process_signals(self):
        for frames,probe in [([card(),card()],RuntimeError("busy")),([card(),card(status="ACTIVE")],None)]:
            with patch.object(ui,"require_recovery_owner"), patch.object(ui,"require_idle_call_center",side_effect=probe), patch.object(ui,"capture",side_effect=frames), patch.object(ui.time,"sleep"), patch.object(ui.subprocess,"run") as run:
                with self.assertRaises(RuntimeError):
                    ui.reset_stale_notification(None,None,"/tmp",card())
                run.assert_not_called()

    def test_exact_same_user_process_reset_and_postchecks(self):
        with patch.object(ui,"require_recovery_owner"), patch.object(ui,"require_idle_call_center") as idle, patch.object(ui,"capture",return_value=card()), patch.object(ui.time,"sleep"), patch.object(ui.os,"getuid",return_value=501), patch.object(ui.subprocess,"run",return_value=subprocess.CompletedProcess([],0,"","")) as run, patch.object(ui,"stable_quiescence") as quiet:
            self.assertTrue(ui.reset_stale_notification(None,None,"/tmp",card()))
            self.assertEqual(idle.call_count,3)
            quiet.assert_called_once()
            self.assertEqual([c.args[0] for c in run.call_args_list],
                [["/usr/bin/pkill","-TERM","-x","-u","501",n] for n in ui.NOTIFICATION_PROCESSES])

    def test_postcheck_failure_does_not_allow_recovery(self):
        with patch.object(ui,"require_recovery_owner"), patch.object(ui,"require_idle_call_center"), patch.object(ui,"capture",return_value=card()), patch.object(ui.time,"sleep"), patch.object(ui.subprocess,"run",return_value=subprocess.CompletedProcess([],0,"","")), patch.object(ui,"stable_quiescence",side_effect=RuntimeError("not quiet")):
            with self.assertRaises(RuntimeError):
                ui.reset_stale_notification(None,None,"/tmp",card())

if __name__=="__main__":
    unittest.main()
