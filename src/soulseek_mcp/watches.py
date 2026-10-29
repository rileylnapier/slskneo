"""Persistent, bounded Beatport watches. No inferred follows or automatic downloads."""
from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

from .watch_profiles import clean_profile
from .discovery import normalized
from .library_research import clean_candidate, stamp

INTERVALS = {24, 72, 168}
MAX_WATCHES = 500


def profile_identity(url, kind):
    if kind not in {'artist', 'remixer', 'label'} or not isinstance(url, str):
        raise ValueError('Choose an artist, remixer, or label profile.')
    parts = urlsplit(url)
    category = 'label' if kind == 'label' else 'artist'
    match = re.fullmatch(rf'/{category}/[^/]+/([1-9][0-9]*)/?', parts.path)
    if (parts.scheme != 'https' or parts.netloc not in {'beatport.com', 'www.beatport.com'}
            or parts.query or parts.fragment or not match):
        raise ValueError('Use a Beatport artist or label profile URL, not a search or track link.')
    return match[1]


def matches_watch(record, watch):
    if watch['kind'] == 'label':
        urls = [record.get('label_url', '')]
    else:
        roles = {'artist', 'remixer'} if watch['kind'] == 'artist' else {'remixer'}
        urls = [c['url'] for c in record['credits'] if c['role'] in roles]
    for url in urls:
        try:
            if profile_identity(url, watch['kind']) == watch['source_id']:
                return True
        except ValueError:
            continue
    return False


