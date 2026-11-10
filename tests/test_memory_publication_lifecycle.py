"""Publication schema and state machine regression tests."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from discord_bot.storage.database import Database
from discord_bot.storage.memory_publication_lifecycle import (
    next_revision_number, next_revision_state, reconcile_attempt,
)


class LifecycleTests(unittest.TestCase):
    def test_publish_requires_remote_confirmation(self):
        with self.assertRaises(ValueError):
            next_revision_state("pending", "published")
        self.assertEqual(next_revision_state(
            "pending", "published", remote_confirmed=True), "published")

    def test_supersede_requires_replacement_confirmation(self):
        with self.assertRaises(ValueError):
            next_revision_state("published", "superseded")
        self.assertEqual(next_revision_state(
            "published", "superseded", remote_confirmed=True), "superseded")

    def test_invalidated_is_terminal(self):
        with self.assertRaises(ValueError):
            next_revision_state("invalidated", "pending")

    def test_unknown_remote_outcome_is_not_success(self):
        self.assertEqual(reconcile_attempt("pending", "unknown"), "uncertain")
        self.assertEqual(reconcile_attempt("pending", "matching"), "uncertain")
        self.assertEqual(reconcile_attempt(
            "pending", "matching", matching_vector=True), "confirmed")
        self.assertEqual(reconcile_attempt("pending", "missing"), "failed")

    def test_monotonic_revisions(self):
        self.assertEqual(next_revision_number([1, 2]), 3)
        with self.assertRaises(ValueError):
            next_revision_number([1, 1])


class PublicationMigrationTests(unittest.TestCase):
    def test_migration_idempotent_and_foreign_keys(self):
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / "bot.db")
            with Database(path) as db:
                for table in ("memory_records", "memory_revisions",
                              "memory_revision_sources", "memory_publication_attempts"):
                    self.assertIsNotNone(db.connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                        (table,)).fetchone())
                db.migrate()
                self.assertEqual(db.connection.execute(
                    "PRAGMA foreign_keys").fetchone()[0], 1)
                with self.assertRaises(sqlite3.IntegrityError):
                    db.connection.execute(
                        "INSERT INTO memory_revisions "
                        "(memory_id, revision, proposal_id, summary, durability, source_hash) "
                        "VALUES ('missing', 1, 'p', 'text', 'durable', 'h')")

    def test_revision_and_attempt_constraints(self):
        with tempfile.TemporaryDirectory() as temp:
            with Database(str(Path(temp) / "bot.db")) as db:
                db.connection.execute(
                    "INSERT INTO memory_records (memory_id, guild_id, scope, participant_ids) "
                    "VALUES ('m', 'g', 'individual', '[\"u\"]')")
                db.connection.execute(
                    "INSERT INTO memory_revisions "
                    "(memory_id, revision, proposal_id, summary, durability, source_hash) "
                    "VALUES ('m', 1, 'p', 'text', 'durable', 'h')")
                with self.assertRaises(sqlite3.IntegrityError):
                    db.connection.execute(
                        "INSERT INTO memory_revisions "
                        "(memory_id, revision, proposal_id, summary, durability, source_hash) "
                        "VALUES ('m', 2, 'p', 'duplicate', 'durable', 'h')")
                with self.assertRaises(sqlite3.IntegrityError):
                    db.connection.execute(
                        "INSERT INTO memory_publication_attempts "
                        "(attempt_id, memory_id, revision, operation, status, vector_id) "
                        "VALUES ('a', 'm', 1, 'upsert', 'published', 'v')")


if __name__ == "__main__":
    unittest.main()
