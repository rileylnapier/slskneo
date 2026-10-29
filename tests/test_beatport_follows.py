import pytest
from soulseek_mcp.listening import ListeningLibrary
from soulseek_mcp.beatport_feed import read_follows


def profile(identity,kind='artist',name='Same name'):
    return {'kind':kind,'name':name,'url':f'https://www.beatport.com/{kind}/profile/{identity}'}

@pytest.fixture
def library(tmp_path):
    lib=ListeningLibrary(tmp_path/'discovery.sqlite3')
    yield lib
    lib.close()

async def test_import_all_follows_is_idempotent_preserves_pauses_and_local_preferences(library,monkeypatch):
    profiles=[profile(i) for i in range(1,70)]+[profile(i,'label') for i in range(1,26)]
    async def read(_):return {'profiles':profiles}
    monkeypatch.setattr(library,'beatport_read',read)
    first=await library.beatport_import_follows()
    assert (first['added'],first['artists'],first['labels'])==(94,69,25)
    assert library.db.execute('select count(*) from follows').fetchone()[0]==0
    library.watch_update('artist:1',enabled=False,interval_hours=168)
    second=await library.beatport_import_follows()
    assert (second['added'],second['existing'])==(0,94)
    paused=next(w for w in library.watch_state()['watches'] if w['id']=='artist:1')
    assert not paused['enabled'] and paused['interval_hours']==168 and paused['from_beatport_follow']
    # Additive import cannot remove watches based on an empty/changed upstream list.
    profiles.clear()
    await library.beatport_import_follows()
    assert len(library.watch_state()['watches'])==94
    reopened=ListeningLibrary(library.db.execute('PRAGMA database_list').fetchone()[2])
    assert len(reopened.watch_state()['watches'])==94
    reopened.close()

async def test_invalid_or_failed_import_does_not_partially_write(library,monkeypatch):
    async def bad(_):return {'profiles':[profile(1),profile(2,kind='remixer')]}
    monkeypatch.setattr(library,'beatport_read',bad)
    with pytest.raises(ValueError):await library.beatport_import_follows()
    assert library.watch_state()['watches']==[]
    assert library.watch_state()['beatport_follows'] is None

async def test_same_names_do_not_make_same_identity_and_labels_guide_ranking(library,monkeypatch):
    async def read(_):return {'profiles':[profile(42),profile(7,'label','Label')]}
    monkeypatch.setattr(library,'beatport_read',read)
    await library.beatport_import_follows()
    def track(identity,artist_id,label_id):
        return {'artist':'Same name','title':f'Song {identity}','url':f'https://www.beatport.com/track/song/{identity}',
                'credits':[{'name':'Same name','role':'artist','url':profile(artist_id)['url']}],
                'label':'Label','label_url':profile(label_id,'label')['url']}
    library.import_batch([track(1,42,7),track(2,43,8)],'Beatport')
    rows={t['title']:t for t in library.inbox()['tracks']}
    assert rows['Song 1']['score']==16
    assert rows['Song 2']['score']==0
    assert any('(label)' in reason for reason in rows['Song 1']['reasons'])
    assert not rows['Song 1']['favorite'] and rows['Song 1']['rating']==0

async def test_reader_uses_account_follows_and_rejects_partial_or_bad_responses():
    class Client:
        calls=[]
        async def get(self,path):
            self.calls.append(path)
            return [{'id':42,'name':'Artist'}] if path.endswith('/artists/') else [{'id':7,'name':'Label'}]
    client=Client()
    rows=(await read_follows(client))['profiles']
    assert client.calls==['/my/beatport/artists/','/my/beatport/labels/']
    assert [r['kind'] for r in rows]==['artist','label']
    class Bad:
        async def get(self,path):return {'results':[],'next':'page2'}
    with pytest.raises(ValueError):await read_follows(Bad())
