import wave

import pytest
from mutagen.wave import WAVE
from mutagen.id3 import TPE1, TIT2, TCON, TBPM

from soulseek_mcp.library_seed import read_music_folder
from soulseek_mcp.listening import ListeningLibrary


def audio_file(path, tagged=True):
    with wave.open(str(path), 'wb') as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(8000)
        f.writeframes(b'\x00\x00' * 800)
    if tagged:
        audio = WAVE(path)
        audio.add_tags()
        audio.tags.add(TPE1(encoding=3, text=['Seed Artist']))
        audio.tags.add(TIT2(encoding=3, text=['Loved Track']))
        audio.tags.add(TCON(encoding=3, text=['House']))
        audio.tags.add(TBPM(encoding=3, text=['128']))
        audio.save()


def test_scan_reads_tags_and_never_changes_audio(tmp_path):
    path = tmp_path / 'music.wav'
    audio_file(path)
    before = path.read_bytes()
    report = read_music_folder(tmp_path)
    assert report['scanned'] == 1 and len(report['files']) == 1
    record = report['files'][0]['record']
    assert (record['artist'], record['title'], record['genre'], record['bpm']) == ('Seed Artist', 'Loved Track', 'House', 128)
    assert path.read_bytes() == before


def test_filename_fallback_is_explicit_and_scan_is_bounded(tmp_path):
    audio_file(tmp_path / 'Artist - Song (Edit).wav', tagged=False)
    audio_file(tmp_path / 'Unknown.wav', tagged=False)
    report = read_music_folder(tmp_path)
    assert report['files'][0]['method'] == 'filename'
    assert report['files'][0]['record']['title'] == 'Song (Edit)'
    assert report['skipped'] == 1
    assert read_music_folder(tmp_path, limit=1)['truncated']


def test_symlinked_audio_is_not_scanned(tmp_path):
    root = tmp_path / 'music'
    root.mkdir()
    external = tmp_path / 'outside.wav'
    audio_file(external)
    (root / 'linked.wav').symlink_to(external)
    assert read_music_folder(root)['scanned'] == 0


@pytest.mark.asyncio
async def test_owned_music_seeds_related_tracks_without_favoriting(tmp_path):
    folder = tmp_path / 'music'
    folder.mkdir()
    audio_file(folder / 'seed.wav')
    library = ListeningLibrary(tmp_path / 'db.sqlite3')
    try:
        imported = await library.seed_folder(str(folder))
        assert imported['matched_files'] == 1
        assert (await library.seed_folder(str(folder)))['added'] == 0
        library.import_batch([{'artist': 'Seed Artist', 'title': 'New Track', 'genre': 'House'},
                              {'artist': 'Other', 'title': 'Unrelated', 'genre': 'Techno'}], 'Manual')
        tracks = {t['title']: t for t in library.inbox()['tracks']}
        assert tracks['Loved Track']['owned'] and not tracks['Loved Track']['favorite']
        assert tracks['Loved Track']['rating'] == 0
        assert tracks['New Track']['score'] > tracks['Unrelated']['score']
        assert not any(p['followed'] for p in library.inbox()['people'])
        # Another source for an already owned version stays owned.
        library.import_batch([{'artist': 'Seed Artist', 'title': 'Loved Track',
                               'url': 'https://soundcloud.com/seed/track'}], 'SoundCloud')
        track = next(t for t in library.inbox()['tracks'] if t['title'] == 'Loved Track')
        assert track['owned'] and len(track['sources']) == 2
    finally:
        library.close()
