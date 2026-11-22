# FaceTime Audio Controller v3.1.0

First **stable public distribution** of the FaceTime Audio Controller, following the audited v3.0.0-beta.4 source release.

## Included functionality

- FaceTime Audio control through a macOS CLI and an optional MCP server, with a fixed configured recipient.
- Asynchronous call lifecycle, monitored hangup and recovery.
- macOS speech synthesis, optional MiniMax Speech 2.8 Turbo/HD and provider fallback.
- Optional NanoKVM-based locked-screen control, subject to separately configured permissions and tested UI layouts.
- Guided per-user macOS installation, OpenClaw MCP registration and diagnostic tooling.

## Validation and scope

- MIT-licensed source distribution with automated privacy checks.
- Automated offline regression, MCP protocol tests and GitHub Actions release packaging.
- macOS and Linux CI must pass before the stable tag is published.
- **No automatic real FaceTime call is performed by CI.** FaceTime sign-in, audio routing, OS permissions and optional NanoKVM operation require installation-specific verification.

See [README](../README.md), [installation](installation.md), [security notes](security.md) and [changelog](../CHANGELOG.md) for limitations and setup.
