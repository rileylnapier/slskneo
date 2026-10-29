"""Source-attributed artist and label profiles for watch cards."""
import asyncio
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlsplit
from .library_research import stamp

class PlainText(HTMLParser):
    def __init__(self):
        super().__init__();self.parts=[];self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag in {'script','style'}:self.hidden+=1
        if tag in {'p','br','div','li'}:self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in {'script','style'}:self.hidden=max(0,self.hidden-1)
    def handle_data(self,data):
        if not self.hidden:self.parts.append(data)

def clean_profile(record):
    image=record.get('image') or ''
    if not isinstance(image,str):raise ValueError('Invalid profile image')
    if image:
        p=urlsplit(image)
        if len(image)>4096 or p.scheme!='https' or p.netloc!='geo-media.beatport.com' or p.fragment:
            raise ValueError('Invalid profile image host')
    bio=record.get('bio') or ''
    if not isinstance(bio,str):raise ValueError('Invalid biography')
    parser=PlainText();parser.feed(bio[:20000])
    text='\n'.join(line.strip() for line in unescape(''.join(parser.parts)).splitlines() if line.strip())
    return {'image':image,'bio':text[:12000]}

class WatchProfileMixin:
    def init_watch_profiles(self):
        self._profile_task=None
        self.db.executescript('''CREATE TABLE IF NOT EXISTS watch_profiles (
            watch_id TEXT PRIMARY KEY REFERENCES watches(id), image TEXT NOT NULL,
            bio TEXT NOT NULL, checked_at TEXT NOT NULL, error TEXT NOT NULL DEFAULT ''
        );''')

    def _save_watch_profile(self,watch_id,record):
        profile=clean_profile(record)
        self.db.execute('INSERT OR REPLACE INTO watch_profiles VALUES(?,?,?,?,?)',
                        (watch_id,profile['image'],profile['bio'],stamp(),''))

    async def watch_profiles_refresh(self):
        if self._profile_task and not self._profile_task.done():return {'running':True}
        rows=[dict(r) for r in self.db.execute("SELECT * FROM watches WHERE source='Beatport' ORDER BY name")]
        self._profile_task=asyncio.create_task(self._run_watch_profiles(rows))
        return {'started':True,'count':len(rows)}

    async def _run_watch_profiles(self,rows):
        from .watches import profile_identity
        for row in rows:
            try:
                profile=await self.beatport_read({'operation':'watch_profile','kind':row['kind'],'source_id':row['source_id']})
                if profile_identity(profile.get('url'),row['kind'])!=row['source_id']:raise ValueError('Profile mismatch')
                with self.db:self._save_watch_profile(row['id'],profile)
            except asyncio.CancelledError:raise
            except Exception:
                with self.db:
                    self.db.execute("""INSERT INTO watch_profiles VALUES(?,'','',?,'Profile unavailable; try refreshing later.')
                        ON CONFLICT(watch_id) DO UPDATE SET error=excluded.error""",(row['id'],stamp()))
