"""Bounded, resumable-to-review library research. No automatic downloads or merges."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import re
import uuid

from .discovery import normalized


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_candidate(row):
    from .listening import safe_url
    if not isinstance(row, dict):
        raise ValueError("Invalid catalog track.")
    if row.get('source') == 'SoundCloud':
        from .soundcloud import clean_upload_record
        return clean_upload_record(row)
    result = {}
    for key in ("artist", "title", "source_id", "genre", "label", "release", "release_date", "isrc"):
        value = row.get(key) or ""
        if not isinstance(value, str) or len(value) > 500:
            raise ValueError("Invalid catalog metadata.")
        result[key] = value.strip()
    if not result["artist"] or not result["title"] or not result["source_id"].isdigit():
        raise ValueError("Incomplete catalog track.")
    for key in ("url", "preview_url", "artwork", "label_url"):
        result[key] = safe_url(row.get(key) or "", media=key in {"preview_url", "artwork"})
    if not result["url"].startswith("https://www.beatport.com/track/"):
        raise ValueError("Missing catalog source link.")
    bpm = row.get("bpm")
    result["bpm"] = bpm if type(bpm) is int and 20 <= bpm <= 400 else None
    result["key"] = row.get("key") if isinstance(row.get("key"), str) else None
    result["credits"] = []
    for c in row.get("credits", []):
        if (not isinstance(c, dict) or not isinstance(c.get("name"), str)
                or not c["name"].strip() or len(c["name"]) > 250
                or c.get("role") not in {"artist", "remixer", "editor"}):
            raise ValueError("Invalid catalog credit.")
        result["credits"].append({"name": c["name"].strip(), "role": c["role"], "url": safe_url(c.get("url", ""))})
    return result


class LibraryResearchMixin:
    def init_library_research(self):
        self._library_research_task = None
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS library_research_jobs (
                id TEXT PRIMARY KEY, status TEXT NOT NULL, started_at TEXT NOT NULL,
                finished_at TEXT, completed INTEGER NOT NULL DEFAULT 0, seeds TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS library_research_candidates (
                id TEXT PRIMARY KEY, record TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                track_id TEXT REFERENCES tracks(id), first_seen TEXT NOT NULL, last_seen TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS library_research_links (
                candidate_id TEXT REFERENCES library_research_candidates(id),
                seed_id TEXT REFERENCES tracks(id), job_id TEXT REFERENCES library_research_jobs(id),
                reason TEXT NOT NULL, kind TEXT NOT NULL, checked_at TEXT NOT NULL,
                PRIMARY KEY(candidate_id,seed_id)
            );
        """)
        # A closed app never claims an abandoned worker is still running.
        with self.db:
            self.db.execute("UPDATE library_research_jobs SET status='interrupted',finished_at=? WHERE status='running'", (stamp(),))

    def library_research_state(self):
        row = self.db.execute("SELECT * FROM library_research_jobs ORDER BY rowid DESC LIMIT 1").fetchone()
        job = {**dict(row), "seeds": json.loads(row["seeds"])} if row else None
        focus = self.representation_state()
        focus_artists = {r['profile_key']:r for r in focus['artists']}
        candidates = []
        for r in self.db.execute("SELECT * FROM library_research_candidates ORDER BY last_seen DESC,id LIMIT 500"):
            links = [dict(l) for l in self.db.execute("""SELECT l.*,t.artist,t.title FROM library_research_links l
                        JOIN tracks t ON t.id=l.seed_id WHERE candidate_id=? ORDER BY checked_at DESC""", (r["id"],))]
            candidates.append({**dict(r), "record": json.loads(r["record"]), "evidence": links + self.watch_evidence(r["id"])})
        for candidate in candidates:
            record = candidate['record']
            candidate['women_focus_matches'] = self.representation_matches([{**record,'source':record.get('source','Beatport')}],focus_artists)
        counts = {r["status"]: r["n"] for r in self.db.execute("SELECT status,COUNT(*) n FROM library_research_candidates GROUP BY status")}
        return {"women_focus_enabled":focus['enabled'], "job": job, "candidates": candidates, "counts": counts}

    async def library_research_start(self, seed_ids):
        if self._library_research_task and not self._library_research_task.done():
            raise ValueError("Library research is already running.")
        if (not isinstance(seed_ids, list) or not 1 <= len(seed_ids) <= 30
                or any(not isinstance(i, str) for i in seed_ids) or len(set(seed_ids)) != len(seed_ids)):
            raise ValueError("Choose 1–30 different owned tracks.")
        seeds = []
        for identity in seed_ids:
            row = self.db.execute("""SELECT id,artist,title FROM tracks WHERE id=? AND
                EXISTS(SELECT 1 FROM library_files WHERE track_id=tracks.id)""", (identity,)).fetchone()
            if not row:
                raise ValueError("Every seed must be a track in your imported library.")
            seeds.append({**dict(row), "status": "waiting"})
        if not self.beatport_python().is_file():
            raise ValueError("Connect the Beatport MCP installation first.")
        job_id = uuid.uuid4().hex
        with self.db:
            self.db.execute("INSERT INTO library_research_jobs(id,status,started_at,seeds) VALUES(?,'running',?,?)",
                            (job_id, stamp(), json.dumps(seeds)))
        self._library_research_task = asyncio.create_task(self._run_library_research(job_id, seeds))
        return {"job_id": job_id}

    async def library_research_cancel(self):
        task = self._library_research_task
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        # Also covers cancellation before the task gets its first event-loop turn.
        with self.db:
            self.db.execute("UPDATE library_research_jobs SET status='cancelled',finished_at=? WHERE status='running'", (stamp(),))
        return {"cancelled": True}

    async def shutdown_library_research(self):
        await self.library_research_cancel()

    def _save_research_job(self, job_id, seeds, status="running"):
        with self.db:
            self.db.execute("UPDATE library_research_jobs SET seeds=?,completed=?,status=?,finished_at=? WHERE id=?",
                            (json.dumps(seeds), sum(s["status"] in {"done", "error"} for s in seeds), status,
                             None if status == "running" else stamp(), job_id))

    async def _run_library_research(self, job_id, seeds):
        status = "complete"
        try:
            for seed in seeds:
                seed["status"] = "researching"
                self._save_research_job(job_id, seeds)
                try:
                    result = await self.beatport_read({"operation": "research", "seed": seed})
                    # Validate the whole seed response before persisting any part.
                    found = [(clean_candidate(t), "possible_version") for t in result.get("versions", [])[:3]]
                    found += [(clean_candidate(t), "artist_catalog") for t in result.get("recent", [])[:8]]
                    seed["candidates"], seed["collected"] = self._store_library_findings(job_id, seed, found)
                    seed["status"] = "done"
                except asyncio.CancelledError:
                    raise
                except Exception:
                    seed.update(status="error", error="Beatport could not be read for this seed. Check the connection and retry.")
                self._save_research_job(job_id, seeds)
                await asyncio.sleep(.3)
            if any(s["status"] == "error" for s in seeds):
                status = "partial" if any(s["status"] == "done" for s in seeds) else "failed"
        except asyncio.CancelledError:
            status = "cancelled"
            for seed in seeds:
                if seed["status"] == "researching":
                    seed["status"] = "cancelled"
        finally:
            self._save_research_job(job_id, seeds, status)

    def _store_library_findings(self, job_id, seed, found):
        seen, collected = set(), set()
        seed_names = {normalized(seed["artist"])} | {
            normalized(r[0]) for r in self.db.execute("SELECT name FROM credits WHERE track_id=?", (seed["id"],))
        } | {normalized(n) for n in re.split(r",\s*|\s+&\s+", seed["artist"]) if n.strip()}
        with self.db:
            for track, kind in found:
                cid = track["source_id"]
                if cid in seen:
                    continue
                # A name filter may return unrelated substring matches. Admit
                # recent releases only when a structured credit matches the seed.
                names = {normalized(c["name"]) for c in track["credits"]} | {normalized(track["artist"])}
                if not names.intersection(seed_names):
                    continue
                known = self.db.execute("SELECT 1 FROM sources WHERE source='Beatport' AND url=?", (track["url"],)).fetchone()
                known = known or self.db.execute("SELECT 1 FROM context WHERE source='Beatport' AND json_extract(data,'$.source_id')=?", (cid,)).fetchone()
                # Exact text is sufficient for suppressing a duplicate suggestion,
                # but never for enriching/merging a local recording automatically.
                known = known or any(normalized(r["artist"]) == normalized(track["artist"]) and normalized(r["title"]) == normalized(track["title"])
                                     for r in self.db.execute("SELECT artist,title FROM tracks"))
                if known:
                    collected.add(cid)
                    continue
                seen.add(cid)
                reason = (f"Beatport search for {seed['artist']} — {seed['title']}. Artist and exact version need review."
                          if kind == "possible_version" else
                          f"A recent catalog result credits {seed['artist']}, an artist on your seed track. Name matches can include aliases; check the profile.")
                now = stamp()
                self.db.execute("""INSERT INTO library_research_candidates(id,record,first_seen,last_seen) VALUES(?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET record=excluded.record,last_seen=excluded.last_seen""",
                    (cid, json.dumps(track), now, now))
                self.db.execute("INSERT OR REPLACE INTO library_research_links VALUES(?,?,?,?,?,?)",
                                (cid, seed["id"], job_id, reason, kind, now))
        return len(seen), len(collected)

    def library_research_review(self, candidate_id, decision, artist=None, title=None, content_kind=None):
        if decision not in {"keep", "dismiss", "restore"}:
            raise ValueError("Choose keep, dismiss, or restore.")
        row = self.db.execute("SELECT * FROM library_research_candidates WHERE id=?", (candidate_id,)).fetchone()
        if not row:
            raise ValueError("Research finding not found.")
        if row["status"] == "kept":
            return {"saved": True, "track_id": row["track_id"]}
        track_id = None
        if decision == "keep":
            record = json.loads(row['record'])
            source = record.get('source', 'Beatport')
            if source == 'SoundCloud':
                from .soundcloud import KINDS
                if (not isinstance(artist, str) or not artist.strip() or len(artist) > 250
                        or not isinstance(title, str) or not title.strip() or len(title) > 500 or content_kind not in KINDS):
                    raise ValueError('Confirm the recording artist, title/version, and upload type before keeping this SoundCloud find.')
                record.update(artist=artist.strip(), title=title.strip(), content_kind=content_kind,
                              identity_confirmed=True, identity_note='Recording artist and version confirmed by you.')
            track_id = self.import_batch([record], source)['track_ids'][0]
            with self.db:
                self.db.execute('UPDATE library_research_candidates SET record=? WHERE id=?', (json.dumps(record), candidate_id))
        with self.db:
            self.db.execute("UPDATE library_research_candidates SET status=?,track_id=? WHERE id=?",
                            ({"keep": "kept", "dismiss": "dismissed", "restore": "pending"}[decision], track_id, candidate_id))
        return {"saved": True, "track_id": track_id}

    def library_research_reasons(self, track_id):
        return [r[0] for r in self.db.execute("""SELECT DISTINCT l.reason FROM library_research_links l
            JOIN library_research_candidates c ON c.id=l.candidate_id WHERE c.track_id=? LIMIT 3""", (track_id,))] + [r[0] for r in self.db.execute("""SELECT DISTINCT f.reason FROM watch_findings f
            JOIN library_research_candidates c ON c.id=f.candidate_id WHERE c.track_id=? LIMIT 3""", (track_id,))]
