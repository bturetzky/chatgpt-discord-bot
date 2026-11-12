from datetime import datetime, timezone
from argparse import Namespace
import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import httpx
from openai import AsyncOpenAI

from discord_bot import admin
from discord_bot.handlers.discord_handler import DiscordHandler

from discord_bot.storage.database import Database
from discord_bot.storage.discovery_shadow import (
    DiscoveryShadow, INTERVAL, canonical_url,
)
from discord_bot.storage.message_archive import utc_iso

URL = "https://example.org/releases/lunar"
QUOTE = "The Lunar Colony expansion adds cooperative missions and launches this Friday."
STORY = "Lunar Colony's new expansion adds cooperative missions."
TOPIC = {"query": "Lunar Colony release news", "recent": [0, 1]}
DRAFT = "Co-op missions sound like the right next step for Lunar Colony. Who's in?"


class ConfigTests(TestCase):
    def test_canonical_identity(self):
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
        self.hints = {("1", "2"): {"name": "game-chat", "topic": "Lunar Colony"}}
        self.results(URL)
        self.source(URL)
        for index in range(3):
            self.message(index, f"Lunar Colony base building session {index}", self.now - 7200)

    @property
    def db(self):
        return self.database.connection

    def worker(self):
        return DiscoveryShadow(
            self.db, SimpleNamespace(
                responses=SimpleNamespace(create=self.model),
                embeddings=SimpleNamespace(create=self.embed),
            ), "test-model", "9", search=self.search, reader=self.reader, clock=lambda: self.now,
        )

    def message(self, index, content, timestamp, *, guild="1", channel="2"):
        self.db.execute(
            """INSERT INTO messages(guild_id, channel_id, message_id, author_id, content, created_at)
               VALUES (?, ?, ?, '3', ?, ?)""",
            (guild, channel, str(index), content, utc_iso(datetime.fromtimestamp(timestamp, timezone.utc))),
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

    async def test_sqlite_rows_serialize_in_topic_and_review(self):
        old_message = "Lunar Colony has been a regular co-op game for months."
        self.message(8, old_message, self.now - 80 * 86400)
        prior_url = URL + "-earlier"
        prior_story = "Lunar Colony received a new soundtrack."
        run = self.db.execute(
            "INSERT INTO discovery_runs(guild_id, channel_id, started_at) VALUES ('1', '2', ?)",
            (self.now - INTERVAL,),
        ).lastrowid
        self.db.execute(
            """INSERT INTO discovery_candidates (guild_id, url, source_url, run_id, reason, story)
               VALUES ('1', ?, ?, ?, 'selected', ?)""",
            (prior_url, prior_url, run, prior_story),
        )
        self.db.row_factory = sqlite3.Row
        self.responses({"story": STORY, "quote": QUOTE, "draft": DRAFT}, {"reason": "selected"})

        await self.worker().run_once(self.hints)

        self.assertEqual(self.model.await_count, 3)
        topic, _, review = [json.loads(call.kwargs["input"]) for call in self.model.call_args_list]
        self.assertEqual(topic["older"][0][0], old_message)
        self.assertEqual(review["prior_suggestions"], [[prior_story, prior_url]])
        self.assertEqual(tuple(self.db.execute(
            "SELECT reason, draft FROM discovery_candidates WHERE url=?", (URL,),
        ).fetchone()), ("selected", f"{DRAFT}\n<{URL}>"))
        self.assertIs(self.db.row_factory, sqlite3.Row)

    async def test_topic_http_rejection_logs_safe_traceback_with_no_usage(self):
        private_marker = "synthetic private payload"
        requests = []

        def reject(request):
            requests.append(json.loads(request.content))
            return httpx.Response(400, json={
                "error": {"message": private_marker, "code": "unsupported_parameter", "param": "text.format"},
            })

        async with AsyncOpenAI(
            api_key="synthetic-key", max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(reject)),
        ) as client:
            worker = self.worker()
            worker.client = client
            with self.assertLogs(level="WARNING") as logs:
                await worker.run_once(self.hints)

        self.assertEqual(len(requests), 1)
        request = requests[0]
        self.assertEqual(request["model"], "test-model")
        self.assertEqual(request["text"], {"format": {"type": "json_object"}})
        self.assertEqual(json.loads(request["input"])["output_instruction"], "Return a JSON object.")
        self.assertEqual(request["max_output_tokens"], 650)
        self.assertFalse(request["store"])
        self.assertNotIn("tools", request)
        logged = "\n".join(logs.output)
        for expected in ("run=1", "stage=topic", "BadRequestError", "HTTP 400",
                         "unsupported_parameter", "param=text.format", "Traceback", "in ask"):
            self.assertIn(expected, logged)
        for private in (private_marker, "synthetic-key", "base building", request["instructions"]):
            self.assertNotIn(private, logged)
        self.assert_topic_failed((0, 0))

    async def test_topic_timeout_omits_exception_and_chained_messages(self):
        async def timeout(**kwargs):
            try:
                raise OSError("private chained diagnostic")
            except OSError as cause:
                raise TimeoutError("private timeout diagnostic") from cause

        self.model.side_effect = timeout
        with self.assertLogs(level="WARNING") as logs:
            await self.worker().run_once(self.hints)
        self.model.assert_awaited_once()
        logged = "\n".join(logs.output)
        self.assertIn("stage=topic exception=TimeoutError", logged)
        self.assertIn("in timeout", logged)
        self.assertNotIn("private", logged)
        self.assert_topic_failed((0, 0))

    async def test_topic_response_failures_record_reported_usage(self):
        cases = [
            ("incomplete", "max_output_tokens", '{"query":', "incomplete_max_output_tokens"),
            ("incomplete", "content_filter", "", "incomplete_content_filter"),
            ("failed", None, "", "response_not_completed"),
            ("completed", None, "", "empty_output"),
            ("completed", None, "synthetic non-JSON output", "JSONDecodeError"),
            ("completed", None, "[]", "non_object_output"),
        ]
        for status, reason, output, diagnostic in cases:
            with self.subTest(diagnostic=diagnostic):
                self.model.return_value = SimpleNamespace(
                    status=status, incomplete_details=SimpleNamespace(reason=reason),
                    output_text=output, usage=SimpleNamespace(input_tokens=30, output_tokens=10),
                )
                with self.assertLogs(level="WARNING") as logs:
                    await self.worker().run_once(self.hints)
                self.assertIn(diagnostic, "\n".join(logs.output))
                self.assertNotIn("synthetic non-JSON output", "\n".join(logs.output))
                self.assert_topic_failed((30, 10))
                self.now += INTERVAL

    def assert_topic_failed(self, tokens):
        self.assertEqual(self.db.execute(
            """SELECT outcome, model_calls, input_tokens, output_tokens, searches, fetches
               FROM discovery_runs ORDER BY id DESC LIMIT 1""",
        ).fetchone(), ("provider_error", 1, *tokens, 0, 0))
        self.assertEqual(self.reasons(), [])
        self.search.execute.assert_not_awaited()
        self.reader.execute.assert_not_awaited()

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

    async def test_dynamic_topic_uses_older_context_and_channel_metadata(self):
        self.message(8, "Lunar Colony co-op nights have been a regular event", self.now - 80 * 86400)
        self.responses({})
        await self.worker().run_once(self.hints)
        context = json.loads(self.model.call_args_list[0].kwargs["input"])
        self.assertIn("regular event", context["older"][0][0])
        self.assertEqual(context["channel_hints"], self.hints["1", "2"])
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
        self.message(8, paraphrase, self.now - 7200, channel="7")
        self.hints["1", "7"] = {"name": "another-channel"}
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
        self.message(4, "Active discussion", self.now)
        await self.worker().run_once({**self.hints, ("3", "5"): {"name": "quiet"}})
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
        self.responses(topic={"query": "Unrelated Space Kart news", "recent": [0, 0]})
        await self.worker().run_once(self.hints)
        self.search.execute.assert_not_awaited()
        self.assertEqual(self.db.execute(
            "SELECT outcome FROM discovery_runs",
        ).fetchone(), ("weak_context",))

    async def test_global_interval_and_rotation_survive_restart_and_channel_removal(self):
        self.db.execute("DELETE FROM messages")
        await self.worker().run_once({})
        self.assertEqual(self.db.execute("SELECT count(*) FROM discovery_runs").fetchone()[0], 0)
        # Seed a reservation in the format written by the deployed per-guild scheduler.
        self.db.execute(
            "INSERT INTO discovery_runs(guild_id, channel_id, started_at) VALUES ('1', '2', ?)",
            (self.now,),
        )
        channels = {("3", "6"): {}, ("3", "5"): {}, ("1", "1"): {}}
        self.database.close()
        self.database.open()
        self.now += INTERVAL - 1
        await self.worker().run_once(channels)
        self.assertEqual(self.db.execute("SELECT count(*) FROM discovery_runs").fetchone()[0], 1)
        self.now += 1
        for _ in range(4):
            await self.worker().run_once(channels)
            self.now += INTERVAL
        self.assertEqual(self.db.execute(
            "SELECT guild_id, channel_id, outcome FROM discovery_runs WHERE id>1 ORDER BY id",
        ).fetchall(), [
            ("3", "5", "weak_context"), ("3", "6", "weak_context"),
            ("1", "1", "weak_context"), ("3", "5", "weak_context"),
        ])
        self.search.execute.assert_not_awaited()
        self.reader.execute.assert_not_awaited()
        self.model.assert_not_awaited()
        self.embed.assert_not_awaited()

    async def test_review_and_canonical_url_dedupe_are_guild_scoped(self):
        self.message(8, "Lunar Colony hidden discussion", self.now - 7200, channel="7")
        self.message(9, "Lunar Colony second guild private discussion", self.now - 7200, guild="3", channel="5")
        self.message(10, "Lunar Colony strategies", self.now - 7200, guild="3", channel="5")
        self.hints["3", "5"] = {"name": "other-guild"}
        proposal = {"story": STORY, "quote": QUOTE, "draft": DRAFT}
        self.responses(proposal, {"reason": "selected"})
        await self.worker().run_once(self.hints)
        first_review = self.model.call_args.kwargs["input"]
        self.assertNotIn("second guild private", first_review)
        self.assertNotIn("hidden discussion", first_review)
        self.assertNotIn("hidden discussion", str(self.embed.call_args.kwargs["input"]))
        self.now += INTERVAL
        self.responses(proposal, {"reason": "selected"})
        await self.worker().run_once(self.hints)
        second_review = json.loads(self.model.call_args.kwargs["input"])
        self.assertEqual(second_review["prior_suggestions"], [])
        self.assertNotIn("base building", str(second_review))
        self.assertEqual(self.db.execute(
            "SELECT guild_id, url, reason FROM discovery_candidates ORDER BY run_id",
        ).fetchall(), [("1", URL, "selected"), ("3", URL, "selected")])
        with patch.dict("os.environ", {"DISCORD_SQLITE_PATH": self.path}), patch.object(admin, "output") as output:
            admin.discovery(Namespace(guild_id=None, limit=20))
            self.assertEqual({row["guild_id"] for row in output.call_args.args[0]["candidates"]}, {"1", "3"})
            admin.discovery(Namespace(guild_id="3", limit=20))
            self.assertEqual({row["guild_id"] for row in output.call_args.args[0]["candidates"]}, {"3"})


