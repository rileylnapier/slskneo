"""Local discovery from imported track credits. No network or download actions."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import unicodedata
from pathlib import Path
from urllib.parse import quote


def normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def credits(artist: str, title: str) -> list[dict]:
    """Keep ambiguous '&' collaborations intact; never invent profile identities."""
    found = [{"name": name.strip(), "role": "artist"}
             for name in re.split(r"\s+[x×]\s+", artist) if name.strip()]
    for part in re.findall(r"\(([^()]*)\)", title):
        match = re.fullmatch(
            r"(.+?)\s+(?:(?:\d{4}|VIP)\s+)*(Remix|Edit|Flip|Bootleg|Rework|EDAT)",
            part, re.IGNORECASE,
        )
        if not match:
            continue
        name, kind = match.groups()
        if normalized(name) in {"original", "extended", "radio", "club", "vip"}:
            continue
        role = "remixer" if kind.casefold() == "remix" else "editor"
        found.extend({"name": n.strip(), "role": role}
                     for n in re.split(r"\s+[x×]\s+", name) if n.strip())
    return list({(normalized(c["name"]), c["role"]): c for c in found}.values())


class DiscoveryStore:
    def __init__(self, path: str | Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS tracks (
                id TEXT PRIMARY KEY, artist TEXT NOT NULL, title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'new', bpm INTEGER, musical_key TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS credits (
                track_id TEXT REFERENCES tracks(id), person_key TEXT, name TEXT,
                role TEXT, PRIMARY KEY(track_id, person_key, role)
            );
            CREATE TABLE IF NOT EXISTS sources (
                track_id TEXT REFERENCES tracks(id), source TEXT, url TEXT,
                first_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(track_id, source, url)
            );
            CREATE TABLE IF NOT EXISTS follows (
                person_key TEXT PRIMARY KEY, name TEXT NOT NULL
            );
        """)

    def close(self):
        self.db.close()

    def import_tracks(self, records: list[dict], source: str, url: str = "") -> dict:
        if not isinstance(records, list) or not source.strip():
            raise ValueError("Supply a JSON array of tracks and a source name.")
        prepared = []
        for row in records:
            if not isinstance(row, dict):
                raise ValueError("Each track must be a JSON object.")
            artist, title = row.get("artist"), row.get("title")
            if not isinstance(artist, str) or not isinstance(title, str) or not artist.strip() or not title.strip():
                raise ValueError("Every track needs a non-empty artist and title.")
            artist, title = artist.strip(), title.strip()
            status = row.get("status", "new")
            if not isinstance(status, str) or status not in {"new", "queued", "keep", "pass"}:
                raise ValueError("Status must be new, queued, keep, or pass.")
            bpm = row.get("bpm")
            if bpm is not None and (type(bpm) is not int or not 20 <= bpm <= 400):
                raise ValueError("BPM must be an integer from 20 to 400.")
            key = row.get("key")
            if key is not None and not isinstance(key, str):
                raise ValueError("Key must be text.")
            identity = hashlib.sha256(json.dumps([normalized(artist), normalized(title)]).encode()).hexdigest()[:20]
            prepared.append((identity, artist, title, status, bpm, key))
        added, new_sources, ids = 0, 0, []
        with self.db:
            for identity, artist, title, status, bpm, key in prepared:
                result = self.db.execute(
                    "INSERT OR IGNORE INTO tracks(id,artist,title,status,bpm,musical_key) VALUES(?,?,?,?,?,?)",
                    (identity, artist, title, status, bpm, key),
                )
                added += result.rowcount
                self.db.execute(
                    "UPDATE tracks SET bpm=COALESCE(?,bpm),musical_key=COALESCE(?,musical_key) WHERE id=?",
                    (bpm, key, identity),
                )
                for person in credits(artist, title):
                    self.db.execute("INSERT OR IGNORE INTO credits VALUES(?,?,?,?)",
                                    (identity, normalized(person["name"]), person["name"], person["role"]))
                new_sources += self.db.execute(
                    "INSERT OR IGNORE INTO sources(track_id,source,url) VALUES(?,?,?)",
                    (identity, source.strip(), url),
                ).rowcount
                self.db.execute("UPDATE sources SET last_seen=CURRENT_TIMESTAMP WHERE track_id=? AND source=? AND url=?",
                                (identity, source.strip(), url))
                ids.append(identity)
        return {"received": len(records), "added": added, "new_source_links": new_sources, "track_ids": ids}

    def feedback(self, identity: str, status: str):
        if status not in {"new", "queued", "keep", "pass"}:
            raise ValueError("Status must be new, queued, keep, or pass.")
        with self.db:
            if not self.db.execute("UPDATE tracks SET status=? WHERE id=?", (status, identity)).rowcount:
                raise ValueError("Unknown track id.")

    def follow(self, name: str, enabled: bool = True):
        key = normalized(name)
        person = self.db.execute("SELECT name FROM credits WHERE person_key=? LIMIT 1", (key,)).fetchone()
        if not person:
            raise ValueError("Choose a credit name from the people report.")
        with self.db:
            if enabled:
                self.db.execute("INSERT OR REPLACE INTO follows VALUES(?,?)", (key, person["name"]))
            else:
                self.db.execute("DELETE FROM follows WHERE person_key=?", (key,))

    def people(self) -> list[dict]:
        result = []
        for row in self.db.execute("""
            SELECT c.person_key, MIN(c.name) AS name,
                COUNT(DISTINCT c.track_id) AS tracks,
                COUNT(DISTINCT CASE WHEN t.status='keep' THEN t.id END) AS kept,
                COUNT(DISTINCT CASE WHEN t.status='queued' THEN t.id END) AS queued,
                COUNT(DISTINCT CASE WHEN t.status='pass' THEN t.id END) AS passed,
                GROUP_CONCAT(DISTINCT c.role) AS roles,
                EXISTS(SELECT 1 FROM follows f WHERE f.person_key=c.person_key) AS followed
            FROM credits c JOIN tracks t ON t.id=c.track_id GROUP BY c.person_key
        """):
            person = dict(row)
            person["roles"] = person["roles"].split(",")
            person["followed"] = bool(person["followed"])
            person["identity_verified"] = False
            person["review_note"] = "Credit inferred from title; verify profile identity."
            if " & " in person["name"]:
                person["review_note"] = "May be a group or collaboration; kept intact for review."
            person["search_url"] = "https://soundcloud.com/search/people?q=" + quote(person["name"])
            person["evidence"] = [dict(x) for x in self.db.execute("""
                SELECT DISTINCT t.id,t.artist,t.title,t.status FROM tracks t
                JOIN credits c ON c.track_id=t.id WHERE c.person_key=? ORDER BY t.title
            """, (person["person_key"],))]
            # Queue selections are weaker signals than an explicit Keep.
            person["score"] = 4 * person["kept"] + 2 * person["queued"] - 3 * person["passed"]
            result.append(person)
        return sorted(result, key=lambda p: (-p["score"], -("editor" in p["roles"] or "remixer" in p["roles"]),
                                             -p["tracks"], p["person_key"]))

    def recommendations(self) -> list[dict]:
        people = {p["person_key"]: p for p in self.people()}
        results = []
        for row in self.db.execute("SELECT * FROM tracks WHERE status='new'"):
            track = dict(row)
            reasons, score = [], 0
            scored_people = set()
            for c in self.db.execute("SELECT * FROM credits WHERE track_id=?", (track["id"],)):
                if c["person_key"] in scored_people:
                    continue
                scored_people.add(c["person_key"])
                p = people[c["person_key"]]
                if p["followed"]:
                    reasons.append(f"You follow {p['name']} ({c['role']} credit).")
                    score += 10
                elif p["score"] > 0:
                    reasons.append(f"{p['name']} also appears on {p['kept']} kept and {p['queued']} queued track(s).")
                    score += p["score"]
            if not reasons:
                continue
            track["score"], track["reasons"] = score, reasons
            track["sources"] = [dict(s) for s in self.db.execute(
                "SELECT source,url,first_seen,last_seen FROM sources WHERE track_id=?", (track["id"],))]
            results.append(track)
        return sorted(results, key=lambda t: (-t["score"], t["title"]))

    def report(self) -> dict:
        return {"track_count": self.db.execute("SELECT COUNT(*) FROM tracks").fetchone()[0],
                "people": self.people(), "recommendations": self.recommendations(),
                "scope": "Imported metadata only. Follows are local interests, not social-platform follows. "
                         "Credit identities and profile search results require review. No scheduled collection or downloads."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("state/discovery.sqlite3"))
    sub = parser.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import")
    imp.add_argument("file", type=Path)
    imp.add_argument("--source", required=True)
    imp.add_argument("--url", default="")
    sub.add_parser("report")
    follow = sub.add_parser("follow")
    follow.add_argument("name")
    follow.add_argument("--remove", action="store_true")
    feedback = sub.add_parser("feedback")
    feedback.add_argument("track_id")
    feedback.add_argument("status", choices=["new", "queued", "keep", "pass"])
    args = parser.parse_args()
    store = DiscoveryStore(args.db)
    try:
        if args.command == "import":
            result = store.import_tracks(json.loads(args.file.read_text()), args.source, args.url)
        elif args.command == "follow":
            store.follow(args.name, not args.remove)
            result = {"name": args.name, "followed_locally": not args.remove}
        elif args.command == "feedback":
            store.feedback(args.track_id, args.status)
            result = {"id": args.track_id, "status": args.status}
        else:
            result = store.report()
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Discovery: {exc}\n")
    finally:
        store.close()


if __name__ == "__main__":
    main()
