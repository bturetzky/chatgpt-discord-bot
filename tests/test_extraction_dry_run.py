import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from discord_bot.storage import Database
from discord_bot.storage.extraction import discover_windows
from discord_bot.storage.extraction_dry_run import dry_run, parse_candidates


class DryRunTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.temp.name) / "archive.sqlite3")).open()
        self.start = datetime(2026, 11, 8, tzinfo=timezone.utc)
        for i in range(2):
            self.db.connection.execute(
                """INSERT INTO messages
                   (guild_id, channel_id, message_id, author_id, content, created_at)
                   VALUES ('guild', 'channel', ?, '12345', ?, ?)""",
                (str(i + 1), "our running joke" if i else "remember the joke",
                 (self.start + timedelta(minutes=i)).isoformat()),
            )
        self.client = SimpleNamespace(responses=SimpleNamespace(create=AsyncMock()))

    async def asyncTearDown(self):
        self.db.close()
        self.temp.cleanup()

    def response(self, candidates):
        return SimpleNamespace(
            output_text=json.dumps({"candidates": candidates}),
            usage=SimpleNamespace(input_tokens=100, output_tokens=20),
        )

    def candidate(self):
        return {"memory_type": "lore", "summary": "The group has a recurring joke.",
                "participant_ids": ["12345"], "source_message_ids": ["1", "2"],
                "confidence": "medium", "rationale": "Both messages mention the joke."}

    async def run_dry(self):
        return await dry_run(
            self.db.connection, guild_id="guild", since=self.start,
            until=self.start + timedelta(hours=1), model="test-model",
            client=self.client, bot_author_id="99999",
        )

    async def test_persists_dry_run_and_skips_completed_batch(self):
        self.client.responses.create.return_value = self.response([self.candidate()])
        result = await self.run_dry()
        self.assertEqual((result["processed"], result["candidates"]), (1, 1))
        self.assertEqual(result["input_tokens"], 100)
        self.assertEqual(self.db.connection.execute(
            "SELECT count(*) FROM extraction_candidates"
        ).fetchone()[0], 1)
        self.assertEqual(self.db.connection.execute(
            "SELECT status FROM extraction_batches"
        ).fetchone()[0], "completed")
        second = await self.run_dry()
        self.assertEqual(second["skipped"], 1)
        self.assertEqual(self.client.responses.create.await_count, 1)

    async def test_invalid_evidence_is_rejected_without_candidates(self):
        bad = {**self.candidate(), "source_message_ids": ["not-a-message"]}
        self.client.responses.create.return_value = self.response([bad])
        result = await self.run_dry()
        self.assertEqual(result["failed"], 1)
        self.assertEqual(self.db.connection.execute(
            "SELECT count(*) FROM extraction_candidates"
        ).fetchone()[0], 0)
        self.assertEqual(self.db.connection.execute(
            "SELECT status FROM extraction_batches"
        ).fetchone()[0], "failed")

    async def test_zero_candidates_and_changed_evidence_reprocess(self):
        self.client.responses.create.return_value = self.response([])
        self.assertEqual((await self.run_dry())["candidates"], 0)
        self.db.connection.execute(
            "UPDATE messages SET content='corrected joke' WHERE message_id='1'"
        )
        self.assertEqual((await self.run_dry())["processed"], 1)
        self.assertEqual(self.client.responses.create.await_count, 2)

    async def test_rejects_unbounded_windows(self):
        self.client.responses.create.return_value = self.response([])
        with self.assertRaises(ValueError):
            await dry_run(self.db.connection, guild_id="guild", since=self.start,
                          until=self.start + timedelta(hours=1), model="test",
                          client=self.client, bot_author_id="99999", max_windows=0)
        self.client.responses.create.assert_not_awaited()

    async def test_prompt_is_separate_and_no_tools(self):
        self.client.responses.create.return_value = self.response([])
        await self.run_dry()
        kwargs = self.client.responses.create.call_args.kwargs
        self.assertNotIn("tools", kwargs)
        self.assertIn("untrusted evidence", kwargs["instructions"])
        self.assertEqual(kwargs["model"], "test-model")

    async def test_bot_only_recollection_cannot_create_memory(self):
        self.db.connection.execute(
            "UPDATE messages SET author_id='99999' WHERE message_id='2'"
        )
        self.client.responses.create.return_value = self.response([{
            **self.candidate(), "source_message_ids": ["2"],
            "participant_ids": ["99999"],
        }])
        result = await self.run_dry()
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["candidates"], 0)

    async def test_bot_only_window_skips_model(self):
        self.db.connection.execute("UPDATE messages SET author_id='99999'")
        result = await self.run_dry()
        self.assertEqual(result["skipped"], 1)
        self.client.responses.create.assert_not_awaited()

    async def test_same_summary_repeated_in_new_window_is_deduplicated(self):
        self.client.responses.create.return_value = self.response([self.candidate()])
        self.assertEqual((await self.run_dry())["candidates"], 1)
        self.db.connection.execute(
            "UPDATE messages SET content='a different conversation' WHERE message_id='1'"
        )
        # Different evidence in the same batch should still be re-evaluated.
        result = await self.run_dry()
        self.assertEqual(result["processed"], 1)
        self.db.connection.execute(
            """INSERT INTO messages
               (guild_id, channel_id, message_id, author_id, content, created_at)
               VALUES ('guild', 'channel', '3', '12345', 'another joke',
                       '2026-11-08T00:45:00+00:00')"""
        )
        # A second, separate conversation window returns the same claim.
        self.client.responses.create.return_value = self.response([{
            **self.candidate(), "source_message_ids": ["3"]
        }])
        result = await self.run_dry()
        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["duplicates"], 1)
        self.assertEqual(result["candidates"], 0)


if __name__ == "__main__":
    unittest.main()
