"""SQLite cache of per-part ZIP entry listings.

Reading a part's central directory over Drive is cheap (KBs), but caching it
means repeat runs need neither a token nor network, and the report can be
rebuilt offline. A part is re-read only if its Drive size or modifiedTime
changed (the cache key), so edits to an export invalidate just that part.
"""

from __future__ import annotations

import datetime
import sqlite3

DEFAULT_PATH = "poc/.cache.sqlite"


def open_cache(path: str = DEFAULT_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS parts("
        "file_id TEXT PRIMARY KEY, name TEXT, size INTEGER, "
        "modified_time TEXT, indexed_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS entries(file_id TEXT, name TEXT, size INTEGER)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS ix_entries_file ON entries(file_id)")
    conn.commit()
    return conn


def get_entries(conn, file_id: str, size: int, modified_time: str):
    """Cached (name, size) entries for a part, or None if absent/stale."""
    row = conn.execute(
        "SELECT size, modified_time FROM parts WHERE file_id=?", (file_id,)
    ).fetchone()
    if not row or row[0] != size or row[1] != modified_time:
        return None
    cur = conn.execute("SELECT name, size FROM entries WHERE file_id=?", (file_id,))
    return [(n, s) for n, s in cur.fetchall()]


def put_entries(conn, file_id, name, size, modified_time, entries) -> None:
    conn.execute("DELETE FROM entries WHERE file_id=?", (file_id,))
    conn.executemany(
        "INSERT INTO entries(file_id, name, size) VALUES(?,?,?)",
        ((file_id, n, s) for n, s in entries),
    )
    conn.execute(
        "INSERT OR REPLACE INTO parts(file_id, name, size, modified_time, indexed_at) "
        "VALUES(?,?,?,?,?)",
        (file_id, name, size, modified_time,
         datetime.datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()


def get_parts(conn) -> list[dict]:
    """All cached parts as Drive-like dicts (for offline runs)."""
    cur = conn.execute(
        "SELECT file_id, name, size, modified_time FROM parts ORDER BY name"
    )
    return [
        {"id": r[0], "name": r[1], "size": r[2], "modifiedTime": r[3]}
        for r in cur.fetchall()
    ]
