import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from aioslsk.events import SearchRequestSentEvent
from aioslsk.network.connection import ConnectionState
from aioslsk.protocol.primitives import DirectoryData, FileData
from aioslsk.search.model import SearchRequest, SearchType
from soulseek_mcp.desktop_service import DesktopService
from soulseek_mcp.service import ClientError, Search
from test_service import FakeClient, result_event


async def configured(tmp_path):
    fake = FakeClient()
    fake.transfers.get_uploads = lambda: []
    service = DesktopService(tmp_path / "state", client_factory=lambda _: fake)
    await service.configure(username="tester", password="secret-do-not-store", download_dir=str(tmp_path / "downloads"))
    await service.connect()
    return service, fake


async def test_private_credentials_and_nonsecret_persistence(tmp_path):
    s = DesktopService(tmp_path / "state")
    await s.configure(username="alice", password="sensitive-example", upload_slots=4)
    s.wishlist_add("rare album")
    content = (tmp_path / "state/desktop.json").read_text()
    assert "sensitive-example" not in content
    assert '"password"' not in content
    assert "sensitive-example" not in str(s.settings_get())
    assert (tmp_path / "state/desktop.json").stat().st_mode & 0o777 == 0o600
    restarted = DesktopService(tmp_path / "state")
    assert restarted.preferences["username"] == "alice"
    assert restarted.preferences["upload_slots"] == 4
    assert restarted.wishlist()["items"][0]["query"] == "rare album"
    assert not restarted.status()["credentials_configured"]
    await s.close()
    await restarted.close()


async def test_shared_folder_scanning_is_real_offline_and_confined(tmp_path):
    shared = tmp_path / "music"
    shared.mkdir()
    (shared / "album.txt").write_text("album")
    secret = tmp_path / "not-shared.txt"
    secret.write_text("secret")
    (shared / "outside.txt").symlink_to(secret)
    s = DesktopService(tmp_path / "state")
    await s.share_add(str(shared))
    await s._scan_task
    view = s.shares()
    assert view["total_files"] == 1
    assert view["directories"][0]["size_bytes"] == 5
    assert view["directories"][0]["error"] is None
    assert s._client is None  # No network client was started to scan files.
    await s.share_remove(str(shared))
    assert s.shares()["directories"] == []
    await s.close()


async def test_results_filter_sort_and_history(tmp_path):
    s, fake = await configured(tmp_path)
    query = await s.search("  test music  ")
    request = next(iter(fake.searches.requests.values()))
    await fake.events.emit(result_event(request, ["Album\\b.flac", "Album\\a.flac"]))
    rows = s.results(query["search_id"], filter="album", extension="flac", min_bitrate=800)["results"]
    assert [r["filename"] for r in rows] == ["Album\\a.flac", "Album\\b.flac"]
    assert s.results(query["search_id"], min_bitrate=1000)["results"] == []
    assert s.snapshot()["history"][0]["query"] == "test music"
    await s.close()


async def test_wishlist_events_create_bounded_results_without_downloading(tmp_path):
    s, fake = await configured(tmp_path)
    fake.settings = SimpleNamespace(searches=SimpleNamespace(wishlist=[]))
    wish = s.wishlist_add("rare album")["items"][0]
    req = SearchRequest(99, "rare album", search_type=SearchType.WISHLIST)
    fake.searches.requests[99] = req
    await fake.events.emit(SearchRequestSentEvent(req))
    await fake.events.emit(result_event(req, ["album\\track.flac"]))
    assert wish["last_count"] == 1
    assert len(s.results(wish["last_search_id"])["results"]) == 1
    assert fake.transfers.download_calls == []
    s.wishlist_update(wish["id"], False)
    assert not fake.settings.searches.wishlist[0].enabled
    await s.close()


async def test_transfer_journal_preserves_and_restores_partial_file(tmp_path):
    s, fake = await configured(tmp_path)
    query = await s.search("music")
    request = next(iter(fake.searches.requests.values()))
    await fake.events.emit(result_event(request, ["album\\track.flac"]))
    result = s.results(query["search_id"])["results"][0]
    transfer = await s.download(result["result_id"])
    path = Path(transfer["local_path"])
    path.write_bytes(b"partial")
    await s.disconnect()
    restarted, another_fake = await configured(tmp_path)
    row = restarted.transfers()["transfers"][0]
    assert row["state"] == "PAUSED"
    resumed = await restarted.resume_transfer(row["transfer_id"])
    assert resumed["state"] == "QUEUED"
    assert path.read_bytes() == b"partial"
    assert another_fake.transfers.queued_paths == [str(path)]
    await restarted.close()


