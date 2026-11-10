"""Autonomous publication eligibility and deterministic identity tests."""
import unittest
from discord_bot.storage.autonomous_memory import eligible, memory_vector_id


class AutonomousMemoryTests(unittest.TestCase):
    def test_only_clean_create_is_eligible(self):
        plan = {"decision": "review_required", "operation": "create",
                "blockers": [], "memory": {"summary": "Likes puzzles"}}
        self.assertTrue(eligible(plan))
        for key, value in [("decision", "blocked"), ("operation", "merge"),
                           ("blockers", ["edited source"])]:
            changed = dict(plan, **{key: value})
            self.assertFalse(eligible(changed))

    def test_id_is_stable_and_attributed(self):
        a = memory_vector_id("1", "individual", ["3"], "Likes  puzzles")
        self.assertEqual(a, memory_vector_id("1", "individual", ["3"], "likes puzzles"))
        self.assertNotEqual(a, memory_vector_id("2", "individual", ["3"], "Likes puzzles"))
        self.assertNotEqual(a, memory_vector_id("1", "individual", ["4"], "Likes puzzles"))
        self.assertNotEqual(a, memory_vector_id("1", "collective", ["3"], "Likes puzzles"))


if __name__ == "__main__":
    unittest.main()
