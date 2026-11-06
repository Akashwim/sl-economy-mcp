"""Tests for the one-click Claude extension's build script, without the internet."""

import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

from sl_economy_mcp import __version__

SCRIPT = Path(__file__).resolve().parent.parent / "extension" / "build.py"
spec = importlib.util.spec_from_file_location("build_extension", SCRIPT)
build_extension = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_extension)


def test_the_bundle_holds_the_code_and_what_claude_needs_to_run_it(tmp_path):
    bundle = build_extension.build(tmp_path)
    assert bundle.name == f"sl-economy-mcp-{__version__}.mcpb"
    names = set(zipfile.ZipFile(bundle).namelist())
    modules = {f"src/sl_economy_mcp/{p.name}" for p in build_extension.PACKAGE.glob("*.py")}
    expected = {"manifest.json", "run_server.py", "pyproject.toml", "uv.lock", ".python-version", "README.md", "LICENSE"}
    assert expected | modules == names
    assert not any("__pycache__" in name or name.startswith("tests/") for name in names)


def test_the_manifest_matches_the_code(tmp_path):
    zipped = zipfile.ZipFile(build_extension.build(tmp_path))
    manifest = json.loads(zipped.read("manifest.json"))
    assert manifest["version"] == __version__  # the version Claude's install screen shows
    assert manifest["display_name"] == "Sri Lanka Economy"
    assert manifest["server"]["type"] == "uv"
    assert manifest["server"]["entry_point"] in zipped.namelist()
    args = manifest["server"]["mcp_config"]["args"]
    assert args[-1] == manifest["server"]["entry_point"]
    assert "--frozen" in args  # the exact versions in uv.lock, never newer ones chosen on the day
    assert "win32" in manifest["compatibility"]["platforms"]  # the bank's colleagues use Windows
    for field in ("manifest_version", "name", "version", "description", "author", "server"):
        assert manifest[field], field  # required by the bundle format


def test_the_entry_point_starts_this_projects_server(tmp_path, monkeypatch):
    from sl_economy_mcp import server

    started = []
    monkeypatch.setattr(server, "main", lambda: started.append(True))
    code = zipfile.ZipFile(build_extension.build(tmp_path)).read("run_server.py").decode("utf-8")
    exec(compile(code, "run_server.py", "exec"), {"__name__": "__main__"})
    assert started == [True]


def test_the_lock_matches_the_projects_requirements():
    # uv.lock must have been made from the current pyproject.toml, or uv would
    # use versions that were never tested with it.
    tomllib = pytest.importorskip("tomllib")  # in Python 3.11 and newer; the 3.10 run skips this check

    project = Path(build_extension.PROJECT)
    lock = tomllib.loads((project / "uv.lock").read_text(encoding="utf-8"))
    pyproject = tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))
    ours = next(package for package in lock["package"] if package["name"] == "sl-economy-mcp")
    locked = sorted(f"{d['name']}{d.get('specifier', '')}" for d in ours["metadata"]["requires-dist"] if "marker" not in d)
    wanted = sorted(r.replace(" ", "") for r in pyproject["project"]["dependencies"])
    assert locked == wanted
    assert (project / ".python-version").read_text(encoding="utf-8").strip() == "3.14"
