"""SQLite lifecycle and ordered schema migrations.

A single bot process owns each database file. Keep feature-specific queries in
separate modules; this layer owns only connections and schema upgrades.
"""

import sqlite3
from pathlib import Path

MIGRATIONS = (
    """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """,
)


class Database:
    def __init__(self, path: str):
        if not path or path == ":memory:":
            raise ValueError("Database requires a persistent file path")
        self.path = Path(path).expanduser()
        self.connection = None

    def open(self):
        if self.connection is not None:
            raise RuntimeError("Database is already open")
        if not self.path.parent.is_dir():
            raise FileNotFoundError(f"SQLite parent directory does not exist: {self.path.parent}")
        connection = sqlite3.connect(str(self.path), timeout=5, isolation_level=None)
        try:
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute("PRAGMA foreign_keys=ON")
            mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            if mode.lower() != "wal":
                raise RuntimeError("SQLite WAL mode unavailable")
            self.connection = connection
            self.migrate()
            return self
        except Exception:
            connection.close()
            self.connection = None
            raise

    def migrate(self):
        if self.connection is None:
            raise RuntimeError("Database is not open")
        for version, sql in enumerate(MIGRATIONS, start=1):
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                # executescript commits implicitly; execute each statement within
                # the explicit transaction to keep the migration atomic.
                for statement in sql.split(";"):
                    if statement.strip():
                        self.connection.execute(statement)
                self.connection.execute(
                    "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)",
                    (version,),
                )
                self.connection.execute("COMMIT")
            except Exception:
                self.connection.execute("ROLLBACK")
                raise

    def integrity_check(self):
        if self.connection is None:
            raise RuntimeError("Database is not open")
        result = self.connection.execute("PRAGMA quick_check").fetchone()[0]
        if result != "ok":
            raise RuntimeError("SQLite integrity check failed")
        return True

    def close(self):
        if self.connection is not None:
            try:
                self.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                self.connection.close()
                self.connection = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *_):
        self.close()
