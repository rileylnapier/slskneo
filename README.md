# slskneo

**slskneo** is an independent Electron Soulseek client with a light, compact file-library interface and Soulseek blue controls. The desktop app and its MCP tools share one backend, connection, search collection and transfer queue. This is a new client built on aioslsk, not recompiled SoulseekQt source.

## Open the app

The current desktop bundle is named Soulseek Studio. The Apple Silicon build is at:

`release/Soulseek Studio-darwin-arm64/Soulseek Studio.app`

Open it, enter a new or existing Soulseek username and password in **Settings**, then click **Save and connect**. An unused username is registered by Soulseek when you connect. Startup never logs in automatically. Passwords are encrypted through macOS-backed Electron safeStorage; they are not exposed to MCP or written into the backend settings file.

## Included features

- **Search:** global searches, paged results, filename/format/bitrate filters, sorting, selected-file and whole-folder downloads, and browsing a user's shared files.
- **Downloads:** progress, pause/resume/retry/remove controls, completed history, and reveal in Finder. Saved unfinished transfers require an explicit resume after restarting.
- **Shared Files:** choose folders, scan/rescan real files, remove shares, and view uploads. No folders are shared until selected.
- **Wishlist:** persistent saved searches, enable/pause/remove, manual search and server-scheduled searches. Matches never download automatically.
- **Settings:** account, download folder, listening ports, slots, bandwidth limits, and completion/match notifications.

Chat rooms, private messages, buddies, user profiles and original-client theme compatibility are outside this first build.

## MCP

The packaged backend supports `--mcp` and exposes 24 tools. It connects to the running desktop app rather than starting a second Soulseek session. Open the app before calling tools.

```toml
[mcp_servers.soulseek]
command = "/absolute/path/to/slskneo/release/Soulseek Studio-darwin-arm64/Soulseek Studio.app/Contents/Resources/backend/soulseek-backend"
args = ["--mcp"]
startup_timeout_sec = 30
tool_timeout_sec = 150
```

Tools cover status/snapshot, connect/disconnect, search/results/stop, downloads/folders, transfer controls, user browsing, shares/rescan, and wishlist management. Credentials are entered in the app only.

State is stored in `~/Library/Application Support/Soulseek Studio/`. The backend uses a private Unix socket and owner-only state files. `SLSK_STATE_DIR` and `SLSK_SOCKET` support isolated development/test profiles.

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
