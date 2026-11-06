"""Build the one-click Claude extension: dist/sl-economy-mcp-<version>.mcpb.

Run it from the project folder, with any Python 3.10 or newer:

    python extension/build.py

The file it makes is an "MCP Bundle" (https://github.com/modelcontextprotocol/mcpb)
of the "uv" kind: a zip holding this project's code, its pyproject.toml (which
lists the add-ons it needs) and a manifest. Double-clicking it in Claude's
desktop app installs it. The app downloads its own copy of uv from GitHub,
which then downloads Python and the add-ons, so nobody has to install Python.
Tested on a Mac on 6 November 2026; the bank's colleagues use Windows.

Every install gets the same, tested versions: uv.lock pins the exact version
of every add-on (make it with the uv that Claude's app uses, so that uv can
read it), .python-version pins Python, and "--frozen" tells uv to use the
lock as it is. After changing pyproject.toml, run `uv lock` again and rerun
the tests in an environment made from the new lock.

Rebuild it after every change to the code, and give it to people only after
the version number in src/sl_economy_mcp/__init__.py has been raised.
"""

import json
import re
import sys
import zipfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
PACKAGE = PROJECT / "src" / "sl_economy_mcp"
# pyproject.toml needs the README to build; uv.lock and .python-version pin the versions.
COPIED = ["pyproject.toml", "uv.lock", ".python-version", "README.md", "LICENSE"]

# The bundle's own entry point: start the server, as `sl-economy-mcp` would.
RUN_SERVER = '''"""Starts the Sri Lanka Economy tool server for Claude's desktop app."""

from sl_economy_mcp.server import main

main()
'''


def version() -> str:
    text = (PACKAGE / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'^__version__ = "([^"]+)"$', text, re.M).group(1)


def manifest(number: str) -> dict:
    return {
        "manifest_version": "0.4",
        "name": "sl-economy-mcp",
        "display_name": "Sri Lanka Economy",
        "version": number,
        "description": (
            "Live Sri Lankan economic figures from official sources: the Central Bank of "
            "Sri Lanka and the Ministry of Finance. Includes the Morning Sheet."
        ),
        "author": {"name": "Akash Wimalananda", "url": "https://github.com/Akashwim"},
        "homepage": "https://github.com/Akashwim/sl-economy-mcp",
        "license": "MIT",
        "server": {
            "type": "uv",
            "entry_point": "run_server.py",
            "mcp_config": {
                "command": "uv",
                "args": ["run", "--frozen", "--directory", "${__dirname}", "run_server.py"],
            },
        },
        "compatibility": {"platforms": ["win32", "darwin"], "runtimes": {"python": ">=3.10"}},
        "keywords": ["sri-lanka", "economics", "central-bank", "treasury-bills", "exchange-rates"],
    }


def build(out_dir: Path = PROJECT / "dist") -> Path:
    number = version()
    out_dir.mkdir(parents=True, exist_ok=True)
    bundle = out_dir / f"sl-economy-mcp-{number}.mcpb"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as zipped:
        zipped.writestr("manifest.json", json.dumps(manifest(number), indent=2) + "\n")
        zipped.writestr("run_server.py", RUN_SERVER)
        for name in COPIED:
            zipped.write(PROJECT / name, name)
        for module in sorted(PACKAGE.glob("*.py")):  # the code only: no caches, no tests
            zipped.write(module, f"src/sl_economy_mcp/{module.name}")
    return bundle


if __name__ == "__main__":
    made = build()
    print(f"Built {made.relative_to(PROJECT)} ({made.stat().st_size // 1000} KB)", file=sys.stderr)
