# Per-user configuration

All sensitive settings live outside Git in `~/.config/facetime-controller/` as owner-only files:

- `config.json`: fixed recipient, Loopback audio device name, optional NanoKVM endpoint.
- `tts.json`: provider, MiniMax model/region/voice/speed/volume/pitch and model limits; local macOS voice/rate/cap.
- `secrets/minimax.json`: private API key under `minimaxApiKey`.
- `secrets/nanokvm-authorization`: private `Bearer ...` token.
- `openclaw-mcp-snippet.json`: generated nonsecret MCP configuration reference.
- `backups/`: private backups of existing OpenClaw config where present.

The install wizard is interactive by default. Scripted options include `--recipient`, `--audio-device`, `--reconfigure`, `--tts-provider`, `--minimax-model`, `--minimax-region`, `--minimax-key-file`, `--tts-voice`, `--tts-speed`, `--tts-volume`, `--tts-pitch`, `--max-characters`, `--macos-rate`, `--macos-max-characters`, `--nanokvm`, `--nanokvm-endpoint`, `--nanokvm-auth-file`, `--accept-unlocked-only`, `--openclaw`, `--openclaw-cli`, `--replace-openclaw-mcp`, `--watchdog`, `--check-permissions` and `--test-tts`.

No-NanoKVM noninteractive mode requires `--accept-unlocked-only`. The wizard never unlocks the Mac or disables screen locking. A missing MiniMax key or invalid NanoKVM bearer is an installation error, not an implicit successful setup.

Advanced environment variables include `FACETIME_CONFIG_DIR`, `FACETIME_CONFIG`, `FACETIME_RECIPIENT`, `FACETIME_NANOKVM_ENDPOINT`, `FACETIME_NANOKVM_AUTH_FILE`, `FACETIME_MINIMAX_KEY_FILE`, `FACETIME_STATE_DIR`, `FACETIME_TTS_CONFIG` and `FACETIME_BIN_DIR`. Treat them as local privileged settings, never user-supplied MCP tool arguments.
