"""Read a bounded catalog batch using an existing Beatport MCP installation.

Executed by that installation's Python. Credentials stay in its token cache.
"""
import asyncio
from datetime import date, timedelta
import json
from pathlib import Path
import sys


def format_tracks(raw):
    tracks = []
    for t in {t["id"]: t for t in raw}.values():
        mix = t.get("mix_name") or ""
        title = t["name"] + (f" ({mix})" if mix else "")
        people = [{"name": a["name"], "role": role,
                   "url": f"https://www.beatport.com/artist/{a.get('slug', 'artist')}/{a['id']}"}
                  for field, role in [("artists", "artist"), ("remixers", "remixer")]
                  for a in t.get(field, [])]
        release = t.get("release") or {}
        tracks.append({"artist": " & ".join(a["name"] for a in t.get("artists", [])),
                       "title": title, "source_id": str(t["id"]),
                       "url": f"https://www.beatport.com/track/{t.get('slug', 'track')}/{t['id']}",
                       "bpm": t.get("bpm"), "key": (t.get("key") or {}).get("name"),
                       "preview_url": t.get("sample_url") or "", "credits": people,
                       "genre": (t.get("genre") or {}).get("name", ""),
                       "label": (release.get("label") or {}).get("name", ""),
                       "label_url": (f"https://www.beatport.com/label/{release['label'].get('slug', 'label')}/{release['label']['id']}"
                                     if (release.get('label') or {}).get('id') else ''),
                       "release_date": t.get("publish_date") or "",
                       "release": release.get("name", ""), "isrc": t.get("isrc") or "",
                       "artwork": (release.get("image") or {}).get("uri", "")})
    return tracks


async def read_watch(client, request):
    kind = request['kind']
    category = 'labels' if kind == 'label' else 'artists'
    singular = 'label' if kind == 'label' else 'artist'
    operation = request['operation']
    if operation == 'watch_search':
        data = await client.get('/catalog/search/', q=request['query'], type=singular, page=1, per_page=10)
        rows = data.get(category, [])
        if isinstance(rows, dict):
            rows = rows.get('results', [])
        return {'profiles': [{'name': r['name'], 'url': f"https://www.beatport.com/{singular}/{r.get('slug', singular)}/{r['id']}"} for r in rows[:10]]}
    identity = int(request['source_id'])
    if operation == 'watch_profile':
        row = await client.get(f'/catalog/{category}/{identity}/')
        if row['id'] != identity:
            raise ValueError('Profile mismatch')
        return {'name': row['name'], 'url': f"https://www.beatport.com/{singular}/{row.get('slug', singular)}/{identity}", 'image': (row.get('image') or {}).get('uri',''), 'bio': row.get('bio') or row.get('description') or ''}
    if kind == 'label':
        data = await client.get('/catalog/tracks/', label_id=identity, page=1, per_page=100, order_by='-publish_date')
    else:
        data = await client.get(f'/catalog/artists/{identity}/tracks/', page=1, per_page=100, order_by='-publish_date')
    raw = data['results']
    # Some catalog entries temporarily omit all credits. They cannot establish
    # identity and remain unseen, so later complete records can be discovered.
    complete = [t for t in raw if t.get('artists') and (kind != 'label' or ((t.get('release') or {}).get('label') or {}).get('id'))]
    skipped = len(raw) - len(complete)
    # The artist endpoint includes both original artist and remixer credits.
    def belongs(t):
        if kind == 'label':
            return ((t.get('release') or {}).get('label') or {}).get('id') == identity
        return any(a['id'] == identity for field in ('artists', 'remixers') for a in t.get(field, []))
    if any(not belongs(t) for t in complete):
        raise ValueError('Catalog filter was not honored')
    cutoff = (date.today() + timedelta(days=366)).isoformat()
    valid = [t for t in complete if (t.get('publish_date') or '9999')[:10] <= cutoff]
    if kind == 'remixer':
        valid = [t for t in valid if any(a['id'] == identity for a in t.get('remixers', []))]
    return {'tracks': format_tracks(valid), 'skipped': skipped, 'limited': bool(data.get('next')) or data.get('count', 0) > len(raw)}


