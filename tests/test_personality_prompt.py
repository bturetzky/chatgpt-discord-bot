from datetime import datetime
import unittest

from discord_bot.handlers.personality_prompt import build_system_prompt


class PersonalityPromptTests(unittest.TestCase):
    def setUp(self):
        self.prompt = build_system_prompt("<@123>", datetime(2026, 11, 7, 10, 30))

    def test_identity_and_time(self):
        self.assertIn("<@123>", self.prompt)
        self.assertIn("2026-11-07 10:30:00", self.prompt)

    def test_personality_and_relationship_boundaries(self):
        for expected in ("dry humor", "not a customer-service assistant", "Never fabricate", "who is speaking", "serious questions"):
            self.assertIn(expected, self.prompt)

    def test_memory_instructions_preserved(self):
        for expected in ("store_memory", "multi-person conversation", "clear attribution", "duplicate writes", "Never store credentials"):
            self.assertIn(expected, self.prompt)


if __name__ == "__main__":
    unittest.main()
