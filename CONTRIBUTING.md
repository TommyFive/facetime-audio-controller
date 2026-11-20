# Contributing

Use English for issues, pull requests, code reviews, documentation and release notes.

- Work in a feature branch; do not edit deployed production scripts as part of source refactoring.
- No personal data, credentials, production URLs, screenshots, logs or call transcripts in commits or issues.
- Keep the fixed recipient, idempotence, transaction ownership and fail-closed UI verification guarantees intact.
- Add synthetic tests for each safety-affecting change and execute the full offline test suite.
- Real FaceTime calls and KVM/HID interactions require explicit permission and a consenting recipient.
- Do not merge on green unit tests alone if installer, macOS permissions or hardware integration changed.