async def test_folder_download_fetches_complete_peer_listing(tmp_path):
    s, fake = await configured(tmp_path)
    query = await s.search("album")
    request = next(iter(fake.searches.requests.values()))
    await fake.events.emit(result_event(request, ["album\\one.flac"]))
    commands = []

    async def execute(command, **kwargs):
        commands.append(command)
        return [DirectoryData("album", [FileData(1, "one.flac", 10, "flac", []),
                                         FileData(1, "two.flac", 12, "flac", [])])]

    fake.execute = execute
    response = await s.download_folder(query["search_id"], "peer", "album")
    assert response["queued_count"] == 2
    assert len(commands) == 1
    assert len(fake.transfers.download_calls) == 2
    assert len({str(Path(r["local_path"]).parent) for r in response["queued"]}) == 1
    await s.close()


async def test_invalid_settings_are_atomic(tmp_path):
    s = DesktopService(tmp_path / "state")
    before = s.settings_get()
    with pytest.raises(ClientError):
        await s.configure(username="changed", listen_port=70000)
    assert s.settings_get() == before
    with pytest.raises(ClientError):
        await s.configure(listen_port=60001)
    assert s.settings_get() == before
    await s.close()


async def test_reconnect_preserves_queue_after_unexpected_network_loss(tmp_path):
    s, fake = await configured(tmp_path)
    query = await s.search("music")
    request = next(iter(fake.searches.requests.values()))
    await fake.events.emit(result_event(request, ["album\\track.flac"]))
    transfer = await s.download(s.results(query["search_id"])["results"][0]["result_id"])
    fake.network.server_connection.state = ConnectionState.CLOSED
    await s.connect()
    rows = s.transfers()["transfers"]
    assert len(rows) == 1
    assert rows[0]["transfer_id"] == transfer["transfer_id"]
    assert rows[0]["state"] == "PAUSED"
    assert len(fake.transfers.download_calls) == 1  # Resume remains explicit.
    await s.close()


async def test_wishlist_event_cannot_steal_pending_manual_search(tmp_path):
    s, fake = await configured(tmp_path)
    fake.settings = SimpleNamespace(searches=SimpleNamespace(wishlist=[]))
    s.wishlist_add("rare album")
    pending = Search("pending", "manual query", s._clock())
    s._pending_search = pending
    await fake.events.emit(SearchRequestSentEvent(SearchRequest(99, "rare album", search_type=SearchType.WISHLIST)))
    assert pending.ticket is None
    s._pending_search = None
    await s.close()


async def test_queue_failure_remains_tracked_and_paused(tmp_path):
    s, fake = await configured(tmp_path)
    query = await s.search("music")
    request = next(iter(fake.searches.requests.values()))
    await fake.events.emit(result_event(request, ["album\\track.flac"]))

    async def fail_queue(transfer):
        transfer.state.VALUE.name = "QUEUED"
        raise RuntimeError("network queue failed")

    fake.transfers.queue = fail_queue
    with pytest.raises(ClientError, match="inspect the download list"):
        await s.download(s.results(query["search_id"])["results"][0]["result_id"])
    rows = s.transfers()["transfers"]
    assert len(rows) == 1
    assert rows[0]["state"] == "PAUSED"
    assert Path(rows[0]["local_path"]).is_file()
    assert len(fake.transfers.pause_calls) == 1
    await s.close()


async def test_archived_transfer_cannot_resume_outside_download_root(tmp_path):
    s, fake = await configured(tmp_path)
    query = await s.search("music")
    request = next(iter(fake.searches.requests.values()))
    await fake.events.emit(result_event(request, ["album\\track.flac"]))
    transfer = await s.download(s.results(query["search_id"])["results"][0]["result_id"])
    await s.disconnect()
    outside = tmp_path / "outside.flac"
    outside.write_bytes(b"keep")
    s._archive[transfer["transfer_id"]]["local_path"] = str(outside)
    await s.connect()
    with pytest.raises(ClientError, match="outside"):
        await s.resume_transfer(transfer["transfer_id"])
    assert len(fake.transfers.download_calls) == 1
    assert outside.read_bytes() == b"keep"
    await s.close()
