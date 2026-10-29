import math

import pytest

from soulseek_mcp.listening import ListeningLibrary, resolve_link, safe_url


@pytest.fixture
def library(tmp_path):
    store = ListeningLibrary(tmp_path / "music.sqlite3")
    yield store
    store.close()


def sample(**changes):
    return {"artist": "Artist", "title": "Track (Editor Remix)", "genre": "House",
            "url": "https://www.beatport.com/track/track/123",
            "preview_url": "https://geo-samples.beatport.com/track/123.mp3", **changes}


def test_favorites_ratings_and_sources_survive_refresh_and_reopen(library):
    track_id = library.import_batch([sample()], "Beatport")["track_ids"][0]
    library.react(track_id, favorite=True, rating=-1)
    library.import_batch([sample()], "Beatport")
    library.import_batch([sample(url="https://soundcloud.com/artist/track", preview_url="")], "SoundCloud")
    t = library.inbox()["tracks"][0]
    assert t["favorite"] and t["rating"] == -1
    assert len(t["sources"]) == 2
    path = library.db.execute("PRAGMA database_list").fetchone()[2]
    reopened = ListeningLibrary(path)
    assert reopened.inbox()["tracks"][0]["favorite"]
    reopened.close()


def test_explicit_feedback_changes_related_track_rank(library):
    ids = library.import_batch([sample(), sample(title="Another"), sample(artist="Other", title="Different", genre="Techno")], "Beatport")["track_ids"]
    library.react(ids[0], rating=1)
    ranked = {t["id"]: t for t in library.inbox()["tracks"]}
    assert ranked[ids[1]]["score"] > ranked[ids[2]]["score"]
    assert any("Artist" in reason for reason in ranked[ids[1]]["reasons"])
    library.react(ids[0], rating=-1)
    ranked = {t["id"]: t for t in library.inbox()["tracks"]}
    assert ranked[ids[1]]["score"] < ranked[ids[2]]["score"]


def test_follow_is_local_and_reversible(library):
    library.import_batch([sample()], "Beatport")
    library.follow("Editor")
    assert "You follow Editor." in library.inbox()["tracks"][0]["reasons"]
    library.follow("Editor", False)
    assert not any(c["followed"] for c in library.inbox()["tracks"][0]["credits"])


def test_source_context_cannot_overwrite_user_feedback(library):
    track_id = library.import_batch([sample()], "Beatport")["track_ids"][0]
    library.react(track_id, favorite=True, rating=1)
    library.import_batch([sample(favorite=False, rating=-1, label="New label")], "Beatport")
    t = library.inbox()["tracks"][0]
    assert t["favorite"] and t["rating"] == 1 and t["label"] == "New label"


def test_remix_versions_do_not_merge(library):
    library.import_batch([sample(), sample(title="Track (Other Remix)")], "Beatport")
    assert len(library.inbox()["tracks"]) == 2


def test_structured_people_survive_unstructured_cross_reference(library):
    a = sample(artist="A & B", credits=[{"name": "A", "role": "artist"}, {"name": "B", "role": "artist"}])
    library.import_batch([a], "Beatport")
    library.follow("A")
    library.import_batch([sample(artist="A & B", url="https://hypeddit.com/track/abc")], "Hypeddit")
    t = library.inbox()["tracks"][0]
    assert {c["name"] for c in t["credits"]} == {"A", "B"}
    assert next(c for c in t["credits"] if c["name"] == "A")["followed"]


def test_invalid_batch_does_not_partially_import(library):
    with pytest.raises(ValueError):
        library.import_batch([sample(), sample(title="Bad", preview_url="file:///etc/passwd")], "Beatport")
    assert library.inbox()["tracks"] == []


def test_preview_cues_are_bound_to_the_exact_audio(library):
    track_id = library.import_batch([sample()], "Beatport")["track_ids"][0]
    preview = sample()["preview_url"]
    library.cue(track_id, preview, 23.5, "Great moment")
    with pytest.raises(ValueError):
        library.cue(track_id, "https://geo-samples.beatport.com/wrong.mp3", 23)
    with pytest.raises(ValueError):
        library.cue(track_id, preview, math.nan)
    assert library.inbox()["tracks"][0]["cues"][0]["seconds"] == 23.5
    library.cue(track_id, preview, 23.5, remove=True)
    assert not library.inbox()["tracks"][0]["cues"]


@pytest.mark.parametrize("url", ["file:///etc/passwd", "javascript:alert(1)", "https://beatport.com.evil.test/a", "https://user:secret@beatport.com/a", "https://127.0.0.1/a", "https://beatport.com:8080/a"])
def test_unsafe_source_links_are_rejected(url):
    with pytest.raises(ValueError):
        safe_url(url)


def test_unsupported_provider_can_be_saved_manually_without_a_network_call():
    result = resolve_link("https://www.1001tracklists.com/tracklist/example/index.html")
    assert result["source"] == "1001Tracklists"
    assert result["artist"] == result["title"] == ""


def test_unknown_track_and_invalid_rating_rejected(library):
    with pytest.raises(ValueError):
        library.react("missing", favorite=True)
    track_id = library.import_batch([sample()], "Beatport")["track_ids"][0]
    with pytest.raises(ValueError):
        library.react(track_id, rating=True)


@pytest.mark.asyncio
async def test_desktop_dispatch_persists_discovery_without_connecting(tmp_path):
    from soulseek_mcp.desktop_service import DesktopService
    service = DesktopService(tmp_path)
    imported = await service.dispatch("discovery_import", {"records": [sample()], "source": "Beatport"})
    await service.dispatch("discovery_react", {"track_id": imported["track_ids"][0], "favorite": True})
    assert (await service.dispatch("discovery_inbox", {}))["tracks"][0]["favorite"]
    assert not service._client
    await service.close()
