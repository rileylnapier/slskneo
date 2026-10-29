# Taste

**Taste** is a personal music discovery app for following artists, finding tracks, and digging through collections. It brings a listening inbox and your existing library together with Soulseek search and downloads. The desktop app and its MCP tools share one backend, connection, search collection, and transfer queue. Its Soulseek client is built on aioslsk, not recompiled SoulseekQt source.

## Open the app

Run `npm run package` to build the Apple Silicon desktop bundle:

`release/Taste-darwin-arm64/Taste.app`

Open it, enter a new or existing Soulseek username and password in **Settings**, then click **Save and connect**. An unused username is registered by Soulseek when you connect. Startup never logs in automatically. Passwords are encrypted through macOS-backed Electron safeStorage; they are not exposed to MCP or written into the backend settings file.

## Included features

- **Search:** global searches, paged results, filename/format/bitrate filters, sorting, selected-file and whole-folder downloads, and browsing a user's shared files.
- **Downloads:** progress, pause/resume/retry/remove controls, completed history, and reveal in Finder. Saved unfinished transfers require an explicit resume after restarting.
- **Shared Files:** choose folders, scan/rescan real files, remove shares, and view uploads. No folders are shared until selected.
- **Wishlist:** persistent saved searches, enable/pause/remove, manual search and server-scheduled searches. Matches never download automatically.
- **Settings:** account, download folder, listening ports, slots, bandwidth limits, and completion/match notifications.

Chat rooms, private messages, buddies, user profiles and original-client theme compatibility are outside this first build.

## MCP

The packaged backend supports `--mcp` and exposes 28 tools. It connects to the running desktop app rather than starting a second Soulseek session. Open the app before calling tools.

```toml
[mcp_servers.soulseek]
command = "/absolute/path/to/slskneo/release/Taste-darwin-arm64/Taste.app/Contents/Resources/backend/soulseek-backend"
args = ["--mcp"]
startup_timeout_sec = 30
tool_timeout_sec = 150
```

Tools cover status/snapshot, connect/disconnect, search/results/stop, downloads/folders, transfer controls, user browsing, shares/rescan, wishlist management, and library uses/tasks. Credentials are entered in the app only.

### Library uses and agent tasks

Every library track can be marked **DJ**, **Sample**, **Remix**, or any combination. Mark a
track under **Discover → Library → What it's for**, or pick **For: DJ / Sample / Remix** in
Search before downloading; MCP's `soulseek_download` and `soulseek_download_folder` accept the
same `uses` list. Completed audio downloads join the library automatically (source **Soulseek**)
with the uses chosen when they were queued. Non-audio files stay in Downloads. Purchased files
enter the library through **Import music folder**; mark them there.

Agents use four local tools to pick up work without duplicating it:

- `library_queue(use, needs_task)` lists owned tracks with real file paths, uses, and task
  history. `needs_task="stems"` hides tracks whose stems are done or being worked on.
- `library_task_claim(track_id, task, agent)` claims a task slug such as `stems`. Only one
  agent can win; check `claimed` before starting.
- `library_task_finish(..., status, output, note)` records `done` or `failed` and where the
  results were written. Failed claims, and claims left open for six hours, become available again.
- `library_mark(track_id, uses)` replaces a track's uses.

The library view shows each track's task status. File paths and task outputs stay out of the
renderer. Taste stores tags and the work ledger only; it doesn't run stem separation itself.

Taste retains the legacy state directory `~/Library/Application Support/Soulseek Studio/`, runtime identity, and bundle ID so existing state and credential access remain compatible. Internal `soulseek` module, socket, and MCP tool names remain stable. The backend uses a private Unix socket and owner-only state files. `SLSK_STATE_DIR` and `SLSK_SOCKET` support isolated development/test profiles.

An isolated profile has its own saved login by default. To explicitly reuse the
normal profile's encrypted login while keeping development discovery data separate,
launch with `SLSK_CREDENTIALS_DIR="$HOME/Library/Application Support/Soulseek Studio"`.
This reads and saves `credentials.enc` in that directory; it does not copy or expose
the password, and restoring a saved login does not automatically connect a second
Soulseek session. Leave this override unset for isolated tests.

