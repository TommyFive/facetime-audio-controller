# Troubleshooting and safe recovery

Begin with `facetime-controller-doctor` and `facetime-call --status`. Status may wake the display but does not originate a call.

| Condition | Recommended action |
| --- | --- |
| `RECIPIENT_NOT_CONFIGURED` | Set a private fixed target in config.json; do not patch source |
| `ACCESSIBILITY_PERMISSION_DENIED` | Grant the invoking app/agent Accessibility rights under macOS Privacy & Security |
| `NANOKVM_NOT_CONFIGURED` | Configure an authorized HTTPS endpoint and owner-only bearer, or use an unlocked GUI |
| `NANOKVM_ACCESS_DENIED` | Check TLS, VPN/network, endpoint and user-provided credential permissions |
| `AUDIO_ROUTE_HUNG` | Check Rogue Amoeba Loopback / CoreAudio independently; do not blindly redial |
| `CALL_UNAVAILABLE` | The recipient may have declined, missed or been unreachable; do not infer intent |
| `ANSWER_TIMEOUT` | Inspect GUI and journal before deciding whether another attempt is safe |
| `RECOVERY_REQUIRED` | Use inspected, bounded recovery; never delete transaction lock files |
| `REQUEST_ID_CONFLICT` | Reuse the same original intent ID only with its original payload |
| `LOCK_BUSY` | Another cooperating call owns the outgoing transaction |

Manual diagnosis of the virtual audio route may use the separate `facetime-audio-health.py` utility. This can play synthetic local audio but never initiates FaceTime; it is **not** automatically run in MCP health preflight.

An incomplete async call must be examined with `facetime_call_status` and `facetime_status`. Priority `--hangup` may safely end an identifiable active FaceTime UI. Do not repeatedly dial while the result is uncertain.

For installer troubles, inspect the generated version directory, the current symlink and the dedicated launchd label. The uninstall process preserves configuration, state and older versions by default.
