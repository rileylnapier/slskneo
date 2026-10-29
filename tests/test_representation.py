import pytest
from soulseek_mcp.listening import ListeningLibrary
from soulseek_mcp.representation import evidence_url

URL='https://www.beatport.com/artist/test/42'
@pytest.fixture
def library(tmp_path):
    s=ListeningLibrary(tmp_path/'taste.sqlite3')
    s.db.execute("INSERT INTO watches(id,kind,source_id,name,url) VALUES('artist:42','artist','42','Artist',?)",(URL,))
    s.db.execute("INSERT INTO watches(id,kind,source_id,name,url) VALUES('label:42','label','42','Label','https://www.beatport.com/label/test/42')")
    s.db.commit()
    yield s
    s.close()

def test_requires_explicit_information_and_leaves_unknowns_unset(library):
    assert library.representation_state()=={'enabled':False,'artists':[]}
    with pytest.raises(ValueError):library.representation_save('artist:42',True,URL,'')
    with pytest.raises(ValueError):library.representation_save('label:42',True,URL,'Public artist statement.')
    library.representation_save('artist:42',True,URL,'Artist explicitly identifies as a woman in this public bio.')
    state=library.representation_state()
    assert len(state['artists'])==1 and not state['enabled']
    assert library.watch_state()['watches'][0]['women_focus']
    assert not library.watch_state()['watches'][1]['women_focus']
    library.representation_save('artist:42',False)
    assert library.representation_state()['artists']==[]

@pytest.mark.parametrize('url',['http://example.com','https://user:pass@example.com','https://127.0.0.1','https://localhost','file:///tmp/source','https://example.com:443'])
def test_sources_are_public_https_without_credentials(url):
    with pytest.raises(ValueError):evidence_url(url)

def test_focus_prioritizes_exact_artist_and_remixer_ids_without_hiding_tracks(library):
    def rec(title,identity,role='artist',source='Beatport'):
        return {'artist':'Artist','title':title,'credits':[{'name':'Artist','role':role,'url':URL.replace('/42',f'/{identity}')}],'label_url':'https://www.beatport.com/label/test/42'}
    library.import_batch([rec('Z remixed song',42,'remixer'),rec('A same name, different person',43)],'Beatport')
    library.import_batch([rec('B uploader context',42)],'SoundCloud')
    library.representation_save('artist:42',True,URL,'Public bio identifies this artist as a woman.')
    original=library.inbox()['tracks']
    assert original[0]['title']=='A same name, different person'
    library.representation_mode(True)
    tracks=library.inbox()['tracks']
    assert len(tracks)==3 and tracks[0]['title']=='Z remixed song'
    assert all(not t['women_focus_matches'] for t in tracks[1:])
    assert all(t['score']==0 and not t['favorite'] and not t['rating'] for t in tracks)
    library.representation_mode(False)
    assert library.inbox()['tracks'][0]['title']==original[0]['title']
    path=library.db.execute('PRAGMA database_list').fetchone()[2]
    r=ListeningLibrary(path);assert len(r.representation_state()['artists'])==1;r.close()

async def test_focus_exploration_is_bounded_and_never_resurfaces_reviewed_tracks(library,monkeypatch):
    library.representation_save('artist:42',True,URL,'Artist identifies as a woman in this source.')
    async def read(_):return {'tracks':[{'source_id':str(i),'artist':'Artist','title':f'Song {i}','url':f'https://www.beatport.com/track/song/{i}','credits':[{'name':'Artist','role':'artist','url':URL}]} for i in range(1,6)]}
    monkeypatch.setattr(library,'beatport_read',read)
    assert (await library.representation_explore())['added']==3
    library.library_research_review('1','dismiss')
    assert (await library.representation_explore())['added']==2
    assert library.library_research_state()['counts']=={'dismissed':1,'pending':4}
    assert library.db.execute('SELECT count(*) FROM watch_seen').fetchone()[0]==0
    assert library.watch_state()['watches'][0]['last_success'] is None
