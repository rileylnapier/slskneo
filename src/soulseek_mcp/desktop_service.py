"""One stateful Soulseek session shared by the desktop and MCP adapters."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import replace
import json
import os
from pathlib import Path, PureWindowsPath
import time
from typing import Any
from uuid import uuid4

from aioslsk.client import SoulSeekClient
from aioslsk.commands import PeerGetDirectoryContentCommand, PeerGetSharesCommand
from aioslsk.search.model import SearchType
from aioslsk.settings import Settings, SharedDirectorySettingEntry, WishlistSettingEntry
from aioslsk.shares.manager import SharesManager

from .logging_utils import configure_logging
from .service import ClientError, Config, Search, SoulseekService


class ConfinedSharesManager(SharesManager):
    """Do not follow file symlinks outside an explicitly selected share root."""

    async def scan_directory_files(self, directory):
        await super().scan_directory_files(directory)
        root = Path(directory.absolute_path).resolve()
        directory.items = {item for item in directory.items
                           if Path(item.get_absolute_path()).resolve().is_relative_to(root)}
        # super has already indexed the scan; rebuild the search index after pruning.
        self.rebuild_term_map()


class DesktopClient(SoulSeekClient):
    def create_shares_manager(self, cache, executor_factory=None):
        return ConfinedSharesManager(self.settings, self.events, self.network, cache, executor_factory)


class DesktopService(SoulseekService):
    def __init__(self, state_dir: Path, client_factory=None):
        self.state_dir = state_dir.resolve()
        self.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.state_dir.chmod(0o700)
        self.state_path = self.state_dir / "desktop.json"
        self._state = self._read_state()
        defaults = Config.from_env()
        self.preferences = {
            "username": defaults.username, "download_dir": str(defaults.download_dir),
            "listen_port": defaults.listen_port, "obfuscated_port": defaults.obfuscated_port,
            "upload_slots": 2, "upload_speed_kbps": 0, "download_speed_kbps": 0,
            "notifications": True,
        }
        self.preferences.update({k: v for k, v in self._state.get("settings", {}).items()
                                 if k in self.preferences})
        self._share_paths = list(self._state.get("share_paths", []))[:100]
        self._share_stats = self._state.get("share_stats", {})
        self._wishes = list(self._state.get("wishlist", []))[:50]
        self._history = list(self._state.get("history", []))[:100]
        self._archive: OrderedDict[str, dict] = OrderedDict()
        for row in self._state.get("transfers", [])[-200:]:
            if row.get("transfer_id") and row.get("local_path"):
                if row.get("state") not in ("COMPLETE", "FAILED", "ABORTED"):
                    row["state"] = "PAUSED"
                row["speed_bytes_per_second"] = 0
                self._archive[row["transfer_id"]] = row
        self._scan_task: asyncio.Task | None = None
        self._scan_error: str | None = None
        self._maintenance_task: asyncio.Task | None = None
        self._search_times: dict[str, float] = {}
        self._browse_ids: set[str] = set()
        self._saved_serialized = ""
        config = replace(defaults, username=self.preferences["username"],
                         download_dir=Path(self.preferences["download_dir"]).expanduser().resolve(),
                         listen_port=self.preferences["listen_port"],
                         obfuscated_port=self.preferences["obfuscated_port"], max_searches=32)
        super().__init__(config, client_factory or self._build_client)
        configure_logging(config.password)

    def _read_state(self):
        if not self.state_path.exists():
            return {}
        try:
            result = json.loads(self.state_path.read_text())
            if not isinstance(result, dict):
                raise ValueError
            return result
        except (OSError, ValueError):
            raise ClientError("Saved application state is unreadable. Preserve desktop.json and restore a valid backup.") from None

    def _build_client(self, config):
        settings = Settings(
            credentials={"username": config.username, "password": config.password},
            network={"server": {"hostname": config.server, "port": config.server_port, "reconnect": {"auto": False}},
                     "listening": {"port": config.listen_port, "obfuscated_port": config.obfuscated_port},
                     "upnp": {"enabled": False},
                     "limits": {"upload_speed_kbps": self.preferences["upload_speed_kbps"],
                                "download_speed_kbps": self.preferences["download_speed_kbps"]}},
            searches={"send": {"store_results": False, "request_timeout": config.search_seconds,
                                "wishlist_request_timeout": config.search_seconds},
                      "wishlist": [{"query": w["query"], "enabled": w["enabled"]} for w in self._wishes]},
            shares={"download": str(config.download_dir), "directories": [{"path": p} for p in self._share_paths],
                    "scan_on_start": False},
            transfers={"limits": {"upload_slots": self.preferences["upload_slots"]}},
            rooms={"auto_join": False, "private_room_invites": False},
        )
        return DesktopClient(settings)

    async def start(self):
        if self._maintenance_task is None:
            self._maintenance_task = asyncio.create_task(self._maintain())

    async def close(self):
        if self._maintenance_task:
            self._maintenance_task.cancel()
            await asyncio.gather(self._maintenance_task, return_exceptions=True)
            self._maintenance_task = None
        if self._scan_task:
            await asyncio.gather(self._scan_task, return_exceptions=True)
        await self.disconnect()
        self._persist()

    async def _maintain(self):
        while True:
            await asyncio.sleep(5)
            self._persist()

    def _current_transfers(self):
        rows = OrderedDict(self._archive)
        for tid in self._transfers:
            rows[tid] = self._transfer_view(tid)
        return rows

    def _persist(self):
        state = {"version": 1, "settings": self.preferences, "share_paths": self._share_paths,
                 "share_stats": self._share_stats, "wishlist": self._wishes, "history": self._history,
                 "transfers": list(self._current_transfers().values())}
        encoded = json.dumps(state, ensure_ascii=False, indent=2) + "\n"
        if encoded == self._saved_serialized:
            return
        temporary = self.state_dir / (".desktop-" + uuid4().hex + ".tmp")
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.state_path)
        self._saved_serialized = encoded

    def settings_get(self):
        return {**self.preferences, "credentials_configured": bool(self.config.username and self.config.password)}

    async def configure(self, **changes):
        allowed = set(self.preferences) | {"password"}
        if set(changes) - allowed:
            raise ClientError("Unknown settings field.")
        prefs = dict(self.preferences)
        for key, value in changes.items():
            if key in ("listen_port", "obfuscated_port"):
                if type(value) is not int or not 1 <= value <= 65535:
                    raise ClientError(f"{key} must be between 1 and 65535.")
            elif key in ("upload_speed_kbps", "download_speed_kbps"):
                if type(value) is not int or not 0 <= value <= 1000000:
                    raise ClientError(f"{key} must be a nonnegative integer, at most 1000000.")
            elif key == "upload_slots":
                if type(value) is not int or not 1 <= value <= 100:
                    raise ClientError("Upload slots must be between 1 and 100.")
            elif key == "notifications":
                if not isinstance(value, bool):
                    raise ClientError("notifications must be true or false.")
            elif key in ("username", "password"):
                if not isinstance(value, str) or len(value) > 1024 or any(c in value for c in "\r\n\x00"):
                    raise ClientError("Invalid credentials format.")
            elif key == "download_dir":
                if not isinstance(value, str) or not value.strip() or "\x00" in value:
                    raise ClientError("Choose a valid download directory.")
                value = str(Path(value).expanduser().resolve())
            if key != "password":
                prefs[key] = value
        if prefs["listen_port"] == prefs["obfuscated_port"]:
            raise ClientError("Listening ports must be different.")
        async with self._lock:
            sensitive = ("username", "password", "download_dir", "listen_port", "obfuscated_port")
            if self.connected and any(k in changes and changes[k] != (self.config.password if k == "password" else self.preferences.get(k)) for k in sensitive):
                raise ClientError("Disconnect before changing account, download directory or listening ports.")
            self.preferences = prefs
            self.config = replace(self.config, username=prefs["username"], password=changes.get("password", self.config.password),
                                  download_dir=Path(prefs["download_dir"]), listen_port=prefs["listen_port"],
                                  obfuscated_port=prefs["obfuscated_port"])
            configure_logging(self.config.password)
            if self._client:
                self._client.settings.transfers.limits.upload_slots = prefs["upload_slots"]
                self._client.network.set_upload_speed_limit(prefs["upload_speed_kbps"])
                self._client.network.set_download_speed_limit(prefs["download_speed_kbps"])
            self._persist()
        return self.settings_get()

    def status(self):
        result = super().status()
        result.update(username=self.config.username, sharing_enabled=bool(self._share_paths),
                      persistence="Settings, wishlist, search history and transfer journal",
                      transfers=len(self._current_transfers()), scanning=bool(self._scan_task and not self._scan_task.done()))
        return result

    async def connect(self):
        await super().connect()
        if self._share_paths:
            await self.shares_rescan()
        return self.status()

    async def disconnect(self):
        if self._scan_task and not self._scan_task.done():
            await asyncio.gather(self._scan_task, return_exceptions=True)
        await super().disconnect()
        return self.status()

    async def _stop(self):
        # connect() also stops a stale session after an unexpected disconnect.
        # Preserve that session's queue before the base service clears it.
        self._archive = self._current_transfers()
        for row in self._archive.values():
            if row["state"] not in ("COMPLETE", "FAILED", "ABORTED"):
                row["state"] = "PAUSED"
            row["speed_bytes_per_second"] = 0
        try:
            await super()._stop()
        finally:
            self._search_times.clear()
            self._browse_ids.clear()
            self._persist()

    async def search(self, query):
        result = await super().search(query)
        self._search_times[result["search_id"]] = time.time()
        self._history = [h for h in self._history if h["query"] != result["query"]]
        self._history.insert(0, {"query": result["query"], "created": time.time()})
        self._history = self._history[:100]
        self._persist()
        return result

    def _forget_search(self, search):
        super()._forget_search(search)
        self._search_times.pop(search.id, None)
        self._browse_ids.discard(search.id)

    def _on_search_sent(self, event):
        if event.query.search_type != SearchType.WISHLIST:
            super()._on_search_sent(event)
            return
        if event.query.search_type == SearchType.WISHLIST:
            wish = next((w for w in self._wishes if w["query"] == event.query.query), None)
            if wish:
                old = self._searches.get(wish.get("last_search_id", ""))
                if old:
                    self._forget_search(old)
                while len(self._searches) >= self.config.max_searches:
                    self._forget_search(next(iter(self._searches.values())))
                search = Search(uuid4().hex, event.query.query, self._clock())
                self._searches[search.id] = search
                self._bind_search(search, event.query.ticket)
                self._search_times[search.id] = time.time()
                wish.update(last_run=time.time(), last_search_id=search.id, last_count=0)

    def _on_result(self, event):
        super()._on_result(event)
        sid = self._tickets.get(event.query.ticket)
        if sid in self._searches:
            for wish in self._wishes:
                if wish.get("last_search_id") == sid:
                    wish["last_count"] = len(self._searches[sid].results)

    def results(self, search_id, offset=0, limit=100, filter="", extension="", min_bitrate=0, sort="filename"):
        self._pagination(offset, limit)
        self._expire_searches()
        search = self._searches.get(search_id)
        if search is None:
            raise ClientError("Unknown or expired search. Run it again.")
        if sort not in ("filename", "size", "speed", "username", "bitrate"):
            raise ClientError("Unknown result sort.")
        if type(min_bitrate) is not int or min_bitrate < 0:
            raise ClientError("Minimum bitrate must be a nonnegative integer.")
        words = filter.casefold().split()
        ext = extension.casefold().lstrip(".")
        rows = [r for r in search.results.values()
                if all(word in r["filename"].casefold() for word in words)
                and (not ext or r["extension"].casefold() == ext or r["filename"].casefold().endswith("." + ext))
                and int(r["attributes"].get("0", 0)) >= min_bitrate]
        keys = {"filename": lambda r: r["filename"].casefold(), "username": lambda r: r["username"].casefold(),
                "size": lambda r: r["size_bytes"], "speed": lambda r: r["speed_bytes_per_second"],
                "bitrate": lambda r: r["attributes"].get("0", 0)}
        rows.sort(key=keys[sort], reverse=sort in ("size", "speed", "bitrate"))
        total = len(rows)
        return {"search_id": search_id, "query": search.query, "collecting": search.active,
                "total_retained": len(search.results), "total_filtered": total, "truncated": search.truncated,
                "offset": offset, "next_offset": offset + limit if offset + limit < total else None,
                "results": rows[offset:offset + limit]}

    def snapshot(self):
        self._expire_searches()
        uploads = []
        if self._client:
            for transfer in self._client.transfers.get_uploads()[:200]:
                uploads.append({"username": transfer.username, "filename": transfer.remote_path,
                                "state": transfer.state.VALUE.name, "size_bytes": transfer.filesize,
                                "bytes_transferred": transfer.bytes_transferred,
                                "speed_bytes_per_second": transfer.get_speed()})
        return {"status": self.status(), "searches": [
            {"search_id": s.id, "query": s.query, "collecting": s.active, "total_retained": len(s.results),
             "created": self._search_times.get(s.id), "browse": s.id in self._browse_ids}
            for s in reversed(list(self._searches.values()))],
            "transfers": list(self._current_transfers().values()), "uploads": uploads,
            "wishlist": self._wishes, "shares": self.shares()["directories"], "history": self._history}

    async def download(self, result_id):
        return await self._queue_download(result_id)

    async def _queue_download(self, result_id, directory: Path | None = None):
        async with self._lock:
            client = self._require_client()
            self._expire_searches()
            selected = next((s.results[result_id] for s in self._searches.values() if result_id in s.results), None)
            if selected is None:
                raise ClientError("Unknown or expired result. Search again before downloading.")
            if selected["locked"]:
                raise ClientError("This file is locked by the peer.")
            for row in self._current_transfers().values():
                if (row["username"], row["filename"]) == (selected["username"], selected["filename"]):
                    return {**row, "already_queued": True}
            if len(self._current_transfers()) >= self.config.max_transfers:
                raise ClientError("Transfer capacity reached. Remove completed records before adding more.")
            name = PureWindowsPath(selected["filename"]).name
            if name in ("", ".", "..") or len(name.encode("utf-8")) > 240 or any(ord(c) < 32 for c in name):
                raise ClientError("The peer filename is not a supported local filename.")
            transfer_id = uuid4().hex
            own_directory = directory is None
            if directory is None:
                directory = self.config.download_dir / transfer_id
                directory.mkdir(mode=0o700, parents=True, exist_ok=False)
            if not directory.resolve().is_relative_to(self.config.download_dir.resolve()):
                raise ClientError("The selected destination is outside the download directory.")
            destination = directory / name
            try:
                descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                os.close(descriptor)
            except FileExistsError:
                raise ClientError("A file with this name already exists in the destination; it was preserved.") from None
            try:
                async with asyncio.timeout(15):
                    transfer = await client.transfers.download(selected["username"], selected["filename"], paused=True)
                    transfer.local_path = str(destination)
                    self._transfers[transfer_id] = transfer
                    self._transfer_keys[(selected["username"], selected["filename"])] = transfer_id
                    await client.transfers.queue(transfer)
            except BaseException as error:
                if transfer_id in self._transfers:
                    try:
                        async with asyncio.timeout(5):
                            await client.transfers.pause(transfer)
                    except Exception:
                        pass
                else:
                    destination.unlink(missing_ok=True)
                    if own_directory:
                        directory.rmdir()
                self._persist()
                if isinstance(error, asyncio.CancelledError):
                    raise
                raise ClientError(f"Could not queue the file ({type(error).__name__}); inspect the download list before retrying.") from None
            self._persist()
            return self._transfer_view(transfer_id)

    def transfers(self, offset=0, limit=100):
        self._pagination(offset, limit)
        rows = list(self._current_transfers().values())
        return {"transfers": rows[offset:offset + limit], "total": len(rows),
                "next_offset": offset + limit if offset + limit < len(rows) else None}

    async def pause_transfer(self, transfer_id):
        if transfer_id not in self._transfers and transfer_id in self._archive:
            return self._archive[transfer_id]
        result = await super().pause_transfer(transfer_id)
        self._persist()
        return result

    async def _restore_transfer(self, transfer_id):
        client = self._require_client()
        row = self._archive.get(transfer_id)
        if not row:
            raise ClientError("Unknown transfer.")
        if row["state"] == "COMPLETE":
            raise ClientError("This file is already complete.")
        path = Path(row["local_path"])
        root = self.config.download_dir.resolve()
        if path.is_symlink() or not path.resolve().is_relative_to(root) or not path.is_file():
            raise ClientError("The partial file is missing or outside the current download directory. Search and queue it again.")
        transfer = await client.transfers.download(row["username"], row["filename"], paused=True)
        transfer.local_path = str(path)
        transfer.filesize = row.get("size_bytes")
        self._transfers[transfer_id] = transfer
        self._transfer_keys[(row["username"], row["filename"])] = transfer_id
        self._archive.pop(transfer_id, None)
        return transfer

    async def resume_transfer(self, transfer_id):
        if transfer_id not in self._transfers:
            async with self._lock:
                await self._restore_transfer(transfer_id)
        result = await super().resume_transfer(transfer_id)
        self._persist()
        return result

    async def retry_transfer(self, transfer_id):
        async with self._lock:
            client = self._require_client()
            transfer = self._transfers.get(transfer_id) or await self._restore_transfer(transfer_id)
            if transfer.state.VALUE.name not in ("FAILED", "INCOMPLETE", "PAUSED"):
                raise ClientError("Only failed, incomplete or paused transfers can be retried.")
            await client.transfers.queue(transfer)
            self._persist()
            return self._transfer_view(transfer_id)

    async def remove_transfer(self, transfer_id):
        async with self._lock:
            transfer = self._transfers.get(transfer_id)
            if transfer:
                # The library remove() deletes partial files. Detach the path only
                # after pausing, so removing a queue record always preserves files.
                if transfer.state.VALUE.name not in ("PAUSED", "COMPLETE", "FAILED", "ABORTED"):
                    await self._client.transfers.pause(transfer)
                path = transfer.local_path
                transfer.local_path = None
                try:
                    await self._client.transfers.remove(transfer)
                finally:
                    transfer.local_path = path
                del self._transfers[transfer_id]
                self._transfer_keys.pop((transfer.username, transfer.remote_path), None)
            elif transfer_id not in self._archive:
                raise ClientError("Unknown transfer.")
            self._archive.pop(transfer_id, None)
            self._persist()
        return {"removed": transfer_id, "files_preserved": True}

    def shares(self):
        scanning = bool(self._scan_task and not self._scan_task.done())
        rows = [{"path": path, "name": Path(path).name, "files": self._share_stats.get(path, {}).get("files", 0),
                 "size_bytes": self._share_stats.get(path, {}).get("size_bytes", 0), "scanning": scanning,
                 "error": self._scan_error if self._scan_error else (None if Path(path).is_dir() else "Folder is unavailable")}
                for path in self._share_paths]
        return {"directories": rows, "total_files": sum(row["files"] for row in rows), "scanning": scanning}

    async def share_add(self, path):
        target = Path(path).expanduser().resolve()
        if not target.is_dir():
            raise ClientError("Choose an existing folder to share.")
        if len(self._share_paths) >= 100:
            raise ClientError("Maximum shared-folder count reached.")
        if str(target) not in self._share_paths:
            self._share_paths.append(str(target))
            self._persist()
        return await self.shares_rescan()

    async def share_remove(self, path):
        target = str(Path(path).expanduser().resolve())
        if target not in self._share_paths:
            raise ClientError("This folder is not shared.")
        if self._scan_task and not self._scan_task.done():
            await self._scan_task
        self._share_paths.remove(target)
        self._share_stats.pop(target, None)
        if self._client:
            self._client.settings.shares.directories = [SharedDirectorySettingEntry(path=p) for p in self._share_paths]
            self._client.shares.load_from_settings()
            await self._client.shares.report_shares()
        self._persist()
        return self.shares()

    async def shares_rescan(self):
        if self._scan_task and not self._scan_task.done():
            return self.shares()
        self._scan_error = None

        async def scan():
            try:
                client = self._client or self._build_client(self.config)
                client.settings.shares.directories = [SharedDirectorySettingEntry(path=p) for p in self._share_paths]
                client.shares.load_from_settings()
                await client.shares.scan()
                counts = {}
                for directory in client.shares.shared_directories:
                    size = 0
                    for item in directory.items:
                        try:
                            size += Path(item.get_absolute_path()).stat().st_size
                        except OSError:
                            pass
                    counts[directory.absolute_path] = {"files": len(directory.items), "size_bytes": size}
                self._share_stats = counts
            except Exception as error:
                self._scan_error = f"Scan failed ({type(error).__name__}); check folder access."
            finally:
                self._persist()

        self._scan_task = asyncio.create_task(scan())
        return self.shares()

    def _new_browse(self, username, directories, locked_directories=()):
        self._expire_searches()
        while len(self._searches) >= self.config.max_searches:
            self._forget_search(next(iter(self._searches.values())))
        search = Search(uuid4().hex, f"Files from {username}", self._clock(), active=False)
        for locked, dirs in ((False, directories), (True, locked_directories)):
            for directory in dirs:
                for file in directory.files:
                    if len(search.results) >= 20000:
                        search.truncated = True
                        break
                    filename = str(PureWindowsPath(directory.name) / file.filename)
                    rid = uuid4().hex
                    search.results[rid] = {"result_id": rid, "username": username, "filename": filename,
                        "size_bytes": file.filesize, "extension": file.extension, "locked": locked,
                        "free_slots": False, "speed_bytes_per_second": 0, "queue_size": 0,
                        "attributes": {str(a.key): a.value for a in file.attributes[:32]}}
                if search.truncated:
                    break
        self._searches[search.id] = search
        self._search_times[search.id] = time.time()
        self._browse_ids.add(search.id)
        return search

    async def browse_user(self, username):
        if not isinstance(username, str) or not username.strip() or len(username) > 256:
            raise ClientError("Enter a valid username.")
        client = self._require_client()
        try:
            directories, locked = await client.execute(PeerGetSharesCommand(username), response=True, timeout=30)
        except Exception as error:
            raise ClientError(f"Could not browse this user ({type(error).__name__}); they may be offline or unreachable.") from None
        search = self._new_browse(username, directories, locked)
        return {**self.results(search.id), "username": username}

    async def download_folder(self, search_id, username, folder):
        client = self._require_client()
        source = self._searches.get(search_id)
        if source is None or not any(r["username"] == username and str(PureWindowsPath(r["filename"]).parent) == folder
                                     for r in source.results.values()):
            raise ClientError("Select a folder from current search or browse results.")
        try:
            directories = await client.execute(PeerGetDirectoryContentCommand(username, folder), response=True, timeout=30)
        except Exception as error:
            raise ClientError(f"Could not retrieve the full folder ({type(error).__name__}). No files were queued.") from None
        selected = [d for d in directories if str(PureWindowsPath(d.name)) == str(PureWindowsPath(folder))]
        search = self._new_browse(username, selected)
        rows = list(search.results.values())
        if not rows:
            raise ClientError("The peer returned no files for this folder. Nothing was queued.")
        if search.truncated or len(rows) + len(self._current_transfers()) > self.config.max_transfers:
            raise ClientError("Folder exceeds the remaining transfer capacity; browse and select individual files.")
        folder_name = PureWindowsPath(folder).name
        if folder_name in ("", ".", "..") or any(ord(c) < 32 for c in folder_name):
            folder_name = "Album"
        # A new local album directory groups this batch while retaining the
        # peer's file names. No remote directory can select an arbitrary path.
        folder_name = folder_name[:100]
        directory = self.config.download_dir / (folder_name + " - " + uuid4().hex[:8])
        directory.mkdir(mode=0o700, parents=True, exist_ok=False)
        queued, errors = [], []
        for row in rows:
            try:
                queued.append(await self._queue_download(row["result_id"], directory))
            except ClientError as error:
                errors.append({"filename": row["filename"], "message": str(error)})
        if not any(directory.iterdir()):
            directory.rmdir()
        return {"queued": queued, "queued_count": len(queued), "errors": errors, "source": "full peer folder response"}

    def wishlist(self):
        return {"items": self._wishes, "interval_seconds": getattr(getattr(self._client, "searches", None), "wishlist_interval", None)}

    def _sync_wishes(self):
        if self._client:
            self._client.settings.searches.wishlist = [WishlistSettingEntry(query=w["query"], enabled=w["enabled"]) for w in self._wishes]
        self._persist()

    def wishlist_add(self, query):
        query = query.strip()
        if not query or len(query) > 256 or any(ord(c) < 32 for c in query):
            raise ClientError("Enter a search phrase of 1–256 printable characters.")
        if len(self._wishes) >= 50:
            raise ClientError("The wishlist is limited to 50 searches.")
        if not any(w["query"] == query for w in self._wishes):
            self._wishes.append({"id": uuid4().hex, "query": query, "enabled": True,
                                 "last_run": None, "last_search_id": None, "last_count": 0})
        self._sync_wishes()
        return self.wishlist()

    def wishlist_update(self, id, enabled):
        if not isinstance(enabled, bool):
            raise ClientError("enabled must be true or false.")
        wish = self._wish(id)
        wish["enabled"] = enabled
        self._sync_wishes()
        return self.wishlist()

    def wishlist_remove(self, id):
        self._wishes.remove(self._wish(id))
        self._sync_wishes()
        return self.wishlist()

    def _wish(self, id):
        wish = next((w for w in self._wishes if w["id"] == id), None)
        if wish is None:
            raise ClientError("Unknown wishlist item.")
        return wish

    async def wishlist_run(self, id):
        wish = self._wish(id)
        result = await self.search(wish["query"])
        wish.update(last_run=time.time(), last_search_id=result["search_id"], last_count=0)
        self._persist()
        return result

    async def dispatch(self, method, params):
        names = {"status", "snapshot", "settings_get", "configure", "connect", "disconnect", "search", "results",
                 "stop_search", "download", "download_folder", "transfers", "pause_transfer", "resume_transfer",
                 "retry_transfer", "remove_transfer", "shares", "share_add", "share_remove", "shares_rescan", "browse_user",
                 "wishlist", "wishlist_add", "wishlist_update", "wishlist_remove", "wishlist_run"}
        if method not in names or not isinstance(params, dict):
            raise ClientError("Unknown method or invalid parameters.")
        function = getattr(self, method)
        try:
            result = function(**params)
            return await result if asyncio.iscoroutine(result) else result
        except TypeError:
            raise ClientError("Invalid method parameters.") from None
