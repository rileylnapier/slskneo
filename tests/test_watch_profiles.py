import pytest
from soulseek_mcp.listening import ListeningLibrary
from soulseek_mcp.watch_profiles import clean_profile

def test_profile_text_is_plain_and_images_are_restricted():
    assert clean_profile({'bio':'<p>A &amp; B</p><script>bad</script>\nMusic.'})['bio']=='A & B\nMusic.'
    with pytest.raises(ValueError):clean_profile({'image':'https://other.test/image'})
    with pytest.raises(ValueError):clean_profile({'image':'https://user:pass@geo-media.beatport.com/image'})

async def test_profile_fetch_preserves_previous_bio_on_failure_and_survives_restart(tmp_path,monkeypatch):
    s=ListeningLibrary(tmp_path/'music.sqlite3')
    s.db.execute("INSERT INTO watches(id,kind,source_id,name,url) VALUES('artist:42','artist','42','Artist','https://www.beatport.com/artist/test/42')")
    s.db.commit()
    async def read(_):return {'url':'https://www.beatport.com/artist/test/42','bio':'Real source bio','image':'https://geo-media.beatport.com/image.jpg'}
    monkeypatch.setattr(s,'beatport_read',read)
    await s.watch_profiles_refresh();await s._profile_task
    assert s.watch_state()['watches'][0]['profile']['bio']=='Real source bio'
    async def bad(_):raise ValueError('upstream failed')
    monkeypatch.setattr(s,'beatport_read',bad)
    await s.watch_profiles_refresh();await s._profile_task
    profile=s.watch_state()['watches'][0]['profile']
    assert profile['bio']=='Real source bio' and profile['error']
    s.close()
    r=ListeningLibrary(tmp_path/'music.sqlite3');assert r.watch_state()['watches'][0]['profile']['bio']=='Real source bio';r.close()
