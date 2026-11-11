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
TOPIC = {"query": "Lunar Colony release news", "recent": [0, 1]}
DRAFT = "Co-op missions sound like the right next step for Lunar Colony. Who's in?"


class ConfigTests(TestCase):
    def test_allowlist_and_canonical_identity(self):
        self.assertEqual(parse_channels('{"2":"Lunar Colony updates"}'), {"2": "Lunar Colony updates"})
        self.assertEqual(parse_channels('{"2":null}'), {"2": None})
        for invalid in ('[]', '{}', '{"other":"game"}', '{"2":4}'):
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
        self.model = AsyncMock(return_value=self.response(TOPIC))
        self.embed = AsyncMock(side_effect=self.embeddings)
        self.channels = {"2": None}
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
            self.db, "1", self.channels, SimpleNamespace(
                responses=SimpleNamespace(create=self.model),
                embeddings=SimpleNamespace(create=self.embed),
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

    @staticmethod
    def response(payload):
        return SimpleNamespace(status="completed", output_text=json.dumps(payload),
                               usage=SimpleNamespace(input_tokens=30, output_tokens=10))

    @staticmethod
    def embeddings(*, model, input):
        return SimpleNamespace(data=[
            SimpleNamespace(index=index, embedding=[1, 0] if index == 0 or text.startswith("Squads") else [0, 1])
            for index, text in enumerate(input)
        ], usage=SimpleNamespace(total_tokens=35))

    def responses(self, *payloads, topic=TOPIC):
        self.model.side_effect = [self.response(payload) for payload in (topic, *payloads)]

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
        self.assertNotIn("base building", self.model.call_args_list[1].kwargs["input"])
        self.assertIn("base building", self.model.call_args_list[2].kwargs["input"])
        self.database.close()
        self.database.open()
        await self.worker().run_once(self.hints)
        self.assertEqual(self.search.execute.await_count, 1)
        self.now += INTERVAL
        self.results(URL + "?utm_campaign=test#fragment")
        self.responses()
        await self.worker().run_once(self.hints)
        self.assertEqual(self.search.execute.await_count, 2)
        self.assertEqual(self.reader.execute.await_count, 1)
        self.assertEqual(self.model.await_count, 4)
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
        ).fetchone(), (1, 2, 1))
        self.embed.assert_not_awaited()

    async def test_active_and_weak_context_make_no_provider_calls(self):
        self.message(4, "Currently discussing the game", self.now)
        await self.worker().run_once(self.hints)
        self.database.close()
        self.database.open()
        self.db.execute("DELETE FROM messages")
        self.now += 60
        await self.worker().run_once(self.hints)
        self.assertEqual(self.db.execute(
            "SELECT outcome FROM discovery_runs ORDER BY id",
        ).fetchall(), [("deferred_active",), ("weak_context",)])
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
        self.model.side_effect = [self.response(TOPIC), TimeoutError()]
        await self.worker().run_once(self.hints)
        self.now += INTERVAL
        self.responses()
        await self.worker().run_once(self.hints)
        self.assertEqual(self.reasons(), ["provider_error"])
        self.assertEqual(self.model.await_count, 3)
        self.assertEqual(self.db.execute(
            "SELECT outcome, model_calls FROM discovery_runs ORDER BY id",
        ).fetchall(), [("provider_error", 2), ("complete", 1)])

    async def test_model_budget_and_activity_during_review(self):
        self.results(URL, URL + "-2", URL + "-3")
        proposal = {"story": STORY, "quote": QUOTE, "draft": DRAFT}
        self.responses({}, proposal, {"reason": "not_worth_interrupting"})
        first_page = self.reader.execute.return_value
        self.source(URL + "-2")
        self.reader.execute.side_effect = [first_page, self.reader.execute.return_value]
        await self.worker().run_once(self.hints)
        self.assertEqual(self.reasons(), ["weak_source", "not_worth_interrupting"])
        self.assertEqual(self.db.execute(
            "SELECT searches, fetches, model_calls, input_tokens, output_tokens FROM discovery_runs",
        ).fetchone(), (1, 2, 4, 120, 40))
        self.assertFalse(self.worker().spend(1, "model_calls"))

        self.now += INTERVAL
        self.results(URL + "-3")
        self.source(URL + "-3")
        self.reader.execute.side_effect = None

        async def respond(**request):
            if "accepted_memories" in request["input"]:
                payload = TOPIC
            elif "prior_suggestions" in request["input"]:
                self.message(4, "New discussion during review", self.now)
                payload = {"reason": "selected"}
            else:
                payload = proposal
            return SimpleNamespace(status="completed", output_text=json.dumps(payload))

        self.model.side_effect = respond
        await self.worker().run_once(self.hints)
        self.assertEqual(self.reasons()[-1], "deferred_active")
        self.assertIsNone(self.db.execute(
            "SELECT draft FROM discovery_candidates WHERE url=?", (URL + "-3",),
        ).fetchone()[0])

    async def test_dynamic_topic_uses_older_context_and_treats_config_as_hint(self):
        self.channels = {"2": "Unrelated Space Kart news"}
        self.message(8, "Lunar Colony co-op nights have been a regular event", self.now - 80 * 86400)
        self.responses({})
        await self.worker().run_once(self.hints)
        context = json.loads(self.model.call_args_list[0].kwargs["input"])
        self.assertIn("regular event", context["older"][0][0])
        self.assertEqual(context["search_hint"], "Unrelated Space Kart news")
        self.assertEqual(self.search.execute.call_args.args[0]["query"], TOPIC["query"])

    async def test_stale_discussion_alone_is_insufficient_but_accepted_memory_supports_topic(self):
        self.db.execute("DELETE FROM messages")
        self.message(8, "Lunar Colony launch day", self.now - 80 * 86400)
        await self.worker().run_once(self.hints)
        self.search.execute.assert_not_awaited()
        self.model.assert_not_awaited()
        self.db.execute("""
            INSERT INTO extraction_batches
                (batch_id, guild_id, channel_id, first_message_id, last_message_id,
                 source_hash, extractor_version, status)
            VALUES ('batch', '1', '2', '8', '8', 'hash', 'test', 'completed')
        """)
        self.db.execute("""
            INSERT INTO extraction_candidates VALUES
                ('batch', 0, 'fact', 'The group regularly plays Lunar Colony together',
                 '[]', '["8"]', 'high', 'test', 'accepted')
        """)
        self.now += INTERVAL
        self.responses({}, topic={"query": "Lunar Colony update", "durable": [0]})
        await self.worker().run_once(self.hints)
        context = json.loads(self.model.call_args_list[0].kwargs["input"])
        self.assertEqual(context["recent"], [])
        self.assertIn("regularly plays", context["accepted_memories"][0])
        self.search.execute.assert_awaited_once()

    async def test_semantic_shortlist_supplies_paraphrased_cross_channel_evidence(self):
        paraphrase = "Squads can tackle the next add-on's objectives together."
        self.message(8, paraphrase, self.now - 7200)
        self.db.execute("UPDATE messages SET channel_id='7' WHERE message_id='8'")
        self.responses({"story": STORY, "quote": QUOTE, "draft": DRAFT}, {"reason": "same_story"})
        await self.worker().run_once(self.hints)
        review = json.loads(self.model.call_args.kwargs["input"])
        self.assertNotIn(paraphrase, review["related_discussion"])
        self.assertEqual(review["semantic_discussion"][0]["text"], paraphrase)
        self.assertEqual(self.reasons(), ["same_story"])
        self.embed.assert_awaited_once()
        self.assertEqual(self.db.execute(
            "SELECT embedding_calls, embedding_tokens FROM discovery_runs",
        ).fetchone(), (1, 35))

    async def test_quiet_channel_can_use_active_channels_turn(self):
        self.channels = {"2": None, "5": None}
        self.message(4, "Active discussion", self.now)
        await self.worker().run_once({**self.hints, "5": {"name": "quiet"}})
        self.assertEqual(self.db.execute(
            "SELECT channel_id, outcome FROM discovery_runs",
        ).fetchall(), [("5", "weak_context")])

    async def test_embedding_failure_records_attempt_without_draft(self):
        self.responses({"story": STORY, "quote": QUOTE, "draft": DRAFT})
        self.embed.side_effect = TimeoutError()
        await self.worker().run_once(self.hints)
        self.assertEqual(self.db.execute(
            "SELECT reason, draft FROM discovery_candidates",
        ).fetchone(), ("provider_error", None))
        self.assertEqual(self.db.execute(
            "SELECT embedding_calls, model_calls FROM discovery_runs",
        ).fetchone(), (1, 2))

    async def test_hint_cannot_supply_missing_topic_evidence(self):
        self.channels = {"2": "Unrelated Space Kart news"}
        self.responses(topic={"query": self.channels["2"], "recent": [0, 0]})
        await self.worker().run_once(self.hints)
        self.search.execute.assert_not_awaited()
        self.assertEqual(self.db.execute(
            "SELECT outcome FROM discovery_runs",
        ).fetchone(), ("weak_context",))
