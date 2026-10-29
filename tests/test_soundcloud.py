import asyncio
import json
import time
from urllib.error import HTTPError

import pytest

from soulseek_mcp.listening import ListeningLibrary
from soulseek_mcp.soundcloud import SoundCloudClient, format_upload, soundcloud_url, source_links, upload_kind
from soulseek_mcp.library_research import clean_candidate

WATCH={'id':'soundcloud:42','source':'SoundCloud','kind':'soundcloud','source_id':'42','name':'Uploader','artist_name':'Known artist','last_success':'2026-01-01'}

def upload(identity=123, **changes):
    return {'urn':f'soundcloud:tracks:{identity}','title':'Song (Bootleg)', 'permalink_url':f'https://soundcloud.com/uploader/song-{identity}',
            'user':{'urn':'soundcloud:users:42','username':'Uploader'},'sharing':'public','duration':240000,
            'description':'Free DL https://hypeddit.com/uploader/song. Buy https://artist.bandcamp.com/track/song',
            'created_at':'2026-10-26T00:00:00Z', **changes}

@pytest.fixture
def library(tmp_path):
    store=ListeningLibrary(tmp_path/'music.sqlite3')
    store.import_batch([{'artist':'Known artist','title':'Local seed'}],'Library')
    yield store
    store.close()

def test_upload_classification_is_only_a_hint_and_links_preserve_provenance():
    row=clean_candidate(format_upload(upload(),WATCH))
    assert row['content_kind']=='bootleg' and not row['identity_confirmed']
    assert row['credits']==[] and row['artist']=='Known artist' and row['uploader']=='Uploader'
    assert [s['source'] for s in row['source_links']]==['Hypeddit','Manual']
    assert row['source_links'][0]['url']=='https://hypeddit.com/uploader/song'
    assert upload_kind('Untitled')[0]=='unclassified'
    assert upload_kind('Live DJ set')[0]=='dj_set'
    assert upload_kind('Long music', 1800000)[0]=='dj_set'
    assert upload_kind('Original Mix')[0]=='original'
    assert source_links('https://user:secret@hypeddit.com/a https://evil.test/a http://hypeddit.com/a')==[]

@pytest.mark.parametrize('url',['file:///tmp/audio','https://soundcloud.com/uploader/sets','https://soundcloud.com/uploader/song?secret_token=abc','https://soundcloud.com@evil.test/user/song','https://soundcloud.com/user/song/private','https://api.soundcloud.com/users/1'])
def test_soundcloud_player_accepts_public_single_track_urls_only(url):
    with pytest.raises(ValueError):soundcloud_url(url)

def test_uploads_cannot_impersonate_other_profiles_or_stream_private_audio():
    with pytest.raises(ValueError):format_upload(upload(user={'id':43}),WATCH)
    with pytest.raises(ValueError):format_upload(upload(sharing='private'),WATCH)
    assert format_upload(upload(access='blocked'),WATCH)['soundcloud_url']==''
    bad=format_upload(upload(),WATCH);bad['soundcloud_url']='https://soundcloud.com/other/song'
    with pytest.raises(ValueError):clean_candidate(bad)

async def test_profile_link_and_watch_baseline_review_and_restart(library,monkeypatch):
    async def resolve(url):return {'source_id':'42','name':'Uploader','url':'https://soundcloud.com/uploader'}
    monkeypatch.setattr(library.soundcloud_client,'resolve_profile',resolve)
    with pytest.raises(ValueError):await library.soundcloud_watch_add('https://soundcloud.com/uploader','known artist')
    result=await library.soundcloud_watch_add('https://soundcloud.com/uploader','known artist',True)
    watch=dict(library.db.execute('SELECT * FROM watches WHERE id=?',(result['id'],)).fetchone())
    library._store_watch_check(watch,[clean_candidate(format_upload(upload(),watch))],False)
    assert not library.library_research_state()['candidates']
    # Same numeric catalog IDs across sources must never collide.
    library.db.execute("INSERT INTO library_research_candidates VALUES('124','{}','dismissed',NULL,'x','x')")
    watch=dict(library.db.execute('SELECT * FROM watches WHERE id=?',(result['id'],)).fetchone())
    new=clean_candidate(format_upload(upload(124),watch))
    library._store_watch_check(watch,[new],False)
    finding=next(c for c in library.library_research_state()['candidates'] if c['id']=='soundcloud:124')
    assert finding['status']=='pending'
    assert 'SoundCloud' in finding['evidence'][0]['title']
    with pytest.raises(ValueError):library.library_research_review('soundcloud:124','keep')
    kept=library.library_research_review('soundcloud:124','keep',artist='Actual Artist',title='Song (Uploader Bootleg)',content_kind='bootleg')
    track=next(t for t in library.inbox()['tracks'] if t['id']==kept['track_id'])
    assert track['artist']=='Actual Artist' and track['sources'][0]['source']=='SoundCloud'
    assert track['sources'][0]['source_links'][0]['source']=='Hypeddit'
    assert track['soundcloud_url']==new['url'] and not track['favorite']
    library.cue(track['id'],track['soundcloud_url'],20,'Drop')
    library._store_watch_check(watch,[new],False)
    assert library.watch_state()['pending_count']==0
    path=library.db.execute('PRAGMA database_list').fetchone()[2]
    reopened=ListeningLibrary(path)
    assert reopened.watch_state()['watches'][0]['source']=='SoundCloud'
    assert reopened.library_research_state()['counts']['kept']==1
    reopened.close()

