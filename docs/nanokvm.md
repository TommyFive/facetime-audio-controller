# NanoKVM / locked-screen setup

**With NanoKVM:** Supply a pre-authorized HTTPS MCP endpoint ending in `/api/mcp` and an owner-only 0600 bearer file. The installer optionally checks read-only screenshots and the supported target-verification path. NanoKVM must already be provisioned independently.

**Without NanoKVM:** FaceTime automation only works while the local user desktop is **unlocked**. Scheduled calls can fail after macOS automatically locks. The setup wizard warns about this and requires explicit acknowledgment. It does **not** disable screen locking, unlock macOS, store the login password or weaken security settings.

Only German FaceTime notifications at 1920x1080 are verified for the current locked-screen visual classifier; other themes, scales, resolutions or versions require additional hardware acceptance.

Example with placeholders:

    ./install.sh --non-interactive --recipient friend@example.invalid       --nanokvm --nanokvm-endpoint https://kvm.example.invalid/api/mcp       --nanokvm-auth-file /private/nanokvm-bearer.txt --check-permissions

Then run `~/.local/bin/facetime-controller-doctor --permissions` to inspect screenshot access without any call or KVM click. Actual end-to-end usage still needs a consenting real call.