async def read_follows(client):
    profiles = []
    for kind, endpoint in [('artist', 'artists'), ('label', 'labels')]:
        rows = await client.get(f'/my/beatport/{endpoint}/')
        # These endpoints return an unpaginated array, unlike catalog endpoints.
        if not isinstance(rows, list) or len(rows) > 500:
            raise ValueError('Unexpected followed profiles response')
        for row in rows:
            identity = row.get('id')
            name = row.get('name')
            if type(identity) is not int or identity <= 0 or not isinstance(name, str) or not 1 <= len(name.strip()) <= 250:
                raise ValueError('Invalid followed profile')
            profiles.append({'kind': kind, 'name': name.strip(), 'image': (row.get('image') or {}).get('uri',''), 'url': f'https://www.beatport.com/{kind}/{kind}/{identity}'})
    return {'profiles': profiles}


async def main():
    from beatport_mcp.client import BeatportClient
    from beatport_mcp.config import Settings

    token_path = Path.home() / ".beatport-mcp/token.json"
    account = json.loads(token_path.read_text()).get("account", {})
    settings = Settings(_env_file=None, username=account.get("username", ""), password="",
                        client_id=account.get("client_id") or Settings.model_fields["client_id"].default,
                        token_file=token_path, read_only=True, timeout=20)
    request = json.loads(sys.argv[1])
    async with BeatportClient(settings) as client:
        if request.get('operation') == 'follows':
            print(json.dumps(await read_follows(client)))
            return
        if request.get('operation') in {'watch_search', 'watch_profile', 'watch_tracks'}:
            print(json.dumps(await read_watch(client, request)))
            return
        if request.get("operation") == "genres":
            data = await client.get("/catalog/genres/", per_page=100)
            print(json.dumps({"genres": [{"id": r["id"], "name": r["name"]} for r in data["results"]]}))
            return
        if request.get("operation") == "research":
            seed = request["seed"]
            found = await client.get("/catalog/search/", q=f"{seed['artist']} {seed['title']}",
                                     type="tracks", page=1, per_page=3)
            versions = found.get("tracks", found.get("results", []))
            # Catalog search has a different response shape from catalog lists.
            if isinstance(versions, dict):
                versions = versions.get("results", [])
            latest = await client.get("/catalog/tracks/", artist_name=seed["artist"],
                                      order_by="-publish_date", page=1, per_page=8)
            cutoff = (date.today() + timedelta(days=366)).isoformat()
            recent = [t for t in latest["results"] if (t.get("publish_date") or "9999")[:10] <= cutoff]
            print(json.dumps({"versions": format_tracks(versions), "recent": format_tracks(recent)}))
            return
        # An unfiltered catalog includes non-electronic genres and sentinel
        # dates such as 9999-12-31. Sample across electronic genres explicitly.
        genre_ids = [request["genre_id"]] if request.get("genre_id") else [5, 91, 11, 6, 1, 18, 7, 3, 9, 86]
        raw = []
        for genre_id in genre_ids:
            data = await client.get("/catalog/tracks/", genre_id=genre_id,
                                    artist_name=request.get("artist_name") or None,
                                    order_by="-publish_date", page=1, per_page=25 if len(genre_ids) == 1 else 10)
            valid = [t for t in data["results"] if t.get("publish_date", "9999")[:10] <= (date.today() + timedelta(days=366)).isoformat()]
            raw.extend(valid[:25 if len(genre_ids) == 1 else 3])
        tracks = format_tracks(raw)
        print(json.dumps({"tracks": tracks}))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        # Never send raw auth responses, environment values or tokens to the UI.
        print(json.dumps({"error": "Beatport could not be read. Check your Beatport MCP sign-in and try again."}))
        sys.exit(1)
