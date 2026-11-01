"""Persistence only: SQLite transactions, foreign keys, integer cents."""

from contextlib import contextmanager
from pathlib import Path
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS imports (
 id TEXT PRIMARY KEY, content_sha256 TEXT NOT NULL, config_json TEXT NOT NULL,
 fingerprint TEXT NOT NULL UNIQUE, filename TEXT NOT NULL, created_at TEXT NOT NULL,
 total INTEGER NOT NULL, accepted INTEGER NOT NULL, rejected INTEGER NOT NULL,
 duplicated INTEGER NOT NULL, elapsed_ms REAL NOT NULL,
 CHECK(total = accepted + rejected + duplicated)
);
CREATE TABLE IF NOT EXISTS sales (
 id INTEGER PRIMARY KEY, sale_id TEXT NOT NULL, branch TEXT NOT NULL,
 sale_date TEXT NOT NULL, amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
 currency TEXT NOT NULL CHECK(currency IN ('PEN','USD','EUR')), description TEXT NOT NULL,
 import_id TEXT NOT NULL REFERENCES imports(id), source_row INTEGER NOT NULL,
 UNIQUE(branch,sale_id)
);
CREATE INDEX IF NOT EXISTS sales_period ON sales(sale_date,branch,currency);
CREATE TABLE IF NOT EXISTS outcomes (
 import_id TEXT NOT NULL REFERENCES imports(id), source_row INTEGER NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('accepted','rejected','duplicated')),
 reason TEXT NOT NULL, raw_json TEXT NOT NULL, PRIMARY KEY(import_id,source_row)
);
PRAGMA user_version=1;
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA journal_mode=WAL")
        try:
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()