## Discover music

The **Discover** tab brings source metadata into **Fresh picks**, a local listening inbox.
Taste uses a cream, cherry, butter-yellow, and pistachio theme with record-sleeve
cards and a vinyl character that turns during preview playback. Reduced-motion
preferences disable the animation. The theme is in `renderer/src/taste.css`;
internal storage and connection identifiers remain stable.
**Manage sources → Pull new tracks** reads Beatport on demand using the existing
Beatport MCP installation and sign-in at `~/.beatport-mcp/token.json`. Its Python
defaults to `~/.local/share/mcp-servers/beatport/.venv/bin/python`; override with
`SLSK_BEATPORT_PYTHON`. This installation is separate from the desktop bundle.
No credentials are sent to the renderer.

The default **Broad electronic** batch samples up to three tracks each from ten
genres (house, bass house, tech house, techno, drum & bass, dubstep, trance,
electronica, breaks, and UK garage). A selected genre returns up to 25 entries.
Catalog ordering includes upcoming releases; those are labeled. Sentinel dates
and dates more than one year ahead are excluded. This is a bounded catalog
sample, not an exhaustive sync or a popularity chart.

**Research my library** starts a separate, bounded Beatport job from 1–30 owned
tracks. The suggested selection takes up to 20 distinct artist names from your
locally ranked library, with favorites and positive ratings first. Each seed
makes two catalog reads: up to three relevance-search results and eight recent
artist-filtered releases. Structured credit names must overlap the seed's names;
this is a name-based lead, not verified artist identity or audio matching.

Progress and seed-level errors appear while the job runs. Stop cancels the active
request and retains completed findings. Results and review decisions persist in
SQLite; reopening after an unexpected shutdown marks the job interrupted rather
than restarting network work. Select unfinished seeds to retry. Repeated catalog
IDs are deduplicated, and already-collected entries are suppressed.

The **Research** inbox keeps candidates separate from Fresh picks. Filter by
track, seed artist, or label; preview a catalog version; inspect dated seed/source
evidence, people, and release details; then **Keep**, **Dismiss**, or restore a
dismissed finding. Keep imports the catalog entry and its provenance without
favoriting it or claiming it matches a local file. Search-result versions remain
explicitly uncertain. Beatport source links identify the catalog version; Soulseek
handoff remains a filename search. The UI shows the 500 most recently seen findings.
Library-seed research uses Beatport. Scheduled Beatport and SoundCloud watch
findings share this inbox while the app is open. LLM analysis and automatic
downloads are not implemented.

- Favorite tracks independently of thumbs up/down; follow artist/remixer credits.
- **Artists** opens a local profile from exact collected credits, including owned
  music, favorites, source profiles, and people credited on the same tracks.
  These are collected credits, not a verified complete discography or biography.
- **Track research** keeps dated observations for each exact version. Record a DJ
  play with its set/tracklist URL and performance date, or a Beatport chart position
  with its named chart and date. These are manual entries, not automatic scraping.
  Matches start as candidates unless explicitly confirmed. Confirmed DJ names are
  counted distinctly, including separate last-seven-day and previous-seven-day
  windows. These counts describe recorded evidence, not total global support;
  aliases and alternate links to the same set still need identity resolution.
- **Sample Soulseek availability** starts a search bound to the selected track.
  Once it ends (or you stop it), **Record availability sample** saves distinct peer
  and file counts from all retained results, regardless of table filters or page.
  It records query, search duration when known, and truncation. Re-saving the same
  search updates one observation. Peer names are not saved in research history.
  Filename matches remain candidates: this is observed availability, not listening,
  download, or DJ popularity, and different scans aren't a representative census.
  Research never downloads files, follows artists, or changes taste feedback.
- **Dig** starts a free-form Soulseek search from an artist, year, label, or phrase,
  or suggests a random artist from your library. Searches do not affect taste.
  **Search → Folders** groups the current results page by peer and full folder path
  for album exploration. Expand to inspect files or browse the peer's collection.
  Counts are matching files on that page, not complete album track counts; a year
  query matches shared paths rather than verified release metadata.
