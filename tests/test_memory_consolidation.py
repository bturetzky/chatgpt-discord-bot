"""Tests for conservative, read-only memory consolidation decisions."""
import unittest

from discord_bot.storage.memory_consolidation import _matches, parse_proposal


class ConsolidationTests(unittest.TestCase):
    def test_valid_create(self):
        result = parse_proposal(
            '{"operation":"create","summary":"Likes Mario Odyssey",'
            '"existing_id":null,"rationale":"Direct preference"}', set())
        self.assertEqual(result["operation"], "create")

    def test_rejects_unverified_target(self):
        with self.assertRaises(ValueError):
            parse_proposal(
                '{"operation":"merge","summary":"Updated","existing_id":"legacy",'
                '"rationale":"Similar"}', set())

    def test_rejects_unexpected_target(self):
        with self.assertRaises(ValueError):
            parse_proposal(
                '{"operation":"create","summary":"New","existing_id":"old",'
                '"rationale":"No match"}', {"old"})

    def test_legacy_match_visible_but_not_targetable(self):
        results = {"matches": [
            {"id": "legacy", "score": .94, "metadata": {
                "summary": "A similar old memory"}},
            {"id": "different-user", "score": .98, "metadata": {
                "summary": "Another person's preference", "guild_id": "123",
                "scope": "individual", "participant_ids": ["999"]}},
            {"id": "safe", "score": .91, "metadata": {
                "summary": "Matching scoped memory", "guild_id": "123",
                "scope": "individual", "participant_ids": ["42"]}},
        ]}
        matches = _matches(results, "123", "individual", ["42"])
        self.assertEqual(len(matches), 2)
        self.assertEqual([x["targetable"] for x in matches], [False, True])

    def test_no_unattributed_target(self):
        results = {"matches": [{"id": "bad", "metadata": {
            "summary": "Something", "guild_id": "123", "scope": "individual"}}]}
        self.assertEqual(_matches(results, "123", "individual", ["42"]), [])


if __name__ == "__main__":
    unittest.main()
