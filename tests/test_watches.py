import asyncio
import time

import pytest

from soulseek_mcp.listening import ListeningLibrary
from soulseek_mcp.beatport_feed import read_watch
from soulseek_mcp.watches import profile_identity

URL = 'https://www.beatport.com/artist/test/42'


def record(identity='1', **changes):
    return {'source_id': identity, 'artist': 'Artist', 'title': f'Song {identity}',
            'url': f'https://www.beatport.com/track/song/{identity}',
            'credits': [{'name': 'Artist', 'role': 'artist', 'url': URL}],
            'label': 'Label', 'label_url': 'https://www.beatport.com/label/test/7',
            'release_date': '2026-10-26', **changes}


@pytest.fixture
def library(tmp_path):
    lib = ListeningLibrary(tmp_path / 'library.sqlite3')
    yield lib
    lib.close()


async def add(library, monkeypatch, kind='artist'):
    async def read(request):
        return {'name': 'Artist', 'url': URL}
    monkeypatch.setattr(library, 'beatport_read', read)
    return (await library.watch_add(URL, kind=kind))['id']


async def check(library, monkeypatch, records, **extra):
    async def read(request):
        return {'tracks': records, **extra}
    monkeypatch.setattr(library, 'beatport_read', read)
    await library.watch_check()
    await library._watch_task


async def test_baseline_new_entries_dedupe_reviews_and_restart(library, monkeypatch):
    identity = await add(library, monkeypatch)
    await check(library, monkeypatch, [record()])
    assert not library.library_research_state()['candidates']
    assert library.watch_state()['watches'][0]['last_success']
    assert library.watch_state()['watches'][0]['next_check'] > time.time() + 86000
    await check(library, monkeypatch, [record(), record('2')])
    state = library.library_research_state()
    assert state['counts'] == {'pending': 1}
    assert state['candidates'][0]['evidence'][0]['kind'] == 'watch'
    library.library_research_review('2', 'dismiss')
    await check(library, monkeypatch, [record(), record('2'), record('3')], limited=True)
    assert library.library_research_state()['counts'] == {'dismissed': 1, 'pending': 1}
    saved = library.library_research_review('3', 'keep')['track_id']
    assert 'watch' in ' '.join(next(t for t in library.inbox()['tracks'] if t['id'] == saved)['reasons'])
    path = library.db.execute('PRAGMA database_list').fetchone()[2]
    reopened = ListeningLibrary(path)
    assert reopened.watch_state()['watches'][0]['limited']
    await check(reopened, monkeypatch, [record(), record('2'), record('3')])
    assert reopened.library_research_state()['counts'] == {'dismissed': 1, 'kept': 1}
    assert reopened.watch_state()['watches'][0]['added'] == 0
    reopened.close()


async def test_failure_keeps_baseline_and_seen_set_intact_and_retries_later(library, monkeypatch):
    await add(library, monkeypatch)
    await check(library, monkeypatch, [record(), record('2', preview_url='file:///private')])
    watch = library.watch_state()['watches'][0]
    assert watch['status'] == 'error' and watch['last_success'] is None
    assert watch['next_check'] > time.time() + 3500
    assert library.db.execute('SELECT count(*) FROM watch_seen').fetchone()[0] == 0
    assert not (await library.watch_check(due_only=True))['started']
    await check(library, monkeypatch, [record()])
    assert library.watch_state()['watches'][0]['status'] == 'ready'
    assert not library.library_research_state()['candidates']


