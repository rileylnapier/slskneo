import os
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def test_real_stdio_handshake_discovery_status_and_unconfigured_error():
    # Explicitly exclude any real credentials inherited by the test runner.
    env = {key: value for key, value in os.environ.items() if not key.startswith("SLSK_")}
    env["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")
    params = StdioServerParameters(command=sys.executable, args=["-m", "soulseek_mcp"], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            assert names == {"soulseek_status", "soulseek_connect", "soulseek_disconnect", "soulseek_search", "soulseek_results", "soulseek_stop_search", "soulseek_download", "soulseek_transfers", "soulseek_pause_transfer", "soulseek_resume_transfer"}
            result = await session.call_tool("soulseek_status", {})
            assert result.isError is False
            assert result.structuredContent["connected"] is False
            assert result.structuredContent["credentials_configured"] is False
            failed = await session.call_tool("soulseek_connect", {})
            assert failed.isError is True
            assert "SLSK_USERNAME" in failed.content[0].text
            bad_id = await session.call_tool("soulseek_results", {"search_id": "not-real"})
            assert bad_id.isError is True
