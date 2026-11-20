# TTS options

Fresh installs default to **macOS local speech** without third-party API requests. The interactive wizard also offers MiniMax with selectable **Speech 2.8 Turbo (10,000 chars)** and **Speech 2.8 HD (5,000 chars)**, international or mainland China endpoint, voice ID (German default `German_FriendlyMan`), speed (default 1.1), volume, pitch and smaller per-model character limit. The engine rejects text above the model's hard cap even if user config is larger.

MiniMax credentials are entered via a hidden prompt or read from a local owner-only 0600 JSON file using key `minimaxApiKey`. They are stored under `~/.config/facetime-controller/secrets/minimax.json`, never in Git or command arguments. A **paid** MiniMax-only API test is optionally offered at installation; it sends short sample text for synthesis but never dials FaceTime, and only an actual MiniMax response (not macOS fallback) counts as successful key/model validation.

macOS voice, speech rate and optional character cap can also be configured. A null macOS maximum means no additional model-specific cap, not infinite transport capacity.

Speech is rendered before dialing. MiniMax errors fall back once to local macOS speech during calls; if both fail, the controller does not dial. Local playback success is not proof that audio was delivered to a recipient. Cloud provider selection means spoken text leaves the Mac.