- Ranking uses local artist and genre weights, with an explanation on each track.
  Downloads are weak seeds, while explicit ratings and favorites carry more weight.
- Play imported recordings directly from your library, with online previews as a
  separate selectable source. The shared bottom player keeps playing while you
  browse Discover, artists, research, or other tabs; it provides seeking, volume,
  15-second jumps, and system media-key controls. Playback starts only when chosen.
- Start a listening queue from filtered Fresh picks, library tracks, or research
  findings. Add individual recordings, remove queued items, clear upcoming tracks,
  and use previous/next controls. Playback advances at the end of a recording; an
  unavailable source stops for review. Queues last for the current app session.
- The queue panel shows why each find is here and lets you favorite, rate, or follow
  its credited artists without leaving playback. Reacting to an uncollected research
  finding first saves its catalog entry. Explicit feedback updates discovery ranking;
  playing, skipping, and removing queue items never change taste preferences.
- Save named moments against the selected recording or preview. Local file handles
  include the imported file's size and modification time, so replacing a recording
  does not silently reuse its cues. Re-import a folder after moving/changing files.
- Local audio is streamed through a private, range-aware protocol using opaque
  library IDs. Filesystem paths never become renderer-controlled playback URLs.
  No audio is uploaded. Dropbox files must be available locally; codec support is
  provided by Electron. Open an unsupported file (for example AIFF) in your music
  app using the local-file action. Waveform rendering is future work.
  Cue times belong to that preview URL, not the full track. Automatic drop detection
  and LDS/1001Tracklists inline playback are not implemented.
- **Add a link** reads YouTube/SoundCloud oEmbed titles and uploader context.
  Confirm the music artist and exact version before saving. Other supported source
  links can be entered with metadata manually. Provider HTML is never executed.
- Attach another source to a track, import JSON lists from Hypeddit/LDS/1001Tracklists
  and other sources, or open exact source pages and separate search links.
  Matching uses normalized artist plus full version title, not audio fingerprints:
  aliases can remain duplicates, and identical metadata can still collide.
- **Import music folder** reads MP3, FLAC, WAV, AIFF, M4A, Ogg and Opus tags locally.
  Missing tags fall back to an `Artist - Title` filename when possible, marked as
  inferred. Each scan is limited to 5,000 audio files and skips symlinked files.
  It does not change, upload, play, or automatically favorite/follow the files.
  Owned tracks appear in **Your library** and are hidden from the listening inbox.
  Ownership is based on the last import; removed files are not reconciled yet.

State is saved in `discovery.sqlite3` alongside desktop settings. Broad feed refresh
and library research remain manual. **Watches** checks confirmed Beatport artists,
remix credits, and labels daily, every three days, or weekly while Taste is running;
due checks catch up on reopening. The first successful check establishes a baseline.
Later unseen catalog IDs enter the shared research review inbox with dated watch
provenance, previews, Keep/Dismiss, and listening queue controls. Previously collected,
kept, or dismissed versions are not reintroduced as new suggestions. New to a watch
does not necessarily mean newly released.

Following an artist with one unambiguous structured Beatport profile starts a daily
artist-and-remix watch. Unfollowing pauses watches created by that follow; manually
added watches are independent. Other follows continue to guide ranking. Search in
Watches or use an artist's **Watch new releases** / track's **Watch label** action to
choose a source profile explicitly. Watches can be paused/resumed or checked manually.
Checks cover the latest 100 source artist/label tracks (remix-only watches filter
that window), with visible limited-coverage status. Up to 500 watches are supported.
**Import Beatport follows** reads your account's followed artists and labels, adds
daily watches, and gives matching Beatport catalog entries a visible ranking boost.
Identity uses source profile IDs, including label IDs, rather than matching names.
Imports are additive: repeats preserve pauses, cadence, and review decisions; missing
follows are not deleted, and Taste does not change your Beatport account. Local
favorites, ratings, and artist follows remain independent. The first catalog check
establishes a baseline; existing releases are not flooded into the review inbox.
Entries lacking required credits are skipped and counted, without marking them seen.

