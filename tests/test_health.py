import unittest

from discord_bot.health import health


class HealthTests(unittest.TestCase):
    def test_health_returns_ok(self):
        self.assertEqual(health(), {"status": "ok"})
