"""Standalone executable entry: daemon by default, MCP bridge with --mcp."""
import sys

if "--mcp" in sys.argv:
    from soulseek_mcp.desktop_mcp import main
else:
    from soulseek_mcp.daemon import main

if __name__ == "__main__":
    main()
