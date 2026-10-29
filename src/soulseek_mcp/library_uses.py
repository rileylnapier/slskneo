"""What each owned recording is for, and a shared work ledger for agents.

Uses are explicit labels (DJ, sample, remix) on library tracks. Agents read the
queue of owned files, claim a named task such as ``stems`` before starting, and
finish it with an output location, so two agents never process the same file.
"""
from pathlib import Path
import re

USES = ("dj", "sample", "remix")
# A claim that has not finished within this window is treated as abandoned.
STALE_CLAIM = "-6 hours"


def clean_uses(uses):
    if not isinstance(uses, list) or any(not isinstance(u, str) or u not in USES for u in uses):
        raise ValueError("Uses must be a list containing only dj, sample, or remix.")
    return sorted(set(uses), key=USES.index)


def clean_task(task):
    if not isinstance(task, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}", task):
        raise ValueError("Task names are short lowercase slugs, for example stems.")
    return task


def clean_agent(agent):
    if not isinstance(agent, str) or not agent.strip() or len(agent) > 100:
        raise ValueError("Identify the agent with a short name.")
    return agent.strip()


class LibraryUsesMixin:
    def init_library_uses(self):
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS track_uses (
                track_id TEXT REFERENCES tracks(id), use TEXT NOT NULL, marked_at TEXT NOT NULL,
                PRIMARY KEY(track_id,use)
            );
            CREATE TABLE IF NOT EXISTS library_tasks (
                track_id TEXT REFERENCES tracks(id), task TEXT NOT NULL, status TEXT NOT NULL,
                agent TEXT NOT NULL, output TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '',
                claimed_at TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(track_id,task)
            );
        """)

    def track_uses(self, track_id):
        return sorted((r[0] for r in self.db.execute("SELECT use FROM track_uses WHERE track_id=?", (track_id,))
                       if r[0] in USES), key=USES.index)

    def track_tasks(self, track_id, outputs=False):
        tasks = {}
        for r in self.db.execute("SELECT * FROM library_tasks WHERE track_id=? ORDER BY task", (track_id,)):
            tasks[r["task"]] = {"status": r["status"], "agent": r["agent"], "note": r["note"],
                                "claimed_at": r["claimed_at"], "updated_at": r["updated_at"],
                                **({"output": r["output"]} if outputs else {})}
        return tasks

    def library_mark(self, track_id, uses):
        uses = clean_uses(uses)
        if not self.db.execute("SELECT 1 FROM tracks WHERE id=?", (track_id,)).fetchone():
            raise ValueError("Track not found.")
        with self.db:
            self.db.execute("DELETE FROM track_uses WHERE track_id=?", (track_id,))
            for use in uses:
                self.db.execute("INSERT INTO track_uses VALUES(?,?,datetime('now'))", (track_id, use))
        return {"track_id": track_id, "uses": uses}

    def library_queue(self, use="", needs_task="", offset=0, limit=50):
        """Owned recordings with real file paths, for local agents only."""
        if use and use not in USES:
            raise ValueError("Filter by dj, sample, or remix.")
        if needs_task:
            clean_task(needs_task)
        if type(offset) is not int or type(limit) is not int or offset < 0 or not 1 <= limit <= 200:
            raise ValueError("Use an offset of at least 0 and a limit from 1 to 200.")
        where, params = ["EXISTS (SELECT 1 FROM library_files f WHERE f.track_id=t.id)"], []
        if use:
            where.append("EXISTS (SELECT 1 FROM track_uses u WHERE u.track_id=t.id AND u.use=?)")
            params.append(use)
        if needs_task:
            # Failed and abandoned work is available again; done and live claims are not.
            where.append(f"""NOT EXISTS (SELECT 1 FROM library_tasks k WHERE k.track_id=t.id AND k.task=?
                             AND (k.status='done' OR (k.status='claimed' AND k.updated_at>datetime('now','{STALE_CLAIM}'))))""")
            params.append(needs_task)
        rows = self.db.execute(f"""SELECT t.* FROM tracks t WHERE {' AND '.join(where)}
                                   ORDER BY t.created_at DESC,t.id LIMIT ? OFFSET ?""",
                               (*params, limit + 1, offset)).fetchall()
        tracks = []
        for t in rows[:limit]:
            files = [{"path": f["path"], "format": Path(f["path"]).suffix[1:].upper(), "size": f["size"],
                      "present": Path(f["path"]).is_file()}
                     for f in self.db.execute("SELECT * FROM library_files WHERE track_id=? ORDER BY path", (t["id"],))]
            tracks.append({"track_id": t["id"], "artist": t["artist"], "title": t["title"], "bpm": t["bpm"],
                           "key": t["musical_key"], "uses": self.track_uses(t["id"]),
                           "tasks": self.track_tasks(t["id"], outputs=True), "files": files})
        return {"tracks": tracks, "next_offset": offset + limit if len(rows) > limit else None}

    def library_task_claim(self, track_id, task, agent):
        task, agent = clean_task(task), clean_agent(agent)
        if not self.db.execute("SELECT 1 FROM library_files WHERE track_id=? LIMIT 1", (track_id,)).fetchone():
            raise ValueError("Only tracks with files in the library can be claimed.")
        with self.db:
            # One statement decides the claim, so concurrent agents cannot both win.
            claimed = self.db.execute(f"""INSERT INTO library_tasks VALUES(?,?,'claimed',?,'','',datetime('now'),datetime('now'))
                ON CONFLICT(track_id,task) DO UPDATE SET status='claimed',agent=excluded.agent,output='',note='',
                    claimed_at=excluded.claimed_at,updated_at=excluded.updated_at
                WHERE library_tasks.status='failed'
                   OR (library_tasks.status='claimed' AND library_tasks.updated_at<=datetime('now','{STALE_CLAIM}'))""",
                (track_id, task, agent)).rowcount == 1
        return {"claimed": claimed, "track_id": track_id, "task": task, **self.track_tasks(track_id, outputs=True)[task]}

    def library_task_finish(self, track_id, task, agent, status, output="", note=""):
        task, agent = clean_task(task), clean_agent(agent)
        if status not in ("done", "failed"):
            raise ValueError("Finish a task as done or failed.")
        if not isinstance(output, str) or len(output) > 4096 or not isinstance(note, str) or len(note) > 1000:
            raise ValueError("Output and note must be short text.")
        with self.db:
            finished = self.db.execute("""UPDATE library_tasks SET status=?,output=?,note=?,updated_at=datetime('now')
                                          WHERE track_id=? AND task=? AND agent=? AND status='claimed'""",
                                       (status, output, note.strip(), track_id, task, agent)).rowcount == 1
        if not finished:
            raise ValueError("This agent does not hold an open claim on that task.")
        return {"track_id": track_id, "task": task, **self.track_tasks(track_id, outputs=True)[task]}

    def import_download(self, found, uses=()):
        """Add one completed Soulseek download to the library with its intended uses."""
        identity = self.import_batch([found["record"]], "Soulseek")["track_ids"][0]
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO library_files VALUES(?,?,?,?)",
                            (found["path"], identity, found["modified_ns"], found["size"]))
            for use in clean_uses(list(uses)):
                self.db.execute("INSERT OR IGNORE INTO track_uses VALUES(?,?,datetime('now'))", (identity, use))
        return identity
