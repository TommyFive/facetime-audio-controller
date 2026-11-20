# Durable asynchronous MCP calls

Some agent runtimes have a per-tool RPC timeout shorter than a long FaceTime speech message. The recommended non-blocking API isolates call execution from the original MCP request.

1. `facetime_call_start` validates the message and reserves a stable request ID, writes a private input file and launches a detached worker.
2. `facetime_call_wait` polls for up to 45 seconds each time; `facetime_call_status` reads durable state across agent restarts.
3. The worker initiates at most one request to the fixed recipient, supervises TTS/playback/hangup and records terminal results.
4. A dedicated 30-second launchd watchdog inspects dead or overdue workers. It may intervene only when the controller journal's transaction ID matches the worker record.
5. `facetime_call_cancel` uses the same transaction ownership requirement and guarded priority hangup.

## State and ownership

Requests and owner-only logs are under `~/.local/state/facetime-controller/mcp/async`. The controller journal and lockfiles are under `~/.local/state/facetime-controller`. Individual files are mode 0600 and their directories are mode 0700.

The detached process argument contains a request ID, not the speech content. The watchdog is independent of the MCP connection and agent lifetime, and must never hang up an unrelated or ambiguous call.

## Failure semantics

- Reuse the **same** request ID when checking or retrying an uncertain result; do not generate a new ID blindly.
- A disconnected remote party during playback is a failed delivery, even if local playback had started.
- An already-clear FaceTime UI means no visible call; it does not prove that this controller clicked the red hangup.
- A worker crash does not authorize an automatic redial.
- No success claim is made until a complete local playback and verified call termination.

Start the Watchdog LaunchAgent only within a logged-in macOS GUI user session. The installer owns the `com.facetime-controller.async-watchdog` label.
