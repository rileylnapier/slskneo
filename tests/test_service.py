import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from aioslsk.events import EventBus, SearchRequestSentEvent, SearchResultEvent
from aioslsk.protocol.primitives import Attribute, FileData
from aioslsk.search.model import SearchRequest, SearchResult
from aioslsk.network.connection import ConnectionState
from soulseek_mcp.service import ClientError, Config, SoulseekService, build_client


class FakeSearches:
    def __init__(self, events):
        self.events = events
        self.requests = {}
        self.counter = 0
        self.early_result = False

    async def search(self, query):
        self.counter += 1
        request = SearchRequest(ticket=self.counter, query=query)
        request.timer = Mock()
        self.requests[request.ticket] = request
        await self.events.emit(SearchRequestSentEvent(request))
        if self.early_result:
            await self.events.emit(result_event(request, ["early.flac"]))
        return request

    def remove_request(self, ticket):
        self.requests.pop(ticket)


class FakeTransfer:
    def __init__(self, username, remote_path):
        self.username = username
        self.remote_path = remote_path
        self.local_path = None
        self.state = SimpleNamespace(VALUE=SimpleNamespace(name="PAUSED"))
        self.filesize = 1024
        self.bytes_transferred = 0
        self.place_in_queue = None

    def get_speed(self):
        return 0


class FakeTransfers:
    def __init__(self):
        self.download_calls = []
        self.queued_paths = []
        self.pause_calls = []

    async def download(self, username, filename, paused=False):
        self.download_calls.append((username, filename, paused))
        return FakeTransfer(username, filename)

    async def queue(self, transfer):
        self.queued_paths.append(transfer.local_path)
        transfer.state.VALUE.name = "QUEUED"

    async def pause(self, transfer):
        self.pause_calls.append(transfer)
        transfer.state.VALUE.name = "PAUSED"


class FakeClient:
    def __init__(self):
        self.events = EventBus()
        self.searches = FakeSearches(self.events)
        self.transfers = FakeTransfers()
        self.session = None
        self.network = SimpleNamespace(server_connection=SimpleNamespace(state=ConnectionState.CLOSED))
        self.starts = 0
        self.stops = 0
        self.login_error = None

    async def start(self):
        self.starts += 1
        self.network.server_connection.state = ConnectionState.CONNECTED

    async def login(self):
        if self.login_error:
            raise self.login_error
        self.session = object()

    async def stop(self):
        self.stops += 1
        self.session = None
        self.network.server_connection.state = ConnectionState.CLOSED


def result_event(request, names, *, locked=False, username="peer"):
    files = [FileData(1, name, 1024, "flac", [Attribute(0, 900)]) for name in names]
    peer = SearchResult(request.ticket, username, True, 12345, 0,
                        shared_items=[] if locked else files,
                        locked_results=files if locked else [])
    return SearchResultEvent(request, peer)


@pytest.fixture
def configured(tmp_path):
    config = Config(username="test-user", password="private-password", download_dir=tmp_path / "downloads")
    fake = FakeClient()
    service = SoulseekService(config, lambda _: fake)
    return service, fake


async def add_result(service, fake, filename="music\\track.flac", **kwargs):
    search = await service.search("test music")
    request = list(fake.searches.requests.values())[-1]
    await fake.events.emit(result_event(request, [filename], **kwargs))
    return service.results(search["search_id"])["results"][0]


async def test_configuration_and_discovery_never_start_network(configured):
    service, fake = configured
    assert service.status()["connected"] is False
    assert fake.starts == 0
    assert "private-password" not in repr(service.config)
    assert "private-password" not in str(service.status())
    unconfigured = SoulseekService(Config(), Mock(side_effect=AssertionError("factory must not run")))
    with pytest.raises(ClientError, match="SLSK_USERNAME"):
        await unconfigured.connect()


