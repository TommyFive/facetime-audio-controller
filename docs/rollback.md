# Upgrade, rollback and removal

The installer keeps installed package versions under `~/.local/share/facetime-controller/versions/` and points `current` at the active version. A failed build or verification does not switch the current pointer. User configuration, secrets and durable call journals live outside installed versions.

## Safe rollback

1. Confirm there is no active or uncertain FaceTime transaction with `facetime-call --status` and MCP status tools.
2. Stop only the dedicated `com.facetime-controller.async-watchdog` LaunchAgent if needed.
3. Point the `current` symlink to a previously installed, verified version and restart the dedicated agent. Do not blindly overwrite user settings or unrelated OpenClaw services.
4. Run read-only doctor and protocol tests before requesting another call.

Do not roll back in the middle of speech or while a UI state is ambiguous.

## Uninstall

    ./uninstall.sh

This removes only package-managed launchd and CLI entrypoints and unlinks the active version. It preserves configuration, credentials, state and installed versions by default.

Purging requires `./uninstall.sh --purge --yes`; the state directory is intentionally retained for auditing. Ensure the relevant installation is inactive and back up settings before purging. Do not delete another product's LaunchAgents, OpenClaw gateway settings or unrelated tunnels.
