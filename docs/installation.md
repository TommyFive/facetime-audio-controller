# Guided installation and removal

## Before installation

1. Sign in to FaceTime in the **same logged-in macOS user** that will run the controller.
2. Install Homebrew Python 3.11+, FFmpeg, Xcode Command Line Tools and licensed Rogue Amoeba Loopback.
3. Configure Loopback as the default macOS input device and FaceTime microphone.
4. Optional: have a region-compatible MiniMax API key, a separately authorized NanoKVM HTTPS MCP endpoint and bearer, and OpenClaw with a native `openclaw mcp` CLI.

Typical prerequisites:

    brew install python ffmpeg
    xcode-select --install

Only run the second command when Command Line Tools are missing.

## During installation

    git clone https://github.com/TommyFive/facetime-audio-controller.git
    cd facetime-audio-controller
    ./install.sh

The guided wizard presents and validates:

1. Fixed FaceTime recipient (Apple ID email/E.164 telephone; MCP cannot select arbitrary recipients).
2. Audio device (normally `Loopback Audio`).
3. TTS: local macOS or MiniMax, including **2.8 Turbo (10,000 chars)** versus **2.8 HD (5,000 chars)**, API region, voice, speed, volume, pitch and optional smaller character limits.
4. MiniMax API key, entered without echo and stored in a private JSON file. A short paid real **TTS-only API test** is opt-in and does not call FaceTime.
5. NanoKVM: authorized HTTPS endpoint, owner-only Bearer file and locked-screen checks, or explicit acceptance of **unlocked-session-only** operation. The installer never disables the screen lock.
6. OpenClaw: optionally register a native stdio MCP entry through `openclaw mcp set`, with protected backup and validation. An existing registration requires explicit consent for replacement.
7. Optional 30-second async watchdog LaunchAgent (recommended for unattended jobs). No permanent MCP server daemon is needed.
8. Read-only readiness diagnostics, including macOS audio and current effective Accessibility/Automation permissions when selected, plus NanoKVM screenshot verification when configured.

The installer does not call the configured recipient. A real consenting end-to-end call is a separate manual acceptance test.

## Noninteractive setup

Standalone, no NanoKVM:

    ./install.sh --non-interactive --recipient friend@example.invalid --tts-provider macos --accept-unlocked-only --no-watchdog

MiniMax adds `--tts-provider minimax --minimax-model turbo|hd --minimax-region international|china --minimax-key-file /private/minimax.json`. The local file must be owner-only 0600 JSON with key `minimaxApiKey`. Never put a raw API key on the CLI.

NanoKVM adds `--nanokvm --nanokvm-endpoint https://kvm.example.invalid/api/mcp --nanokvm-auth-file /private/bearer.txt`, where the private local file holds an authorized `Bearer ...` value.

Native OpenClaw adds `--openclaw --watchdog`; use `--openclaw-cli /absolute/path/to/openclaw` if PATH differs. A deliberate replacement requires `--replace-openclaw-mcp`.

Set `--check-permissions` to run read-only current GUI/KVM checks in automation. `--test-tts` explicitly opts into a short paid MiniMax API validation without calling FaceTime.

## After installation

    ~/.local/bin/facetime-controller-doctor --permissions
    ~/.local/bin/facetime-call --dry-run
    ~/.local/bin/facetime-call --status

Correct macOS TCC permissions under System Settings > Privacy & Security > Accessibility/Automation when prompted; the installer cannot grant them silently. Verify the signed-in FaceTime account manually. If OpenClaw was selected, open a fresh agent session and run `openclaw mcp doctor facetime-controller` and `openclaw mcp probe facetime-controller --json`.

Finally, explicitly arrange one short call with a consenting recipient and verify connection, remote audibility, complete local playback and confirmed hangup. The installer cannot prove handset delivery.

## Upgrade and uninstall

Run the reviewed installer again to upgrade the versioned runtime. Existing private settings are retained unless changed in the wizard or with explicit arguments; configured watchdog state is preserved by default. The current version symlink is switched atomically. `./uninstall.sh` removes only package-managed launchd/CLI entrypoints by default, preserving user settings and old versions. Consult [rollback](rollback.md).

No production OpenClaw Gateway is restarted by setup. No lockscreen setting or TCC database entry is modified automatically.
