"""Exercise the real daemon socket and MCP bridge, without a network client."""
import asyncio
import json
import os
from pathlib import Path
import stat
import tempfile
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from soulseek_mcp.daemon import Daemon
from soulseek_mcp.desktop_service import DesktopService
from soulseek_mcp.desktop_mcp import request as mcp_request
from soulseek_mcp.service import ClientError


async def socket_request(socket_path, method, params=None, identifier="desktop-test"):
    reader, writer = await asyncio.open_unix_connection(str(socket_path))
    try:
        writer.write((json.dumps({"id": identifier, "method": method, "params": params or {}}) + "\n").encode())
        await writer.drain()
        return json.loads(await reader.readline())
    finally:
        writer.close()
        await writer.wait_closed()


@pytest.fixture
async def desktop(monkeypatch):
    # macOS Unix-domain socket paths have a short limit; pytest's default
    # per-user temporary root may itself already exceed that limit.
    with tempfile.TemporaryDirectory(prefix="ss-integration-", dir="/tmp") as directory:
        state = Path(directory)
        socket = state / "backend.sock"
        monkeypatch.setenv("SLSK_USERNAME", "")
        monkeypatch.setenv("SLSK_PASSWORD", "")
        monkeypatch.setenv("SLSK_SOCKET", str(socket))

        def forbidden_client(_config):
            raise AssertionError("Offline operations must not construct a network client")

        service = DesktopService(state, client_factory=forbidden_client)
        daemon = Daemon(service, socket)
        await daemon.start()
        try:
            yield daemon, service, state, socket, forbidden_client
        finally:
            await daemon.close()


async def test_desktop_and_mcp_clients_share_wishlist_and_settings(desktop):
    _daemon, _service, state, socket, _factory = desktop
    status = await mcp_request("status")
    assert status["connected"] is False
    assert status["credentials_configured"] is False
    added = await socket_request(socket, "wishlist_add", {"query": "A saved search"})
    wish = added["result"]["items"][0]
    seen_by_mcp = await mcp_request("wishlist")
    assert seen_by_mcp["items"][0]["id"] == wish["id"]
    await mcp_request("wishlist_update", {"id": wish["id"], "enabled": False})
    desktop_snapshot = await socket_request(socket, "snapshot")
    assert desktop_snapshot["result"]["wishlist"][0]["enabled"] is False
    await socket_request(socket, "configure", {"username": "local-user", "password": "local-only-secret"})
    saved = (state / "desktop.json").read_text()
    assert "local-only-secret" not in saved
    assert "password" not in saved
    assert (await mcp_request("status"))["credentials_configured"] is True
    assert stat.S_IMODE(state.stat().st_mode) == 0o700
    assert stat.S_IMODE(socket.stat().st_mode) == 0o600
    assert stat.S_IMODE((state / "desktop.json").stat().st_mode) == 0o600


async def test_actual_stdio_mcp_server_controls_existing_daemon(desktop):
    _daemon, _service, _state, socket, _factory = desktop
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "soulseek_mcp.desktop_mcp"],
        env={**os.environ, "SLSK_SOCKET": str(socket), "SLSK_USERNAME": "", "SLSK_PASSWORD": ""},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            inventory = await session.list_tools()
            assert {"soulseek_status", "soulseek_wishlist_add", "soulseek_download"}.issubset(
                {tool.name for tool in inventory.tools}
            )
            result = await session.call_tool("soulseek_wishlist_add", {"query": "Added through MCP stdio"})
            assert not result.isError
            desktop_view = await socket_request(socket, "snapshot")
            assert desktop_view["result"]["wishlist"][0]["query"] == "Added through MCP stdio"
            blocked = await session.call_tool("soulseek_connect", {})
            assert blocked.isError
            assert (await socket_request(socket, "status"))["result"]["connected"] is False


async def test_persistent_state_survives_daemon_restart_without_network(desktop):
    daemon, _service, state, socket, factory = desktop
    await mcp_request("wishlist_add", {"query": "Persist this search"})
    await mcp_request("configure", {"username": "remembered-user", "password": "not-persisted"})
    await daemon.close()
    assert not socket.exists()
    restored_service = DesktopService(state, client_factory=factory)
    restored = Daemon(restored_service, socket)
    await restored.start()
    try:
        snapshot = await mcp_request("snapshot")
        assert snapshot["wishlist"][0]["query"] == "Persist this search"
        assert snapshot["status"]["username"] == "remembered-user"
        assert snapshot["status"]["connected"] is False
        assert snapshot["status"]["credentials_configured"] is False
    finally:
        await restored.close()


async def test_second_daemon_cannot_replace_active_socket(desktop):
    _daemon, _service, state, socket, factory = desktop
    competitor = Daemon(DesktopService(state, client_factory=factory), socket)
    with pytest.raises(ClientError, match="already running"):
        await competitor.start()
    response = await socket_request(socket, "status")
    assert response["result"]["connected"] is False


async def test_invalid_calls_are_errors_and_do_not_break_following_requests(desktop):
    _daemon, _service, _state, socket, _factory = desktop
    invalid = await socket_request(socket, "__getattribute__", {"name": "config"})
    assert "error" in invalid
    wrong_field = await socket_request(socket, "configure", {"unknown": "field"})
    assert "error" in wrong_field
    disconnected = await socket_request(socket, "search", {"query": "test"})
    assert "error" in disconnected
    assert (await socket_request(socket, "snapshot"))["result"]["status"]["connected"] is False


async def test_regular_file_at_socket_path_is_preserved(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="ss-collision-", dir="/tmp") as directory:
        state = Path(directory)
        socket = state / "backend.sock"
        socket.write_text("do not overwrite")
        daemon = Daemon(DesktopService(state), socket)
        with pytest.raises(ClientError, match="regular file"):
            await daemon.start()
        assert socket.read_text() == "do not overwrite"