class DiscoveryGatewayTests(IsolatedAsyncioTestCase):
    @staticmethod
    def channel(cid, *, kind=discord.ChannelType.text, view=True, history=True):
        permissions = SimpleNamespace(view_channel=view, read_message_history=history)
        return SimpleNamespace(id=cid, type=kind, name="dev-chat", topic=None,
                               permissions_for=lambda member: permissions)

    async def test_ready_starts_one_worker_with_archive_and_refreshes_eligibility(self):
        allowed = self.channel(2)
        hidden = self.channel(4, view=False)
        history_denied = self.channel(5, history=False)
        announcement = self.channel(6, kind=discord.ChannelType.news)
        first = SimpleNamespace(id=1, me=object(), unavailable=False,
                                text_channels=[allowed, hidden, history_denied, announcement])
        second = SimpleNamespace(id=3, me=object(), unavailable=False, text_channels=[self.channel(7)])
        unavailable = SimpleNamespace(id=8, me=object(), unavailable=True, text_channels=[self.channel(9)])
        client = MagicMock(user=SimpleNamespace(id=10), guilds=[first, second, unavailable])
        client.event.side_effect = lambda callback: callback
        client.close = AsyncMock()
        archive = SimpleNamespace(db=object())
        with patch.dict("os.environ", {}, clear=True), \
             patch("discord_bot.handlers.discord_handler.discord.Client", return_value=client), \
             patch("discord_bot.handlers.discord_handler.VectorHandler") as vector, \
             patch("discord_bot.handlers.discord_handler.ChatGPTHandler"), \
             patch("discord_bot.handlers.discord_handler.reconcile_recent", new_callable=AsyncMock), \
             patch.object(DiscoveryShadow, "run_configured", new_callable=AsyncMock) as run:
            vector.return_value.close = AsyncMock()
            handler = DiscordHandler("test", "test", "test")
            self.addAsyncCleanup(handler.shutdown)
            ready = client.event.call_args_list[0].args[0]
            await ready()
            self.assertIsNone(handler._discovery_task)
            run.assert_not_awaited()
            handler.archive = archive
            await ready()
            await ready()
            await handler._discovery_task
            run.assert_awaited_once()
            self.assertEqual(run.call_args.args[:3], (archive.db, "test", "10"))
            channel_hints = run.call_args.args[3]
            self.assertEqual(set(channel_hints()), {("1", "2"), ("3", "7")})
            first.text_channels.remove(allowed)
            history_denied.permissions_for(first.me).read_message_history = True
            second.text_channels.append(self.channel(11))
            self.assertEqual(set(channel_hints()), {("1", "5"), ("3", "7"), ("3", "11")})
            client.is_ready.return_value = False
            self.assertEqual(channel_hints(), {})
