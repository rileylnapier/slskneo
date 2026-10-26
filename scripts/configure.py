"""Prompt locally for credentials; never send them through chat or shell history."""
from getpass import getpass
import os
from pathlib import Path
import stat

from dotenv import set_key

ROOT = Path(__file__).resolve().parents[1]


def main():
    path = ROOT / ".env.local"
    if path.is_symlink():
        raise SystemExit("Refusing a symlink at .env.local")
    username = input("Soulseek username: ").strip()
    password = getpass("Soulseek password (hidden): ")
    if not username or not password:
        raise SystemExit("Both values are required; configuration was not changed.")
    if any(c in username + password for c in "\r\n\x00"):
        raise SystemExit("Credentials cannot contain newlines or NUL bytes.")
    fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise SystemExit(".env.local must be a regular file")
        os.fchmod(fd, 0o600)
    finally:
        os.close(fd)
    set_key(path, "SLSK_USERNAME", username, quote_mode="always")
    set_key(path, "SLSK_PASSWORD", password, quote_mode="always")
    path.chmod(0o600)
    print("Saved private local configuration. Restart the Soulseek MCP server to load it.")


if __name__ == "__main__":
    main()

