#!/usr/bin/env python3
"""Safely append private registries to /etc/docker/daemon.json.

Run with sudo on each node, then restart Docker manually when convenient.
The script never pipes the original file through tee, so it avoids truncating
the config before it is read.
"""

import argparse
import json
import shutil
import time
from pathlib import Path


def update_daemon_config(path, registries):
    data = {}
    if path.exists():
        text = path.read_text(encoding="utf-8").strip()
        if text:
            data = json.loads(text)

    insecure = data.setdefault("insecure-registries", [])
    if not isinstance(insecure, list):
        raise SystemExit(f"{path} field insecure-registries must be a list")

    changed = False
    for registry in registries:
        clean_registry = registry.strip()
        if clean_registry and clean_registry not in insecure:
            insecure.append(clean_registry)
            changed = True

    if not changed:
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_name("{}.bak.{}".format(path.name, time.strftime("%Y%m%d%H%M%S")))
        shutil.copy2(path, backup)
    tmp = path.with_name("{}.tmp".format(path.name))
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return True


def main():
    parser = argparse.ArgumentParser(description="Append Docker insecure registries safely")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("/etc/docker/daemon.json"),
        help="Docker daemon config path",
    )
    parser.add_argument(
        "--registry",
        action="append",
        default=[],
        help="Registry host:port to append; may be repeated",
    )
    args = parser.parse_args()
    registries = args.registry or ["172.16.0.254:5000"]
    changed = update_daemon_config(args.config, registries)
    print("updated" if changed else "unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