async def test_public_api_tokens_are_cached_refreshed_and_never_returned(monkeypatch):
    calls=[]
    def http(url,headers=None,data=None):
        calls.append((url,headers,data))
        if '/oauth/token' in url:return {'access_token':'fixture-access','refresh_token':'fixture-refresh','expires_in':3600}
        return {'kind':'user','urn':'soundcloud:users:42','username':'Uploader','permalink_url':'https://soundcloud.com/uploader'}
    monkeypatch.setattr('soulseek_mcp.soundcloud.http_json',http)
    client=SoundCloudClient();await client.configure('fixture-id','fixture-secret')
    await asyncio.gather(client.resolve_profile('https://soundcloud.com/uploader'),client.resolve_profile('https://soundcloud.com/uploader'))
    assert len([c for c in calls if '/oauth/token' in c[0]])==1
    client.expires=0;await client.check()
    assert b'grant_type=refresh_token' in calls[-1][2]
    assert await client.check()=={'connected':True}
    assert 'fixture-secret' not in json.dumps(await client.resolve_profile('https://soundcloud.com/uploader'))

async def test_missing_credentials_and_malformed_responses_do_not_advance_a_watch(library,monkeypatch):
    library.db.execute("INSERT INTO watches(id,kind,source_id,name,url,source,artist_name) VALUES('soundcloud:42','soundcloud','42','Uploader','https://soundcloud.com/uploader','SoundCloud','Known artist')")
    await library.watch_check();await library._watch_task
    w=library.watch_state()['watches'][0]
    assert w['status']=='error' and w['last_success'] is None
    assert not library.library_research_state()['candidates']
    await library.soundcloud_configure('fixture-id','fixture-secret')
    assert library.watch_state()['watches'][0]['next_check']==0
    async def bad(_):return {'tracks':[format_upload(upload(),WATCH),{'source':'SoundCloud'}]}
    monkeypatch.setattr(library.soundcloud_client,'uploads',bad)
    await library.watch_check();await library._watch_task
    assert library.db.execute('SELECT count(*) FROM watch_seen').fetchone()[0]==0


def test_credentials_are_not_forwarded_to_cross_origin_redirects(monkeypatch):
    from soulseek_mcp.soundcloud import http_json
    calls=[]
    class Opener:
        def open(self,request,timeout):
            calls.append(request.full_url)
            raise HTTPError(request.full_url,302,'redirect',{'Location':'https://evil.test/collect'},None)
    monkeypatch.setattr('soulseek_mcp.soundcloud.build_opener',lambda *a:Opener())
    with pytest.raises(ValueError,match='temporarily unavailable'):
        http_json('https://api.soundcloud.com/resolve',{'Authorization':'OAuth fixture-secret'})
    assert len(calls)==1


def test_manual_soundcloud_links_get_player_without_api_credentials(library):
    identity=library.import_batch([{'artist':'Confirmed Artist','title':'Confirmed edit','url':'https://soundcloud.com/uploader/song'}],'SoundCloud')['track_ids'][0]
    track=next(t for t in library.inbox()['tracks'] if t['id']==identity)
    assert track['soundcloud_url']=='https://soundcloud.com/uploader/song'
    assert not library.soundcloud_status()['configured']
