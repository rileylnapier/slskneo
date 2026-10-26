# Soulseek investigation and implementation evidence

These historical notes describe the initial headless prototype. For the current
Electron app, sharing, wishlist, persistence and 24-tool MCP bridge, see
[README.md](../README.md). Referenced raw REA artifacts are retained locally
and excluded from this repository.

## Target identity

Original installed executable:
`/Applications/SoulseekQt.app/Contents/MacOS/SoulseekQt`.
SHA-256: `a2a789b1f23658cfdd5c4f8e7bbbf77d43db9b7577da56948cd85a289781f383`.

REA's Ghidra adapter requires a single-architecture Mach-O. Apple `lipo` extracted
the ARM64 slice into `.tools/targets/SoulseekQt-arm64`; the installed application
was not modified. Slice SHA-256:
`f40560bed6b44636c92a9cefb7bbd84c95eb825053c55a37a21cae911c8ce769`.

REA 6.8.0 with Ghidra 12.1.4 and Temurin JDK 21.0.13 produced the evidence below.
Both downloaded archives passed comparison against release SHA-256 values.
The ARM64 native decompiler was built locally from the Ghidra release source.
`ghidra-doctor.json` records provider readiness; `rea/evidence-bundle.json`
retains complete REA evidence. Each procedure also has its original JSON result
and a readable `.c` pseudocode export under `rea/`.

## Observed static behavior

| Question | Observation | Evidence |
| --- | --- | --- |
| Where does a global search start? | `SearchForm::onSearchEntered` trims input, skips an empty query, and routes the “All” choice to `Server::FileSearch`. It creates a search-results form using the returned token. | `rea/search-entry.json`, `ev_9f7cfaa259be5be46ab49c1947c907a4b92e20741cd895607fff06b87e8290a2` |
| What is sent for a global search? | `Server::FileSearch` calls `PrepareSearch`, increments an integer request counter, writes code `0x1a` (26), the request token and query, calls `SendMessage`, then emits `SearchRequested`. A nonempty second argument selects code `0x67`. | `rea/server-file-search.json`, `ev_3232047f3ab86bcb677440d76401d23753b7ed65f6814c9fa8afd9e7018b7c04` |
| How does the original transform queries? | `Server::PrepareSearch` trims whitespace. For input of length at least three it strips matching outer double quotes, splits on spaces and omits one-character terms. Decompiled details do not establish complete search semantics. | `rea/prepare-search.json`, `ev_54b2811124d55ba4e5246fb85754dcbbdba0a320b6248011e2f0b28663555bce` |
| How does a selected file become a download? | `SearchResultMenuOptions::OnDownloadFile` iterates selected results, retrieves peer, filename, folder and file size, and passes them to `TransferQueueManager::addDownload`. | `rea/download-selection.json`, `ev_515f05fbe75540922a298358a928aa3b29d031a29a472e9c4e08344ffebd6dc5` |
| What does a peer queue request contain? | `PeerMessenger::QueueDownload` writes code `0x2b` (43), then a four-byte path length and path bytes, and calls `PeerMessenger::SendMessage`. | `rea/peer-queue-download.json`, `ev_1d3029902e1c546be14f29209efe0b5dd5f439829cb60724245180cf54b21d63` |

These are static decompiler observations, not runtime captures or original
source. Ghidra emits unknown types and unreachable-block warnings. The evidence
does not establish complete client behavior or full protocol equivalence.

## New implementation

`src/soulseek_mcp` is newly written Python code using aioslsk 1.6.4 and the official
MCP Python SDK 1.30.0. It is an independent client, not a patched or recompiled
SoulseekQt application. REA observations informed the search/result/download
separation and supplied independent checks for the two message layouts in
`tests/test_protocol_evidence.py`.

Design choices include explicit login; result IDs for selected downloads;
bounded, temporary result storage; separate transfer pause/resume controls;
private local credentials; unique destination directories; and no shared
directories configured in this first version. It trims and validates submitted
queries but does not reproduce SoulseekQt's one-character-term filtering.

## Validation and remaining work

- Native provider: health check passed and five functions returned pseudocode.
- MCP: a real stdio client initialized the new server, discovered 10 tools, read
  status, and verified missing-credential, disconnected-search and invalid-download
  failures. `mcp-smoke.json` records this check; no Soulseek network was used.
- Automated tests exercise client lifecycle, asynchronous results, limits,
  download selection, pause/resume, and observed message IDs/payload order.
- **Unverified:** successful login, peer reachability, real search results and
  file transfer against the live network. Credentials must be supplied locally.
- **Outside this initial implementation:** Qt UI reconstruction, complete binary
  decompilation, uploads/sharing, chat, wishlist, room/user searches, persistent
  transfer recovery, and automatic migration of the desktop app's settings.

## Primary references

- REA: https://github.com/morluto/rea
- Ghidra release: https://github.com/NationalSecurityAgency/ghidra/releases/tag/Ghidra_12.1.4_build
- Java: https://github.com/adoptium/temurin21-binaries/releases/tag/jdk-21.0.13%2B9
- aioslsk: https://github.com/JurgenR/aioslsk
- MCP Python SDK: https://github.com/modelcontextprotocol/python-sdk
