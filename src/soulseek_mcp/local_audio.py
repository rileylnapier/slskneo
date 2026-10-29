"""Opaque playback handles for files explicitly imported into the library."""
import hashlib
import json
from pathlib import Path
import re

from .library_seed import EXTENSIONS


def file_identity(row):
    return hashlib.sha256(json.dumps([row['path'], row['modified_ns'], row['size']]).encode()).hexdigest()[:20]


class LocalAudioMixin:
    def local_audio(self, track_id):
        files = []
        for row in self.db.execute('SELECT * FROM library_files WHERE track_id=? ORDER BY path', (track_id,)):
            file = Path(row['path'])
            if file.suffix.lower() not in EXTENSIONS or not file.is_absolute():
                continue
            identity = file_identity(row)
            files.append({'id': identity, 'url': f'taste-audio://library/{track_id}/{identity}',
                          'name': file.name, 'format': file.suffix[1:].upper()})
        return files

    def local_audio_file(self, track_id, file_id):
        # Only the main process calls this method. Renderer requests contain IDs,
        # never filesystem paths; source imports cannot manufacture library_files.
        if any(not isinstance(v, str) or not re.fullmatch(r'[0-9a-f]{20}', v) for v in (track_id, file_id)):
            raise ValueError('Invalid library audio handle.')
        for row in self.db.execute('SELECT * FROM library_files WHERE track_id=?', (track_id,)):
            file = Path(row['path'])
            if file_identity(row) == file_id and file.is_absolute() and file.suffix.lower() in EXTENSIONS:
                return {'path': row['path'], 'modified_ns': str(row['modified_ns']), 'size': row['size']}
        raise ValueError('This recording is no longer in the imported library. Re-import its folder.')
