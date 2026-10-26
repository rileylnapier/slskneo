"""Run a focused, reproducible REA investigation without launching Soulseek.

Uses a separate local REA MCP process so newly installed provider paths take
effect immediately. Retains original MCP results and an exported evidence bundle.
"""
import asyncio
from datetime import timedelta
import json
import os
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "analysis" / "rea"
NODE = Path.home() / ".nvm/versions/node/v24.22.1/bin/node"
REA = NODE.parent.parent / "lib/node_modules/rea-agents/scripts/rea.mjs"
# Ghidra's REA provider requires an explicit thin slice of universal Mach-O.
# Created with: lipo /Applications/SoulseekQt.app/Contents/MacOS/SoulseekQt
#              -thin arm64 -output .tools/targets/SoulseekQt-arm64
TARGET = str(ROOT / ".tools/targets/SoulseekQt-arm64")
PROCEDURES = {
    "search-entry": "0x100130b5c",
    "server-file-search": "0x10006ca10",
    "prepare-search": "0x10006d19c",
    "download-selection": "0x1001785c8",
    "peer-queue-download": "0x1000b138c",
}


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update({
        "GHIDRA_INSTALL_DIR": str(ROOT / ".tools/ghidra_12.1.4_PUBLIC"),
        "JAVA_HOME": str(ROOT / ".tools/jdk-21.0.13+9/Contents/Home"),
        "REA_ANALYSIS_PROVIDER": "ghidra",
    })
    params = StdioServerParameters(command=str(NODE), args=[str(REA), "mcp"], env=env)
    with (OUT / "server.log").open("a") as log:
        async with stdio_client(params, errlog=log) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=450)) as session:
                await session.initialize()

                async def call(label, name, args):
                    print(f"REA {name}: {label}", flush=True)
                    result = await session.call_tool(name, args)
                    raw = result.model_dump(mode="json", exclude_none=True)
                    (OUT / f"{label}.json").write_text(json.dumps(raw, indent=2) + "\n")
                    if result.isError:
                        raise RuntimeError(f"REA returned an error; inspect {OUT / (label + '.json')}")
                    print(f"Saved {label}", flush=True)
                    return raw

                await call("open", "open_binary", {"path": TARGET, "provider_id": "ghidra"})
                try:
                    for label, address in PROCEDURES.items():
                        await call(label, "procedure_pseudo_code", {"procedure": address})
                    await call("export", "export_evidence_bundle", {
                        "path": str(OUT / "evidence-bundle.json"), "overwrite": True,
                    })
                finally:
                    await call("close", "close_binary", {})


if __name__ == "__main__":
    asyncio.run(main())
