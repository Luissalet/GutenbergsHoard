from __future__ import annotations

import os
from pathlib import Path

from hoard_link.appconfig import AppPaths, env_int, env_str, resolve_paths

ROOT = Path(__file__).resolve().parent.parent


def paths() -> AppPaths:
    return resolve_paths("gutenberg", ROOT, env_prefix="GUTENBERG")


def _local_settings() -> dict:
    try:
        import json
        value = json.loads((ROOT / "local-config.json").read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def designcraft_cli() -> Path | None:
    value = env_str("GUTENBERG_DESIGNCRAFT_CLI")
    if not value:
        value = str(_local_settings().get("designcraft_cli") or "").strip()
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    return path if path.is_file() else None


def designcraft_gui() -> Path | None:
    value = env_str("GUTENBERG_DESIGNCRAFT_GUI")
    if not value:
        value = str(_local_settings().get("designcraft_gui") or "").strip()
    if value:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = ROOT / path
        path = path.resolve()
        return path if path.is_file() else None
    cli = designcraft_cli()
    if cli and cli.name.lower() == "designcraft-cli.exe":
        candidate = cli.with_name("designcraft.exe")
        return candidate if candidate.is_file() else None
    return None


def port() -> int:
    value = env_int("GUTENBERG_PORT", "PORT", default=5218, minimum=0, maximum=65535)
    return 5218 if value is None else value


def host() -> str:
    return env_str("GUTENBERG_HOST", default="127.0.0.1") or "127.0.0.1"
