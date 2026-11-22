# FaceTime Audio Controller

A macOS FaceTime Audio controller with pre-rendered speech, safe hangup/recovery, an optional MCP server and an optional NanoKVM path for locked screens. This project requires a signed-in FaceTime account and a configured virtual audio routing device. It is not affiliated with Apple.

The software uses a **single fixed recipient configured on each Mac**. MCP callers cannot supply arbitrary destinations. All mutating actions require unambiguous FaceTime UI state; they fail closed if identity, connection or hangup cannot be verified.

## Requirements

- macOS with FaceTime enabled and an interactive logged-in GUI session
- Python 3.11+, FFmpeg, Xcode Command Line Tools for a small Swift/Vision OCR helper
- Rogue Amoeba Loopback installed and configured as the FaceTime microphone
- Optional: MiniMax API key for cloud TTS, NanoKVM MCP with authorized TLS for locked-screen automation, OpenClaw for native MCP integration
- German FaceTime UI at 1920 x 1080 is the only locked-screen visual layout currently tested. Other versions/locales require separate acceptance testing.

## Quick start

Clone the public source repository:

    git clone https://github.com/TommyFive/facetime-audio-controller.git
    cd facetime-audio-controller
    ./install.sh

The installer runs as the current macOS user and does not use sudo. It creates an isolated runtime and private user configuration, and optionally installs a 30-second launchd watchdog for asynchronous MCP calls. It does not place a FaceTime call. The wizard asks for TTS provider/model, NanoKVM, OpenClaw and permissions; macOS TTS is the fresh default. Add `~/.local/bin` to your shell PATH if necessary.

Run the read-only diagnostic after installation:

    ~/.local/bin/facetime-controller doctor --permissions

Only place a real call when the recipient has agreed to the test:

    ~/.local/bin/facetime-controller call 'This is a controlled FaceTime Audio test.'

## Guided installer and OpenClaw integration

**Before installation:** Sign in to FaceTime under the installing macOS account; install Python, FFmpeg, Xcode Command Line Tools and licensed Rogue Amoeba Loopback. Set Loopback as the default microphone. Optional dependencies are a MiniMax API key, authorized NanoKVM HTTPS MCP plus a private bearer, and a recent OpenClaw with native MCP registry support.

**During installation:** The interactive `./install.sh` wizard asks for a fixed FaceTime recipient, audio device, local macOS TTS or MiniMax Speech 2.8 **Turbo/HD**, voice, speed, volume, pitch and character cap. MiniMax credentials use a hidden prompt and private local file; a real paid short TTS-only API test is optional and never calls FaceTime. It also asks whether NanoKVM and OpenClaw integration are wanted, and whether to enable the independent 30-second hangup watchdog.

**Without NanoKVM:** Automatic FaceTime control requires the Mac session to remain **unlocked** when calls execute. A scheduled call will fail if the screen has locked. The wizard explicitly requires acknowledging this limitation; it does not turn off macOS screen locking.

**OpenClaw:** If selected, setup registers the stdio MCP server with the supported `openclaw mcp set` CLI, backs up the previous OpenClaw configuration and verifies MCP tool discovery using read-only probes. The MCP server starts on demand, **not** as a persistent launchd daemon. The separate optional 30-second watchdog uses a user LaunchAgent; no existing Gateway is automatically restarted, and an existing MCP registration is never replaced without explicit approval. Start a fresh OpenClaw agent session after integration.

**After installation:** The installer runs a read-only doctor, checks Audio/Loopback, and interactively probes macOS Accessibility/Automation and NanoKVM permission paths. It provides manual TCC instructions and offers a recheck. Confirm the FaceTime login manually; only a separately authorized real call can test remote audio and hangup.

Read the [full setup sequence](docs/installation.md), [OpenClaw integration](docs/openclaw.md), [NanoKVM policy](docs/nanokvm.md) and [TTS configuration](docs/tts.md). Review [OpenClaw's native MCP registry documentation](https://docs.openclaw.ai/cli/mcp/registry) for tool and version behavior.

Example scripted CLI-only install (the example recipient is non-routable):

    ./install.sh --non-interactive --recipient friend@example.invalid --tts-provider macos --accept-unlocked-only --no-watchdog

Use `./install.sh --help` to list all settings. A fresh installation is tested without dialing a recipient.

## Interfaces

- Local CLI: `facetime-call` for status, call, speak, hangup, cancel and recovery.
- MCP stdio: `facetime-mcp-server.py`, ten tools including asynchronous start/wait/status/cancel.
- Native OpenClaw integration is optional; the installer can register its MCP server using a supported OpenClaw CLI, or generate a local configuration snippet for manual review.
- NanoKVM lockscreen control requires an independently provisioned MCP endpoint and owner-only bearer.
- ChatGPT Secure MCP Tunnel is a separate optional module, not part of the normal install.

## Documentation

- [Documentation index](docs/index.md)
- [Installation and removal](docs/installation.md)
- [Quick start and first call](docs/quickstart.md)
- [Private configuration](docs/configuration.md)
- [CLI reference](docs/cli-reference.md)
- [MCP tools](docs/mcp-reference.md)
- [OpenClaw setup](docs/openclaw.md)
- [NanoKVM requirements](docs/nanokvm.md)
- [TTS provider policy](docs/tts.md)
- [Safety and threat model](docs/security.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Architecture and contributor guide](docs/development.md)
- [Async call supervision](docs/async-calls.md)
- [Release notes](CHANGELOG.md)
- [Public source privacy and release audit](docs/privacy-audit.md)

## Safety boundaries

Calls cannot be rolled back transactionally. The controller uses a durable journal, an outgoing-call lock, conservative UI verification and priority hangup. External FaceTime activity bypasses these protections. CallServices evidence is host-wide and is not a cryptographically authenticated target identifier. A successful local playback does not prove the handset heard all audio.

Cloud TTS sends message text to MiniMax. Select local macOS TTS if cloud transmission is inappropriate. Never commit settings, credentials, call transcripts, screenshots or logs.

[MIT License](LICENSE) | [Security](SECURITY.md)

## Usage journal (local CLI, no MCP tools)

Speech synthesis is counted at successful generation, independently from whether
FaceTime connects. A separate call result records whether the call was dialed,
connected, played and verified as hung up. No message text, phone numbers,
recipients, API keys, file paths, or pricing are stored. MiniMax service usage
characters are recorded only when the API supplies them; otherwise the field is
unknown, never fabricated. Fallback macOS audio is a distinct reporting lane.

```bash
facetime-controller stats
facetime-controller stats --since 2026-11-01 --json
```

Owner-only records are stored outside the repository in
`~/.local/state/facetime-controller/usage.jsonl` (mode 0600, parent 0700).
The report is read-only. See [usage journal and CLI](docs/usage-journal.md).
