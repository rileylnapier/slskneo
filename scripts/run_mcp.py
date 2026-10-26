"""Start the installed server with optional private project configuration."""
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env.local", override=False)

from soulseek_mcp.server import main

if __name__ == "__main__":
    main()

