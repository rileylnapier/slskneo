"""Official SoundCloud public API client and conservative upload metadata."""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import time
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urljoin, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

KINDS = {'unclassified', 'original', 'remix', 'edit', 'bootleg', 'dj_set'}


def soundcloud_url(value, profile=False):
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError('Use a public SoundCloud profile or track URL.')
    parsed = urlsplit(value)
    pattern = r'/[A-Za-z0-9_-]+/?' if profile else r'/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+/?'
    if (parsed.scheme != 'https' or parsed.netloc not in {'soundcloud.com', 'www.soundcloud.com'}
            or parsed.query or parsed.fragment or not re.fullmatch(pattern, parsed.path)
            or parsed.path.strip('/').split('/')[0] in {'discover', 'search', 'you', 'stream', 'charts'}
            or (not profile and parsed.path.rstrip('/').split('/')[-1] in {'tracks', 'sets', 'albums', 'likes', 'reposts'})):
        raise ValueError('Use a public SoundCloud profile or single-track URL without tracking parameters.')
    return 'https://soundcloud.com' + parsed.path.rstrip('/')


def resource_id(row, resource):
    value = str(row.get('urn') or row.get('id') or '')
    match = re.fullmatch(rf'(?:soundcloud:{resource}:)?([1-9][0-9]*)', value)
    if not match:
        raise ValueError('SoundCloud returned an invalid identity.')
    return match[1]


def upload_kind(title, duration_ms=0):
    rules = [('dj_set', r'\b(dj set|live set|dj mix|guest mix|mixtape|podcast)\b'),
             ('bootleg', r'\bbootleg\b'), ('remix', r'\bremix\b'), ('edit', r'\b(edit|vip|flip|rework|mashup)\b'),
             ('original', r'\boriginal mix\b')]
    for kind, pattern in rules:
        if re.search(pattern, title, re.I):
            return kind, 'Title hint; confirm before keeping.'
    if duration_ms >= 20 * 60 * 1000:
        return 'dj_set', 'Long upload; could be a set. Confirm before keeping.'
    return 'unclassified', 'The title does not establish the version or artist credits.'


def source_links(text, purchase_url=''):
    """Keep supported creator-provided destinations, never follow or unlock them."""
    from .listening import safe_url, DOMAINS
    links = []
    for url in [purchase_url] + re.findall(r'https://[^\s<>"\']+', text[:20000]):
        if not url:
            continue
        url = url.rstrip('.,);]')
        try:
            safe_url(url)
        except (ValueError, TypeError):
            continue
        host = urlsplit(url).hostname
        source = next((name for domain, name in DOMAINS.items() if host == domain or host.endswith('.' + domain)), None)
        if source and source != 'SoundCloud' and not any(x['url'] == url for x in links):
            links.append({'source': source, 'url': url, 'note': 'Uploader-provided link; verify the version at the destination.'})
    return links[:10]


def format_upload(row, watch):
    if resource_id(row.get('user') or {}, 'users') != watch['source_id']:
        raise ValueError('SoundCloud returned another uploader’s track.')
    if row.get('sharing', 'public') != 'public':
        raise ValueError('Only public uploads can be watched.')
    identity = resource_id(row, 'tracks')
    title = str(row.get('title') or '').strip()[:500]
    if not title:
        raise ValueError('Upload title is missing.')
    url = soundcloud_url(row.get('permalink_url'))
    duration = row.get('duration') if type(row.get('duration')) is int else 0
    kind, note = upload_kind(title, duration)
    # Artist is a user-confirmed profile association, not an inferred recording credit.
    return {'source': 'SoundCloud', 'source_id': identity, 'artist': watch['artist_name'], 'title': title,
            'url': url, 'soundcloud_url': url if row.get('embeddable_by', 'all') != 'none' and row.get('access') != 'blocked' else '',
            'preview_url': '', 'artwork': '', 'credits': [], 'label': '', 'genre': str(row.get('genre') or '')[:500],
            'release': '', 'release_date': '', 'uploaded_at': str(row.get('created_at') or '')[:80],
            'uploader': str((row.get('user') or {}).get('username') or watch['name'])[:250],
            'uploader_id': watch['source_id'], 'content_kind': kind, 'classification_note': note,
            'identity_note': 'Linked artist profile. Confirm the recording artist and exact version before keeping.',
            'identity_confirmed': False, 'duration_ms': duration,
            'source_links': source_links(str(row.get('description') or ''), str(row.get('purchase_url') or '')),
            'download_available': bool(row.get('downloadable'))}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http_json(url, headers=None, data=None):
    """Fixed API destinations, bounded reads, and no cross-origin credential redirects."""
    for _ in range(4):
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.netloc not in {'api.soundcloud.com', 'secure.soundcloud.com'}:
            raise ValueError('Unexpected SoundCloud API destination.')
        try:
            request = Request(url, data=data, headers={'Accept': 'application/json', **(headers or {})})
            with build_opener(NoRedirect).open(request, timeout=20) as response:
                raw = response.read(4_000_001)
            if len(raw) > 4_000_000:
                raise ValueError('SoundCloud response was too large.')
            return json.loads(raw)
        except HTTPError as error:
            if data is None and error.code in {301, 302, 303, 307, 308}:
                target = urljoin(url, error.headers.get('Location', ''))
                if urlsplit(target).netloc == 'api.soundcloud.com' and target != url:
                    url = target
                    continue
            # Do not expose raw responses, URLs, or credentials.
            raise ValueError({401: 'SoundCloud rejected the app credentials. Reconnect in Watches.',
                              403: 'SoundCloud does not allow access to this resource.',
                              404: 'This SoundCloud profile or upload is unavailable.',
                              429: 'SoundCloud rate limit reached. The watch will retry later.'}.get(error.code, 'SoundCloud is temporarily unavailable.')) from None
    raise ValueError('SoundCloud returned too many redirects.')


