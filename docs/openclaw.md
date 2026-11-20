# Native OpenClaw MCP integration

Official references: [OpenClaw MCP registry](https://docs.openclaw.ai/cli/mcp/registry) and [MCP config](https://docs.openclaw.ai/gateway/config-extensions).

## Requirements

Install OpenClaw under the same Mac user as FaceTime and Loopback and verify the CLI provides `openclaw mcp set`, `openclaw mcp doctor` and `openclaw mcp probe`. Configure any necessary Accessibility/Automation permissions for the actual executing process. Optional NanoKVM handles a locked session; without it the Mac must remain unlocked for automated calls.

The FaceTime MCP server uses **stdio**. OpenClaw launches it on demand. A separate launchd MCP daemon is not installed; the optional 30-second crash-recovery watchdog is a LaunchAgent and does not serve MCP itself.

## Guided registration

Select OpenClaw during `./install.sh` or provide `--openclaw --watchdog`. The installer:

1. Checks OpenClaw CLI availability and registry capability before touching the installed runtime.
2. Refuses to overwrite an existing `facetime-controller` MCP registration without an explicit `--replace-openclaw-mcp` plus confirmation.
3. Saves an owner-only backup of the existing OpenClaw config under `~/.config/facetime-controller/backups/`, where the standard config path is present.
4. Registers the local installed Python environment and `facetime-mcp-server.py` with the supported `openclaw mcp set` command.
5. Filters tools to the asynchronous API, health, status, speech and guarded hangup. The legacy synchronous `facetime_call` is excluded by default to avoid dynamic-tool RPC timeouts. Codex tool approval defaults to `prompt`.
6. Uses `openclaw mcp doctor` and `openclaw mcp probe` to verify server startup and discovery **without calling FaceTime**.
7. Leaves the running OpenClaw Gateway untouched; start a fresh agent session after registration if tools are not immediately listed.

The source installer always generates `~/.config/facetime-controller/openclaw-mcp-snippet.json` as a reference, but never replaces the whole OpenClaw configuration with that partial snippet.

## After installation

    openclaw mcp list
    openclaw mcp show facetime-controller
    openclaw mcp doctor facetime-controller
    openclaw mcp probe facetime-controller --json
    ~/.local/bin/facetime-controller-doctor --permissions

These commands do not dial FaceTime. A new OpenClaw session should expose `facetime_call_start`, `facetime_call_wait`, `facetime_call_status` and `facetime_call_cancel`. Tool profiles such as `minimal`, `tools.deny` or explicit tool filters can suppress server tools; inspect the effective policy.

Use one stable `request_id` per intended call, never blindly retry with a new ID after an unknown outcome. A detached call needs the watchdog for hangup recovery. Scheduled briefings and messaging fallbacks are separately configured; the installer does not create cron jobs or restart unrelated services.
