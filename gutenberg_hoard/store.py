from __future__ import annotations

import json
import hashlib
import os
import re
import time
from contextlib import contextmanager
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .config import paths


def _db() -> sqlite3.Connection:
    p = paths().ensure().db_path
    con = sqlite3.connect(p, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("""CREATE TABLE IF NOT EXISTS publications (
        id TEXT PRIMARY KEY, title TEXT NOT NULL, native_path TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, page_count INTEGER NOT NULL DEFAULT 1,
        profile_json TEXT NOT NULL DEFAULT '{}')""")
    con.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    con.execute("""CREATE TABLE IF NOT EXISTS publication_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, publication_id TEXT NOT NULL, snapshot_path TEXT NOT NULL,
        created_at TEXT NOT NULL, after_sha256 TEXT NOT NULL DEFAULT '',
        FOREIGN KEY(publication_id) REFERENCES publications(id) ON DELETE CASCADE)""")
    cols = {row[1] for row in con.execute("PRAGMA table_info(publication_history)")}
    if "after_sha256" not in cols:
        con.execute("ALTER TABLE publication_history ADD COLUMN after_sha256 TEXT NOT NULL DEFAULT ''")
    con.commit()
    return con


def list_publications() -> list[dict]:
    with _db() as con:
        rows = con.execute("SELECT * FROM publications ORDER BY updated_at DESC").fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["profile"] = json.loads(item.pop("profile_json"))
        path = Path(item["native_path"])
        item["exists"] = path.is_file()
        result.append(item)
    return result


def get_publication(publication_id: str) -> dict:
    with _db() as con:
        row = con.execute("SELECT * FROM publications WHERE id=?", (publication_id,)).fetchone()
    if not row:
        raise LookupError("Publication not found")
    item = dict(row)
    item["profile"] = json.loads(item.pop("profile_json"))
    item["path"] = item.pop("native_path")
    return item


def add_publication(title: str, native_path: Path, pages: int, profile: dict | None = None) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    pid = uuid.uuid4().hex
    with _db() as con:
        con.execute("INSERT INTO publications(id,title,native_path,created_at,updated_at,page_count,profile_json) VALUES(?,?,?,?,?,?,?)",
                    (pid, title, str(native_path.resolve()), now, now, pages, json.dumps(profile or {}, ensure_ascii=False)))
    return get_publication(pid)


def touch(publication_id: str, title: str | None = None, pages: int | None = None) -> dict:
    pub = get_publication(publication_id)
    with _db() as con:
        con.execute("UPDATE publications SET title=?,page_count=?,updated_at=? WHERE id=?",
                    (title or pub["title"], pages or pub["page_count"], datetime.now(timezone.utc).isoformat(), publication_id))
    return get_publication(publication_id)


def publication_dir() -> Path:
    root = paths().ensure().data_dir / "publications"
    root.mkdir(parents=True, exist_ok=True)
    return root


def safe_stem(title: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_-]+", "-", title).strip("-_")[:48]
    return value or "publication"


def setting(key: str, default: str = "") -> str:
    with _db() as con:
        row = con.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
    return str(row[0]) if row else default


def set_setting(key: str, value: str) -> None:
    with _db() as con:
        con.execute("INSERT INTO app_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, value))


def add_history(publication_id: str, snapshot_path: Path, limit: int = 30) -> None:
    after = Path(get_publication(publication_id)["path"]).read_bytes()
    with _db() as con:
        con.execute("INSERT INTO publication_history(publication_id,snapshot_path,created_at,after_sha256) VALUES(?,?,?,?)",
                    (publication_id, str(snapshot_path), datetime.now(timezone.utc).isoformat(), hashlib.sha256(after).hexdigest()))
        stale = con.execute("SELECT id,snapshot_path FROM publication_history WHERE publication_id=? ORDER BY id DESC LIMIT -1 OFFSET ?",
                            (publication_id, limit)).fetchall()
        for row in stale:
            Path(row["snapshot_path"]).unlink(missing_ok=True)
            con.execute("DELETE FROM publication_history WHERE id=?", (row["id"],))


def peek_history(publication_id: str) -> dict | None:
    with _db() as con:
        row = con.execute("SELECT id,snapshot_path,after_sha256 FROM publication_history WHERE publication_id=? ORDER BY id DESC LIMIT 1",
                          (publication_id,)).fetchone()
    return dict(row) if row else None


def pop_history(publication_id: str) -> Path | None:
    with _db() as con:
        row = con.execute("SELECT id,snapshot_path FROM publication_history WHERE publication_id=? ORDER BY id DESC LIMIT 1",
                          (publication_id,)).fetchone()
        if not row:
            return None
        con.execute("DELETE FROM publication_history WHERE id=?", (row["id"],))
    return Path(row["snapshot_path"])


def has_history(publication_id: str) -> bool:
    with _db() as con:
        return con.execute("SELECT 1 FROM publication_history WHERE publication_id=? LIMIT 1",
                           (publication_id,)).fetchone() is not None


@contextmanager
def publication_lock(publication_id: str, timeout: float = 300):
    """Cross-process lock shared by the web API and stdio MCP server."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", publication_id):
        raise ValueError("Invalid publication ID")
    lock_dir = paths().ensure().data_dir / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / f"{publication_id}.lock"
    with lock_path.open("a+b") as fh:
        fh.seek(0, 2)
        if fh.tell() == 0:
            fh.write(b"\0")
            fh.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                fh.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Another Gutenberg worker is still editing this publication")
                time.sleep(.05)
        try:
            yield
        finally:
            fh.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
