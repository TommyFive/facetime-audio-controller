# CLI interface

The unified entry point after installation is
`~/.local/bin/facetime-controller`. It is a thin dispatcher to the existing
FaceTime shell controller, read-only doctor and privacy-safe usage CLI.

| Command | Effect |
| --- | --- |
| `facetime-controller help` | Show all supported commands |
| `facetime-controller dry-run` | Check prerequisites, no dialing |
| `facetime-controller status` | Inspect FaceTime state; may wake screen |
| `facetime-controller call [TTS flags] 'text'` | Pre-render TTS, dial fixed target, verify hangup |
| `facetime-controller speak [TTS flags] 'text'` | Play through Loopback, no FaceTime URL |
| `facetime-controller stats [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--json]` | Read the local usage journal; HD/Turbo/MiniMax total and macOS fallback |
| `facetime-controller doctor [--permissions]` | Read-only system and setup diagnostics |
| `facetime-controller hangup [--timeout 24]` | Priority interruption of a verified active call |
| `facetime-controller cancel-pending` | Priority cancellation of confirmed pending UI |
| `facetime-controller recover` | Bounded recovery (never places a call) |
| `facetime-controller dial` | Advanced dial-only mode |
| `facetime-controller confirm` | Confirm a verified pending UI card |

Legacy `~/.local/bin/facetime-call --call 'text'` and
`~/.local/bin/facetime-controller-doctor --permissions` remain available as
compatibility launchers. **There is only one implementation per function.**
The CLI does not register new MCP tools or change the secure tunnel.

Outgoing call timeouts are bounded. TTS overrides include
`--tts-provider minimax|macos`, `--tts-speed`, `--tts-volume`,
`--tts-pitch` and `--tts-voice`. The renderer's selected model comes from
the TTS configuration. See [usage journal](usage-journal.md).

Priority hangup and cancel bypass the outgoing lock but retain a bounded UI
action lock. Calls fail closed on unidentified or ambiguous screens.

**Consent:** `call` makes a real outgoing FaceTime call to the configured
recipient. `doctor`, `stats` and the automated unit suite never dial.

See [MCP reference](mcp-reference.md) for request IDs and asynchronous calls.
