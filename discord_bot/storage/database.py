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
    (
        """CREATE TABLE extraction_candidates (
            batch_id TEXT NOT NULL REFERENCES extraction_batches(batch_id),
            candidate_index INTEGER NOT NULL,
            memory_type TEXT NOT NULL,
            summary TEXT NOT NULL,
            participant_ids TEXT NOT NULL,
            source_message_ids TEXT NOT NULL,
            confidence TEXT NOT NULL,
            rationale TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'proposed'
                CHECK (status IN ('proposed', 'accepted', 'rejected', 'superseded')),
            PRIMARY KEY (batch_id, candidate_index)
        )""",
        """CREATE TABLE extraction_usage (
            batch_id TEXT PRIMARY KEY REFERENCES extraction_batches(batch_id),
            model TEXT NOT NULL,
            input_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL,
            evaluated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
    ),
    (
        """CREATE TABLE candidate_evaluations (
            batch_id TEXT NOT NULL,
            candidate_index INTEGER NOT NULL,
            evaluator_version TEXT NOT NULL,
            scope TEXT NOT NULL CHECK(scope IN ('individual', 'collective', 'uncertain')),
            durability TEXT NOT NULL CHECK(durability IN ('durable', 'evolving', 'transient', 'uncertain')),
            disposition TEXT NOT NULL CHECK(disposition IN ('eligible', 'review', 'exclude')),
            rationale TEXT NOT NULL,
            evaluated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (batch_id, candidate_index, evaluator_version),
            FOREIGN KEY (batch_id, candidate_index)
                REFERENCES extraction_candidates(batch_id, candidate_index)
                ON DELETE CASCADE
        )""",
        """CREATE INDEX candidate_evaluations_disposition
            ON candidate_evaluations(disposition, evaluated_at)""",
    ),
    # Publication foundation only. No writer, scheduler or automated transitions.
    (
        """CREATE TABLE memory_records (
            memory_id TEXT PRIMARY KEY,
            guild_id TEXT NOT NULL,
            scope TEXT NOT NULL CHECK(scope IN ('individual', 'collective')),
            participant_ids TEXT NOT NULL,
            current_revision INTEGER,
            lifecycle TEXT NOT NULL DEFAULT 'staged'
                CHECK(lifecycle IN ('staged', 'active', 'superseded', 'invalidated')),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(memory_id, guild_id),
            FOREIGN KEY(memory_id, current_revision)
                REFERENCES memory_revisions(memory_id, revision)
                DEFERRABLE INITIALLY DEFERRED
        )""",
        """CREATE TABLE memory_revisions (
            memory_id TEXT NOT NULL REFERENCES memory_records(memory_id),
            revision INTEGER NOT NULL CHECK(revision > 0),
            proposal_id TEXT NOT NULL UNIQUE,
            summary TEXT NOT NULL,
            durability TEXT NOT NULL CHECK(durability IN ('durable', 'evolving')),
            source_hash TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'staged'
                CHECK(state IN ('staged', 'pending', 'published', 'superseded', 'invalidated', 'failed')),
            supersedes_revision INTEGER,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(memory_id, revision),
            FOREIGN KEY(memory_id, supersedes_revision)
                REFERENCES memory_revisions(memory_id, revision)
        )""",
        """CREATE TABLE memory_revision_sources (
            memory_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            message_id TEXT NOT NULL,
            channel_id TEXT NOT NULL,
            author_id TEXT NOT NULL,
            source_created_at TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            PRIMARY KEY(memory_id, revision, message_id),
            FOREIGN KEY(memory_id, revision)
                REFERENCES memory_revisions(memory_id, revision)
        )""",
        """CREATE INDEX memory_revision_sources_message
            ON memory_revision_sources(message_id)""",
        """CREATE TABLE memory_publication_attempts (
            attempt_id TEXT PRIMARY KEY,
            memory_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            operation TEXT NOT NULL CHECK(operation IN ('upsert', 'delete')),
            status TEXT NOT NULL CHECK(status IN ('pending', 'confirmed', 'failed', 'uncertain')),
            vector_id TEXT NOT NULL,
            error_category TEXT,
            started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT,
            FOREIGN KEY(memory_id, revision)
                REFERENCES memory_revisions(memory_id, revision)
        )""",
        """CREATE INDEX memory_publication_attempts_unresolved
            ON memory_publication_attempts(status, started_at)""",
    ),
    (
        """CREATE TABLE discovery_runs (
            id INTEGER PRIMARY KEY,
            guild_id TEXT NOT NULL,
            channel_id TEXT NOT NULL,
            started_at INTEGER NOT NULL,
            outcome TEXT NOT NULL DEFAULT 'interrupted',
            searches INTEGER NOT NULL DEFAULT 0,
            fetches INTEGER NOT NULL DEFAULT 0,
            model_calls INTEGER NOT NULL DEFAULT 0,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0
        )""",
        """CREATE TABLE discovery_candidates (
            guild_id TEXT NOT NULL,
            url TEXT NOT NULL,
            run_id INTEGER NOT NULL REFERENCES discovery_runs(id),
            source_url TEXT,
            reason TEXT NOT NULL DEFAULT 'interrupted',
            story TEXT,
            evidence TEXT,
            draft TEXT,
            PRIMARY KEY (guild_id, url)
        )""",
        """CREATE INDEX discovery_source ON discovery_candidates(guild_id, source_url)""",
        """CREATE INDEX discovery_story ON discovery_candidates(guild_id, story COLLATE NOCASE)
            WHERE reason='selected'""",
        """CREATE INDEX discovery_recent ON discovery_candidates(guild_id, reason, run_id DESC)""",
        """CREATE INDEX discovery_archive_recent
            ON messages(guild_id, channel_id, created_at DESC) WHERE deleted_at IS NULL""",
    ),
    (
        """ALTER TABLE discovery_runs ADD COLUMN embedding_calls INTEGER NOT NULL DEFAULT 0""",
        """ALTER TABLE discovery_runs ADD COLUMN embedding_tokens INTEGER NOT NULL DEFAULT 0""",
        """CREATE INDEX discovery_server_recent
            ON messages(guild_id, created_at DESC) WHERE deleted_at IS NULL""",
    ),
    (
        "ALTER TABLE shadow_evaluations ADD COLUMN posting_outcome TEXT",
        "ALTER TABLE shadow_evaluations ADD COLUMN posted_at TEXT",
    ),
    (
        # NULL is archive-only, a positive timestamp is queued, and zero is processed.
        "ALTER TABLE messages ADD COLUMN reaction_queued_at INTEGER",
        """CREATE INDEX reaction_pending ON messages(guild_id, channel_id, reaction_queued_at)
            WHERE reaction_queued_at > 0 AND deleted_at IS NULL""",
        "ALTER TABLE shadow_evaluations ADD COLUMN selected_message_id TEXT",
        "ALTER TABLE shadow_evaluations ADD COLUMN new_message_count INTEGER",
    ),
    (
        # NULL identifies legacy snapshots whose reply metadata is unknown.
        "ALTER TABLE messages ADD COLUMN reply_message_id TEXT",
        "ALTER TABLE messages ADD COLUMN reply_channel_id TEXT",
        """CREATE INDEX messages_reply ON messages(guild_id, reply_channel_id, reply_message_id, message_id)
            WHERE reply_message_id IS NOT NULL AND reply_message_id != ''""",
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
