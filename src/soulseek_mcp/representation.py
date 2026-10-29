"""Explicit, source-attributed artist representation for an optional listening focus."""
import asyncio
import json
from urllib.parse import urlsplit
import ipaddress
from .library_research import stamp


def evidence_url(value):
    if not isinstance(value,str) or len(value)>2048:
        raise ValueError('Add a public source link.')
    p=urlsplit(value)
    if p.scheme!='https' or not p.hostname or '.' not in p.hostname or p.username or p.password or p.port or p.hostname.endswith(('.local','.localhost')):
        raise ValueError('Use a public HTTPS source without credentials.')
    try:ipaddress.ip_address(p.hostname)
    except ValueError:return value
    raise ValueError('Use a public source website.')


class RepresentationMixin:
    def init_representation(self):
        self._focus_explore_lock=asyncio.Lock()
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS artist_representation (
                profile_key TEXT PRIMARY KEY, name TEXT NOT NULL, source_url TEXT NOT NULL,
                note TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS listening_focus (
                id INTEGER PRIMARY KEY CHECK(id=1), women INTEGER NOT NULL DEFAULT 0
            );
            INSERT OR IGNORE INTO listening_focus VALUES(1,0);
        ''')

    def representation_state(self):
        return {'enabled':bool(self.db.execute('SELECT women FROM listening_focus WHERE id=1').fetchone()[0]),
                'artists':[dict(r) for r in self.db.execute('SELECT * FROM artist_representation ORDER BY name')]}

    def representation_mode(self,enabled):
        if type(enabled) is not bool:raise ValueError('Focus must be on or off.')
        with self.db:self.db.execute('UPDATE listening_focus SET women=? WHERE id=1',(enabled,))
        return self.representation_state()

    def representation_save(self,watch_id,included,source_url='',note=''):
        watch=self.db.execute('SELECT * FROM watches WHERE id=?',(watch_id,)).fetchone()
        if not watch or watch['source']!='Beatport' or watch['kind'] not in {'artist','remixer'}:
            raise ValueError('Choose a Beatport artist profile. Labels and uploaders are not artist identity.')
        if type(included) is not bool:raise ValueError('Choose whether to include this artist.')
        key='artist:'+watch['source_id']
        if included:
            evidence_url(source_url)
            if not isinstance(note,str) or not 10<=len(note.strip())<=1000:
                raise ValueError('Add a short note explaining the explicit artist information in this source.')
        with self.db:
            if included:
                self.db.execute('INSERT OR REPLACE INTO artist_representation VALUES(?,?,?,?,?)',(key,watch['name'],source_url,note.strip(),stamp()))
            else:self.db.execute('DELETE FROM artist_representation WHERE profile_key=?',(key,))
        return self.representation_state()

    def representation_source(self,profile_key):
        row=self.db.execute('SELECT source_url FROM artist_representation WHERE profile_key=?',(profile_key,)).fetchone()
        if not row:raise ValueError('No source saved for this artist.')
        return {'url':evidence_url(row[0])}

    def representation_matches(self,sources,artists=None):
        from .watches import profile_identity
        artists=artists if artists is not None else {r['profile_key']:dict(r) for r in self.db.execute('SELECT * FROM artist_representation')}
        matches={}
        for source in sources:
            if source.get('source')!='Beatport':continue
            for credit in source.get('credits',[]):
                if credit.get('role') not in {'artist','remixer'}:continue
                try:key='artist:'+profile_identity(credit.get('url'),'artist')
                except ValueError:continue
                if key in artists:matches[key]=artists[key]
        return list(matches.values())

    async def representation_explore(self):
        from .library_research import clean_candidate
        from .watches import matches_watch
        profiles=self.representation_state()['artists'][:10]
        if not profiles:raise ValueError('Add sourced artist information in Watches first.')
        if self._focus_explore_lock.locked():raise ValueError('A focus discovery run is already in progress.')
        added=0;errors=[]
        async with self._focus_explore_lock:
            for profile in profiles:
                identity=profile['profile_key'].split(':')[1]
                watch=self.db.execute("SELECT * FROM watches WHERE source='Beatport' AND source_id=? AND kind IN ('artist','remixer') ORDER BY kind LIMIT 1",(identity,)).fetchone()
                if not watch:continue
                try:
                    result=await self.beatport_read({'operation':'watch_tracks','kind':'artist','source_id':identity})
                    records=[clean_candidate(r) for r in result['tracks']]
                    if any(not matches_watch(r,{'kind':'artist','source_id':identity}) for r in records):raise ValueError('Identity mismatch')
                    now=stamp();found=0
                    with self.db:
                        for record in records:
                            if self.db.execute("SELECT 1 FROM context WHERE source='Beatport' AND (url=? OR json_extract(data,'$.source_id')=?)",(record['url'],record['source_id'])).fetchone():continue
                            changed=self.db.execute('INSERT OR IGNORE INTO library_research_candidates(id,record,first_seen,last_seen) VALUES(?,?,?,?)',(record['source_id'],json.dumps(record),now,now)).rowcount
                            if not changed:continue
                            reason=f"Women focus exploration: catalog artist/remixer credit matches {profile['name']}. Representation source: {profile['source_url']}. This is a recent catalog pick, not a newly detected release."
                            self.db.execute('INSERT OR IGNORE INTO watch_findings VALUES(?,?,?,?)',(watch['id'],record['source_id'],reason,now))
                            added+=1;found+=1
                            if found>=3:break
                except Exception:
                    errors.append(profile['name'])
        return {'added':added,'profiles_checked':len(profiles),'errors':errors}
