"""Read metadata from a chosen music folder without modifying or uploading files."""
from __future__ import annotations

import os
from pathlib import Path
import re

from mutagen import File

EXTENSIONS = {".mp3", ".flac", ".wav", ".aif", ".aiff", ".m4a", ".ogg", ".opus"}


def tag(tags, *names):
    for name in names:
        value = tags.get(name)
        if value is not None:
            if hasattr(value, "text"):
                value = value.text
            if isinstance(value, (list, tuple)):
                value = " & ".join(str(v).strip() for v in value if str(v).strip())
            if str(value).strip():
                return str(value).strip()
    return ""


def read_music_file(file):
    """Return one importable record, or None when no artist/title is recoverable."""
    file = Path(file)
    stat = file.stat()
    audio = File(file, easy=True)
    tags = audio.tags if audio is not None and audio.tags else {}
    artist = tag(tags, "artist", "TPE1", "albumartist", "TPE2")
    title = tag(tags, "title", "TIT2")
    method = "tags"
    if not artist or not title:
        parts = re.split(r"\s+[-–—]\s+", file.stem, maxsplit=1)
        if len(parts) == 2 and all(p.strip() for p in parts):
            artist = artist or re.sub(r"^\d{1,3}[. _-]+", "", parts[0]).strip()
            title = title or parts[1].strip()
            method = "filename"
    if not artist or not title:
        return None
    bpm_text = tag(tags, "bpm", "TBPM")
    try:
        bpm = round(float(bpm_text))
        if not 20 <= bpm <= 400:
            bpm = None
    except ValueError:
        bpm = None
    return {"record": {"artist": artist[:500], "title": title[:500],
                       "genre": tag(tags, "genre", "TCON")[:500],
                       "release": tag(tags, "album", "TALB")[:500], "bpm": bpm,
                       "key": tag(tags, "initialkey", "TKEY")[:50],
                       "source_title": f"Local {method}: {file.name}"[:500]},
            "path": str(file), "modified_ns": stat.st_mtime_ns, "size": stat.st_size,
            "method": method}


def read_music_folder(path, limit=5000):
    root = Path(path).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Choose a music folder.")
    records, skipped, unreadable, scanned = [], 0, 0, 0
    truncated = False

    def walk_error(_error):
        nonlocal unreadable
        unreadable += 1

    for directory, folders, filenames in os.walk(root, followlinks=False, onerror=walk_error):
        folders[:] = sorted(f for f in folders if not f.startswith('.'))
        for name in sorted(filenames):
            file = Path(directory) / name
            if file.suffix.lower() not in EXTENSIONS or file.is_symlink():
                continue
            if scanned >= limit:
                truncated = True
                break
            scanned += 1
            try:
                found = read_music_file(file)
                if found is None:
                    skipped += 1
                    continue
                records.append(found)
            except Exception:
                # A malformed file must not prevent importing the rest of a folder.
                # Return counts only; file contents and full paths never reach UI errors.
                unreadable += 1
        if truncated:
            break
    return {"files": records, "scanned": scanned, "skipped": skipped,
            "unreadable": unreadable, "truncated": truncated}
