import asyncio
from pathlib import Path

import pytest

from soulseek_mcp.listening import ListeningLibrary
from soulseek_mcp.library_research import clean_candidate


@pytest.fixture
def library(tmp_path, monkeypatch):
    store = ListeningLibrary(tmp_path / 'music.sqlite3')
    monkeypatch.setattr(store, 'beatport_python', lambda: Path(__file__))
    yield store
    store.close()


def seed(store, artist='Artist', title='My record'):
    identity = store.import_batch([{'artist': artist, 'title': title}], 'Library')['track_ids'][0]
    with store.db:
        store.db.execute('INSERT INTO library_files VALUES(?,?,0,0)', (f'/music/{identity}.mp3', identity))
    return identity


def track(identity='123', **changes):
    return {'source_id': identity, 'artist': 'Artist', 'title': 'New song (Extended Mix)',
            'url': f'https://www.beatport.com/track/new/{identity}',
            'preview_url': f'https://geo-samples.beatport.com/{identity}.mp3',
            'label': 'Label', 'credits': [{'name': 'Artist', 'role': 'artist', 'url': 'https://www.beatport.com/artist/artist/1'}], **changes}


async def run(store, ids):
    await store.library_research_start(ids)
    await store._library_research_task
    return store.library_research_state()


async def test_findings_are_reviewable_not_automatically_imported(library, monkeypatch):
    identity = seed(library)
    async def read(request):
        assert request['seed']['id'] == identity
        return {'versions': [track()], 'recent': [track(), track('124', title='New song (Radio Edit)')]}
    monkeypatch.setattr(library, 'beatport_read', read)
    state = await run(library, [identity])
    assert state['job']['status'] == 'complete' and state['job']['completed'] == 1
    assert state['counts'] == {'pending': 2}
    assert len(library.inbox()['tracks']) == 1
    possible = next(c for c in state['candidates'] if c['id'] == '123')
    assert possible['evidence'][0]['kind'] == 'possible_version'
    assert possible['evidence'][0]['seed_id'] == identity
    result = library.library_research_review('123', 'keep')
    kept = next(t for t in library.inbox()['tracks'] if t['id'] == result['track_id'])
    assert not kept['favorite'] and kept['rating'] == 0
    assert kept['sources'][0]['url'] == track()['url']
    assert any('My record' in r for r in kept['reasons'])
    assert kept['title'] == 'New song (Extended Mix)'
    library.library_research_review('124', 'dismiss')
    assert len(library.inbox()['tracks']) == 2
    # Reruns preserve dismissal and feedback, and do not duplicate evidence.
    library.react(result['track_id'], favorite=True, rating=1)
    state = await run(library, [identity])
    assert state['counts'] == {'dismissed': 1, 'kept': 1}
    assert len(next(c for c in state['candidates'] if c['id'] == '124')['evidence']) == 1
    assert next(t for t in library.inbox()['tracks'] if t['id'] == result['track_id'])['favorite']
    library.library_research_review('124', 'restore')
    assert library.library_research_state()['counts']['pending'] == 1


async def test_collected_versions_and_unrelated_name_matches_are_not_suggested(library, monkeypatch):
    identity = seed(library, title='New song (Extended Mix)')
    library.import_batch([track('126', title='Known')], 'Beatport')
    async def read(_):
        return {'versions': [track(), track('125', title='New song (Radio Edit)'), track('128', artist='Unrelated', credits=[])],
                'recent': [track('126', title='Known'), track('127', artist='Unrelated', credits=[{'name': 'Artist Two', 'role': 'artist'}])]}
    monkeypatch.setattr(library, 'beatport_read', read)
    state = await run(library, [identity])
    assert [c['id'] for c in state['candidates']] == ['125']
    assert state['job']['seeds'][0]['collected'] == 2


async def test_cancel_is_bounded_and_partial_findings_survive(library, monkeypatch):
    ids = [seed(library), seed(library, artist='Other')]
    second_started = asyncio.Event()
    async def read(request):
        if request['seed']['id'] == ids[1]:
            second_started.set()
            await asyncio.Event().wait()
        return {'versions': [track()], 'recent': []}
    monkeypatch.setattr(library, 'beatport_read', read)
    await library.library_research_start(ids)
    await asyncio.wait_for(second_started.wait(), 3)
    with pytest.raises(ValueError, match='already running'):
        await library.library_research_start(ids)
    await asyncio.wait_for(library.library_research_cancel(), 1)
    state = library.library_research_state()
    assert state['job']['status'] == 'cancelled'
    assert state['job']['completed'] == 1
    assert state['counts'] == {'pending': 1}
    assert state['job']['seeds'][1]['status'] == 'cancelled'


async def test_cancel_before_worker_starts(library):
    await library.library_research_start([seed(library)])
    await library.library_research_cancel()
    assert library.library_research_state()['job']['status'] == 'cancelled'


async def test_failed_seed_does_not_discard_other_results_or_leak_details(library, monkeypatch):
    ids = [seed(library), seed(library, artist='Other')]
    async def read(request):
        if request['seed']['id'] == ids[0]:
            raise RuntimeError('private auth detail')
        return {'versions': [track(artist='Other', credits=[{'name':'Other','role':'artist'}])], 'recent': []}
    monkeypatch.setattr(library, 'beatport_read', read)
    state = await run(library, ids)
    assert state['job']['status'] == 'partial' and state['job']['completed'] == 2
    assert state['job']['seeds'][0]['status'] == 'error'
    assert 'private auth detail' not in str(state)
    assert state['counts'] == {'pending': 1}


async def test_bad_metadata_cannot_partially_persist_a_seed(library, monkeypatch):
    async def read(_):
        return {'versions': [track(), track('124', preview_url='file:///private')], 'recent': []}
    monkeypatch.setattr(library, 'beatport_read', read)
    state = await run(library, [seed(library)])
    assert state['job']['status'] == 'failed'
    assert not state['candidates']


async def test_seed_selection_validated_before_job_creation(library):
    identity = seed(library)
    not_owned = library.import_batch([track()], 'Beatport')['track_ids'][0]
    for ids in ([], [identity] * 31, [identity, identity], [identity, 'missing'], [not_owned], 'bad', [4]):
        with pytest.raises(ValueError):
            await library.library_research_start(ids)
        assert library.library_research_state()['job'] is None


def test_restart_marks_abandoned_job_interrupted_and_retains_results(library):
    identity = seed(library)
    with library.db:
        library.db.execute("INSERT INTO library_research_jobs(id,status,started_at,seeds) VALUES('job','running','2026-01-01','[]')")
    library._store_library_findings('job', {'id': identity, 'artist': 'Artist', 'title': 'My record'}, [(clean_candidate(track()), 'possible_version')])
    path = library.db.execute('PRAGMA database_list').fetchone()[2]
    reopened = ListeningLibrary(path)
    state = reopened.library_research_state()
    assert state['job']['status'] == 'interrupted'
    assert state['counts'] == {'pending': 1}
    reopened.close()


async def test_multiple_seeds_preserve_provenance(library, monkeypatch):
    async def read(_):
        return {'versions': [track()], 'recent': []}
    monkeypatch.setattr(library, 'beatport_read', read)
    state = await run(library, [seed(library), seed(library, title='Another record')])
    assert state['counts'] == {'pending': 1}
    assert len(state['candidates'][0]['evidence']) == 2
