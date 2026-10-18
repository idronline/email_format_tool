"""Usage log for the IDR tools: one row per use, read by the admin panel.

Master copy: email_format_tool/shared/ - edit it there, then run shared/sync.sh to copy it to every tool.

    from idr_usage import record
    record("translate", ok=True, seconds=12.3, language="hi", size_kb=40)

Stores only counts and settings - never document text, file names, email addresses
or images. Rows go to a small SQLite file (IDR_USAGE_DB, default ~/idr-usage.db) that
all tools on one server share. Recording must never break a tool, so every error is
swallowed and printed.
"""

import hashlib
import hmac
import json
import os
import sqlite3
import time

DB_PATH = os.environ.get("IDR_USAGE_DB") or os.path.expanduser("~/idr-usage.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id       INTEGER PRIMARY KEY,
    ts       REAL    NOT NULL,          -- unix time
    tool     TEXT    NOT NULL,          -- translate | audio | emails | image-search
    ok       INTEGER NOT NULL,          -- 1 worked, 0 failed
    seconds  REAL,                      -- how long it took
    details  TEXT    NOT NULL,          -- JSON: language, sizes, counts ...
    error    TEXT                       -- short error message when ok = 0
);
CREATE INDEX IF NOT EXISTS events_ts ON events (ts);
"""


def connect(path=None):
    conn = sqlite3.connect(path or DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")      # several tools write to the same file
    conn.executescript(SCHEMA)
    conn.row_factory = sqlite3.Row
    return conn


def record(tool, ok=True, seconds=None, error=None, path=None, **details):
    """Add one usage row. Never raises."""
    try:
        conn = connect(path)
        with conn:
            conn.execute("INSERT INTO events (ts, tool, ok, seconds, details, error) VALUES (?, ?, ?, ?, ?, ?)",
                         (time.time(), tool, 1 if ok else 0, None if seconds is None else round(seconds, 2),
                          json.dumps(details, ensure_ascii=False, sort_keys=True),
                          None if error is None else str(error)[:500]))
        conn.close()
    except Exception as e:  # noqa: BLE001 - usage logging must never break a tool
        print(f"[usage] could not record {tool}: {type(e).__name__}: {e}")


def events_since(ts, path=None):
    """All rows since unix time ts, oldest first, as plain dicts (details decoded)."""
    if not os.path.exists(path or DB_PATH):
        return []
    conn = connect(path)
    rows = conn.execute("SELECT * FROM events WHERE ts >= ? ORDER BY ts", (ts,)).fetchall()
    conn.close()
    return [dict(r, details=json.loads(r["details"] or "{}")) for r in rows]


def export_token():
    """Token the admin panel sends to fetch another server's usage (derived from the shared
    SECRET_KEY, so nothing new to configure). None when SECRET_KEY is not set."""
    key = os.environ.get("SECRET_KEY", "")
    return hmac.new(key.encode(), b"idr-usage-export", hashlib.sha256).hexdigest() if key else None


def token_ok(given):
    expected = export_token()
    return bool(expected and given and hmac.compare_digest(expected, given))