class WatchMixin:
    def init_watches(self):
        self._watch_task = None
        self._watch_scheduler = None
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS beatport_follow_imports (
                watch_id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
                imported_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS beatport_follow_sync (
                id INTEGER PRIMARY KEY CHECK(id=1), imported_at TEXT NOT NULL,
                artists INTEGER NOT NULL, labels INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS watches (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, source_id TEXT NOT NULL,
                name TEXT NOT NULL, url TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
                interval_hours INTEGER NOT NULL DEFAULT 24, next_check REAL NOT NULL DEFAULT 0,
                last_attempt TEXT, last_success TEXT, status TEXT NOT NULL DEFAULT 'waiting',
                error TEXT NOT NULL DEFAULT '', checked_count INTEGER NOT NULL DEFAULT 0,
                added INTEGER NOT NULL DEFAULT 0, limited INTEGER NOT NULL DEFAULT 0, follow_key TEXT
            );
            CREATE TABLE IF NOT EXISTS watch_seen (
                watch_id TEXT REFERENCES watches(id), source_id TEXT NOT NULL,
                PRIMARY KEY(watch_id,source_id)
            );
            CREATE TABLE IF NOT EXISTS watch_findings (
                watch_id TEXT REFERENCES watches(id), candidate_id TEXT REFERENCES library_research_candidates(id),
                reason TEXT NOT NULL, checked_at TEXT NOT NULL,
                PRIMARY KEY(watch_id,candidate_id)
            );
        ''')
        columns = {row[1] for row in self.db.execute('PRAGMA table_info(watches)')}
        for column, definition in [('source', "TEXT NOT NULL DEFAULT 'Beatport'"), ('person_key', 'TEXT'), ('artist_name', 'TEXT'), ('skipped_count', 'INTEGER NOT NULL DEFAULT 0')]:
            if column not in columns:
                self.db.execute(f'ALTER TABLE watches ADD COLUMN {column} {definition}')
        self.db.commit()
        with self.db:
            self.db.execute("UPDATE watches SET status='interrupted',next_check=0 WHERE status='checking'")

    async def beatport_import_follows(self):
        result = await self.beatport_read({'operation': 'follows'})
        profiles = result.get('profiles')
        if not isinstance(profiles, list) or len(profiles) > MAX_WATCHES:
            raise ValueError('Beatport follows exceed the 500-watch limit or could not be read.')
        valid = {}
        for profile in profiles:
            kind, name = profile.get('kind'), profile.get('name')
            if kind not in {'artist', 'label'} or not isinstance(name, str) or not 1 <= len(name.strip()) <= 250:
                raise ValueError('Beatport returned an invalid followed profile. Nothing was imported.')
            identity = profile_identity(profile.get('url'), kind)
            valid[f'{kind}:{identity}'] = {**profile, **clean_profile({'image':profile.get('image','')}), 'name': name.strip(), 'source_id': identity}
        existing = {r[0] for r in self.db.execute('SELECT id FROM watches')}
        if len(existing | valid.keys()) > MAX_WATCHES:
            raise ValueError('This import would exceed the 500-watch limit. Nothing was imported.')
        now = stamp()
        with self.db:
            for key, p in valid.items():
                # Never resume a paused watch or overwrite a listener's cadence.
                self.db.execute("""INSERT OR IGNORE INTO watches(id,kind,source_id,name,url)
                    VALUES(?,?,?,?,?)""", (key,p['kind'],p['source_id'],p['name'],p['url']))
                if p['image'] and not self.db.execute('SELECT 1 FROM watch_profiles WHERE watch_id=?',(key,)).fetchone():
                    self._save_watch_profile(key,p)
                self.db.execute('INSERT OR REPLACE INTO beatport_follow_imports VALUES(?,?,?,?)',
                                (key,p['name'],p['kind'],now))
            counts = {kind: sum(p['kind'] == kind for p in valid.values()) for kind in ('artist','label')}
            self.db.execute('INSERT OR REPLACE INTO beatport_follow_sync VALUES(1,?,?,?)', (now,counts['artist'],counts['label']))
        return {'added': len(valid.keys()-existing), 'existing': len(valid.keys() & existing),
                'artists': counts['artist'], 'labels': counts['label'], 'imported_at': now}

    def beatport_follow_reasons(self, sources, imported):
        matched = set()
        for source in sources:
            if source.get('source') != 'Beatport':
                continue
            links = [('artist', c.get('url')) for c in source.get('credits', [])]
            links.append(('label', source.get('label_url')))
            for kind, url in links:
                try:
                    key = f'{kind}:{profile_identity(url,kind)}'
                except ValueError:
                    continue
                if key in imported:
                    matched.add(key)
        return [f"You follow {imported[key]} on Beatport ({key.split(':')[0]})." for key in sorted(matched)]

    async def soundcloud_configure(self, client_id, client_secret):
        result = await self.soundcloud_client.configure(client_id, client_secret)
        with self.db:
            self.db.execute("UPDATE watches SET next_check=0,status='waiting',error='' WHERE source='SoundCloud' AND enabled=1 AND status='error'")
        return result

    def soundcloud_status(self):
        return {'configured': self.soundcloud_client.configured}

    async def soundcloud_resolve_profile(self, url):
        return await self.soundcloud_client.resolve_profile(url)

    async def soundcloud_watch_add(self, url, person_key, identity_confirmed=False, interval_hours=24):
        if identity_confirmed is not True:
            raise ValueError('Confirm that this SoundCloud profile belongs to the selected artist.')
        if type(interval_hours) is not int or interval_hours not in INTERVALS:
            raise ValueError('Choose daily, every three days, or weekly checks.')
        person = self.db.execute('SELECT name FROM credits WHERE person_key=? LIMIT 1', (person_key,)).fetchone()
        if not person:
            raise ValueError('Choose an artist from your collected music.')
        profile = await self.soundcloud_client.resolve_profile(url)
        key = 'soundcloud:' + profile['source_id']
        existing = self.db.execute('SELECT person_key FROM watches WHERE id=?', (key,)).fetchone()
        if existing:
            if existing['person_key'] != person_key:
                raise ValueError('This profile is already linked to another artist. Review the existing watch.')
            return {'id': key, 'existing': True}
        if self.db.execute('SELECT count(*) FROM watches').fetchone()[0] >= MAX_WATCHES:
            raise ValueError('This version supports up to 500 watches.')
        with self.db:
            self.db.execute("""INSERT INTO watches(id,kind,source_id,name,url,interval_hours,source,person_key,artist_name)
                VALUES(?,'soundcloud',?,?,?,?, 'SoundCloud',?,?)""",
                (key, profile['source_id'], profile['name'], profile['url'], interval_hours, person_key, person['name']))
        return {'id': key, 'existing': False}

    def follow(self, name, enabled=True):
        if type(enabled) is not bool:
            raise ValueError('Enabled must be true or false.')
        super().follow(name, enabled)
        key = normalized(name)
        if not enabled:
            with self.db:
                self.db.execute("UPDATE watches SET enabled=0,status='paused' WHERE follow_key=?", (key,))
            return
        # Only an unambiguous structured source credit can create a watch without
        # asking the listener to choose between same-named Beatport profiles.
        profiles = {}
        for row in self.db.execute("SELECT data FROM context WHERE source='Beatport'"):
            for credit in json.loads(row[0]).get('credits', []):
                if normalized(credit['name']) != key:
                    continue
                try:
                    identity = profile_identity(credit.get('url'), 'artist')
                except ValueError:
                    continue
                profiles[identity] = credit
        if len(profiles) != 1:
            return
        identity, credit = next(iter(profiles.items()))
        watch_id = f'artist:{identity}'
        if self.db.execute('SELECT count(*) FROM watches').fetchone()[0] >= MAX_WATCHES and not self.db.execute('SELECT 1 FROM watches WHERE id=?', (watch_id,)).fetchone():
            return
        with self.db:
            self.db.execute("""INSERT OR IGNORE INTO watches(id,kind,source_id,name,url,follow_key)
                VALUES(?,'artist',?,?,?,?)""", (watch_id, identity, credit['name'], credit['url'], key))
            self.db.execute("UPDATE watches SET enabled=1,status='waiting',next_check=0 WHERE id=? AND follow_key=? AND enabled=0", (watch_id, key))

    def watch_state(self):
        watches = [dict(r) for r in self.db.execute('SELECT * FROM watches ORDER BY name,kind')]
        profiles = {r['watch_id']: dict(r) for r in self.db.execute('SELECT * FROM watch_profiles')}
        focus = self.representation_state()
        focus_artists = {r['profile_key']:r for r in focus['artists']}
        imported = {r[0] for r in self.db.execute('SELECT watch_id FROM beatport_follow_imports')}
        for watch in watches:
            watch['women_focus'] = focus_artists.get('artist:'+watch['source_id']) if watch['source']=='Beatport' and watch['kind'] in {'artist','remixer'} else None
            watch['profile'] = profiles.get(watch['id'])
            watch['from_beatport_follow'] = watch['id'] in imported
            watch['enabled'] = bool(watch['enabled'])
            watch['limited'] = bool(watch['limited'])
            watch['pending'] = self.db.execute('''SELECT count(*) FROM watch_findings f
                JOIN library_research_candidates c ON c.id=f.candidate_id
                WHERE f.watch_id=? AND c.status='pending' ''', (watch['id'],)).fetchone()[0]
        pending = self.db.execute("SELECT count(DISTINCT c.id) FROM library_research_candidates c JOIN watch_findings f ON f.candidate_id=c.id WHERE c.status='pending'").fetchone()[0]
        sync = self.db.execute('SELECT * FROM beatport_follow_sync WHERE id=1').fetchone()
        return {'women_focus': focus, 'profiles_running': bool(self._profile_task and not self._profile_task.done()), 'beatport_follows': dict(sync) if sync else None, 'watches': watches, 'pending_count': pending, 'running': bool(self._watch_task and not self._watch_task.done())}

    async def watch_search(self, query, kind='artist'):
        if kind not in {'artist', 'remixer', 'label'} or not isinstance(query, str) or not 2 <= len(query.strip()) <= 150:
            raise ValueError('Enter at least two characters to find a Beatport profile.')
        result = await self.beatport_read({'operation': 'watch_search', 'query': query.strip(), 'kind': kind})
        profiles = []
        for row in result.get('profiles', [])[:10]:
            identity = profile_identity(row['url'], kind)
            if not isinstance(row.get('name'), str) or not 1 <= len(row['name']) <= 250:
                raise ValueError('Invalid Beatport profile.')
            profiles.append({'id': identity, 'name': row['name'], 'url': row['url']})
        return {'profiles': profiles}

    async def watch_add(self, url, kind='artist', interval_hours=24):
        identity = profile_identity(url, kind)
        if type(interval_hours) is not int or interval_hours not in INTERVALS:
            raise ValueError('Choose daily, every three days, or weekly checks.')
        key = f'{kind}:{identity}'
        if self.db.execute('SELECT 1 FROM watches WHERE id=?', (key,)).fetchone():
            return {'id': key, 'existing': True}
        if self.db.execute('SELECT count(*) FROM watches').fetchone()[0] >= MAX_WATCHES:
            raise ValueError('This version supports up to 500 watches.')
        profile = await self.beatport_read({'operation': 'watch_profile', 'kind': kind, 'source_id': identity})
        name = profile.get('name')
        if profile_identity(profile.get('url'), kind) != identity or not isinstance(name, str) or not 1 <= len(name) <= 250:
            raise ValueError('Beatport profile could not be verified.')
        if self.db.execute('SELECT count(*) FROM watches').fetchone()[0] >= MAX_WATCHES and not self.db.execute('SELECT 1 FROM watches WHERE id=?', (key,)).fetchone():
            raise ValueError('This version supports up to 500 watches.')
        with self.db:
            self.db.execute('''INSERT OR IGNORE INTO watches(id,kind,source_id,name,url,interval_hours)
                VALUES(?,?,?,?,?,?)''', (key, kind, identity, name, profile['url'], interval_hours))
        return {'id': key, 'existing': False}

    def watch_update(self, watch_id, enabled=None, interval_hours=None):
        if enabled is not None and type(enabled) is not bool:
            raise ValueError('Enabled must be true or false.')
        if interval_hours is not None and (type(interval_hours) is not int or interval_hours not in INTERVALS):
            raise ValueError('Choose daily, every three days, or weekly checks.')
        row = self.db.execute('SELECT * FROM watches WHERE id=?', (watch_id,)).fetchone()
        if not row:
            raise ValueError('Watch not found.')
        active = bool(row['enabled']) if enabled is None else enabled
        hours = interval_hours or row['interval_hours']
        status = 'waiting' if active and not row['enabled'] else row['status'] if active else 'paused'
        due = 0 if active and not row['enabled'] else row['next_check']
        if interval_hours is not None and row['last_success']:
            due = datetime.fromisoformat(row['last_success']).timestamp() + hours * 3600
        with self.db:
            self.db.execute('UPDATE watches SET enabled=?,interval_hours=?,status=?,next_check=? WHERE id=?',
                            (active, hours, status, due, watch_id))
        return {'saved': True}

    async def watch_check(self, watch_id=None, due_only=False):
        if self._watch_task and not self._watch_task.done():
            return {'started': False, 'running': True}
        rows = [dict(r) for r in self.db.execute('SELECT * FROM watches WHERE enabled=1 ORDER BY next_check,id')
                if (watch_id is None or r['id'] == watch_id) and (not due_only or r['next_check'] <= time.time())]
        if watch_id is not None and not rows:
            raise ValueError('Resume this watch before checking it.')
        if not rows:
            return {'started': False, 'running': False}
        self._watch_task = asyncio.create_task(self._run_watches([r['id'] for r in rows]))
        return {'started': True, 'count': len(rows)}

    async def _run_watches(self, identities):
        for identity in identities:
            row = self.db.execute('SELECT * FROM watches WHERE id=?', (identity,)).fetchone()
            if not row or not row['enabled']:
                continue
            watch = dict(row)
            with self.db:
                self.db.execute("UPDATE watches SET status='checking',last_attempt=?,error='',next_check=? WHERE id=?",
                                (stamp(), time.time() + 3600, identity))
            try:
                result = (await self.soundcloud_client.uploads(watch) if watch['source'] == 'SoundCloud' else
                          await self.beatport_read({'operation': 'watch_tracks', 'kind': watch['kind'], 'source_id': watch['source_id']}))
                if not isinstance(result.get('tracks'), list) or len(result['tracks']) > 100:
                    raise ValueError('Invalid watch response.')
                tracks = [clean_candidate(t) for t in result['tracks']]
                # Fail closed if the source ever stops honoring its identity filter.
                if any((t.get('uploader_id') != watch['source_id'] if watch['source'] == 'SoundCloud' else not matches_watch(t, watch)) for t in tracks):
                    raise ValueError('Unexpected catalog identity.')
                if not self.db.execute('SELECT enabled FROM watches WHERE id=?', (identity,)).fetchone()[0]:
                    continue
                skipped = result.get('skipped',0)
                if type(skipped) is not int or not 0 <= skipped <= 100:
                    raise ValueError('Invalid skipped count.')
                self._store_watch_check(watch, tracks, bool(result.get('limited')), skipped)
            except asyncio.CancelledError:
                with self.db:
                    self.db.execute("UPDATE watches SET status='interrupted',next_check=0 WHERE id=? AND enabled=1", (identity,))
                raise
            except Exception:
                with self.db:
                    self.db.execute("""UPDATE watches SET status='error',error=?
                        WHERE id=? AND enabled=1""", (f"{watch['source']} could not be checked. Retry or check your connection.", identity))

    def _store_watch_check(self, watch, tracks, limited, skipped=0):
        baseline = watch['last_success'] is None
        now, added = stamp(), 0
        known_text = {(normalized(r['artist']), normalized(r['title'])) for r in self.db.execute('SELECT artist,title FROM tracks')}
        with self.db:
            for track in tracks:
                source = watch.get('source', 'Beatport')
                cid = ('soundcloud:' if source == 'SoundCloud' else '') + track['source_id']
                fresh = self.db.execute('INSERT OR IGNORE INTO watch_seen VALUES(?,?)', (watch['id'], cid)).rowcount
                if baseline or not fresh:
                    continue
                known = self.db.execute("SELECT 1 FROM context WHERE source=? AND (url=? OR json_extract(data,'$.source_id')=?)", (source, track['url'], track['source_id'])).fetchone()
                if known or (source == 'Beatport' and (normalized(track['artist']), normalized(track['title'])) in known_text):
                    continue
                added += self.db.execute('''INSERT OR IGNORE INTO library_research_candidates(id,record,first_seen,last_seen)
                    VALUES(?,?,?,?)''', (cid, json.dumps(track), now, now)).rowcount
                reason = (f"New public upload from {watch['name']} on SoundCloud, linked by you to {watch['artist_name']}. Uploaded: {track.get('uploaded_at') or 'unknown'}. Artist and version need review."
                          if source == 'SoundCloud' else f"Newly seen on your Beatport {watch['kind']} watch for {watch['name']}. Listed release date: {track['release_date'] or 'unknown'}.")
                self.db.execute('INSERT OR IGNORE INTO watch_findings VALUES(?,?,?,?)', (watch['id'], cid, reason, now))
            current = self.db.execute('SELECT interval_hours FROM watches WHERE id=?', (watch['id'],)).fetchone()
            self.db.execute("""UPDATE watches SET status='ready',last_success=?,next_check=?,error='',checked_count=?,added=?,limited=?,skipped_count=? WHERE id=?""",
                            (now, time.time() + current[0] * 3600, len(tracks), added, limited, skipped, watch['id']))

    def watch_evidence(self, candidate_id):
        return [dict(r) for r in self.db.execute('''SELECT 'watch:' || w.id seed_id,w.name artist,w.source || ' watch' title,
            'watch' kind,f.reason,f.checked_at,w.url FROM watch_findings f JOIN watches w ON w.id=f.watch_id
            WHERE f.candidate_id=? ORDER BY f.checked_at DESC''', (candidate_id,))]

    def start_watches(self):
        if self._watch_scheduler is None:
            self._watch_scheduler = asyncio.create_task(self._schedule_watches())

    async def _schedule_watches(self):
        while True:
            await self.watch_check(due_only=True)
            await asyncio.sleep(60)

    async def shutdown_watches(self):
        for task in (self._watch_scheduler, self._watch_task, self._profile_task):
            if task and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        self._watch_scheduler = None
