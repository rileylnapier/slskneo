import pytest

from soulseek_mcp.discovery import DiscoveryStore, credits


@pytest.fixture
def store(tmp_path):
    db = DiscoveryStore(tmp_path / "discovery.sqlite3")
    yield db
    db.close()


def test_editor_is_distinct_from_original_artist():
    result = credits("Singer x Producer", "Song (Editor VIP Edit)")
    assert {tuple(c.values()) for c in result} == {
        ("Singer", "artist"), ("Producer", "artist"), ("Editor", "editor")}
    assert credits("Earth, Wind & Fire", "September (Extended Edit)") == [
        {"name": "Earth, Wind & Fire", "role": "artist"}]
    assert credits("Artist", "Song (Esentrik 2026 VIP Edit)")[-1]["name"] == "Esentrik"


def test_versions_and_sources_survive_reimport(store):
    first = {"artist": "Artist", "title": "Song (One Remix)", "status": "queued"}
    identity = store.import_tracks([first], "LDS")["track_ids"][0]
    store.feedback(identity, "pass")
    assert store.import_tracks([first], "LDS")["added"] == 0
    store.import_tracks([first], "Other", "https://example.org")
    store.import_tracks([{**first, "title": "Song (Two Remix)"}], "LDS")
    assert store.report()["track_count"] == 2
    assert store.db.execute("SELECT status FROM tracks WHERE id=?", (identity,)).fetchone()[0] == "pass"
    assert store.db.execute("SELECT COUNT(*) FROM sources WHERE track_id=?", (identity,)).fetchone()[0] == 2


def test_follow_matches_new_tracks_and_pass_removes_them(store):
    store.import_tracks([{"artist": "A", "title": "First (Editor Edit)"}], "LDS")
    store.follow("editor")
    result = store.import_tracks([{"artist": "B", "title": "Second (Editor Edit)"}], "LDS")
    matches = store.recommendations()
    assert len(matches) == 2
    assert "You follow Editor" in matches[0]["reasons"][0]
    store.feedback(result["track_ids"][0], "pass")
    assert len(store.recommendations()) == 1
    store.follow("Editor", False)
    assert not store.recommendations()


def test_queue_is_weak_evidence_and_does_not_follow_anyone(store):
    store.import_tracks([
        {"artist": "A", "title": "One (Person Remix)", "status": "queued"},
        {"artist": "B", "title": "Two (Person Remix)"},
    ], "LDS")
    p = next(p for p in store.people() if p["name"] == "Person")
    assert p["score"] == 2 and not p["followed"] and not p["identity_verified"]
    assert len(store.recommendations()) == 1


def test_bad_import_is_atomic(store):
    with pytest.raises(ValueError):
        store.import_tracks([{"artist": "A", "title": "Good"}, {"artist": "B"}], "LDS")
    assert store.report()["track_count"] == 0


def test_group_names_are_not_silently_split(store):
    store.import_tracks([{"artist": "A", "title": "Song (Matthew Topper & L3XI Edit)"}], "LDS")
    p = next(p for p in store.people() if "&" in p["name"])
    assert "collaboration" in p["review_note"]


def test_unknown_identity_cannot_be_followed(store):
    with pytest.raises(ValueError):
        store.follow("Made Up")


def test_multiple_roles_do_not_double_weight_one_person(store):
    store.import_tracks([{"artist": "Person", "title": "Song (Person Edit)"}], "LDS")
    store.follow("Person")
    match = store.recommendations()[0]
    assert match["score"] == 10
    assert len(match["reasons"]) == 1
