# CLI interface

Entry point after installation: `~/.local/bin/facetime-call`.

| Command | Effect |
| --- | --- |
| `--help` | Show supported commands |
| `--dry-run` | Check prerequisites, no dialing |
| `--status` | Inspect FaceTime state; may wake screen |
| `--call [TTS flags] 'text'` | Pre-render TTS, dial fixed target, verify hangup |
| `--speak 'text'` | Play through Loopback only, no FaceTime URL |
| `--hangup [--timeout 24]` | Priority interruption of a verified active call |
| `--cancel-pending` | Priority cancel of confirmed pending UI |
| `--recover` | Bounded cleanup of verified stale cards; never initiates a new call |
| `--dial` | Confirm without automatic speech or hangup; advanced/manual |
| `--confirm` | Explicitly confirm a verified pending card |

For outgoing calls, `--confirm-timeout`, `--answer-timeout` and `--hangup-timeout` have bounded accepted ranges. TTS overrides include `--tts-provider minimax|macos`, `--tts-speed`, `--tts-volume`, `--tts-pitch` and `--tts-voice`.

Priority hangup and cancel bypass the outgoing lock but retain a bounded UI action lock. They fail closed on unidentified or ambiguous screens. The journal is never reset by deleting lock files.

**Consent:** `--call` makes a real outgoing FaceTime call to the configured recipient. Neither `--dry-run` nor the automated unit suite does.

See [MCP reference](mcp-reference.md) for idempotent request IDs and asynchronous calls.
