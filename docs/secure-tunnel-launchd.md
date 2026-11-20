# Optional ChatGPT Secure MCP Tunnel

The normal installer uses local stdio MCP and does not install any remote tunnel. A ChatGPT Secure MCP tunnel is an **optional integration** requiring separate owner authorization, a locally configured tunnel-client profile and credentials.

The repository includes `tools/install-tunnel.sh`, `tools/status-tunnel.sh` and `tools/uninstall-tunnel.sh`. These scripts operate on a dedicated `facetime-mcp` tunnel LaunchAgent and refuse missing credentials or a conflicting running foreground tunnel. They never install credentials or a control-plane identity on behalf of another user.

Configure the tunnel-client profile, its owner-only secret and `FACETIME_TUNNEL_ID` explicitly in the environment before installation. The tool checks that the profile matches the current installed stdio MCP runtime. Run it from a GUI session on the intended Mac.

    export FACETIME_TUNNEL_ID=YOUR_OWN_TUNNEL_ID
    /bin/sh tools/install-tunnel.sh
    /bin/sh tools/status-tunnel.sh

The service writes owner-only logs and exposes a loopback readiness endpoint, not a publicly listening MCP port. Readiness is not evidence that a real FaceTime call is safe or delivered. Never grant tunnel action tools broadly or bypass ChatGPT access reviews.

To remove only this dedicated tunnel service:

    /bin/sh tools/uninstall-tunnel.sh

The authenticated tunnel profile and credentials are deliberately preserved. This optional component may require additional adaptation to the current tunnel-client release; it is not part of the clean-install acceptance gate.