async def test_pause_during_request_discards_result_and_concurrency_is_bounded(library, monkeypatch):
    identity = await add(library, monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()
    async def read(request):
        entered.set()
        await release.wait()
        return {'tracks': [record()]}
    monkeypatch.setattr(library, 'beatport_read', read)
    await library.watch_check()
    await entered.wait()
    assert (await library.watch_check())['running']
    library.watch_update(identity, enabled=False)
    release.set()
    await library._watch_task
    assert library.watch_state()['watches'][0]['status'] == 'paused'
    assert library.watch_state()['watches'][0]['last_success'] is None
    assert not (await library.watch_check())['started']
    library.watch_update(identity, enabled=True, interval_hours=168)
    assert library.watch_state()['watches'][0]['next_check'] == 0


async def test_shutdown_interrupts_worker_and_restart_retries(library, monkeypatch):
    await add(library, monkeypatch)
    entered = asyncio.Event()
    async def read(request):
        entered.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(library, 'beatport_read', read)
    library.start_watches()
    await asyncio.wait_for(entered.wait(), 1)
    await asyncio.wait_for(library.shutdown_watches(), 1)
    assert library.watch_state()['watches'][0]['status'] == 'interrupted'
    assert library.watch_state()['watches'][0]['next_check'] == 0


async def test_exact_source_identity_and_remix_role_are_required(library, monkeypatch):
    await add(library, monkeypatch, kind='remixer')
    await check(library, monkeypatch, [record()])
    assert library.watch_state()['watches'][0]['status'] == 'error'
    await check(library, monkeypatch, [record(credits=[{'name':'Same name', 'role':'remixer', 'url':URL}])])
    assert library.watch_state()['watches'][0]['status'] == 'ready'
    await check(library, monkeypatch, [record('2', credits=[{'name':'Artist','role':'remixer','url':URL.replace('/42','/43')}])])
    assert library.watch_state()['watches'][0]['status'] == 'error'
    assert not library.library_research_state()['candidates']


async def test_collected_recordings_and_overlapping_watches_do_not_duplicate(library, monkeypatch):
    await add(library, monkeypatch)
    await check(library, monkeypatch, [])
    library.import_batch([record()], 'Beatport')
    await check(library, monkeypatch, [record(), record('2')])
    assert library.library_research_state()['counts'] == {'pending': 1}
    # Another watch sees the same version: one finding, multiple explanations.
    watch = dict(library.db.execute('SELECT * FROM watches').fetchone())
    library.db.execute("INSERT INTO watches(id,kind,source_id,name,url,last_success) VALUES('other','artist','42','Other',?,'2026-10-01')", (URL,))
    watch.update(id='other', last_success='2026-10-01')
    library._store_watch_check(watch, [record('2')], False)
    assert library.library_research_state()['counts'] == {'pending': 1}
    assert len(library.library_research_state()['candidates'][0]['evidence']) == 2


def test_follow_creates_watch_only_for_unambiguous_structured_profile(library):
    library.import_batch([record()], 'Beatport')
    library.follow('Artist')
    assert len(library.watch_state()['watches']) == 1
    library.follow('Artist', False)
    assert not library.watch_state()['watches'][0]['enabled']
    library.follow('Artist')
    assert library.watch_state()['watches'][0]['enabled']
    library.import_batch([record('2', credits=[{'name':'Ambiguous','role':'artist','url':URL}]),
                          record('3', credits=[{'name':'Ambiguous','role':'artist','url':URL.replace('/42','/43')}])], 'Beatport')
    library.follow('Ambiguous')
    assert len(library.watch_state()['watches']) == 1


@pytest.mark.parametrize('url', ['https://evil.test/artist/a/42','http://www.beatport.com/artist/a/42','https://www.beatport.com/track/a/42','https://www.beatport.com/artist/a/42?secret=x'])
def test_profile_urls_cannot_change_source_or_entity(url):
    with pytest.raises(ValueError):
        profile_identity(url, 'artist')


async def test_helper_uses_exact_entities_and_filters_remix_credits():
    class Client:
        async def get(self, url, **params):
            assert url == '/catalog/artists/42/tracks/'
            assert params['per_page'] == 100
            return {'results': [
                {'id':1, 'name':'Original', 'artists':[{'id':42,'name':'Artist'}], 'publish_date':'2026-01-01'},
                {'id':2, 'name':'Remix', 'artists':[{'id':3,'name':'Someone'}], 'remixers':[{'id':42,'name':'Artist'}], 'publish_date':'2026-01-01'}], 'count':101, 'next':'page2'}
    result = await read_watch(Client(), {'kind':'remixer','source_id':'42','operation':'watch_tracks'})
    assert [t['source_id'] for t in result['tracks']] == ['2']
    assert result['limited']

async def test_incomplete_credits_are_skipped_without_accepting_wrong_artist():
    class Client:
        async def get(self,*a,**k):
            return {'count':2,'results':[{'id':1,'artists':[],'remixers':[]},
                {'id':2,'name':'Song','artists':[{'id':42,'name':'Artist'}],'publish_date':'2026-01-01'}]}
    r=await read_watch(Client(),{'operation':'watch_tracks','kind':'artist','source_id':'42'})
    assert r['skipped']==1 and [t['source_id'] for t in r['tracks']]==['2']
    with pytest.raises(ValueError,match='not honored'):
        await read_watch(Client(),{'operation':'watch_tracks','kind':'artist','source_id':'43'})
