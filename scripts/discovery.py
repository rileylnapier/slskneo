#!/usr/bin/env python3
"""Run the local discovery prototype without installing the desktop dependencies."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from soulseek_mcp.discovery import main

if __name__ == "__main__":
    main()