def test_real_library_settings_bound_storage_and_disable_side_effects():
    client = build_client(Config(username="user", password="pass"))
    assert client.settings.searches.send.store_results is False
    assert client.settings.searches.send.request_timeout == 30
    assert client.settings.network.upnp.enabled is False
    assert client.settings.network.server.reconnect.auto is False
    assert client.settings.shares.directories == []
    assert client.settings.shares.scan_on_start is False
    assert client.settings.rooms.auto_join is False


async def test_failed_login_cleans_up_without_disclosing_secret(configured):
    service, fake = configured
    fake.login_error = RuntimeError("private-password was rejected")
    with pytest.raises(ClientError) as caught:
        await service.connect()
    assert "private-password" not in str(caught.value)
    assert fake.stops == 1
    assert not service.connected


async def test_stale_session_is_not_reported_connected(configured):
    service, fake = configured
    await service.connect()
    fake.network.server_connection.state = ConnectionState.CLOSED
    assert fake.session is not None
    assert service.status()["connected"] is False
    with pytest.raises(ClientError, match="Not connected"):
        await service.search("example")


async def test_failed_shutdown_prevents_a_second_client(configured):
    service, fake = configured
    await service.connect()

    async def bad_stop():
        raise RuntimeError("cannot stop")

    fake.stop = bad_stop
    with pytest.raises(ClientError, match="shutdown failed"):
        await service.disconnect()
    with pytest.raises(ClientError, match="previous client failed to stop"):
        await service.connect()
    assert fake.starts == 1


async def test_connection_idempotence_and_early_results(configured):
    service, fake = configured
    await asyncio.gather(service.connect(), service.connect())
    assert fake.starts == 1
    fake.searches.early_result = True
    search = await service.search("example")
    page = service.results(search["search_id"])
    assert page["results"][0]["filename"] == "early.flac"
    assert fake.transfers.download_calls == []


async def test_deduplication_pagination_and_result_limit(configured):
    service, fake = configured
    service.config = replace(service.config, max_results_per_search=3)
    await service.connect()
    search = await service.search("test")
    request = next(iter(fake.searches.requests.values()))
    await fake.events.emit(result_event(request, ["a.flac", "a.flac", "b.flac"]))
    first = service.results(search["search_id"], limit=1)
    assert first["total_retained"] == 2
    assert first["next_offset"] == 1
    assert service.results(search["search_id"], offset=1)["results"][0]["filename"] == "b.flac"
    await fake.events.emit(result_event(request, ["c.flac", "d.flac"]))
    full = service.results(search["search_id"])
    assert full["total_retained"] == 3
    assert full["truncated"] is True
    assert full["collecting"] is False
    assert request.ticket not in fake.searches.requests
    request.timer.cancel.assert_called_once()
    for offset, limit in [(-1, 1), (0, 0), (0, 101)]:
        with pytest.raises(ClientError):
            service.results(search["search_id"], offset, limit)


async def test_eviction_and_expiry_remove_library_requests(configured):
    service, fake = configured
    service.config = replace(service.config, max_searches=1)
    now = [1.0]
    service._clock = lambda: now[0]
    await service.connect()
    first = await service.search("first")
    old_request = next(iter(fake.searches.requests.values()))
    second = await service.search("second")
    with pytest.raises(ClientError, match="expired"):
        service.results(first["search_id"])
    old_request.timer.cancel.assert_called_once()
    assert len(fake.searches.requests) == 1
    now[0] += 601
    with pytest.raises(ClientError, match="expired"):
        service.results(second["search_id"])
    assert fake.searches.requests == {}


async def test_download_requires_selected_unlocked_result(configured):
    service, fake = configured
    await service.connect()
    with pytest.raises(ClientError, match="result_id"):
        await service.download("invented")
    locked = await add_result(service, fake, locked=True)
    with pytest.raises(ClientError, match="locked"):
        await service.download(locked["result_id"])
    assert fake.transfers.download_calls == []


