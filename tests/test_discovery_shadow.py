from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock

from discord_bot.storage.database import Database
from discord_bot.storage.discovery_shadow import (
    DiscoveryShadow, INTERVAL, canonical_url, parse_channels,
)
from discord_bot.storage.message_archive import utc_iso

URL = "https://example.org/releases/lunar"
QUOTE = "The Lunar Colony expansion adds cooperative missions and launches this Friday."
STORY = "Lunar Colony's new expansion adds cooperative missions."
DRAFT = "Co-op missions sound like the right next step for Lunar Colony. Who's in?"


class ConfigTests(TestCase):
    def test_allowlist_and_canonical_identity(self):
        self.assertEqual(parse_channels('{"2":"Lunar Colony updates"}'), {"2": "Lunar Colony updates"})
        for invalid in ('[]', '{}', '{"other":"game"}', '{"2":""}', '{"2":4}'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                parse_channels(invalid)
        self.assertEqual(canonical_url("http://EXAMPLE.org/releases/lunar/?utm_source=x#top"), URL)
        self.assertNotEqual(canonical_url(URL + "?edition=deluxe"), URL)
        self.assertIsNone(canonical_url("https://user:password@example.org/"))


class ShadowTests(IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = str(Path(temporary.name) / "archive.sqlite")
        self.database = Database(self.path).open()
        self.addCleanup(self.database.close)
        self.now = 1_800_000_000
        self.search = SimpleNamespace(execute=AsyncMock())
        self.reader = SimpleNamespace(execute=AsyncMock())
        self.model = AsyncMock()
        self.hints = {"2": {"name": "game-chat", "topic": "Lunar Colony"}}
        self.results(URL)
        self.source(URL)
        for index in range(3):
            self.message(index, f"Lunar Colony base building session {index}", self.now - 7200)

    @property
    def db(self):
        return self.database.connection

    def worker(self):
        return DiscoveryShadow(
            self.db, "1", {"2": "Lunar Colony updates"}, SimpleNamespace(
                responses=SimpleNamespace(create=self.model)
            ), "test-model", "9", search=self.search, reader=self.reader, clock=lambda: self.now,
        )

    def message(self, index, content, timestamp):
        self.db.execute(
            """INSERT INTO messages(guild_id, channel_id, message_id, author_id, content, created_at)
               VALUES ('1', '2', ?, '3', ?, ?)""",
            (str(index), content, utc_iso(datetime.fromtimestamp(timestamp, timezone.utc))),
        )

    def results(self, *urls):
        self.search.execute.return_value = json.dumps({
            "ok": True, "results": [{"url": url} for url in urls],
        })

    def source(self, url):
        self.reader.execute.return_value = json.dumps({
            "ok": True, "final_url": url, "title": "Lunar Colony release", "content": QUOTE,
        })

    def responses(self, *payloads):
        self.model.side_effect = [
            SimpleNamespace(status="completed", output_text=json.dumps(payload),
                            usage=SimpleNamespace(input_tokens=30, output_tokens=10))
            for payload in payloads
        ]

    def reasons(self):
        return [row[0] for row in self.db.execute(
            "SELECT reason FROM discovery_candidates ORDER BY run_id, url",
        )]

    async def test_selected_and_canonical_duplicate_across_restart(self):
        self.responses({"story": STORY, "quote": QUOTE, "draft": DRAFT}, {"reason": "selected"})
        await self.worker().run_once(self.hints)
        self.assertEqual(self.db.execute(
            "SELECT reason, evidence, draft FROM discovery_candidates",
        ).fetchone(), ("selected", QUOTE, f"{DRAFT}\n<{URL}>"))
        self.assertNotIn("base building", self.model.call_args_list[0].kwargs["input"])
        self.assertIn("base building", self.model.call_args_list[1].kwargs["input"])
        self.database.close()
        self.database.open()
        await self.worker().run_once(self.hints)
        self.assertEqual(self.search.execute.await_count, 1)
        self.now += INTERVAL
        self.results(URL + "?utm_campaign=test#fragment")
        await self.worker().run_once(self.hints)
        self.assertEqual(self.search.execute.await_count, 2)
        self.assertEqual(self.reader.execute.await_count, 1)
        self.assertEqual(self.model.await_count, 2)
        self.assertEqual(self.reasons(), ["selected"])

    async def test_same_story_comparison_and_new_development(self):
        self.responses({"story": STORY, "quote": QUOTE, "draft": DRAFT}, {"reason": "selected"})
        await self.worker().run_once(self.hints)
        self.database.close()
        self.database.open()
        self.now += INTERVAL
        self.results(URL + "-mirror")
        self.source(URL + "-mirror")
        self.responses({"story": "Cooperative missions arrive in Lunar Colony.", "quote": QUOTE,
                        "draft": DRAFT}, {"reason": "same_story"})
        await self.worker().run_once(self.hints)
        self.assertIn(STORY, self.model.call_args.kwargs["input"])
        self.now += INTERVAL
        self.results(URL + "-update")
        self.source(URL + "-update")
        new_quote = "Lunar Colony added a cross-platform matchmaking queue in its first expansion patch."
        page = json.loads(self.reader.execute.return_value)
        self.reader.execute.return_value = json.dumps({**page, "content": new_quote})
        self.responses({"story": "Lunar Colony now supports cross-platform matchmaking.",
                        "quote": new_quote, "draft": "Cross-platform matchmaking should make groups easier to form."},
                       {"reason": "selected"})
        await self.worker().run_once(self.hints)
        self.assertEqual(self.reasons(), ["selected", "same_story", "selected"])

    async def test_archive_link_and_bounded_results(self):
        self.message(4, "Shared: " + URL + "?utm_source=discord", self.now - 7200)
        self.results(URL, URL + "-2", URL + "-3")
        self.reader.execute.side_effect = [
            self.reader.execute.return_value, json.dumps({"ok": False}),
        ]
        await self.worker().run_once(self.hints)
        self.assertEqual(self.reasons(), ["archived_url", "source_unavailable"])
        self.assertEqual(self.db.execute(
            "SELECT searches, fetches, model_calls FROM discovery_runs",
        ).fetchone(), (1, 2, 0))
        self.model.assert_not_awaited()

    async def test_active_and_weak_context_make_no_provider_calls(self):
        self.message(4, "Currently discussing the game", self.now)
        await self.worker().run_once(self.hints)
        self.db.execute("DELETE FROM messages")
        self.now += INTERVAL
        await self.worker().run_once(self.hints)
        self.assertEqual(self.db.execute(
            "SELECT outcome FROM discovery_runs ORDER BY id",
        ).fetchall(), [("active_channel",), ("weak_context",)])
        self.search.execute.assert_not_awaited()

    async def test_unrelated_and_fabricated_evidence_produce_no_draft(self):
        self.responses({"story": STORY, "quote": QUOTE, "draft": DRAFT}, {"reason": "unrelated"})
        await self.worker().run_once(self.hints)
        self.now += INTERVAL
        self.results(URL + "-fake")
        self.source(URL + "-fake")
        self.responses({"story": STORY, "quote": "The developers announced a nonexistent feature.",
                        "draft": DRAFT})
        await self.worker().run_once(self.hints)
        self.assertEqual(self.reasons(), ["unrelated", "unsupported"])
        self.assertEqual(self.db.execute(
            "SELECT count(*) FROM discovery_candidates WHERE draft IS NOT NULL",
        ).fetchone()[0], 0)

    async def test_provider_failure_consumes_attempt_and_does_not_retry(self):
        self.model.side_effect = TimeoutError()
        await self.worker().run_once(self.hints)
        self.now += INTERVAL
        await self.worker().run_once(self.hints)
        self.assertEqual(self.reasons(), ["provider_error"])
        self.assertEqual(self.model.await_count, 1)
        self.assertEqual(self.db.execute(
            "SELECT outcome, model_calls FROM discovery_runs ORDER BY id",
        ).fetchall(), [("provider_error", 1), ("complete", 0)])

    async def test_model_budget_and_activity_during_review(self):
        self.results(URL, URL + "-2", URL + "-3")
        proposal = {"story": STORY, "quote": QUOTE, "draft": DRAFT}
        self.responses(proposal, {"reason": "weak_context"},
                       proposal, {"reason": "not_worth_interrupting"})
        first_page = self.reader.execute.return_value
        self.source(URL + "-2")
        self.reader.execute.side_effect = [first_page, self.reader.execute.return_value]
        await self.worker().run_once(self.hints)
        self.assertEqual(self.reasons(), ["weak_context", "not_worth_interrupting"])
        self.assertEqual(self.db.execute(
            "SELECT searches, fetches, model_calls, input_tokens, output_tokens FROM discovery_runs",
        ).fetchone(), (1, 2, 4, 120, 40))
        self.assertFalse(self.worker().spend(1, "model_calls"))

        self.now += INTERVAL
        self.results(URL + "-3")
        self.source(URL + "-3")
        self.reader.execute.side_effect = None

        async def respond(**request):
            if "prior_suggestions" in request["input"]:
                self.message(4, "New discussion during review", self.now)
                payload = {"reason": "selected"}
            else:
                payload = proposal
            return SimpleNamespace(status="completed", output_text=json.dumps(payload))

        self.model.side_effect = respond
        await self.worker().run_once(self.hints)
        self.assertEqual(self.reasons()[-1], "active_channel")
        self.assertIsNone(self.db.execute(
            "SELECT draft FROM discovery_candidates WHERE url=?", (URL + "-3",),
        ).fetchone()[0])
