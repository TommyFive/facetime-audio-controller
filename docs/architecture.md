# Controller architecture

The repository ships a local CLI engine and a thin Python MCP stdio adapter. The legacy shell CLI remains independent of MCP.

## Outgoing state machine

`STARTING -> RECOVERING -> PREFLIGHT -> DIAL_REQUESTED -> CONFIRMING -> WAITING_ANSWER -> PLAYING -> HANGING_UP -> DONE`.

`INTERRUPTED` and `RECOVERY_REQUIRED` are possible terminal/recovery outcomes. The journal records an intent **before** opening the FaceTime URL, because an external GUI action cannot be transactionally rolled back.

## Concurrency

The outgoing call uses a kernel-managed nonblocking advisory lock. A separate UI lock protects screenshot/verify/click sequences. Priority hangup/cancel uses an independent lock and interrupts a running controller without waiting for the outgoing lock. The journal is written atomically and survives process crashes; never delete lock files to force recovery.

## FaceTime UI paths

- Unlocked macOS desktop: NotificationCenter Accessibility controls and target identity verification.
- Locked desktop: optional NanoKVM screenshot, locally compiled Vision OCR, target/button geometry and stabilization verification.

At most a bounded number of verified gray cancel clicks are used during cleanup; no green confirmation is guessed from stacking order. The active/held/unknown UI is not arbitrarily dismissed.

Speech is rendered before dialing. FFmpeg plays through Loopback only after a host-observed call connection. A remote disconnect stops playback and triggers guarded cleanup. Full local playback and verified hangup are necessary for controller-observed success, but do not prove remote handset perception.

## External dependencies and limits

FaceTime/NotificationCenter UI, Loopback/CoreAudio, the optional MiniMax API, optional NanoKVM MCP, and optional OpenClaw each have independent failure modes. The implementation is fail-closed on uncertain identity, disconnected audio, stale UI or inaccessible external control paths.