**Refresh images & bios** loads Beatport artist photos, label artwork, and source
biographies into watch cards. Source and retrieval time are visible; missing bios
remain empty. Bio text is rendered as plain text, image hosts are restricted, and a
failed refresh keeps the previous successful profile. Large watch lists have a
name/source filter and show twenty cards at a time. Expand a card's check details
for timing, coverage, and errors.

Failures retain the previous successful baseline and retry after an hour. Watches
never download, purchase, or favorite music automatically.

**Watches → SoundCloud** connects a collected artist to an explicitly confirmed
public SoundCloud profile. Enter app credentials in **Set up SoundCloud**, then
**Test connection**. Credentials are encrypted locally in `soundcloud.enc` using
macOS-backed Electron safeStorage; only the backend receives them. OAuth tokens
stay in memory and are refreshed during the session. SoundCloud currently requires
Artist Pro for new API app registration; see the
[official setup guide](https://developers.soundcloud.com/docs/api/register-app).
Without app credentials, individual public track links still work.

SoundCloud watches use the official API and check up to the latest 100 public
uploads, excluding reposts and playlists. The first successful check establishes
a baseline. Later unseen upload IDs arrive for review. Uploader identity is kept
separate from recording credits; confirm the artist, exact version title, and type
before keeping a finding. Original/remix/edit/bootleg/DJ-set labels are title and
length hints, not verified classification. Private or blocked audio is not played.

Add a public SoundCloud track link to listen through the official embedded player.
The same session queue can mix SoundCloud uploads, Beatport previews, and local
files, with pause, seek, skip, and saved moments. The widget controls its own volume
and availability; no SoundCloud audio is downloaded or proxied. Its official JS API
is vendored locally, and remote content is restricted to the SoundCloud iframe.

Hypeddit, purchase, and other supported destination links explicitly supplied by
the uploader are attached to findings. Taste opens these pages; it does not unlock
gates. A gate may provide a different file than the linked upload, so its recording
identity remains unverified. This is link discovery, not a Hypeddit feed collector.

Automatic collection from other sources, OS change notifications, YouTube downloads,
and audio similarity are not connected. Soulseek search hands off to the existing
search/download workflow.

JSON imports accept an array (or an object containing `tracks`) with `artist`,
`title`, optional `bpm`, `key`, `url`, `genre`, `label`, `release`, `release_date`,
`isrc`, `preview_url`, and structured `credits` (`name`, `role`, optional `url`).
Only Beatport preview/artwork hosts are allowed for direct inline media; validated
SoundCloud track URLs use the isolated official widget. Source links are
restricted to supported HTTPS music sites. Source API access and terms must be
checked before deploying public or unattended collectors.

## Women focus

The **Women focus** toggle prioritizes matches in track lists, research findings,
and watches, while keeping other music available. It persists across restarts and
does not alter ratings, favorites, follows, downloads, or watch schedules. Artist
and remixer credits qualify; labels and uploader names do not imply artist gender.

Watch cards let you add, inspect, update, or remove an association with a public
HTTPS source and a note describing explicit artist information. Use an artist's
self-description or a public biography/interview; names, photos, and pronouns are
not automatically classified. Acts with women members can be included with an
appropriate source note. Unset profiles remain unknown rather than being assigned
a different gender. Coverage is deliberately incomplete and visible in the UI.

Matching currently requires exact Beatport profile IDs on structured credits.
Unlinked local-file tags and ambiguous names do not qualify automatically.
**Find music for this focus** reads up to ten included profiles and adds up to three
uncollected catalog picks per profile to Research. Picks preserve exact source
versions and attribution, skip previously reviewed findings, and leave watch
baselines intact. This is an on-demand exploration, not a gender inference service
or a global census of women musicians.

## YouTube videos per song

**See the song** collects video links separately from audio sources. Music videos,
live performances, visualizers, lyric videos, and audio uploads have equal priority.
You can save a YouTube link, give it a type, and mark its relationship to the exact
recording as checked. Saved videos open on YouTube; Taste pauses its audio first.
This does not replace your local audio or change taste feedback.

**Set up YouTube search** accepts a YouTube Data API v3 key, encrypted locally using
Electron safeStorage in `youtube.enc`. Only the backend sends it to Google's API,
in a request header. You can also use `SLSK_YOUTUBE_API_KEY` for development. Enable
YouTube Data API v3 for the key's project before searching. **Find videos** requests
up to ten candidates for the selected artist and exact version title; it runs only
when requested and uses the project's API quota. No credential is needed for saved
links or the external YouTube search button. See the
[YouTube search API](https://developers.google.com/youtube/v3/docs/search/list).

Search results retain source relevance order without an official-video boost.
Types inferred from titles are hints, and uploader identity does not establish an
official artist. Reviews persist across repeated searches. Unreviewed API search
metadata expires after thirty days; manually reviewed/saved links are retained.
There is no automatic search across the whole library, embedded YouTube playback,
channel watch, or video download in this slice.

## Local discovery CLI

`scripts/discovery.py` turns imported track metadata into artist/remixer/editor
candidates and a listening inbox. It uses Python's standard library and SQLite;
it runs separately from the desktop app and MCP server.

Import a JSON array containing `artist` and `title`, with optional `bpm`, `key`,
and `status` (`new`, `queued`, `keep`, or `pass`):

```json
[
  {"artist": "Example Artist", "title": "Example Song (Example Remixer Remix)", "status": "queued"}
]
```

```sh
python3 scripts/discovery.py import tracks.json --source LDS --url https://livedjservice.com/downloads
python3 scripts/discovery.py report
python3 scripts/discovery.py follow 'Example Remixer'
python3 scripts/discovery.py feedback TRACK_ID keep
python3 scripts/discovery.py feedback TRACK_ID pass
python3 scripts/discovery.py follow 'Example Remixer' --remove
```

The default database is `state/discovery.sqlite3`; put `--db PATH` before the
command to use another database. Commands return JSON. The report includes track
IDs, the evidence behind each candidate, profile-search links, and recommendations
with source links. A follow is a local interest, not a social-platform follow.
Kept tracks carry more weight than queue selections. Subsequent imports preserve
feedback, suppress already-reviewed tracks, and match new entries against those
interests. Reimporting the same normalized artist/title does not duplicate it;
different remix titles stay separate. Identical titles for different recordings
can still collide, and aliases/punctuation variants are not resolved.

Credit parsing is deliberately conservative: it separates spaced `x` mashup
credits and named remix/edit parentheses, but keeps ambiguous `&` collaborations
together. Names and profile-search results require identity review. This is
metadata matching, not audio similarity or a verified social graph. This earlier
CLI report uses its own queue/keep/pass signals; the desktop listening library
adds independent favorites, ratings, owned files, and source context.

Run the focused tests with `python3 -m pytest tests/test_discovery.py -q`.

## Develop and verify

Use Node 24 and Python 3.11–3.14:

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[test]'
npm ci
node node_modules/electron/install.js
npm start
```

```sh
.venv/bin/python -m pytest -q
npm test
npm run build
npm run test:desktop
```

The desktop smoke test opens Electron with a temporary profile, exercises all five tabs, indexes a local fixture, changes wishlist/settings, and checks renderer isolation without connecting to Soulseek. Live login, remote search and actual peer transfers still require account/network validation.

To package a standalone macOS ARM64 app:

```sh
.venv/bin/pip install pyinstaller
npm run package
```

The bundle contains its Python runtime and backend. It does not depend on the development virtual environment. `node scripts/package.cjs --reuse-backend` repackages an already-built backend after renderer-only changes.

## Reverse-engineering evidence

REA 6.8.0, Ghidra 12.1.4 and Temurin JDK 21 were installed for analysis. Five selected SoulseekQt functions were decompiled through REA; the findings summary is in [analysis/FINDINGS.md](analysis/FINDINGS.md). Raw analysis artifacts remain local and are excluded from Git. The installed SoulseekQt app was not modified. Decompiled source is not compiled into this client.

`scripts/inspect_soulseek.py` runs the analysis with explicit local Ghidra/Java paths. The original headless prototype remains in `server.py` and `scripts/run_mcp.py`; the desktop integration uses `desktop_mcp.py` instead.

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and [LICENSE](LICENSE) for licensing.
