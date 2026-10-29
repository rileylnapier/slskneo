from datetime import datetime, timedelta, timezone

import pytest

from soulseek_mcp.listening import ListeningLibrary
from soulseek_mcp.service import ClientError
from test_desktop_backend import configured
from test_service import result_event


@pytest.fixture
def library(tmp_path):
    store = ListeningLibrary(tmp_path / "library.sqlite3")
    yield store
    store.close()


def seed(store):
    return store.import_batch([{"artist": "A", "title": "Song (B Remix)"},
                               {"artist": "A", "title": "Song (C Remix)"}], "Library")["track_ids"]


def day(offset=0):
    return (datetime.now(timezone.utc).date() - timedelta(days=offset)).isoformat()


def play(store, track_id, **changes):
    return store.research_record(**{"track_id": track_id, "kind": "dj_play", "subject": "DJ One",
                                    "event_date": day(), "url": "https://www.1001tracklists.com/tracklist/set1/index.html",
                                    **changes})


def test_candidates_do_not_count_as_support_and_versions_stay_separate(library):
    first, second = seed(library)
    observation = play(library, first)
    assert library.research_summary(first)["confirmed_djs"] == 0
    library.research_review(observation["id"], True)
    assert library.research_summary(first)["confirmed_djs"] == 1
    assert library.research_summary(second)["evidence"] == []
    library.research_review(observation["id"], False)
    assert library.research_summary(first)["confirmed_djs"] == 0
    assert not library.inbox()["tracks"][0]["favorite"]


def test_repeat_set_and_repeat_dj_do_not_inflate_unique_support(library):
    first, _ = seed(library)
    play(library, first, confirmed=True)
    play(library, first, confirmed=True, url="https://www.1001tracklists.com/tracklist/set1/index.html#t42")
    play(library, first, confirmed=True, subject="DJ ONE", url="https://soundcloud.com/dj/set2", event_date=day(8))
    play(library, first, confirmed=True, subject="DJ Two", url="https://soundcloud.com/another/set3")
    stats = library.research_summary(first)
    assert len(stats["evidence"]) == stats["dj_plays"] == 3
    assert stats["confirmed_djs"] == stats["djs_last_7_days"] == 2
    assert stats["djs_previous_7_days"] == 1


def test_chart_history_separates_charts_and_dates_and_survives_reimport(library):
    first, _ = seed(library)
    args = dict(track_id=first, kind="chart_position", url="https://www.beatport.com/top-100",
                event_date=day(1), subject="Global Top 100", position=45, confirmed=True)
    library.research_record(**args)
    library.research_record(**{**args, "position": 44})  # Correct the same daily observation.
    library.research_record(**{**args, "event_date": day(), "position": 20})
    library.research_record(**{**args, "subject": "House Top 100", "position": 8})
    seed(library)
    path = library.db.execute("PRAGMA database_list").fetchone()[2]
    reopened = ListeningLibrary(path)
    try:
        history = reopened.research_summary(first)
        assert len(history["evidence"]) == 3
        assert {e["metric"] for e in history["evidence"]} == {44, 20, 8}
        assert history["confirmed_djs"] == 0  # Sales charts aren't DJ support.
    finally:
        reopened.close()


@pytest.mark.parametrize("changes", [
    {"url": "https://evil.test/tracklist"}, {"url": "file:///tmp/set"}, {"url": ""},
    {"url": "https://www.beatport.com/top-100"}, {"event_date": "unknown"},
    {"event_date": day(-1)}, {"subject": ""}, {"confirmed": 1},
    {"kind": "soulseek_snapshot"},
    {"kind": "chart_position", "url": "https://www.beatport.com/top-100", "position": True},
])
def test_invalid_evidence_is_not_saved(library, changes):
    first, _ = seed(library)
    with pytest.raises(ValueError):
        play(library, first, **changes)
    assert library.research_evidence(first) == []


async def test_soulseek_sample_uses_all_retained_results_and_unique_peers(tmp_path):
    service, fake = await configured(tmp_path)
    try:
        first, second = seed(service.listening)
        result = await service.dispatch("discovery_research_search", {"track_id": first})
        sid = result["search_id"]
        request = next(iter(fake.searches.requests.values()))
        await fake.events.emit(result_event(request, ["Music/a.flac", "Music/a.mp3"], username="peer1"))
        await fake.events.emit(result_event(request, ["Other Remix/a.flac"], username="peer2"))
        assert service.results(sid, limit=1, filter="a.mp3")["research_track_id"] == first
        with pytest.raises(ClientError, match="finish"):
            await service.dispatch("discovery_research_capture", {"search_id": sid})
        service.stop_search(sid)
        await service.dispatch("discovery_research_capture", {"search_id": sid})
        await service.dispatch("discovery_research_capture", {"search_id": sid})
        summary = service.listening.research_summary(first)
        assert len(summary["evidence"]) == 1  # Recording one search twice isn't a new sample.
        observation = summary["evidence"][0]
        assert observation["metric"] == observation["details"]["distinct_peers"] == 2
        assert observation["details"]["matching_files"] == 3
        assert observation["status"] == "candidate" and summary["confirmed_djs"] == 0
        assert "peer1" not in str(observation)  # Counts only; no peer identity history.
        assert not service.listening.research_evidence(second)
        with pytest.raises(ValueError):
            service.listening.research_review(observation["id"], True)
        unrelated = await service.search("1975")
        service.stop_search(unrelated["search_id"])
        with pytest.raises(ClientError, match="collected track"):
            await service.dispatch("discovery_research_capture", {"search_id": unrelated["search_id"]})
        assert fake.transfers.download_calls == []
    finally:
        await service.close()


async def test_zero_results_and_truncated_search_are_explicit(tmp_path):
    service, fake = await configured(tmp_path)
    try:
        first, _ = seed(service.listening)
        result = await service.research_search(first)
        service.stop_search(result["search_id"])
        service.research_capture(result["search_id"])
        assert service.listening.research_evidence(first)[0]["metric"] == 0
        second = await service.research_search(first)
        service._searches[second["search_id"]].truncated = True
        service.stop_search(second["search_id"])
        service.research_capture(second["search_id"])
        assert any(e["details"]["truncated"] for e in service.listening.research_evidence(first))
        assert len(service.listening.research_evidence(first)) == 2
    finally:
        await service.close()
