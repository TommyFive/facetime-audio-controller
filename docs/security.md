# Safety and threat model

The controller automates *real outgoing FaceTime calls*. It is intended for a single trusted macOS account with a single fixed, configured recipient.

## Trust boundaries

- Git source and releases contain no personal destination address, private endpoint, API key, call transcript or screenshots.
- Host settings are stored under `~/.config/facetime-controller` with owner-only permissions and are not part of Git.
- Local stdio MCP authentication is determined by its invoking client. Only grant call-capable MCP tools to trusted agents/users; an external tunnel needs a separate access review.
- NanoKVM uses independently authorized HTTPS MCP, with an owner-only credential. No runtime SSH/root escalation.
- MiniMax receives speech text when chosen; macOS local TTS is the private alternative.
- CallServices signals are host-wide observations and not authenticated per FaceTime destination.

## Controls

- Explicit fixed-recipient input validated before dialing.
- A non-blocking outgoing-call mutex and a durable transaction journal written before opening the FaceTime URL.
- Verified, bounded visual confirmation and cancellation; no blind green-button clicks.
- Priority hangup/cancel, including during playback, through a separate UI mutex.
- Independent watchdog that can only act when the async worker record matches the controller journal transaction.
- Idempotent MCP request IDs; no automatic retry under a fresh ID when outcome is unknown.
- Incomplete or ambiguous GUI state returns an error requiring deliberate recovery.

External manual FaceTime activity does not participate in the controller lock. A desktop that fails to expose a uniquely attributable UI must remain untouched.

## Credentials and vulnerability reporting

Review all commits and release assets for secrets before sharing. Keep all historical development refs private. Public releases must contain only audited source files and a new clean history; an audited file tree is not a substitute for credential rotation after an actual leak.

Report security issues privately through GitHub repository security advisories if enabled. Do not attach credentials, unredacted logs, real phone numbers, screenshots or identities to public issues.
