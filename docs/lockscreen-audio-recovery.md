# Lockscreen notification and audio recovery

## Observed symptoms

- A new outgoing request may surface earlier pending or unavailable notification cards alongside the new card.
- A session can become locked between AX dialing and hangup. AX cannot perform the final UI action in that state.
- A native macOS media service can report audio start/stop timeouts and then terminate with a segmentation fault. CallServices may report a media-server crash (reason 13). The direct cause is not proven.
- A successful read-only NanoKVM permission probe does not establish that all Python, microphone, or GUI permissions have been granted.

## Safe response

1. Inspect the journal, GUI state and native call status before taking action. Never dial repeatedly or click by position alone.
2. If multiple genuine pending cards or unknown cards are present, fail closed. A single pending card can coexist with separately verified unavailable cards; confirm only the pending card on stable screenshots.
3. If necessary, unlock the Mac and review pending macOS privacy prompts for the actual invoking Python executable and relevant applications in System Settings > Privacy & Security. Grant only necessary permissions. Do not disable the lock screen or bypass TCC.
4. Check the configured virtual audio device and the system default input; examine recent AVConference and CoreAudio errors and local crash reports. Do not publish raw reports.
5. Only when native idle is verified, consider a targeted restart of stale same-user notification helpers as an operator action. Do not automate broad process termination. Restore an idle journal through the supported recovery command.
6. Perform a consented live test: connection event, complete playback, verified hangup, and recipient confirmation. An offline test or successful exit alone does not establish audible speech.

## Acceptance and limitations

A private deployment reproduced multiple pending cards, and one live attempt failed with a native media-service crash after confirmation. A later locked-screen call succeeded after the operator resolved a Python permission prompt. This is evidence of recovery, not proof that the permission caused the native crashes or that duplicate cards cannot recur. The mixed-card selection and lock transition paths are tested offline. A new release does not modify existing private credentials, speech settings, or TCC permissions.
