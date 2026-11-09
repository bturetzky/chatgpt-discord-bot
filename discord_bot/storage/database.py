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
    # Each migration is a sequence of individual statements, not a SQL script.
    (
        """CREATE TABLE messages (
            guild_id TEXT NOT NULL,
            channel_id TEXT NOT NULL,
            message_id TEXT PRIMARY KEY,
            author_id TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            edited_at TEXT,
            deleted_at TEXT
        )""",
        """CREATE INDEX messages_channel ON messages(channel_id, message_id)""",
        """CREATE VIRTUAL TABLE messages_fts USING fts5(content, content='messages', content_rowid='rowid')""",
        """CREATE TRIGGER messages_ai AFTER INSERT ON messages BEGIN
            INSERT INTO messages_fts(rowid, content) VALUES (new.rowid, new.content);
        END""",
        """CREATE TRIGGER messages_ad AFTER DELETE ON messages BEGIN
            INSERT INTO messages_fts(messages_fts, rowid, content) VALUES ('delete', old.rowid, old.content);
        END""",
        """CREATE TRIGGER messages_au AFTER UPDATE OF content ON messages BEGIN
            INSERT INTO messages_fts(messages_fts, rowid, content) VALUES ('delete', old.rowid, old.content);
            INSERT INTO messages_fts(rowid, content) VALUES (new.rowid, new.content);
        END""",
    ),
    (
        """CREATE TABLE deleted_message_ids (
            message_id TEXT PRIMARY KEY
        )""",
    ),
    (
        """CREATE TABLE backfill_cursors (
            channel_id TEXT PRIMARY KEY,
            before_message_id TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
    ),
    (
        """CREATE TABLE reaction_members (
            guild_id TEXT NOT NULL,
            channel_id TEXT NOT NULL,
            message_id TEXT NOT NULL,
            emoji_key TEXT NOT NULL,
            user_id TEXT NOT NULL,
            observed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (message_id, emoji_key, user_id)
        )""",
        """CREATE INDEX reaction_members_channel ON reaction_members(guild_id, channel_id, message_id)""",
    ),
    (
        """CREATE TABLE shadow_evaluations (
            message_id TEXT PRIMARY KEY,
            guild_id TEXT NOT NULL,
            channel_id TEXT NOT NULL,
            trigger TEXT NOT NULL,
            status TEXT NOT NULL,
            decision TEXT,
            emoji_key TEXT,
            reason_category TEXT,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            evaluated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE INDEX shadow_evaluations_recent ON shadow_evaluations(guild_id, evaluated_at)""",
    ),
    (
        """CREATE TABLE extraction_batches (
            batch_id TEXT PRIMARY KEY,
            guild_id TEXT NOT NULL,
            channel_id TEXT NOT NULL,
            first_message_id TEXT NOT NULL,
            last_message_id TEXT NOT NULL,
            source_hash TEXT NOT NULL,
            extractor_version TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
            attempts INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            processed_at TEXT,
            error_category TEXT
        )""",
        """CREATE INDEX extraction_batches_channel
            ON extraction_batches(guild_id, channel_id, status)""",
    ),
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
        self.connection.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        for version, sql in enumerate(MIGRATIONS, start=1):
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                if self.connection.execute(
                    "SELECT 1 FROM schema_migrations WHERE version=?", (version,)
                ).fetchone():
                    self.connection.execute("COMMIT")
                    continue
                statements = sql if isinstance(sql, tuple) else (sql.strip().rstrip(";"),)
                for statement in statements:
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
