from __future__ import annotations

import os

import uvicorn

from .config import host, port
from . import app as api
from .config import paths
from hoard_link.net import find_available_port, free_port
from hoard_link.tokens import read_or_create_token, write_url
from hoard_link.family import configure as configure_family


def main() -> None:
    p = paths().ensure()
    read_or_create_token(p.token_path)
    configure_family("gutenberg", str(p.data_dir), token_file=str(p.token_path))
    listen_host = host()
    requested = port()
    if requested == 0:
        requested = free_port(listen_host)
    elif os.environ.get("GUTENBERG_PORT_STRICT", "").strip().lower() not in {"1", "true", "yes", "on"}:
        requested = find_available_port(requested, host=listen_host)
    url = f"http://{listen_host}:{requested}"
    write_url(p.url_path, url)
    uvicorn.run(api.app, host=listen_host, port=requested, log_level="info")


if __name__ == "__main__":
    main()
