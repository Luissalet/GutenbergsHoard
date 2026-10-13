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


def engine_cli() -> Path | None:
    path = ROOT / "native/bin" / ("gutenberg-cli.exe" if os.name == "nt" else "gutenberg-cli")
    return path if path.is_file() else None


def engine_gui() -> Path | None:
    path = ROOT / "native/bin" / ("gutenberg.exe" if os.name == "nt" else "gutenberg")
    return path if path.is_file() else None


# Historical import names remain aliases. Old configured paths are preserved as data.
designcraft_cli = engine_cli
designcraft_gui = engine_gui


def port() -> int:
    value = env_int("GUTENBERG_PORT", "PORT", default=5218, minimum=0, maximum=65535)
    return 5218 if value is None else value


def host() -> str:
    return env_str("GUTENBERG_HOST", default="127.0.0.1") or "127.0.0.1"
