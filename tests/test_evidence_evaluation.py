import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from discord_bot.storage import Database
from discord_bot.storage.evidence_evaluation import (
    EVALUATOR_VERSION, evaluate_evidence, parse_decision, source_evidence,
)
from discord_bot.storage.extraction_prompt import EXTRACTOR_VERSION
from discord_bot.storage.memory_evaluation import record


class EvidenceEvaluationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.temp.name) / "test.sqlite")).open()
        self.conn = self.db.connection
        self.conn.execute(
            """INSERT INTO extraction_batches
               (batch_id, guild_id, channel_id, first_message_id,
                last_message_id, source_hash, extractor_version, status)
               VALUES ('batch', 'guild', 'channel', 'm1', 'm2', 'hash', ?, 'completed')""",
            (EXTRACTOR_VERSION,),
        )
        for mid, author, content in (
            ("m1", "111", "I loved our group trip to Ireland"),
            ("m2", "999", "You told me you went to Ireland"),
        ):
            self.conn.execute(
                """INSERT INTO messages
                   (guild_id, channel_id, message_id, author_id, content, created_at)
                   VALUES ('guild', 'channel', ?, ?, ?, '2026-11-08T00:00:00+00:00')""",
                (mid, author, content),
            )
        self.conn.execute(
            """INSERT INTO extraction_candidates
               (batch_id, candidate_index, memory_type, summary,
                participant_ids, source_message_ids, confidence, rationale)
               VALUES ('batch', 0, 'event', 'Group trip to Ireland',
                       '["111"]', '["m1", "m2"]', 'medium', 'recalled')"""
        )
        self.client = SimpleNamespace(responses=SimpleNamespace(create=AsyncMock()))
        self.client.responses.create.return_value = SimpleNamespace(
            output_text=json.dumps({"scope": "collective", "durability": "durable",
                                    "disposition": "review",
                                    "rationale": "Human participants recall shared history"}))

    async def asyncTearDown(self):
        self.db.close()
        self.temp.cleanup()

    async def run_eval(self):
        return await evaluate_evidence(
            self.conn, guild_id="guild", bot_author_id="999", model="test",
            client=self.client,
        )

    async def test_bot_source_excluded_without_model_call(self):
        rows = await self.run_eval()
        self.assertEqual(rows[0]["evaluation"]["disposition"], "exclude")
        self.assertIn("bot-authored", rows[0]["evaluation"]["rationale"])
        self.client.responses.create.assert_not_awaited()

    async def test_human_only_event_can_be_durable(self):
        self.conn.execute(
            """UPDATE extraction_candidates
               SET source_message_ids='["m1"]' WHERE batch_id='batch'"""
        )
        rows = await self.run_eval()
        self.assertEqual(rows[0]["evaluation"]["durability"], "durable")
        self.assertEqual(rows[0]["evaluation"]["disposition"], "review")
        self.assertNotIn("tools", self.client.responses.create.call_args.kwargs)
        self.assertIn("UNTRUSTED", self.client.responses.create.call_args.kwargs["instructions"])
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM candidate_evaluations").fetchone()[0], 0)
        record(self.conn, rows, evaluator_version=EVALUATOR_VERSION)
        self.assertEqual(self.conn.execute(
            "SELECT evaluator_version FROM candidate_evaluations").fetchone()[0],
            EVALUATOR_VERSION)

    async def test_missing_or_deleted_source_excluded(self):
        self.conn.execute(
            "UPDATE extraction_candidates SET source_message_ids='[\"missing\"]'"
        )
        self.assertIn("missing", (await self.run_eval())[0]["evaluation"]["rationale"])
        self.conn.execute(
            "UPDATE extraction_candidates SET source_message_ids='[\"m1\"]'"
        )
        self.conn.execute("UPDATE messages SET deleted_at=CURRENT_TIMESTAMP WHERE message_id='m1'")
        self.assertEqual((await self.run_eval())[0]["evaluation"]["disposition"], "exclude")
        self.client.responses.create.assert_not_awaited()

    async def test_obsolete_extractor_excluded(self):
        self.conn.execute(
            "UPDATE extraction_candidates SET source_message_ids='[\"m1\"]'"
        )
        self.conn.execute(
            "UPDATE extraction_batches SET extractor_version='old' WHERE batch_id='batch'"
        )
        self.assertIn("obsolete", (await self.run_eval())[0]["evaluation"]["rationale"])
        self.client.responses.create.assert_not_awaited()

    async def test_invalid_model_output_fails_closed(self):
        with self.assertRaises(ValueError):
            parse_decision(json.dumps({"scope": "collective", "durability": "durable",
                                       "disposition": "eligible", "rationale": "approved"}))

    async def test_guild_isolation(self):
        self.assertEqual(await evaluate_evidence(
            self.conn, guild_id="other", bot_author_id="999", model="test",
            client=self.client), [])
        self.client.responses.create.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
