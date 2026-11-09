# SQLite persistence foundation

**Status:** Foundation PR proposed; no message indexing or reactions yet.

The bot uses a single SQLite file per environment. The `discord_bot.storage.Database` helper provides WAL mode, a 5-second busy timeout, foreign-key enforcement, ordered schema migrations and an integrity-check hook. The database directory must already exist; the application must not silently create an ephemeral replacement when a PVC is absent. This is intentionally a small foundation, not an ORM.

**Deployment contract (future integration):** Configure a dedicated per-environment Rook-Ceph RBD PVC, mounted by one bot pod at a time. Never share a writable database file between dev and prod. Define an explicit database path on the mounted volume; do not point it at the container filesystem. The PVC and mount belong in `bturetzky/homelab-gitops`. SQLite file, WAL and SHM must live on the same volume. Back up via SQLite backup API or quiesced snapshot, and test restoration.

**Runtime integration:** Set `DISCORD_SQLITE_PATH` to a file under the mounted persistent volume (dev uses `/data/sqlite/bot.sqlite3`). Startup opens the database and runs an integrity check; shutdown closes it. Without the variable, existing behavior is unchanged. The parent directory must exist; startup fails rather than creating an ephemeral database if the mount is missing. Then introduce message/archive tables and FTS5 indexing with separate feature-specific queries. Reaction events, budgets and deduplication use their own tables later. Avoid logging message bodies or sensitive database paths.

**Validation:** `python -m unittest tests.test_storage`; verify open/reopen, WAL, migration idempotence, integrity check, and missing-mount refusal. Deployment readiness, restart persistence and backup/restore are not verified by unit tests.
