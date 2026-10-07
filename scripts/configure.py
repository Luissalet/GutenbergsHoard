"""Save the machine-local DesignCraft executable without replacing existing settings."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "local-config.json"


def main() -> int:
    raw_candidate = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("GUTENBERG_DESIGNCRAFT_CLI", "")
    if not raw_candidate.strip():
        print("Pass the path to designcraft-cli.exe.", file=sys.stderr)
        return 2
    candidate = Path(raw_candidate).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    candidate = candidate.resolve()
    if not candidate.is_file():
        print(f"DesignCraft CLI was not found: {candidate}", file=sys.stderr)
        return 2
    if CONFIG.exists():
        try:
            data = json.loads(CONFIG.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"Existing local-config.json could not be read; left unchanged: {exc}", file=sys.stderr)
            return 2
        if not isinstance(data, dict):
            print("Existing local-config.json is not an object; left unchanged.", file=sys.stderr)
            return 2
    else:
        data = {}
    existing = str(data.get("designcraft_cli") or "").strip()
    if existing:
        print(f"Preserved existing DesignCraft CLI setting: {existing}")
        return 0
    data["designcraft_cli"] = str(candidate)
    gui = candidate.with_name("designcraft.exe")
    if gui.is_file() and not data.get("designcraft_gui"):
        data["designcraft_gui"] = str(gui)
    fd, name = tempfile.mkstemp(prefix=".local-config-", suffix=".tmp", dir=ROOT)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, CONFIG)
    finally:
        Path(name).unlink(missing_ok=True)
    print(f"Saved DesignCraft CLI path in ignored {CONFIG.name}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
