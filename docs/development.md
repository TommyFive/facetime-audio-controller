# Development and verification

The repository intentionally separates source, per-host configuration and live operational evidence. Never commit private runtime files, real contact addresses, chat transcripts, screenshots or temporary audio.

## Working on code

Use a development branch and isolated macOS worktree, not the active production scripts. Keep existing transaction and fail-closed semantics. Protect direct FaceTime and KVM mutations behind explicit reviewed safety checks. Write GitHub issues, PR descriptions, reviews and release notes in English.

## No-call automated tests

    python3 -m venv .venv
    .venv/bin/python -m pip install -r requirements.txt
    .venv/bin/python -m unittest discover -s tests -v
    .venv/bin/python tests/mcp_protocol_smoke.py

The unit suites mock all FaceTime URL requests, KVM clicks, MiniMax network calls and TTS playback. Some local audio fixtures are synthesized with FFmpeg but do not initiate FaceTime. CI must exercise the full offline suite on macOS and on Linux when compatible. An explicit test configuration uses a non-routable example.invalid recipient.

## Acceptance layers

1. Syntax, unit tests and MCP protocol without an outbound call.
2. Installer dry-run, clean installed runtime, private permissions, versioned upgrade and uninstall/rollback.
3. GUI Accessibility and NanoKVM checks in the applicable session.
4. Separately approved real FaceTime call, with connection, full TTS playback, guarded hangup and handset-side audible confirmation.
5. A deliberate failure-mode test for interruption and crash recovery if the environment can safely support it.

Do not mark handset delivery as proven based only on CallServices or FFmpeg logs. Avoid live repeated dial stress tests.

## Release

Run the privacy gate, dependency scan and complete offline test matrix; verify clean installation on a separate Mac. Tag only an audited commit with a reproducible source package. Do not rewrite historic tags to hide sensitive data: a new clean distribution repository can begin with a fresh history after owner approval.
