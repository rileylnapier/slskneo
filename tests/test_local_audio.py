from pathlib import Path

import pytest

from soulseek_mcp.listening import ListeningLibrary


@pytest.fixture
def library(tmp_path):
    store=ListeningLibrary(tmp_path/'music.sqlite3')
    yield store
    store.close()


def owned(library,tmp_path,title='My song',filename='recording.mp3'):
    identity=library.import_batch([{'artist':'Artist','title':title}], 'Library')['track_ids'][0]
    file=tmp_path/filename
    file.write_bytes(b'local test audio')
    stat=file.stat()
    with library.db:
        library.db.execute('INSERT INTO library_files VALUES(?,?,?,?)',(str(file),identity,stat.st_mtime_ns,stat.st_size))
    return identity,file


def test_playback_uses_opaque_ids_and_does_not_expose_paths_in_inbox(library,tmp_path):
    identity,file=owned(library,tmp_path)
    track=library.inbox()['tracks'][0]
    assert track['owned']
    audio=track['local_audio'][0]
    assert audio['format']=='MP3' and audio['name']=='recording.mp3'
    assert str(tmp_path) not in str(track)
    assert audio['url']==f"taste-audio://library/{identity}/{audio['id']}"
    record=library.local_audio_file(identity,audio['id'])
    assert record['path']==str(file) and record['size']==file.stat().st_size


def test_catalog_import_cannot_create_local_file_access(library):
    identity=library.import_batch([{'artist':'Artist','title':'Track','path':'/private/file.mp3','owned':True}], 'Beatport')['track_ids'][0]
    assert not library.inbox()['tracks'][0]['local_audio']
    with pytest.raises(ValueError):library.local_audio_file(identity,'a'*20)
    with pytest.raises(ValueError):library.local_audio_file('../file','a'*20)


def test_multiple_local_versions_have_separate_handles_and_cues(library,tmp_path):
    identity,_=owned(library,tmp_path)
    owned(library,tmp_path,filename='another.wav')
    other,_=owned(library,tmp_path,title='Other',filename='other.mp3')
    a,b=library.local_audio(identity)
    assert a['id']!=b['id']
    library.cue(identity,a['url'],75,'Local moment')
    assert library.inbox()['tracks'][0]['cues'] or library.inbox()['tracks'][1]['cues']
    with pytest.raises(ValueError):library.cue(other,a['url'],75)
    with pytest.raises(ValueError):library.local_audio_file(other,a['id'])
    library.cue(identity,a['url'],75,remove=True)
    assert not any(t['cues'] for t in library.inbox()['tracks'])


def test_reimported_changed_file_invalidates_old_handle_and_cue_association(library,tmp_path):
    identity,file=owned(library,tmp_path)
    old=library.local_audio(identity)[0]
    library.cue(identity,old['url'],10,'Original recording')
    with library.db:library.db.execute('UPDATE library_files SET size=size+1 WHERE path=?',(str(file),))
    new=library.local_audio(identity)[0]
    assert old['url']!=new['url']
    with pytest.raises(ValueError):library.local_audio_file(identity,old['id'])
    with pytest.raises(ValueError):library.cue(identity,old['url'],20)
    assert all(c['preview_url']!=new['url'] for c in library.inbox()['tracks'][0]['cues'])
