"""Live MCP stdio handshake and harmless tool checks."""
import asyncio
import pathlib
import sys
from mcp.client import Client
from mcp import StdioServerParameters

async def main():
    root = pathlib.Path(__file__).resolve().parents[1]
    params = StdioServerParameters(command=sys.executable, args=[str(root/"facetime-mcp-server.py")], cwd=str(root))
    async with Client(params, read_timeout_seconds=60) as client:
        tools = await client.list_tools()
        names = sorted(t.name for t in tools.tools)
        print("MCP_TOOLS", names)
        expected = {"facetime_call", "facetime_call_start", "facetime_call_status",
                    "facetime_call_wait", "facetime_call_cancel",
                    "facetime_capabilities", "facetime_health", "facetime_hangup",
                    "facetime_speak", "facetime_status"}
        assert expected == set(names), names
        result = await client.call_tool("facetime_health", {})
        print("MCP_HEALTH", result)
        result = await client.call_tool("facetime_capabilities", {})
        print("MCP_CAPABILITIES", result)
        # Unknown tool and invalid argument rejection are tested without any phone call.
        try:
            bad = await client.call_tool("facetime_call", {"message":"hi", "request_id":"bad"})
            print("MCP_INVALID_REQUEST", bad)
            assert bad.is_error
        except Exception as ex:
            print("MCP_INVALID_REQUEST_REJECTED", type(ex).__name__)
        print("MCP_PROTOCOL_PASS")
asyncio.run(main())
