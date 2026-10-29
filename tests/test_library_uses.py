from pathlib import Path

import pytest

from soulseek_mcp.listening import ListeningLibrary
from test_desktop_backend import configured
from test_library_seed import audio_file
from test_service import result_event


@pytest.fixture
def library(tmp_path):
    store = ListeningLibrary(tmp_path / 'music.sqlite3')
    yield store
    store.close()


def owned(library, tmp_path, title='Song'):
    identity = library.import_batch([{'artist': 'Artist', 'title': title}], 'Library')['track_ids'][0]
    file = tmp_path / f'{title}.wav'
    audio_file(file, tagged=False)
    stat = file.stat()
    with library.db:
        library.db.execute('INSERT INTO library_files VALUES(?,?,?,?)', (str(file), identity, stat.st_mtime_ns, stat.st_size))
    return identity, file


def test_uses_are_any_combination_and_reach_the_inbox_without_paths(library, tmp_path):
    identity, _ = owned(library, tmp_path)
    assert library.library_mark(identity, ['remix', 'dj', 'remix'])['uses'] == ['dj', 'remix']
    track = library.inbox()['tracks'][0]
    assert track['uses'] == ['dj', 'remix'] and track['tasks'] == {}
    assert library.library_mark(identity, [])['uses'] == []
    for bad in (['stems'], 'dj', [1]):
        with pytest.raises(ValueError):
            library.library_mark(identity, bad)
    with pytest.raises(ValueError):
        library.library_mark('missing', ['dj'])


def test_queue_lists_owned_files_by_use_and_hides_catalog_entries(library, tmp_path):
    sample, file = owned(library, tmp_path, 'Sample')
    dj, _ = owned(library, tmp_path, 'Dj')
    catalog = library.import_batch([{'artist': 'Artist', 'title': 'Catalog'}], 'Beatport')['track_ids'][0]
    library.library_mark(sample, ['sample', 'remix'])
    library.library_mark(dj, ['dj'])
    library.library_mark(catalog, ['sample'])
    rows = library.library_queue(use='sample')['tracks']
    assert [r['track_id'] for r in rows] == [sample]
    assert rows[0]['files'] == [{'path': str(file), 'format': 'WAV', 'size': file.stat().st_size, 'present': True}]
    assert {r['track_id'] for r in library.library_queue()['tracks']} == {sample, dj}
    page = library.library_queue(limit=1)
    assert len(page['tracks']) == 1 and page['next_offset'] == 1
    with pytest.raises(ValueError):
        library.library_queue(use='stems')


def test_claims_are_exclusive_and_finished_work_leaves_the_queue(library, tmp_path):
    identity, _ = owned(library, tmp_path)
    library.library_mark(identity, ['sample'])
    first = library.library_task_claim(identity, 'stems', 'agent-a')
    assert first['claimed'] and first['agent'] == 'agent-a'
    assert not library.library_task_claim(identity, 'stems', 'agent-b')['claimed']
    assert library.library_queue(use='sample', needs_task='stems')['tracks'] == []
    with pytest.raises(ValueError, match='open claim'):
        library.library_task_finish(identity, 'stems', 'agent-b', 'done')
    done = library.library_task_finish(identity, 'stems', 'agent-a', 'done', output='/stems/song', note='4 stems')
    assert done['status'] == 'done' and done['output'] == '/stems/song'
    assert not library.library_task_claim(identity, 'stems', 'agent-b')['claimed']
    assert library.inbox()['tracks'][0]['tasks']['stems'] == {
        'status': 'done', 'agent': 'agent-a', 'note': '4 stems',
        'claimed_at': done['claimed_at'], 'updated_at': done['updated_at']}
    # Another kind of work on the same track is independent.
    assert library.library_task_claim(identity, 'bpm-key', 'agent-b')['claimed']


