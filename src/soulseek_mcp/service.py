"""Bounded, session-scoped operations over the aioslsk client.

Credentials are read only from the process environment. Search result names are
untrusted peer data. Downloads use selected results and locally generated paths.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass, field
import os
from pathlib import Path, PureWindowsPath
import time
from typing import Any, Callable, Mapping
from uuid import uuid4

from aioslsk.client import SoulSeekClient
from aioslsk.exceptions import AuthenticationError, ListeningConnectionFailedError
from aioslsk.events import (
    SearchRequestRemovedEvent,
    SearchRequestSentEvent,
    SearchResultEvent,
)
from aioslsk.settings import Settings
from aioslsk.network.connection import ConnectionState


class ClientError(ValueError):
    """A safe, actionable error that may be returned through MCP."""


@dataclass(frozen=True)
class Config:
    username: str = ""
    password: str = field(default="", repr=False)
    download_dir: Path = field(default_factory=lambda: Path.home() / "Downloads" / "SoulseekMCP")
    server: str = "server.slsknet.org"
    server_port: int = 2416
    listen_port: int = 60000
    obfuscated_port: int = 60001
    max_searches: int = 8
    max_results_per_search: int = 1000
    max_transfers: int = 200
    search_seconds: int = 30
    retention_seconds: int = 600

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Config:
        values = os.environ if env is None else env

        def port(name: str, default: int) -> int:
            try:
                value = int(values.get(name, str(default)))
                if not 1 <= value <= 65535:
                    raise ValueError
                return value
            except ValueError:
                raise ClientError(f"{name} must be a port between 1 and 65535") from None

        return cls(
            username=values.get("SLSK_USERNAME", ""),
            password=values.get("SLSK_PASSWORD", ""),
            download_dir=Path(values.get("SLSK_DOWNLOAD_DIR", str(Path.home() / "Downloads" / "SoulseekMCP"))).expanduser().resolve(),
            server=values.get("SLSK_SERVER", "server.slsknet.org"),
            server_port=port("SLSK_SERVER_PORT", 2416),
            listen_port=port("SLSK_LISTEN_PORT", 60000),
            obfuscated_port=port("SLSK_OBFUSCATED_PORT", 60001),
        )


def build_client(config: Config) -> SoulSeekClient:
    settings = Settings(
        credentials={"username": config.username, "password": config.password},
        network={
            "server": {"hostname": config.server, "port": config.server_port, "reconnect": {"auto": False}},
            "listening": {"port": config.listen_port, "obfuscated_port": config.obfuscated_port},
            "upnp": {"enabled": False},
        },
        # The MCP service owns capped results; avoid an unbounded second copy.
        searches={"send": {"store_results": False, "request_timeout": config.search_seconds}},
        shares={"download": str(config.download_dir), "directories": [], "scan_on_start": False},
        rooms={"auto_join": False, "private_room_invites": False},
    )
    return SoulSeekClient(settings)


@dataclass
class Search:
    id: str
    query: str
    created: float
    ticket: int | None = None
    active: bool = True
    results: OrderedDict[str, dict[str, Any]] = field(default_factory=OrderedDict)
    keys: set[tuple[str, str]] = field(default_factory=set)
    truncated: bool = False


class SoulseekService:
    def __init__(self, config: Config, client_factory: Callable[[Config], Any] = build_client,
                 clock: Callable[[], float] = time.monotonic):
        self.config = config
        self._factory = client_factory
        self._clock = clock
        self._client: Any = None
        self._lock = asyncio.Lock()
        self._searches: OrderedDict[str, Search] = OrderedDict()
        self._tickets: dict[int, str] = {}
        self._pending_search: Search | None = None
        self._transfers: OrderedDict[str, Any] = OrderedDict()
        self._transfer_keys: dict[tuple[str, str], str] = {}
        self._previous_exception_handler: Any = None
        self._shutdown_failed = False

    @property
    def connected(self) -> bool:
        return (self._client is not None and self._client.session is not None
                and self._client.network.server_connection.state == ConnectionState.CONNECTED)

    def status(self) -> dict[str, Any]:
        self._expire_searches()
        return {
            "client": "soulseek-mcp", "backend": "aioslsk", "connected": self.connected,
            "credentials_configured": bool(self.config.username and self.config.password),
            "download_directory": str(self.config.download_dir),
            "searches": len(self._searches), "transfers": len(self._transfers),
            "sharing_enabled": False, "persistence": "current MCP process only",
        }

    async def connect(self) -> dict[str, Any]:
        async with self._lock:
            if self._shutdown_failed:
                raise ClientError("A previous client failed to stop. Restart the MCP server before connecting again.")
            if self.connected:
                return self.status()
            if not self.config.username or not self.config.password:
                raise ClientError("Set SLSK_USERNAME and SLSK_PASSWORD in the server environment, then restart the MCP server.")
            if self._client is not None:
                await self._stop()
            client = self._factory(self.config)
            self._client = client
            self._previous_exception_handler = asyncio.get_running_loop().get_exception_handler()
            client.events.register(SearchRequestSentEvent, self._on_search_sent)
            client.events.register(SearchRequestRemovedEvent, self._on_search_removed)
            client.events.register(SearchResultEvent, self._on_result)
            try:
                async with asyncio.timeout(30):
                    await client.start()
                    await client.login()
            except BaseException as error:
                try:
                    await self._stop()
                except ClientError:
                    pass
                if isinstance(error, asyncio.CancelledError):
                    raise
                if isinstance(error, ListeningConnectionFailedError):
                    raise ClientError("Could not open the local listening ports. Another Soulseek app may be using them. "
                                      "Close that app or choose different ports in Settings → Advanced connection.") from None
                if isinstance(error, AuthenticationError):
                    raise ClientError("Soulseek rejected this login. Check your Soulseek username and password "
                                      "in Settings, then save and connect again.") from None
                raise ClientError(f"Connection failed ({type(error).__name__}); check credentials, server and listening ports.") from None
            return self.status()

    async def disconnect(self) -> dict[str, Any]:
        async with self._lock:
            await self._stop()
            return self.status()

    async def _stop(self) -> None:
        client, self._client = self._client, None
        if client is None:
            return
        for search in list(self._searches.values()):
            self._remove_request(search, client)
        self._searches.clear()
        self._tickets.clear()
        self._transfers.clear()
        self._transfer_keys.clear()
        try:
            async with asyncio.timeout(15):
                await client.stop()
        except Exception as error:
            self._shutdown_failed = True
            raise ClientError(f"Client shutdown failed ({type(error).__name__}); restart the MCP server before reconnecting.") from None
        finally:
            loop = asyncio.get_running_loop()
            if loop.get_exception_handler() == getattr(client, "_exception_handler", None):
                loop.set_exception_handler(self._previous_exception_handler)

    def _require_client(self) -> Any:
        if not self.connected:
            raise ClientError("Not connected. Configure credentials and call soulseek_connect first.")
        return self._client

    def _remove_request(self, search: Search, client: Any = None) -> None:
        client = client or self._client
        if client is not None and search.ticket in client.searches.requests:
            request = client.searches.requests[search.ticket]
            # remove_request does not cancel its timeout timer in aioslsk 1.6.4.
            if request.timer is not None:
                request.timer.cancel()
            client.searches.remove_request(search.ticket)
        search.active = False

    def _expire_searches(self) -> None:
        now = self._clock()
        for search in list(self._searches.values()):
            if now - search.created >= self.config.retention_seconds:
                self._forget_search(search)

    def _forget_search(self, search: Search) -> None:
        self._remove_request(search)
        self._tickets.pop(search.ticket, None)
        self._searches.pop(search.id, None)

    async def search(self, query: str) -> dict[str, Any]:
        query = query.strip()
        if not query or len(query) > 256 or any(ord(c) < 32 for c in query):
            raise ClientError("Search query must contain 1–256 printable characters.")
        async with self._lock:
            client = self._require_client()
            self._expire_searches()
            while len(self._searches) >= self.config.max_searches:
                self._forget_search(next(iter(self._searches.values())))
            search = Search(uuid4().hex, query, self._clock())
            self._searches[search.id] = search
            self._pending_search = search
            try:
                async with asyncio.timeout(15):
                    request = await client.searches.search(query)
                self._bind_search(search, request.ticket)
            except BaseException as error:
                self._forget_search(search)
                if isinstance(error, asyncio.CancelledError):
                    raise
                raise ClientError(f"Search could not start ({type(error).__name__}).") from None
            finally:
                self._pending_search = None
            return {"search_id": search.id, "query": query, "collecting_seconds": self.config.search_seconds,
                    "result_limit": self.config.max_results_per_search, "next_step": "Call soulseek_results with this search_id; results arrive asynchronously."}

    def _bind_search(self, search: Search, ticket: int) -> None:
        search.ticket = ticket
        self._tickets[ticket] = search.id

    def _on_search_sent(self, event: SearchRequestSentEvent) -> None:
        # Bind before search() returns so early results are not dropped.
        if self._pending_search is not None:
            self._bind_search(self._pending_search, event.query.ticket)

    def _on_search_removed(self, event: SearchRequestRemovedEvent) -> None:
        search = self._searches.get(self._tickets.get(event.query.ticket, ""))
        if search is not None:
            search.active = False

    def _on_result(self, event: SearchResultEvent) -> None:
        search = self._searches.get(self._tickets.get(event.query.ticket, ""))
        if search is None or not search.active:
            return
        peer = event.result
        if not peer.username or len(peer.username) > 256:
            return
        for locked, files in ((False, peer.shared_items), (True, peer.locked_results)):
            for file in files:
                if len(search.results) >= self.config.max_results_per_search:
                    search.truncated = True
                    self._remove_request(search)
                    return
                key = (peer.username, file.filename)
                if key in search.keys or not file.filename or len(file.filename) > 4096:
                    continue
                result_id = uuid4().hex
                attributes = {str(attribute.key): int(attribute.value) for attribute in file.attributes[:32]}
                search.results[result_id] = {
                    "result_id": result_id, "username": peer.username,
                    "filename": file.filename, "size_bytes": file.filesize,
                    "extension": file.extension[:32], "locked": locked,
                    "free_slots": peer.has_free_slots, "speed_bytes_per_second": peer.avg_speed,
                    "queue_size": peer.queue_size, "attributes": attributes,
                }
                search.keys.add(key)

    @staticmethod
    def _pagination(offset: int, limit: int) -> None:
        if offset < 0 or not 1 <= limit <= 100:
            raise ClientError("offset must be nonnegative and limit must be between 1 and 100.")

    def results(self, search_id: str, offset: int = 0, limit: int = 25) -> dict[str, Any]:
        self._pagination(offset, limit)
        self._expire_searches()
        search = self._searches.get(search_id)
        if search is None:
            raise ClientError("Unknown or expired search_id. Start a new search.")
        items = list(search.results.values())[offset:offset + limit]
        end = offset + len(items)
        return {"search_id": search.id, "query": search.query, "collecting": search.active,
                "total_retained": len(search.results), "truncated": search.truncated,
                "offset": offset, "next_offset": end if end < len(search.results) else None,
                "results": items, "content_origin": "Untrusted peer-provided filenames and metadata."}

    def stop_search(self, search_id: str) -> dict[str, Any]:
        search = self._searches.get(search_id)
        if search is None:
            raise ClientError("Unknown or expired search_id.")
        self._remove_request(search)
        return {"search_id": search_id, "collecting": False, "total_retained": len(search.results)}

    async def download(self, result_id: str) -> dict[str, Any]:
        async with self._lock:
            client = self._require_client()
            self._expire_searches()
            result = next((search.results[result_id] for search in self._searches.values() if result_id in search.results), None)
            if result is None:
                raise ClientError("Unknown or expired result_id. Select an actual result returned by soulseek_results.")
            if result["locked"]:
                raise ClientError("This result is locked by the peer and cannot be queued through this tool.")
            key = (result["username"], result["filename"])
            if key in self._transfer_keys:
                transfer_id = self._transfer_keys[key]
                return {**self._transfer_view(transfer_id), "already_queued": True}
            if len(self._transfers) >= self.config.max_transfers:
                raise ClientError("This session's transfer limit has been reached. Review transfers before restarting the server.")
            name = PureWindowsPath(result["filename"]).name
            if name in ("", ".", "..") or len(name.encode("utf-8")) > 240 or any(ord(c) < 32 for c in name):
                raise ClientError("The peer filename is not a supported local filename.")
            transfer_id = uuid4().hex
            directory = self.config.download_dir / transfer_id
            directory.mkdir(mode=0o700, parents=True, exist_ok=False)
            destination = directory / name
            # Do not permit the library's append-mode writer to follow an
            # existing path or dangling symlink when creating a new download.
            descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(descriptor)
            try:
                async with asyncio.timeout(15):
                    transfer = await client.transfers.download(*key, paused=True)
                    # Assign a generated local directory before the transfer can run.
                    transfer.local_path = str(destination)
                    self._transfers[transfer_id] = transfer
                    self._transfer_keys[key] = transfer_id
                    await client.transfers.queue(transfer)
            except Exception as error:
                if transfer_id in self._transfers:
                    try:
                        async with asyncio.timeout(5):
                            await client.transfers.pause(transfer)
                    except Exception:
                        pass  # The tracked state remains inspectable even if pausing failed.
                    raise ClientError(f"Could not queue download ({type(error).__name__}); inspect transfer {transfer_id} before retrying.") from None
                destination.unlink(missing_ok=True)
                directory.rmdir()
                raise ClientError(f"Could not queue download ({type(error).__name__}).") from None
            return self._transfer_view(transfer_id)

    def _transfer_view(self, transfer_id: str) -> dict[str, Any]:
        transfer = self._transfers[transfer_id]
        return {"transfer_id": transfer_id, "username": transfer.username,
                "filename": transfer.remote_path, "local_path": transfer.local_path,
                "state": transfer.state.VALUE.name, "size_bytes": transfer.filesize,
                "bytes_transferred": transfer.bytes_transferred,
                "speed_bytes_per_second": transfer.get_speed(), "queue_position": transfer.place_in_queue}

    def transfers(self, offset: int = 0, limit: int = 25) -> dict[str, Any]:
        self._pagination(offset, limit)
        ids = list(self._transfers)[offset:offset + limit]
        end = offset + len(ids)
        return {"transfers": [self._transfer_view(id) for id in ids], "total": len(self._transfers),
                "next_offset": end if end < len(self._transfers) else None}

    async def pause_transfer(self, transfer_id: str) -> dict[str, Any]:
        async with self._lock:
            client = self._require_client()
            transfer = self._transfers.get(transfer_id)
            if transfer is None:
                raise ClientError("Unknown transfer_id.")
            if transfer.state.VALUE.name not in ("PAUSED", "COMPLETE", "ABORTED", "FAILED"):
                try:
                    async with asyncio.timeout(15):
                        await client.transfers.pause(transfer)
                except Exception as error:
                    raise ClientError(f"Could not pause transfer ({type(error).__name__}).") from None
            return {**self._transfer_view(transfer_id), "partial_file_preserved": True}

    async def resume_transfer(self, transfer_id: str) -> dict[str, Any]:
        async with self._lock:
            client = self._require_client()
            transfer = self._transfers.get(transfer_id)
            if transfer is None:
                raise ClientError("Unknown transfer_id.")
            if transfer.state.VALUE.name != "PAUSED":
                raise ClientError("Only paused transfers can be resumed through this tool.")
            try:
                async with asyncio.timeout(15):
                    await client.transfers.queue(transfer)
            except Exception as error:
                raise ClientError(f"Could not resume transfer ({type(error).__name__}).") from None
            return self._transfer_view(transfer_id)

