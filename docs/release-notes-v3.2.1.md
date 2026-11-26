# v3.2.1 — Bounded stale notification recovery

A locked-screen FaceTime confirmation card can remain visible after a normal cancel attempt. This patch adds one tightly scoped escalation on the next outgoing preflight following a recorded answer timeout.

- Require the current transaction's recovery ownership and evidence of a previous dial request that timed out awaiting an answer.
- Require the same uniquely verified recipient card to survive a normal cancel and remain stable on fresh frames. Refuse active, held, multiple, moved, unknown or unverified cards.
- Require a native idle call-center observation before and immediately preceding the reset, and again after stable empty-screen verification.
- Send SIGTERM only to the current user's exact FaceTime notification service and extension names. Never terminate FaceTime itself, the system call-services daemon or other processes.
- Do not retry the reset if a check fails. Recovery remains required and no new dial occurs.

The macOS native call-state probe uses undocumented TelephonyUtilities selectors because the public CXCallObserver API is unavailable to native macOS applications. This is a best-effort additional safety signal, not a supported system-wide guarantee of call absence. Unsupported APIs, non-idle results, warnings, timeouts or malformed output fail closed. No UI automation can exclude a concurrent call created outside the controller with absolute certainty. The change is intentionally restricted to a known answer-timeout transaction and independently verified pending UI.

GitHub Actions runs the no-call regression suite on macOS and Linux, including macOS SDK type-checking of the Swift probe. Live call acceptance remains a separate deployment check.
