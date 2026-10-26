"""Private local JSON-RPC socket for the Electron app and MCP bridge."""
from __future__ import annotations

import asyncio
import fcntl
import json
import os
from pathlib import Path
import signal
import stat

from .desktop_service import DesktopService
from .service import ClientError

ROOT = Path(__file__).resolve().parents[2]


class Daemon:
    def __init__(self, service: DesktopService, socket_path: Path):
        self.service = service
        self.socket_path = socket_path
        self.server = None
        self._lock_fd = None
        self._writers = set()
        self._handlers = set()

    async def start(self):
        self.socket_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.socket_path.parent.chmod(0o700)
        self._lock_fd = os.open(str(self.socket_path) + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(self._lock_fd)
            self._lock_fd = None
            raise ClientError("The Soulseek backend is already running.") from None
        try:
            if self.socket_path.is_symlink():
                raise ClientError("Refusing a symlink at the backend socket path.")
            if self.socket_path.exists():
                if not stat.S_ISSOCK(self.socket_path.stat().st_mode):
                    raise ClientError("The backend socket path is occupied by a regular file.")
                # A lock alone cannot prove an unrelated socket is stale.
                try:
                    _, writer = await asyncio.open_unix_connection(str(self.socket_path))
                except (ConnectionRefusedError, FileNotFoundError):
                    self.socket_path.unlink(missing_ok=True)
                else:
                    writer.close()
                    await writer.wait_closed()
                    raise ClientError("Another process is listening at the backend socket path.")
            self.server = await asyncio.start_unix_server(self._handle, path=str(self.socket_path), limit=1024 * 1024)
            self.socket_path.chmod(0o600)
            await self.service.start()
        except BaseException:
            if self.server:
                self.server.close()
                await self.server.wait_closed()
                self.server = None
                self.socket_path.unlink(missing_ok=True)
            fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            os.close(self._lock_fd)
            self._lock_fd = None
            raise

    async def close(self):
        if self.server is None and self._lock_fd is None:
            return
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            for writer in list(self._writers):
                writer.close()
            pending = list(self._handlers)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            self.socket_path.unlink(missing_ok=True)
            self.server = None
        try:
            await self.service.close()
        finally:
            if self._lock_fd is not None:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                os.close(self._lock_fd)
                self._lock_fd = None

    async def _handle(self, reader, writer):
        task = asyncio.current_task()
        self._handlers.add(task)
        self._writers.add(writer)
        try:
            while True:
                try:
                    line = await reader.readline()
                except ValueError:
                    break
                if not line:
                    break
                identifier = None
                try:
                    request = json.loads(line)
                    if not isinstance(request, dict):
                        raise ClientError("Request must be an object.")
                    identifier = request.get("id")
                    if identifier is not None and not isinstance(identifier, (str, int)):
                        raise ClientError("Invalid request id.")
                    result = await self.service.dispatch(request.get("method"), request.get("params", {}))
                    response = {"id": identifier, "result": result}
                except (ClientError, json.JSONDecodeError) as error:
                    response = {"id": identifier, "error": {"message": str(error)}}
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    response = {"id": identifier, "error": {"message": f"Operation failed ({type(error).__name__})."}}
                writer.write((json.dumps(response, ensure_ascii=False) + "\n").encode())
                await writer.drain()
        except (ConnectionError, BrokenPipeError):
            pass
        finally:
            self._handlers.discard(task)
            self._writers.discard(writer)
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass


async def run():
    state_dir = Path(os.environ.get("SLSK_STATE_DIR", str(ROOT / "state"))).resolve()
    socket_path = Path(os.environ.get("SLSK_SOCKET", str(state_dir / "soulseek.sock")))
    service = DesktopService(state_dir)
    daemon = Daemon(service, socket_path)
    await daemon.start()
    done = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, done.set)
    print(json.dumps({"ready": True, "socket": str(socket_path)}), flush=True)
    try:
        await done.wait()
    finally:
        await daemon.close()


def main():
    try:
        asyncio.run(run())
    except ClientError as error:
        raise SystemExit(str(error)) from None


if __name__ == "__main__":
    main()