async def test_download_is_contained_idempotent_and_pause_preserves_file(configured):
    service, fake = configured
    await service.connect()
    result = await add_result(service, fake, "..\\..\\escape.flac")
    download = await service.download(result["result_id"])
    path = Path(download["local_path"])
    assert path.is_relative_to(service.config.download_dir)
    assert path.name == "escape.flac"
    assert path.parent.name == download["transfer_id"]
    assert fake.transfers.download_calls == [("peer", "..\\..\\escape.flac", True)]
    assert fake.transfers.queued_paths == [str(path)]
    path.write_bytes(b"partial")
    again = await service.download(result["result_id"])
    assert again["transfer_id"] == download["transfer_id"]
    assert again["already_queued"] is True
    assert len(fake.transfers.download_calls) == 1
    paused = await service.pause_transfer(download["transfer_id"])
    assert paused["state"] == "PAUSED"
    assert path.read_bytes() == b"partial"
    assert (await service.resume_transfer(download["transfer_id"]))["state"] == "QUEUED"
    await service.disconnect()
    assert path.read_bytes() == b"partial"
    assert service.transfers()["total"] == 0


async def test_invalid_peer_filename_cannot_create_download(configured):
    service, fake = configured
    await service.connect()
    result = await add_result(service, fake, "evil\x00.flac")
    with pytest.raises(ClientError, match="filename"):
        await service.download(result["result_id"])
    assert fake.transfers.download_calls == []
    assert not service.config.download_dir.exists()


async def test_failed_queue_remains_tracked_and_cannot_duplicate_path(configured):
    service, fake = configured
    await service.connect()
    result = await add_result(service, fake)

    async def bad_queue(transfer):
        transfer.state.VALUE.name = "QUEUED"
        raise RuntimeError("network failed")

    fake.transfers.queue = bad_queue
    with pytest.raises(ClientError, match="inspect transfer"):
        await service.download(result["result_id"])
    transfers = service.transfers()["transfers"]
    assert len(transfers) == 1
    assert transfers[0]["state"] == "PAUSED"
    path = transfers[0]["local_path"]
    again = await service.download(result["result_id"])
    assert again["local_path"] == path
    assert again["already_queued"] is True
    assert len(fake.transfers.download_calls) == 1


def test_config_env_validation_and_password_redaction(tmp_path):
    config = Config.from_env({"SLSK_USERNAME": "user", "SLSK_PASSWORD": "sensitive", "SLSK_DOWNLOAD_DIR": str(tmp_path), "SLSK_SERVER_PORT": "2271"})
    assert config.server_port == 2271
    assert "sensitive" not in repr(config)
    for invalid in ["abc", "0", "65536"]:
        with pytest.raises(ClientError, match="SLSK_SERVER_PORT"):
            Config.from_env({"SLSK_SERVER_PORT": invalid})



async def test_listening_port_conflict_is_distinct_from_bad_credentials(configured):
    from aioslsk.exceptions import ListeningConnectionFailedError
    service, fake = configured

    async def occupied_port():
        raise ListeningConnectionFailedError('private dependency detail')

    fake.start = occupied_port
    with pytest.raises(ClientError, match='Another Soulseek app') as failure:
        await service.connect()
    assert 'check credentials' not in str(failure.value)
    assert 'private dependency detail' not in str(failure.value)
    assert not service.connected
    assert fake.stops == 1


async def test_rejected_login_does_not_blame_ports_or_expose_server_details(configured):
    from aioslsk.exceptions import AuthenticationError
    service, fake = configured

    async def rejected():
        raise AuthenticationError('INVALIDPASS', 'private dependency detail')

    fake.login = rejected
    with pytest.raises(ClientError, match='Soulseek rejected this login') as failure:
        await service.connect()
    assert 'ports' not in str(failure.value)
    assert 'private dependency detail' not in str(failure.value)
    assert not service.connected
    assert fake.stops == 1
