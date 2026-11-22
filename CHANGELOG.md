# Changelog

## 3.1.0 — first stable public release (2026-11-22)

- Promote the audited FaceTime Audio Controller distribution to a stable, non-pre-release GitHub release.
- Preserve CLI/MCP operations, asynchronous call supervision, safe hangup/recovery, optional NanoKVM locked-screen support, macOS/MiniMax Speech 2.8 TTS with fallback, and the guided installer.
- Publish a versioned source archive and SHA-256 checksum through the GitHub Actions release workflow.
- Classify future Semantic Versioning tags correctly: stable versions are marked Latest, and alpha/beta/rc tags remain pre-releases.
- Automated regression testing is offline and does not replace a consented live FaceTime call or platform-specific acceptance tests.

## 3.0.0-beta.4 — public distribution snapshot

- Start a completely new, single-root MIT-licensed Git repository from the audited source snapshot; no previous private Git objects, branches, releases, or tag objects are imported.
- Use a lightweight release tag without tagger metadata, to avoid disclosing workstation names or local account details.
- Retain the reserved fictional telephone-number test and idempotent beta publishing workflow.
- The packaged source and offline test suite are intended for review and distribution; production FaceTime/OpenClaw installations are not modified.

## 3.0.0-beta.3 — initial clean-history MIT publication

- Publish the reviewed distribution snapshot as a new repository with a single root commit, independent of the historical private development Git objects.
- Adopt the MIT license for project-owned source code and correct README and security guidance for public users.
- Preserve CI, MCP, installer and release workflows and begin a fresh public release sequence.
- No production runtime migration or real FaceTime call is implied by publication.

## 3.0.0-beta.2 — guided installer preview (2026-11-20)

- Added interactive setup for fixed FaceTime recipient, Loopback audio device and local/macOS vs MiniMax TTS (Speech 2.8 Turbo/HD, voice, speed, volume, pitch, region and character limits).
- Added private MiniMax key prompts and optional paid no-call API validation.
- Added optional NanoKVM TLS/credential configuration or explicit unlocked-session-only acceptance.
- Added native OpenClaw MCP registration via supported CLI with a private backup, explicit replacement, narrow tool filter and read-only discovery probe; no automatic Gateway restart or extra MCP daemon.
- Added effective macOS TCC/AX and optional NanoKVM read-only permission probes with guided corrective instructions.
- Preserved watchdog state on upgrades, added tests and updated before/during/after setup documentation.

This beta was prepared in private development; the public repository starts from a separate audited filesystem snapshot. No production FaceTime/OpenClaw installation is migrated automatically.

## 3.0.0-beta.1 — distribution-readiness preview (2026-11-20)

- Externalized host-specific identity, TTS and NanoKVM endpoints and credentials.
- Added per-user versioned macOS installer, privacy gate, documentation rewrite and cross-platform CI.

## Older internal releases

Historical 1.0, 2.0 and 2.1 tags stay private; they are not distribution artifacts.
