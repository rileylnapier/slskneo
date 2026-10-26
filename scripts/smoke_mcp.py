"""Verify the actual stdio MCP server without credentials or network access."""
import asyncio
import json
import os
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "soulseek_status", "soulseek_connect", "soulseek_disconnect",
    "soulseek_search", "soulseek_results", "soulseek_stop_search",
    "soulseek_download", "soulseek_transfers", "soulseek_pause_transfer",
    "soulseek_resume_transfer",
}


async def main():
    env = dict(os.environ, SLSK_USERNAME="", SLSK_PASSWORD="")
    params = StdioServerParameters(
        command=sys.executable, args=[str(ROOT / "scripts/run_mcp.py")], env=env,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert {t.name for t in tools.tools} == EXPECTED
            status = await session.call_tool("soulseek_status", {})
            assert not status.isError
            data = json.loads(status.content[0].text)
            assert data["connected"] is False
            assert data["credentials_configured"] is False
            assert data["sharing_enabled"] is False
            denied = await session.call_tool("soulseek_connect", {})
            assert denied.isError, "Missing credentials must block login"
            search = await session.call_tool("soulseek_search", {"query": "test"})
            assert search.isError, "Disconnected searches must not run"
            invalid = await session.call_tool("soulseek_download", {"result_id": "missing"})
            assert invalid.isError, "Unknown results must not download"
            report = {"healthy": True, "tool_count": len(tools.tools), "network_used": False,
                      "checks": ["initialize", "tools/list", "status", "credential guard", "connection guard", "download guard"]}
            (ROOT / "analysis/mcp-smoke.json").write_text(json.dumps(report, indent=2) + "\n")
            print(json.dumps(report))


if __name__ == "__main__":
    asyncio.run(main())
