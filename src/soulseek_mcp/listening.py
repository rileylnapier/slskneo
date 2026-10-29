"""Persistent listening inbox, explicit taste signals and source context."""
from __future__ import annotations

import asyncio
from datetime import date
import json
import os
from pathlib import Path
from urllib.parse import quote, urlsplit, urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler

SOURCES = {"Beatport", "Hypeddit", "LDS", "YouTube", "SoundCloud", "1001Tracklists", "Soulseek", "Library", "Manual"}
DOMAINS = {"beatport.com": "Beatport", "hypeddit.com": "Hypeddit", "livedjservice.com": "LDS",
           "youtube.com": "YouTube", "youtu.be": "YouTube", "soundcloud.com": "SoundCloud",
           "1001tracklists.com": "1001Tracklists", "bandcamp.com": "Manual"}

from .discovery import DiscoveryStore, normalized
from .research import ResearchMixin
from .library_research import LibraryResearchMixin
from .local_audio import LocalAudioMixin
from .library_uses import LibraryUsesMixin
from .representation import RepresentationMixin
from .watch_profiles import WatchProfileMixin
from .videos import VideoMixin
from .watches import WatchMixin
from .soundcloud import SoundCloudClient, soundcloud_url


def safe_url(value, media=False):
    if not value:
        return ""
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError("Invalid source URL.")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("Source links must use HTTPS without credentials.")
    if media and parsed.hostname not in {"geo-samples.beatport.com", "geo-media.beatport.com"}:
        raise ValueError("Inline previews and artwork currently support Beatport only.")
    if not media and not any(parsed.hostname == d or parsed.hostname.endswith('.' + d) for d in DOMAINS):
        raise ValueError("Use a link from a supported music source.")
    return value


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def resolve_link(url):
    """Read oEmbed metadata only; never treat an uploader as the music artist."""
    safe_url(url)
    host = urlsplit(url).hostname
    source = next(value for domain, value in DOMAINS.items() if host == domain or host.endswith('.' + domain))
    result = {"source": source, "url": url, "title": "", "artist": "", "source_title": "", "uploader": ""}
    endpoints = {"YouTube": "https://www.youtube.com/oembed", "SoundCloud": "https://soundcloud.com/oembed"}
    if source in endpoints:
        endpoint = endpoints[source] + '?' + urlencode({"url": url, "format": "json"})
        try:
            request = Request(endpoint, headers={"User-Agent": "SoulseekStudio/0.1"})
            with build_opener(NoRedirect).open(request, timeout=15) as response:
                payload = response.read(256001)
            if len(payload) > 256000:
                raise ValueError("Metadata response too large.")
            metadata = json.loads(payload)
            result["source_title"] = str(metadata.get("title", ""))[:500]
            result["title"] = result["source_title"]
            result["uploader"] = str(metadata.get("author_name", ""))[:500]
        except Exception:
            result["note"] = "Metadata is unavailable. Enter the artist and exact track version to save this link."
    else:
        result["note"] = "Enter the artist and exact track version. For a DJ set, save one track at a time with its set link."
    return result