class SoundCloudClient:
    def __init__(self):
        self.client_id = os.environ.get('SLSK_SOUNDCLOUD_CLIENT_ID', '')
        self.client_secret = os.environ.get('SLSK_SOUNDCLOUD_CLIENT_SECRET', '')
        self.access_token = self.refresh_token = ''
        self.expires = 0
        self.lock = asyncio.Lock()

    @property
    def configured(self):
        return bool(self.client_id and self.client_secret)

    async def configure(self, client_id, client_secret):
        if not all(isinstance(v, str) and 1 <= len(v.strip()) <= 512 for v in (client_id, client_secret)):
            raise ValueError('Enter both SoundCloud app credentials.')
        async with self.lock:
            self.client_id, self.client_secret = client_id.strip(), client_secret.strip()
            self.access_token = self.refresh_token = ''
            self.expires = 0
        return {'configured': True}

    async def _token(self):
        if not self.configured:
            raise ValueError('Connect a registered SoundCloud app in Watches to monitor public uploads.')
        if self.access_token and self.expires > time.monotonic() + 60:
            return self.access_token
        if self.refresh_token:
            fields = {'grant_type': 'refresh_token', 'client_id': self.client_id,
                      'client_secret': self.client_secret, 'refresh_token': self.refresh_token}
            headers = {}
        else:
            fields = {'grant_type': 'client_credentials'}
            basic = base64.b64encode(f'{self.client_id}:{self.client_secret}'.encode()).decode()
            headers = {'Authorization': f'Basic {basic}'}
        response = await asyncio.to_thread(http_json, 'https://secure.soundcloud.com/oauth/token',
                                          {**headers, 'Content-Type': 'application/x-www-form-urlencoded'}, urlencode(fields).encode())
        token = response.get('access_token')
        if not isinstance(token, str) or not token:
            raise ValueError('SoundCloud did not return an access token.')
        self.access_token, self.refresh_token = token, response.get('refresh_token', '')
        self.expires = time.monotonic() + min(float(response.get('expires_in', 3600)), 86400)
        return token

    async def check(self):
        async with self.lock:
            await self._token()
        return {'connected': True}

    async def get(self, path, **params):
        async with self.lock:
            token = await self._token()
            try:
                return await asyncio.to_thread(http_json, 'https://api.soundcloud.com' + path + ('?' + urlencode(params) if params else ''), {'Authorization': f'OAuth {token}'})
            except ValueError as error:
                if 'rejected' in str(error):
                    self.expires = 0
                raise
            except Exception:
                raise ValueError('SoundCloud could not be read. Check the connection and retry.') from None

    async def resolve_profile(self, url):
        value = soundcloud_url(url, profile=True)
        row = await self.get('/resolve', url=value)
        if row.get('kind') != 'user':
            raise ValueError('Choose an artist’s SoundCloud profile, not a track or playlist.')
        return {'source_id': resource_id(row, 'users'), 'name': str(row.get('username') or '')[:250],
                'url': soundcloud_url(row.get('permalink_url'), profile=True)}

    async def uploads(self, watch):
        urn = quote('soundcloud:users:' + watch['source_id'], safe='')
        data = await self.get(f'/users/{urn}/tracks', limit=100, linked_partitioning='true', sort='desc')
        rows = data if isinstance(data, list) else data.get('collection')
        if not isinstance(rows, list) or len(rows) > 100:
            raise ValueError('SoundCloud returned an invalid upload list.')
        return {'tracks': [format_upload(row, watch) for row in rows],
                'limited': len(rows) == 100 or bool(isinstance(data, dict) and data.get('next_href'))}


def clean_upload_record(row):
    from .listening import safe_url
    result = {'source': 'SoundCloud', 'preview_url': '', 'artwork': '', 'credits': [], 'identity_confirmed': False}
    for key in ('artist', 'title', 'source_id', 'uploader', 'uploader_id', 'content_kind', 'classification_note', 'identity_note', 'uploaded_at', 'genre', 'label', 'release', 'release_date'):
        value = row.get(key, '')
        if not isinstance(value, str) or len(value) > 500:
            raise ValueError('Invalid SoundCloud metadata.')
        result[key] = value.strip()
    if not result['artist'] or not result['title'] or not result['source_id'].isdigit() or not result['uploader_id'].isdigit() or result['content_kind'] not in KINDS:
        raise ValueError('Incomplete SoundCloud upload metadata.')
    result['url'] = soundcloud_url(row.get('url'))
    result['soundcloud_url'] = soundcloud_url(row['soundcloud_url']) if row.get('soundcloud_url') else ''
    if result['soundcloud_url'] and result['soundcloud_url'] != result['url']:
        raise ValueError('SoundCloud playback must refer to this upload.')
    result['source_links'] = []
    for link in row.get('source_links', [])[:10]:
        result['source_links'].append({'source': str(link.get('source', 'Source'))[:50], 'url': safe_url(link['url']),
                                       'note': 'Uploader-provided link; verify the version at the destination.'})
    result['download_available'] = bool(row.get('download_available'))
    result['duration_ms'] = row.get('duration_ms', 0) if type(row.get('duration_ms', 0)) is int else 0
    return result
