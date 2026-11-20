# MCP stdio interface

The controller runs locally using the official Python MCP SDK. It opens no public HTTP port. A client starts `facetime-mcp-server.py` with the installed virtual-environment Python. It exposes **ten** tools:

| Tool | Side effects | Purpose |
| --- | --- | --- |
| `facetime_capabilities` | None | Features and limits |
| `facetime_health` | Read-only checks | Permission and availability |
| `facetime_status` | May wake display | Current UI state |
| `facetime_hangup` | Yes | Target-verified priority hangup |
| `facetime_speak` | Local audio | Play synthesized speech, no call |
| `facetime_call` | Real outgoing call | Legacy synchronous API; not recommended for OpenClaw agents |
| `facetime_call_start` | Real outgoing call | Reserve ID and start independent worker |
| `facetime_call_status` | None | Read durable state |
| `facetime_call_wait` | None | Poll bounded wait (maximum 45 seconds) |
| `facetime_call_cancel` | Yes | Cancel a matching in-flight request through guarded hangup |

The target is configured in private local settings. Neither synchronous nor asynchronous MCP calls take a recipient argument.

## Recommended asynchronous pattern

1. Generate one unique but stable `request_id` for the user intent (8 to 80 safe ASCII characters).
2. Invoke `facetime_call_start(message, request_id, provider, ...)` **once**.
3. Use `facetime_call_wait(request_id, wait_seconds=45)` repeatedly until terminal, or use `facetime_call_status`.
4. Treat only a terminal successful result with observed connection, finished local playback and verified hangup as controller-observed completion.
5. If the result is unknown or timed out, do not retry with a different ID. Investigate state/recovery first.

An ID is reserved for 24 hours; reusing the same ID with different content raises a conflict. Cloud TTS request or local playback can outlive a single agent RPC. Detached worker and the independent 30-second watchdog maintain the call lifecycle when the original client disconnects.

## Validation and limits

Messages must be nonempty and within the selected provider/model limit. MiniMax Turbo supports 10,000 characters and HD supports 5,000 by default; optional macOS limit is configurable. Pause markers such as `<#1#>` are preserved for MiniMax. The synchronous API remains for legacy direct clients but may overrun dynamic-tool RPC budgets.

The adapter returns structured results including `ok`, `state`, `code`, `request_id`, controller diagnostics and verification flags. These are host observations, not an authenticated proof of remote handset audio.

## Health and status

`facetime_health` checks OS automation privileges without placing a call or silently playing audio. `facetime_status` may wake the screen. Neither is proof that an eventual call can connect. If the UI is ambiguous, all mutating operations fail closed.
