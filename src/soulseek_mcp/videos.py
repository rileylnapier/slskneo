"""Track-linked YouTube candidates; video types never affect ranking."""
import asyncio
import html
import json
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, parse_qs, urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler
from .library_research import stamp

VIDEO_TYPES = {'music_video','live','visualizer','lyric','audio','other'}

def video_id(url):
    if not isinstance(url,str) or len(url)>2048:
        raise ValueError('Use a YouTube video link.')
    p=urlsplit(url)
    if p.scheme!='https' or p.netloc not in {'youtube.com','www.youtube.com','m.youtube.com','youtu.be'}:
        raise ValueError('Use an HTTPS YouTube video link.')
    identity=p.path.lstrip('/') if p.netloc=='youtu.be' else parse_qs(p.query).get('v',[''])[0] if p.path=='/watch' else p.path.split('/')[-1] if p.path.startswith(('/shorts/','/live/','/embed/')) and len(p.path.split('/'))==3 else ''
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}',identity):
        raise ValueError('Use a single YouTube video link, not a channel or playlist.')
    return identity

def video_type(title):
    for kind,pattern in [('lyric',r'\blyric'),('visualizer',r'\bvisuali[sz]er\b'),('live',r'\blive\b|\bperformance\b|\bdj set\b'),('music_video',r'\bofficial (music )?video\b|\bmusic video\b'),('audio',r'\bofficial audio\b')]:
        if re.search(pattern,title,re.I):return kind
    return 'other'

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def youtube_search(key,query):
    url='https://www.googleapis.com/youtube/v3/search?'+urlencode({'part':'snippet','type':'video','q':query,'maxResults':10,'order':'relevance'})
    try:
        req=Request(url,headers={'X-Goog-Api-Key':key,'Accept':'application/json'})
        with build_opener(NoRedirect).open(req,timeout=20) as response:
            raw=response.read(1000001)
        if len(raw)>1000000:raise ValueError()
        data=json.loads(raw)
        rows=data['items']
        if not isinstance(rows,list) or len(rows)>10:raise ValueError()
        results=[]
        for row in rows:
            identity=video_id('https://www.youtube.com/watch?v='+row['id']['videoId'])
            snippet=row['snippet']
            title=html.unescape(str(snippet['title']))[:500]
            channel=html.unescape(str(snippet.get('channelTitle','')))[:250]
            results.append({'video_id':identity,'title':title,'channel':channel,'kind':video_type(title)})
        return results
    except Exception:
        raise ValueError('YouTube search is unavailable. Check your API key, enabled YouTube Data API, and quota.') from None

class VideoMixin:
    def init_videos(self):
        self._youtube_key=os.environ.get('SLSK_YOUTUBE_API_KEY','')
        self._video_search_lock=asyncio.Lock()
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS track_videos (
                track_id TEXT NOT NULL REFERENCES tracks(id), video_id TEXT NOT NULL,
                title TEXT NOT NULL, channel TEXT NOT NULL, kind TEXT NOT NULL,
                confirmed INTEGER NOT NULL DEFAULT 0, added_at TEXT NOT NULL,
                origin TEXT NOT NULL, PRIMARY KEY(track_id,video_id)
            );
            CREATE TABLE IF NOT EXISTS video_searches (
                track_id TEXT PRIMARY KEY REFERENCES tracks(id), checked_at TEXT NOT NULL
            );
        ''')

    def youtube_configure(self,api_key):
        if not isinstance(api_key,str) or not 10<=len(api_key.strip())<=512:
            raise ValueError('Enter a YouTube Data API key.')
        self._youtube_key=api_key.strip()
        return {'configured':True}

    def _video_track(self,track_id):
        row=self.db.execute('SELECT artist,title FROM tracks WHERE id=?',(track_id,)).fetchone()
        if not row:raise ValueError('Choose a collected track.')
        return row

    def video_state(self,track_id):
        self._video_track(track_id)
        cutoff=(datetime.now(timezone.utc)-timedelta(days=30)).isoformat()
        with self.db:self.db.execute("DELETE FROM track_videos WHERE origin='YouTube search' AND added_at<?",(cutoff,))
        rows=[dict(r) for r in self.db.execute('SELECT * FROM track_videos WHERE track_id=? ORDER BY added_at, rowid',(track_id,))]
        searched=self.db.execute('SELECT checked_at FROM video_searches WHERE track_id=?',(track_id,)).fetchone()
        for r in rows:r['url']='https://www.youtube.com/watch?v='+r['video_id']
        return {'videos':rows,'configured':bool(self._youtube_key),'checked_at':searched[0] if searched else None}

    async def video_search(self,track_id):
        track=self._video_track(track_id)
        if not self._youtube_key:raise ValueError('Set up a YouTube Data API key to search. You can still save video links.')
        if self._video_search_lock.locked():raise ValueError('A video search is already running. Try again shortly.')
        async with self._video_search_lock:
            rows=await asyncio.to_thread(youtube_search,self._youtube_key,f"{track['artist']} {track['title']}")
            now=stamp()
            with self.db:
                for r in rows:
                    self.db.execute('INSERT OR IGNORE INTO track_videos VALUES(?,?,?,?,?,0,?,?)',
                                    (track_id,r['video_id'],r['title'],r['channel'],r['kind'],now,'YouTube search'))
                self.db.execute('INSERT OR REPLACE INTO video_searches VALUES(?,?)',(track_id,now))
        return self.video_state(track_id)

    def video_save(self,track_id,url,title,kind='other',confirmed=False):
        self._video_track(track_id)
        identity=video_id(url)
        if not isinstance(title,str) or not 1<=len(title.strip())<=500 or kind not in VIDEO_TYPES or type(confirmed) is not bool:
            raise ValueError('Enter a video title, type, and match status.')
        with self.db:
            self.db.execute("""INSERT INTO track_videos VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(track_id,video_id) DO UPDATE SET title=excluded.title,kind=excluded.kind,confirmed=excluded.confirmed,origin='Saved link',channel=''""",
                (track_id,identity,title.strip(),'',kind,confirmed,stamp(),'Saved link'))
        return self.video_state(track_id)
