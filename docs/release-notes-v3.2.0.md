# FaceTime Audio Controller v3.2.0

Stable feature release introducing a unified local CLI and a privacy-preserving speech-usage journal.

## New and improved

- **One command:** `facetime-controller call|speak|status|stats|doctor|hangup|cancel-pending|recover|confirm|dial|dry-run|help`. The commands dispatch to existing implementations; the MCP interface is unchanged.
- **Backwards compatibility:** `facetime-call` and `facetime-controller-doctor` remain supported after installing or upgrading.
- **Usage journal:** local, owner-only JSONL records for MiniMax API attempts, finalized speech audio, duration, and FaceTime outcomes (including accepted/connected calls, playback, and hangup). No speech text, recipient identity, credentials, or prices are recorded.
- **MiniMax totals:** separate Speech 2.8 HD and Turbo summaries, plus a combined MiniMax total. Provider-reported usage characters, input characters, API attempts, generated audio and duration are tracked independently. macOS direct synthesis and macOS fallback remain distinct.
- **Installer fixes:** ship the usage/CLI modules in the installed runtime, create the unified `facetime-controller` executable, and quote wrapper arguments correctly even for installation paths containing spaces. Symlinked executable targets are rejected.
- **CLI documentation:** `facetime-controller stats [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--json]` and `facetime-controller doctor --permissions`.

## Validation

- All **185 offline regression tests** passed locally, including new CLI dispatch, installer-wrapper and usage-aggregation tests.
- GitHub Actions CI runs on **macOS and Ubuntu**, with privacy checks, MCP stdio protocol validation and isolated installation smoke tests.
- The release workflow re-runs offline checks and publishes a source archive plus SHA-256 checksums.

## Upgrade and deployment notes

The release is **source distribution**, not an automatic upgrade of existing installations. Follow the guided installer documentation and preserve local configuration, TTS credentials, recipient and optional OpenClaw/NanoKVM settings. The source archive does not contain host-specific configuration or secrets.

The integrated `doctor` subcommand is **read-only**. The unified CLI does not add MCP tools, restart the OpenClaw Gateway, or reconfigure the OpenAI Secure Tunnel.

**CI never places a real FaceTime call.** FaceTime sign-in, macOS GUI permissions, virtual audio routing, and any locked-screen NanoKVM integration still require environment-specific end-to-end acceptance testing.

See [CLI reference](cli-reference.md), [usage journal](usage-journal.md), [installation](installation.md) and [security notes](security.md).
