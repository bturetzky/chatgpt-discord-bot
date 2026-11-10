"""Deterministic publication plan guardrail tests."""
import unittest
from unittest.mock import patch

from discord_bot.storage.memory_publication_plan import plan_entries, stable_id


class FakeConnection:
    def execute(self, query, params):
        return self

    def fetchone(self):
        return (None,)


def entry():
    return {
        "guild_id": "123", "channel_id": "456",
        "batch_id": "batch", "candidate_index": 0, "status": "proposed",
        "batch_status": "completed", "extractor_version": "culture-v2",
        "evaluation_version": "evidence-v1",
        "consolidation_version": "consolidation-v2",
        "participant_ids": '["42"]', "source_message_ids": '["100"]',
        "evaluation": {"scope": "individual", "durability": "durable",
                       "disposition": "review"},
        "consolidation": {"operation": "create", "summary": "Likes gardens",
                          "existing_id": None, "splits": []},
        "grounding_verification": {"supported": True},
    }


class PublicationPlanTests(unittest.TestCase):
    def plan(self, candidate):
        with patch("discord_bot.storage.memory_publication_plan.source_evidence",
                   return_value=([{"message_id": "100",
                                   "created_at": "2026-11-09 12:00:00"}], None)):
            return plan_entries(FakeConnection(), [candidate],
                                guild_id="123", bot_author_id="999")

    def test_stable_ids_are_repeatable_and_split_distinct(self):
        self.assertEqual(stable_id("123", "batch", 0, 0),
                         stable_id("123", "batch", 0, 0))
        self.assertNotEqual(stable_id("123", "batch", 0, 0),
                            stable_id("123", "batch", 0, 1))

    def test_create_requires_review_not_auto_publication(self):
        result = self.plan(entry())
        self.assertFalse(result["publishable"])
        self.assertFalse(result["recorded"])
        self.assertEqual(result["plans"][0]["decision"], "review_required")
        self.assertEqual(result["plans"][0]["memory"]["source_message_ids"], ["100"])

    def test_missing_grounding_blocks(self):
        candidate = entry()
        candidate["grounding_verification"] = {"supported": False}
        self.assertIn("independent grounding not confirmed",
                      self.plan(candidate)["plans"][0]["blockers"])

    def test_legacy_review_blocks(self):
        candidate = entry()
        candidate["consolidation"]["operation"] = "review"
        self.assertEqual(self.plan(candidate)["plans"][0]["decision"], "blocked")

    def test_update_requires_revision_ledger(self):
        candidate = entry()
        candidate["consolidation"]["operation"] = "update"
        candidate["consolidation"]["existing_id"] = "scoped"
        self.assertIn("revision/supersession ledger not implemented",
                      self.plan(candidate)["plans"][0]["blockers"])

    def test_split_requires_atom_provenance(self):
        candidate = entry()
        candidate["consolidation"]["operation"] = "split"
        candidate["consolidation"]["summary"] = ""
        candidate["consolidation"]["splits"] = ["Likes A", "Likes B"]
        self.assertIn("split proposals require per-atom provenance and deduplication",
                      self.plan(candidate)["plans"][0]["blockers"])

    def test_cross_guild_fails_closed(self):
        with self.assertRaises(ValueError):
            self.plan({**entry(), "guild_id": "other"})

    def test_discord_mentions_blocked(self):
        candidate = entry()
        candidate["consolidation"]["summary"] = "<@42> likes gardens"
        self.assertIn("Discord mention markup is not canonical memory text",
                      self.plan(candidate)["plans"][0]["blockers"])


if __name__ == "__main__":
    unittest.main()