class ListeningLibrary(LibraryUsesMixin, RepresentationMixin, WatchProfileMixin, VideoMixin, WatchMixin, LocalAudioMixin, LibraryResearchMixin, ResearchMixin, DiscoveryStore):
    def __init__(self, path):
        super().__init__(path)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS listening (
                track_id TEXT PRIMARY KEY REFERENCES tracks(id), favorite INTEGER NOT NULL DEFAULT 0,
                rating INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS context (
                track_id TEXT REFERENCES tracks(id), source TEXT, url TEXT, data TEXT NOT NULL,
                PRIMARY KEY(track_id,source,url)
            );
            CREATE TABLE IF NOT EXISTS cues (
                track_id TEXT REFERENCES tracks(id), preview_url TEXT, seconds REAL, label TEXT,
                PRIMARY KEY(track_id,preview_url,seconds)
            );
            CREATE TABLE IF NOT EXISTS feed_runs (source TEXT PRIMARY KEY, checked_at TEXT, added INTEGER);
            CREATE TABLE IF NOT EXISTS library_files (
                path TEXT PRIMARY KEY, track_id TEXT REFERENCES tracks(id), modified_ns INTEGER, size INTEGER
            );
        """)
        self.refresh_lock = asyncio.Lock()
        self.init_research()
        self.init_library_research()
        self.soundcloud_client = SoundCloudClient()
        self.init_watches()
        self.init_watch_profiles()
        self.init_videos()
        self.init_representation()
        self.init_library_uses()

    def import_batch(self, records, source, url=""):
        if not isinstance(source, str) or source not in SOURCES:
            raise ValueError("Choose a supported music source.")
        if not isinstance(records, list) or len(records) > 500:
            raise ValueError("Import at most 500 tracks at a time.")
        safe_url(url)
        cleaned = []
        for row in records:
            if not isinstance(row, dict):
                raise ValueError("Every track must be an object.")
            item = {key: row.get(key, "") for key in ("genre", "label", "release", "release_date", "isrc", "source_id", "source_title", "uploader", "content_kind", "classification_note", "identity_note", "uploaded_at")}
            if any(not isinstance(v, str) or len(v) > 500 for v in item.values()):
                raise ValueError("Context fields must be short text.")
            for key in ("url", "preview_url", "artwork", "label_url"):
                item[key] = safe_url(row.get(key, url if key == "url" else ""), media=key in {"preview_url", "artwork"})
            item['soundcloud_url'] = soundcloud_url(row['soundcloud_url']) if row.get('soundcloud_url') else ''
            if source == 'SoundCloud' and not item['soundcloud_url'] and 'soundcloud_url' not in row:
                try:
                    item['soundcloud_url'] = soundcloud_url(item['url'])
                except ValueError:
                    pass
            item['source_links'] = [{'source': str(link.get('source', 'Source'))[:50], 'url': safe_url(link['url'])}
                                    for link in row.get('source_links', [])[:10]]
            item['identity_confirmed'] = row.get('identity_confirmed') is True
            item["credits"] = []
            if not isinstance(row.get("credits", []), list):
                raise ValueError("Credits must be a list.")
            for credit in row.get("credits", []):
                if (not isinstance(credit, dict) or not isinstance(credit.get("name"), str)
                        or not credit["name"].strip() or len(credit["name"]) > 250
                        or credit.get("role") not in ("artist", "remixer", "editor")):
                    raise ValueError("Invalid artist credit.")
                item["credits"].append({"name": credit["name"].strip(), "role": credit["role"],
                                        "url": safe_url(credit.get("url", ""))})
            cleaned.append(item)
        # Base importer validates every record before committing any change.
        result = self.import_tracks(records, source, url)
        with self.db:
            for identity, item in zip(result["track_ids"], cleaned):
                self.db.execute("INSERT OR IGNORE INTO listening(track_id) VALUES(?)", (identity,))
                self.db.execute("INSERT OR REPLACE INTO context VALUES(?,?,?,?)",
                                (identity, source, item["url"], json.dumps(item)))
                if item["credits"]:
                    # Structured source credits beat guesses from punctuation in the title.
                    self.db.execute("DELETE FROM credits WHERE track_id=?", (identity,))
                    for c in item["credits"]:
                        self.db.execute("INSERT OR IGNORE INTO credits VALUES(?,?,?,?)",
                                        (identity, normalized(c["name"]), c["name"], c["role"]))
                else:
                    # A second source must not reintroduce guessed compound names
                    # after a structured catalog already identified the people.
                    structured = [c for r in self.db.execute("SELECT data FROM context WHERE track_id=?", (identity,))
                                  for c in json.loads(r[0]).get("credits", [])]
                    if structured:
                        self.db.execute("DELETE FROM credits WHERE track_id=?", (identity,))
                        for c in structured:
                            self.db.execute("INSERT OR IGNORE INTO credits VALUES(?,?,?,?)",
                                            (identity, normalized(c["name"]), c["name"], c["role"]))
            self.db.execute("INSERT OR REPLACE INTO feed_runs VALUES(?,datetime('now'),?)", (source, result["added"]))
        return result

    def react(self, track_id, favorite=None, rating=None):
        if favorite is not None and type(favorite) is not bool:
            raise ValueError("Favorite must be true or false.")
        if rating is not None and (type(rating) is not int or rating not in (-1, 0, 1)):
            raise ValueError("Rating must be -1, 0, or 1.")
        if not self.db.execute("SELECT 1 FROM tracks WHERE id=?", (track_id,)).fetchone():
            raise ValueError("Track not found.")
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO listening(track_id) VALUES(?)", (track_id,))
            self.db.execute("UPDATE listening SET favorite=COALESCE(?,favorite),rating=COALESCE(?,rating) WHERE track_id=?",
                            (favorite, rating, track_id))
        return {"saved": True}

    def cue(self, track_id, preview_url, seconds, label="Saved moment", remove=False):
        if type(seconds) not in (int, float) or not 0 <= seconds <= 86400:
            raise ValueError("Cue time must be between 0 and 86400 seconds.")
        if not isinstance(label, str) or not label.strip() or len(label) > 80:
            raise ValueError("Give the cue a short label.")
        sources = self.db.execute("SELECT data FROM context WHERE track_id=?", (track_id,)).fetchall()
        local = any(f["url"] == preview_url for f in self.local_audio(track_id))
        if not preview_url or not (local or any(preview_url in {json.loads(r[0]).get("preview_url"), json.loads(r[0]).get("soundcloud_url")} for r in sources)):
            raise ValueError("Cue must belong to this track's recording or preview.")
        with self.db:
            if remove:
                self.db.execute("DELETE FROM cues WHERE track_id=? AND preview_url=? AND seconds=?", (track_id, preview_url, seconds))
            else:
                self.db.execute("INSERT OR REPLACE INTO cues VALUES(?,?,?,?)", (track_id, preview_url, seconds, label.strip()))
        return {"saved": True}

    def inbox(self):
        people = {p["person_key"]: p for p in self.people()}
        tracks = []
        for row in self.db.execute("""SELECT t.*,COALESCE(l.favorite,0) favorite,COALESCE(l.rating,0) rating
                                     FROM tracks t LEFT JOIN listening l ON l.track_id=t.id ORDER BY t.created_at DESC,t.id"""):
            t = dict(row)
            t["favorite"] = bool(t["favorite"])
            t["owned"] = bool(self.db.execute("SELECT 1 FROM library_files WHERE track_id=? LIMIT 1", (t["id"],)).fetchone())
            t["sources"] = [{"source": r["source"], **json.loads(r["data"])} for r in self.db.execute(
                "SELECT * FROM context WHERE track_id=? ORDER BY source,url", (t["id"],))]
            if not t["sources"]:
                t["sources"] = [dict(r) for r in self.db.execute("SELECT source,url FROM sources WHERE track_id=?", (t["id"],))]
            t["credits"] = [{**dict(r), "followed": people[r["person_key"]]["followed"]} for r in self.db.execute(
                "SELECT DISTINCT person_key,name,role FROM credits WHERE track_id=?", (t["id"],))]
            t["cues"] = [dict(r) for r in self.db.execute("SELECT preview_url,seconds,label FROM cues WHERE track_id=? ORDER BY seconds", (t["id"],))]
            t["research"] = self.research_summary(t["id"])
            t["local_audio"] = self.local_audio(t["id"])
            t["uses"] = self.track_uses(t["id"])
            t["tasks"] = self.track_tasks(t["id"])
            t['soundcloud_url'] = next((s['soundcloud_url'] for s in t['sources'] if s.get('soundcloud_url')), '')
            t["preview_url"] = next((s["preview_url"] for s in t["sources"] if s.get("preview_url")), "")
            for key in ("genre", "label", "release", "release_date", "artwork"):
                t[key] = next((s[key] for s in t["sources"] if s.get(key)), "")
            t["upcoming"] = bool(t["release_date"] and t["release_date"][:10] > date.today().isoformat())
            t["query"] = f"{t['artist']} {t['title']}"
            q = quote(t["query"])
            t["lookups"] = [{"name": "Beatport", "url": f"https://www.beatport.com/search?q={q}"},
                            {"name": "YouTube", "url": f"https://www.youtube.com/results?search_query={q}"},
                            {"name": "Bandcamp", "url": f"https://bandcamp.com/search?q={q}"},
                            {"name": "LDS", "url": f"https://livedjservice.com/search?q={q}"},
                            {"name": "SoundCloud", "url": f"https://soundcloud.com/search/sounds?q={q}"}]
            tracks.append(t)
        focus = self.representation_state()
        focus_artists = {r['profile_key']:r for r in focus['artists']}
        imported_follows = {r['watch_id']: r['name'] for r in self.db.execute('SELECT * FROM beatport_follow_imports')}
        # Transparent local preference weights, recomputed from explicit feedback.
        person_weights, genre_weights = {}, {}
        for t in tracks:
            weight = 3 * t["rating"] + 2 * t["favorite"] + t["owned"]
            if not weight:
                continue
            for key in {c["person_key"] for c in t["credits"]}:
                person_weights[key] = person_weights.get(key, 0) + weight
            if t["genre"]:
                genre_weights[t["genre"]] = genre_weights.get(t["genre"], 0) + t["rating"] + .25 * t["owned"]
        for t in tracks:
            own_weight = 3 * t["rating"] + 2 * t["favorite"] + t["owned"]
            reasons = self.beatport_follow_reasons(t['sources'], imported_follows)
            score = 8 * len(reasons)
            for key in {c["person_key"] for c in t["credits"]}:
                p = people[key]
                if p["followed"]:
                    score += 8
                    reasons.append(f"You follow {p['name']}.")
                weight = person_weights.get(key, 0) - own_weight
                score += weight
                if weight > 0:
                    reasons.append(f"Your library, favorites, or ratings point toward {p['name']}.")
            genre_weight = max(-3, min(3, genre_weights.get(t["genre"], 0) - t["rating"] - .25 * t["owned"])) if t["genre"] else 0
            score += genre_weight
            if genre_weight > 0:
                reasons.append(f"Your library or ratings include a preference for {t['genre']}.")
            t['women_focus_matches'] = self.representation_matches(t['sources'],focus_artists)
            if focus['enabled'] and t['women_focus_matches']:
                reasons.append('Women focus: credited artist ' + ', '.join(p['name'] for p in t['women_focus_matches']) + '. Source available in Watches.')
            t["score"] = score
            t["reasons"] = self.library_research_reasons(t["id"]) + reasons or ["Explore a track from your selected sources."]
        tracks.sort(key=lambda t: (-int(focus['enabled'] and bool(t['women_focus_matches'])), -t["score"], t["title"]))
        return {"women_focus":focus, "tracks": tracks, "people": list(people.values()),
                "feeds": [dict(r) for r in self.db.execute("SELECT * FROM feed_runs")],
                "beatport_available": self.beatport_python().is_file() and (Path.home()/".beatport-mcp/token.json").is_file()}

    @staticmethod
    def beatport_python():
        return Path(os.environ.get("SLSK_BEATPORT_PYTHON", str(Path.home()/".local/share/mcp-servers/beatport/.venv/bin/python")))

    async def resolve(self, url):
        return await asyncio.to_thread(resolve_link, url)

    async def seed_folder(self, path):
        from .library_seed import read_music_folder
        if not isinstance(path, str) or not Path(path).is_absolute():
            raise ValueError("Choose an absolute music folder path.")
        result = await asyncio.to_thread(read_music_folder, path)
        added = 0
        for offset in range(0, len(result["files"]), 500):
            batch = result["files"][offset:offset+500]
            imported = self.import_batch([f["record"] for f in batch], "Library")
            added += imported["added"]
            with self.db:
                for f, identity in zip(batch, imported["track_ids"]):
                    self.db.execute("INSERT OR REPLACE INTO library_files VALUES(?,?,?,?)",
                                    (f["path"], identity, f["modified_ns"], f["size"]))
        return {"added": added, "matched_files": len(result["files"]),
                "scanned": result["scanned"], "skipped": result["skipped"], "unreadable": result["unreadable"],
                "truncated": result["truncated"], "filename_inferences": sum(f["method"] == "filename" for f in result["files"])}

    async def beatport(self, operation="refresh", genre_id=0, artist_name=""):
        if operation not in {"refresh", "genres"} or type(genre_id) is not int or genre_id < 0:
            raise ValueError("Choose a valid Beatport genre.")
        if not isinstance(artist_name, str) or len(artist_name) > 250:
            raise ValueError("Invalid artist filter.")
        if not self.beatport_python().is_file():
            raise ValueError("Connect the Beatport MCP installation first.")
        if self.refresh_lock.locked():
            raise ValueError("Beatport is already refreshing.")
        data = await self.beatport_read({"operation": operation, "genre_id": genre_id, "artist_name": artist_name})
        if operation == "genres":
            return data
        return self.import_batch(data["tracks"], "Beatport")

    async def beatport_read(self, request):
        async with self.refresh_lock:
            proc = await asyncio.create_subprocess_exec(str(self.beatport_python()),
                str(Path(__file__).with_name("beatport_feed.py")), json.dumps(request),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            try:
                out, _ = await asyncio.wait_for(proc.communicate(), 50)
            except BaseException:
                if proc.returncode is None:
                    proc.kill()
                await proc.wait()
                raise
            if proc.returncode:
                raise ValueError("Beatport could not be read. Check your Beatport MCP sign-in and try again.")
            return json.loads(out)
