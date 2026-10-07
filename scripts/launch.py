from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hoard_link.net import already_running, find_available_port, free_port, open_in_browser, wait_healthy
from gutenberg_hoard.config import designcraft_cli


def main() -> int:
    preferred = int(os.environ.get("GUTENBERG_PORT", "5218"))
    if preferred == 0:
        preferred = free_port("127.0.0.1")
    if already_running("gutenbergs-hoard", preferred):
        open_in_browser(f"http://127.0.0.1:{preferred}")
        return 0
    port = find_available_port(preferred)
    data = os.environ.get("GUTENBERG_DATA_DIR") or str(ROOT / "data")
    configured_cli = designcraft_cli()
    cli = str(configured_cli) if configured_cli else ""
    if not cli:
        print("Set GUTENBERG_DESIGNCRAFT_CLI or configure the DesignCraft path in local-config.json.", file=sys.stderr)
        return 2
    env = dict(os.environ, GUTENBERG_PORT=str(port), GUTENBERG_PORT_STRICT="1", GUTENBERG_HOST="127.0.0.1", GUTENBERG_DATA_DIR=data,
               GUTENBERG_DESIGNCRAFT_CLI=cli)
    if not designcraft_cli():
        print(f"DesignCraft CLI not found: {cli}", file=sys.stderr)
        return 2
    url = f"http://127.0.0.1:{port}"
    child = subprocess.Popen([sys.executable, "-m", "gutenberg_hoard"], cwd=ROOT, env=env)
    if wait_healthy(url, "gutenbergs-hoard", timeout=30):
        if not open_in_browser(url):
            print(f"Open {url} in your browser.")
    else:
        print(f"Gutenberg could not start at {url}.", file=sys.stderr)
        child.terminate()
        return 1
    try:
        return child.wait()
    except KeyboardInterrupt:
        child.terminate()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
