#!/usr/bin/env python3
"""Read-only, fail-closed FaceTime automation permission and capability preflight.

No calls, no microphone recording, no audio playback, and no TCC mutations.
Run as the *same user/process tree* that will perform the real call.
"""
import json
import pathlib
import subprocess
import sys

BASE = pathlib.Path(__file__).resolve().parent
GUI = BASE / "facetime-gui-session.py"
KVM = BASE / "nanokvm-call-ui.py"
def kvm_python_for(base):
    """Resolve the venv both in repository checkout and installed scripts directory."""
    in_repo = base / ".venv/bin/python"
    if in_repo.is_file():
        return in_repo
    return base / ".venv/bin/python"

KVM_PYTHON = kvm_python_for(BASE)
AX_EXPR = 'tell application "System Events" to tell process "NotificationCenter" to get count of windows'

def probe(run=None):
    if run is None:
        run=subprocess.run
    try:
        gui = run(["/usr/bin/python3", str(GUI)], capture_output=True,
                  text=True, timeout=8)
        mode = gui.stdout.strip()
        if gui.returncode or mode not in ("GUI_LOCKED", "GUI_UNLOCKED"):
            return dict(ok=False, code="GUI_STATE_UNKNOWN", mode="unknown",
                        message="Cannot determine the current macOS console lock state.")
        if mode == "GUI_UNLOCKED":
            # Read-only AX traversal, not a superficial TCC database check.
            # A denial (-25211) is specifically an Accessibility permission issue.
            ax = run(["/usr/bin/osascript", "-e", AX_EXPR], capture_output=True,
                     text=True, timeout=12)
            details = ax.stderr + "\n" + ax.stdout
            if ax.returncode:
                if "-25211" in details or "keine Berechtigung für den Hilfszugriff" in details or "not allowed assistive access" in details.lower():
                    return dict(ok=False, code="ACCESSIBILITY_PERMISSION_DENIED",
                                mode=mode, message="macOS Accessibility permission denied for the invoking automation process. Allow that process under System Settings > Privacy & Security > Accessibility and restart the affected agent if needed.")
                return dict(ok=False, code="ACCESSIBILITY_CHECK_FAILED", mode=mode,
                            message="Cannot inspect NotificationCenter through System Events; verify macOS Accessibility and Automation permissions.")
            return dict(ok=True, code="PERMISSIONS_OK", mode=mode,
                        message="System Events can inspect NotificationCenter accessibility elements.")
        # Locked: AX is not required. Check that the independently authorised
        # NanoKVM inspection path is actually accessible, not just installed.
        if not KVM_PYTHON.is_file() or not KVM.is_file():
            return dict(ok=False, code="NANOKVM_UNAVAILABLE", mode=mode,
                        message="Locked-screen NanoKVM client or Python environment missing.")
        kvm = run([str(KVM_PYTHON), str(KVM), "inspect"], capture_output=True,
                  text=True, timeout=25)
        if kvm.returncode or "KVM_UI_RESULT " not in kvm.stdout:
            return dict(ok=False, code="NANOKVM_ACCESS_DENIED", mode=mode,
                        message="Cannot inspect NanoKVM screen; verify Tailscale, NanoKVM access and credentials.")
        return dict(ok=True, code="PERMISSIONS_OK", mode=mode,
                    message="NanoKVM screen inspection is authorised and reachable. Locked-screen checks cannot verify microphone or all Python TCC permissions; unlock and resolve any pending permission prompts before live acceptance.", audio_permissions_verified=False)
    except subprocess.TimeoutExpired:
        return dict(ok=False, code="PERMISSION_CHECK_TIMEOUT", mode="unknown",
                    message="FaceTime automation permission check timed out.")
    except (OSError, ValueError):
        return dict(ok=False, code="PERMISSION_CHECK_UNAVAILABLE", mode="unknown",
                    message="Cannot execute macOS permission check.")

if __name__ == "__main__":
    result = probe()
    print(json.dumps(result, sort_keys=True), flush=True)
    if not result["ok"]:
        # Plain-text stderr survives controller subprocess error handling and
        # yields a stable MCP error code plus actionable user-facing guidance.
        print(f'{result["code"]}: {result["message"]}', file=sys.stderr, flush=True)
    sys.exit(0 if result["ok"] else 75)
