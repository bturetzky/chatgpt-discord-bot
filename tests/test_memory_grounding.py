"""Tests for evidence-grounded consolidation additions."""
import sqlite3
import unittest

from discord_bot.storage.memory_consolidation import parse_proposal
from discord_bot.storage.memory_grounding import (
    adjacent_human_context, parse_verification,
)


class GroundedConsolidationTests(unittest.TestCase):
    def test_split_proposal(self):
        proposal = parse_proposal(
            '{"operation":"split","summary":"","existing_id":null,'
            '"rationale":"Two separate preferences","splits":'
            '["Likes Mario Odyssey","Dislikes another game"]}', set())
        self.assertEqual(len(proposal["splits"]), 2)

    def test_invalid_split(self):
        with self.assertRaises(ValueError):
            parse_proposal(
                '{"operation":"split","summary":"","existing_id":null,'
                '"rationale":"Only one fact","splits":["One"]}', set())

    def test_verification_schema(self):
        self.assertTrue(parse_verification(
            '{"supported":true,"rationale":"Direct statement"}')["supported"])
        with self.assertRaises(ValueError):
            parse_verification('{"supported":"true","rationale":"Guess"}')

    def test_adjacent_context_is_scoped_and_human_only(self):
        db = sqlite3.connect(":memory:")
        db.execute("""CREATE TABLE messages (
            message_id TEXT, author_id TEXT, content TEXT, created_at TEXT,
            guild_id TEXT, channel_id TEXT, deleted_at TEXT)""")
        rows = [
            ("1", "42", "season four", "2026-11-01 12:00:00", "g", "tv", None),
            ("2", "43", "The Witcher", "2026-11-01 12:01:00", "g", "tv", None),
            ("3", "bot", "The Witcher", "2026-11-01 12:02:00", "g", "tv", None),
            ("4", "43", "Wrong channel", "2026-11-01 12:01:00", "g", "other", None),
        ]
        db.executemany("INSERT INTO messages VALUES (?,?,?,?,?,?,?)", rows)
        result = adjacent_human_context(
            db, {"source_message_ids": '["1"]', "guild_id": "g",
                 "channel_id": "tv"}, bot_author_id="bot")
        self.assertEqual([row["message_id"] for row in result], ["2"])
        db.close()


if __name__ == "__main__":
    unittest.main()
