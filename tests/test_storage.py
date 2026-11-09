import sqlite3
import tempfile
import unittest
from pathlib import Path

from discord_bot.storage import Database


class DatabaseTests(unittest.TestCase):
    def test_initializes_wal_and_migrations_and_reopens(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "bot.sqlite3")
            with Database(path) as database:
                self.assertEqual(database.connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")
                self.assertEqual(database.connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
                self.assertEqual(database.connection.execute("SELECT version FROM schema_migrations").fetchall(), [(1,), (2,), (3,), (4,), (5,), (6,), (7,), (8,)])
                self.assertTrue(database.integrity_check())
            with Database(path) as database:
                self.assertEqual(database.connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0], 8)

    def test_refuses_memory_database_and_missing_parent(self):
        with self.assertRaises(ValueError):
            Database(":memory:")
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                Database(str(Path(directory) / "missing" / "bot.sqlite3")).open()

    def test_rejects_double_open(self):
        with tempfile.TemporaryDirectory() as directory:
            with Database(str(Path(directory) / "bot.sqlite3")) as database:
                with self.assertRaises(RuntimeError):
                    database.open()


if __name__ == "__main__":
    unittest.main()
