#!/usr/bin/env python3
"""Build official LLM .pluginpack archives from tracked source files."""
from __future__ import annotations

import argparse
import json
import platform
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PACKS = {
    "text-local": ["manifest.json", "run.py"],
    "text-privacy": ["manifest.json", "run.py"],
}


def platform_tag() -> str:
    system = "macos" if platform.system() == "Darwin" else platform.system().lower()
    machine = platform.machine().lower()
    return f"{system}-{'arm64' if machine in {'arm64', 'aarch64'} else 'x64'}"


def build(plugin_id: str) -> Path:
    source = ROOT / plugin_id
    output = ROOT / f"{plugin_id}.pluginpack"
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in PACKS[plugin_id]:
            if name == "manifest.json":
                manifest = json.loads((source / name).read_text(encoding="utf-8"))
                manifest["platforms"] = [platform_tag()]
                archive.writestr(name, json.dumps(manifest, indent=2) + "\n")
            else:
                archive.write(source / name, name)
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plugin", choices=[*PACKS, "all"], default="all")
    args = parser.parse_args()
    selected = PACKS if args.plugin == "all" else {args.plugin: PACKS[args.plugin]}
    for plugin_id in selected:
        pack = build(plugin_id)
        print(f"built {pack.name} ({pack.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
