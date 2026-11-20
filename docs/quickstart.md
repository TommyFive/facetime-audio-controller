# Readiness and first call

**Before:** FaceTime signed in on the Mac GUI account; Loopback configured as FaceTime microphone; Python, FFmpeg and Xcode Command Line Tools present. Obtain optional MiniMax, NanoKVM and OpenClaw credentials independently.

**During:** Run `./install.sh` and follow the guided TTS/model, recipient, audio, lockscreen mode, OpenClaw and watchdog prompts. Without NanoKVM, explicitly accept unlocked-session-only control. The installer never places a FaceTime call.

**After:** Grant the invoking terminal/agent Accessibility and Automation rights in System Settings, then execute:

    ~/.local/bin/facetime-controller-doctor --permissions
    ~/.local/bin/facetime-call --dry-run
    ~/.local/bin/facetime-call --status

For OpenClaw, additionally run `openclaw mcp doctor facetime-controller` and `openclaw mcp probe facetime-controller --json` and test tool discovery in a fresh agent session. The MCP server is on-demand stdio, not a launchd daemon. The optional 30-second LaunchAgent supervises detached calls.

Only then arrange one **consent-based** short real call and separately verify remote connection, audible content and safe hangup. Unknown outcomes must never trigger an automatic redial with a new request ID.
