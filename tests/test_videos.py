import json
import pytest
from soulseek_mcp.listening import ListeningLibrary
from soulseek_mcp.videos import video_id, video_type, youtube_search

@pytest.fixture
def library(tmp_path):
    s=ListeningLibrary(tmp_path/'music.sqlite3')
    s.import_batch([{'artist':'Artist','title':'Track (Remix)'}],'Manual')
    yield s
    s.close()

@pytest.mark.parametrize('url',['https://youtube.com.evil.test/watch?v=abcdefghijk','file:///abcdefghijk','https://user:pass@youtube.com/watch?v=abcdefghijk','https://youtube.com/playlist?list=abcdefghijk','https://youtu.be/short','https://youtube.com:444/watch?v=abcdefghijk'])
def test_only_single_public_youtube_links_are_saved(url):
    with pytest.raises(ValueError):video_id(url)

def test_video_types_are_hints_and_saved_links_do_not_change_taste(library):
    tid=library.inbox()['tracks'][0]['id']
    r=library.video_save(tid,'https://youtu.be/abcdefghijk?t=12','Live performance',kind='live')
    assert r['videos'][0]['url']=='https://www.youtube.com/watch?v=abcdefghijk'
    assert not r['videos'][0]['confirmed']
    assert video_type('Official Music Video')=='music_video'
    assert video_type('Live at the festival')=='live'
    r=library.video_save(tid,'https://youtube.com/watch?v=abcdefghijk','Edited title',kind='lyric',confirmed=True)
    assert len(r['videos'])==1 and r['videos'][0]['confirmed']
    t=library.inbox()['tracks'][0]
    assert not t['favorite'] and t['rating']==0 and len(t['sources'])==1

async def test_search_keeps_all_types_in_returned_order_and_preserves_reviews(library,monkeypatch):
    tid=library.inbox()['tracks'][0]['id']
    with pytest.raises(ValueError,match='Set up'):await library.video_search(tid)
    library.youtube_configure('fixture-key-only')
    def search(key,query):
        assert query=='Artist Track (Remix)' and key=='fixture-key-only'
        return [{'video_id':'abcdefghijk','title':'A live video','channel':'Uploader','kind':'live'},
                {'video_id':'bcdefghijkl','title':'An official video','channel':'Uploader','kind':'music_video'}]
    monkeypatch.setattr('soulseek_mcp.videos.youtube_search',search)
    r=await library.video_search(tid)
    assert [v['kind'] for v in r['videos']]==['live','music_video']
    library.video_save(tid,r['videos'][0]['url'],'Reviewed title','live',True)
    r=await library.video_search(tid)
    assert len(r['videos'])==2 and r['videos'][0]['title']=='Reviewed title' and r['videos'][0]['confirmed']
    assert 'fixture-key' not in json.dumps(r)

def test_youtube_request_uses_fixed_google_host_and_key_header(monkeypatch):
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,size):return json.dumps({'items':[{'id':{'videoId':'abcdefghijk'},'snippet':{'title':'Artist &amp; Song','channelTitle':'Channel'}}]}).encode()
    class Opener:
        def open(self,request,timeout):
            assert request.full_url.startswith('https://www.googleapis.com/youtube/v3/search?')
            assert 'fixture-key' not in request.full_url
            assert request.get_header('X-goog-api-key')=='fixture-key'
            return Response()
    monkeypatch.setattr('soulseek_mcp.videos.build_opener',lambda *a:Opener())
    assert youtube_search('fixture-key','track')[0]['title']=='Artist & Song'