def test_failed_and_abandoned_claims_can_be_retried(library, tmp_path):
    identity, _ = owned(library, tmp_path)
    library.library_task_claim(identity, 'stems', 'agent-a')
    library.library_task_finish(identity, 'stems', 'agent-a', 'failed', note='model crashed')
    assert [r['track_id'] for r in library.library_queue(needs_task='stems')['tracks']] == [identity]
    assert library.library_task_claim(identity, 'stems', 'agent-b')['claimed']
    with library.db:
        library.db.execute("UPDATE library_tasks SET updated_at=datetime('now','-7 hours')")
    assert library.library_task_claim(identity, 'stems', 'agent-c')['agent'] == 'agent-c'
    with pytest.raises(ValueError):
        library.library_task_claim(identity, 'Stems!', 'agent-c')
    with pytest.raises(ValueError):
        library.library_task_finish(identity, 'stems', 'agent-c', 'claimed')


def test_only_library_files_can_be_claimed(library):
    identity = library.import_batch([{'artist': 'Artist', 'title': 'Catalog'}], 'Beatport')['track_ids'][0]
    with pytest.raises(ValueError, match='files in the library'):
        library.library_task_claim(identity, 'stems', 'agent-a')


async def test_completed_download_joins_library_with_its_uses(tmp_path):
    s, fake = await configured(tmp_path)
    query = await s.search('artist')
    request = next(iter(fake.searches.requests.values()))
    await fake.events.emit(result_event(request, ['music\\Peer Artist - Peer Song.wav', 'music\\cover.jpg']))
    rows = s.results(query['search_id'])['results']
    song = next(r for r in rows if r['filename'].endswith('.wav'))
    cover = next(r for r in rows if r['filename'].endswith('.jpg'))
    transfer = await s.download(song['result_id'], uses=['sample', 'remix'])
    assert transfer['uses'] == ['sample', 'remix']
    other = await s.download(cover['result_id'], uses=['dj'])
    audio_file(Path(transfer['local_path']), tagged=False)
    await s._import_completed_downloads()
    assert s.listening.library_queue()['tracks'] == []  # Still downloading.
    for t in s._transfers.values():
        t.state.VALUE.name = 'COMPLETE'
    await s._import_completed_downloads()
    await s._import_completed_downloads()
    tracks = s.listening.library_queue(use='sample')['tracks']
    assert [(t['artist'], t['title'], t['uses']) for t in tracks] == [('Peer Artist', 'Peer Song', ['sample', 'remix'])]
    assert tracks[0]['files'][0]['path'] == transfer['local_path']
    assert len(s.listening.library_queue()['tracks']) == 1  # Non-audio files are not imported.
    assert s.listening.inbox()['tracks'][0]['owned']
    assert transfer['transfer_id'] not in s._download_uses and other['transfer_id'] not in s._download_uses
    with pytest.raises(Exception, match='dj, sample, or remix'):
        await s.download(song['result_id'], uses=['stems'])
    await s.close()


async def test_pending_uses_survive_restart(tmp_path):
    s, fake = await configured(tmp_path)
    query = await s.search('artist')
    request = next(iter(fake.searches.requests.values()))
    await fake.events.emit(result_event(request, ['music\\Peer Artist - Peer Song.wav']))
    transfer = await s.download(s.results(query['search_id'])['results'][0]['result_id'], uses=['dj'])
    await s.disconnect()
    await s.close()
    restarted, _ = await configured(tmp_path)
    assert restarted._download_uses == {transfer['transfer_id']: ['dj']}
    await restarted.close()


async def test_library_methods_are_dispatched(tmp_path):
    s, _ = await configured(tmp_path)
    identity, _ = owned(s.listening, tmp_path)
    assert (await s.dispatch('discovery_library_mark', {'track_id': identity, 'uses': ['dj']}))['uses'] == ['dj']
    assert (await s.dispatch('library_task_claim', {'track_id': identity, 'task': 'stems', 'agent': 'a'}))['claimed']
    assert (await s.dispatch('library_queue', {'use': 'dj'}))['tracks'][0]['tasks']['stems']['status'] == 'claimed'
    await s.close()
