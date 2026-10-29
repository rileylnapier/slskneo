"""Dated source evidence for exact track versions, separate from taste and rank."""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from urllib.parse import urlsplit, urlunsplit

from .discovery import normalized


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ResearchMixin:
    def init_research(self):
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS research_observations (
                id TEXT PRIMARY KEY, track_id TEXT NOT NULL REFERENCES tracks(id),
                kind TEXT NOT NULL, source TEXT NOT NULL, url TEXT NOT NULL,
                event_date TEXT NOT NULL, subject TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('candidate','confirmed')),
                metric INTEGER, recorded_at TEXT NOT NULL, details TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS research_track ON research_observations(track_id,event_date);
        """)

    def research_track(self, track_id):
        row = self.db.execute("SELECT id,artist,title FROM tracks WHERE id=?", (track_id,)).fetchone()
        if not row:
            raise ValueError("Choose a collected track version first.")
        return dict(row)

    def _save_observation(self, track_id, kind, source, url, event_date, subject,
                          status, metric, details, identity_parts):
        identity = hashlib.sha256(json.dumps([track_id, kind, *identity_parts]).encode()).hexdigest()[:24]
        with self.db:
            self.db.execute("""INSERT INTO research_observations VALUES(?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET metric=excluded.metric,details=excluded.details,
                    status=excluded.status,recorded_at=excluded.recorded_at,event_date=excluded.event_date""",
                (identity, track_id, kind, source, url, event_date, subject, status, metric, utc_now(), json.dumps(details)))
        return {"saved": True, "id": identity}

    def research_record(self, track_id, kind, url, event_date, subject, confirmed=False, position=None):
        from .listening import safe_url, DOMAINS
        self.research_track(track_id)
        if kind not in ("dj_play", "chart_position"):
            raise ValueError("Choose a DJ play or chart position.")
        if type(confirmed) is not bool:
            raise ValueError("Match confirmation must be true or false.")
        if not isinstance(subject, str) or not subject.strip() or len(subject) > 250:
            raise ValueError("Enter the DJ name or exact chart name.")
        try:
            day = date.fromisoformat(event_date)
        except (ValueError, TypeError):
            raise ValueError("Enter an event date as YYYY-MM-DD.") from None
        if day > datetime.now(timezone.utc).date():
            raise ValueError("Record observed events, not future plays or chart positions.")
        if not url:
            raise ValueError("Attach the source page for this observation.")
        safe_url(url)
        parsed = urlsplit(url)
        source = next(value for domain, value in DOMAINS.items()
                      if parsed.hostname == domain or parsed.hostname.endswith('.' + domain))
        if (kind == "dj_play" and source not in {"1001Tracklists", "YouTube", "SoundCloud"}
                or kind == "chart_position" and source != "Beatport"):
            raise ValueError("Use a tracklist/set link for DJ support or a Beatport chart link for chart position.")
        if kind == "chart_position" and (type(position) is not int or not 1 <= position <= 1000):
            raise ValueError("Chart position must be between 1 and 1000.")
        # A timestamp fragment on the same set is not a second play.
        url = urlunsplit(parsed._replace(fragment=""))
        subject = subject.strip()
        identity_parts = [source, url, normalized(subject)]
        if kind == "chart_position":
            identity_parts.append(day.isoformat())
        return self._save_observation(track_id, kind, source, url, day.isoformat(), subject,
                                      "confirmed" if confirmed else "candidate",
                                      position if kind == "chart_position" else None,
                                      {"entered_by": "user"}, identity_parts)

    def research_review(self, observation_id, confirmed):
        if type(confirmed) is not bool:
            raise ValueError("Match confirmation must be true or false.")
        with self.db:
            row = self.db.execute("SELECT kind FROM research_observations WHERE id=?", (observation_id,)).fetchone()
            if not row or row[0] == "soulseek_snapshot":
                raise ValueError("Only a DJ play or chart observation can be confirmed as this version.")
            self.db.execute("UPDATE research_observations SET status=? WHERE id=?",
                            ("confirmed" if confirmed else "candidate", observation_id))
        return {"saved": True}

    def record_soulseek_snapshot(self, track_id, search_id, query, rows, started_at, truncated, duration_seconds):
        """Called only by DesktopService from a completed, bound network search."""
        self.research_track(track_id)
        peers = {r["username"] for r in rows}
        details = {"query": query, "matching_files": len(rows), "distinct_peers": len(peers),
                   "started_at": datetime.fromtimestamp(started_at, timezone.utc).isoformat(timespec="seconds"),
                   "duration_seconds": duration_seconds, "truncated": bool(truncated),
                   "scope": "all retained results; candidate filename matches"}
        return self._save_observation(track_id, "soulseek_snapshot", "Soulseek", "",
                                      datetime.fromtimestamp(started_at, timezone.utc).date().isoformat(),
                                      query, "candidate", len(peers), details, [search_id])

    def research_evidence(self, track_id):
        return [{**dict(row), "details": json.loads(row["details"])} for row in self.db.execute(
            "SELECT * FROM research_observations WHERE track_id=? ORDER BY event_date DESC,recorded_at DESC,id",
            (track_id,))]

    def research_summary(self, track_id):
        evidence = self.research_evidence(track_id)
        plays = [r for r in evidence if r["kind"] == "dj_play" and r["status"] == "confirmed"]
        today = datetime.now(timezone.utc).date()
        recent = [r for r in plays if today - timedelta(days=6) <= date.fromisoformat(r["event_date"]) <= today]
        previous = [r for r in plays if today - timedelta(days=13) <= date.fromisoformat(r["event_date"]) < today - timedelta(days=6)]
        return {"evidence": evidence, "confirmed_djs": len({normalized(r["subject"]) for r in plays}),
                "dj_plays": len(plays), "djs_last_7_days": len({normalized(r["subject"]) for r in recent}),
                "djs_previous_7_days": len({normalized(r["subject"]) for r in previous})}
