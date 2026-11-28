"""Offline regression tests for GUI transitions; no calls or UI actions."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location("gui_routing_fast",ROOT/"facetime-call-fast.py")
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
class RoutingTests(unittest.TestCase):
    def test_lock_during_playback(self):
        with patch.object(mod,"call_state",return_value="GUI_LOCKED"), patch.object(mod,"guarded") as ax, patch.object(mod,"kvm") as kvm:
            mod.verified_hangup("test",24,"GUI_UNLOCKED")
            ax.assert_not_called()
            kvm.assert_called_once()
    def test_unlock_during_playback(self):
        with patch.object(mod,"call_state",return_value="GUI_UNLOCKED"), patch.object(mod,"guarded") as ax, patch.object(mod,"kvm") as kvm:
            mod.verified_hangup("test",24,"GUI_LOCKED")
            ax.assert_called_once()
            kvm.assert_not_called()
    def test_lock_between_probe_and_ax(self):
        with patch.object(mod,"call_state",side_effect=["GUI_UNLOCKED","GUI_LOCKED"]), patch.object(mod,"guarded",side_effect=RuntimeError("AX locked")), patch.object(mod.txn,"check"), patch.object(mod,"kvm") as kvm:
            mod.verified_hangup("test",24,"GUI_UNLOCKED")
            kvm.assert_called_once()
    def test_ax_failure_while_unlocked_fails_closed(self):
        with patch.object(mod,"call_state",return_value="GUI_UNLOCKED"), patch.object(mod,"guarded",side_effect=RuntimeError("AX failed")), patch.object(mod.txn,"check"), patch.object(mod,"kvm") as kvm:
            with self.assertRaisesRegex(RuntimeError,"AX failed"):
                mod.verified_hangup("test",24,"GUI_UNLOCKED")
            kvm.assert_not_called()
    def test_priority_interrupt_never_falls_back(self):
        with patch.object(mod,"call_state",return_value="GUI_UNLOCKED"), patch.object(mod,"guarded",side_effect=mod.txn.Interrupted("priority")), patch.object(mod,"kvm") as kvm:
            with self.assertRaises(mod.txn.Interrupted):
                mod.verified_hangup("test",24,"GUI_UNLOCKED")
            kvm.assert_not_called()
