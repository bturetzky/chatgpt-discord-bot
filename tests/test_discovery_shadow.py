from datetime import datetime, timezone
from contextlib import redirect_stdout
from io import StringIO
from argparse import Namespace
import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import discord
import httpx
from openai import AsyncOpenAI

from discord_bot import admin
from discord_bot.handlers.discord_handler import DiscordHandler

from discord_bot.storage.database import Database, MIGRATIONS
from discord_bot.storage.discovery_shadow import (
    CANDIDATE_COOLDOWN, DAY, DEFAULT_INTERVAL, FINAL_SELECTION, LIMITS, REVIEW, DiscoveryShadow,
    canonical_url, discovery_allowed, discovery_interval_seconds,
)
from discord_bot.storage.message_archive import utc_iso

URL = "https://example.org/releases/lunar"
QUOTE = "The Lunar Colony expansion adds cooperative missions and launches this Friday."
STORY = "Lunar Colony's new expansion adds cooperative missions."
SEARCH = {"action": "search", "query": "indie automation games programmable organisms",
          "summary": "Look for games adjacent to Lunar Colony base building."}
FETCH = {"action": "fetch", "result": 1}
PROPOSE = {"action": "propose", "result": 1, "story": STORY, "quote": QUOTE}
APPROVED = {"approved": True, "reason": "interesting_connection",
            "summary": "The verified co-op mechanic makes for a good discussion."}
FINISH = {"action": "finish", "result": 1}
DRAFT = "Co-op missions sound like the right next step for Lunar Colony. Who's in?"


def request_data(request):
    context, _, state = request["input"]
    return {**json.loads(context["content"][0]["text"]), **json.loads(state["content"])}


def pacific_timestamp(hour, minute=0, *, month=1):
    return datetime(2027, month, 15, hour, minute, tzinfo=ZoneInfo("America/Los_Angeles")).timestamp()


class ConfigTests(TestCase):
    def test_interval_configuration(self):
        with patch.dict("os.environ", clear=True):
            self.assertEqual(discovery_interval_seconds(), DAY)
        with patch.dict("os.environ", {"DISCOVERY_INTERVAL_HOURS": "6"}):
            self.assertEqual(discovery_interval_seconds(), 6 * 3600)
        for invalid in ("0", "-2", "invalid", "1.5"):
            with self.subTest(invalid=invalid), patch.dict(
                "os.environ", {"DISCOVERY_INTERVAL_HOURS": invalid},
            ), self.assertLogs(level="WARNING"):
                self.assertEqual(discovery_interval_seconds(), DAY)

    def test_pacific_boundaries_use_standard_and_daylight_time(self):
        for month, opening_utc, closing_utc in ((1, 16, 6), (7, 15, 5)):
            opens = datetime(2027, month, 15, opening_utc, tzinfo=timezone.utc).timestamp()
            closes = datetime(2027, month, 16, closing_utc, tzinfo=timezone.utc).timestamp()
            self.assertFalse(discovery_allowed(opens - 1))
            self.assertTrue(discovery_allowed(opens))
            self.assertTrue(discovery_allowed(closes - 1))
            self.assertFalse(discovery_allowed(closes))

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
        self.random_slot = patch('discord_bot.storage.discovery_shadow.secrets.randbelow', return_value=0)
        self.random_slot.start()
        self.addCleanup(self.random_slot.stop)
        self.now = pacific_timestamp(12)
        self.search = SimpleNamespace(execute=AsyncMock())
        self.reader = SimpleNamespace(execute=AsyncMock())
        self.model = AsyncMock(return_value=self.response({"action": "finish"}))
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

    def responses(self, *payloads):
        self.model.side_effect = [self.response(payload) for payload in payloads]

    def latest(self):
        self.db.row_factory = sqlite3.Row
        run = dict(self.db.execute("SELECT * FROM discovery_runs ORDER BY id DESC LIMIT 1").fetchone())
        run["trace"] = json.loads(run["trace"]) if run["trace"] else None
        self.db.row_factory = None
        return run

    def reasons(self):
        return [row[0] for row in self.db.execute(
            "SELECT reason FROM discovery_candidates ORDER BY run_id, url",
        )]

    async def test_explores_and_selects_older_adjacent_source_with_long_personal_commentary(self):
        draft = DRAFT + " " + (
            "I'm more interested in how a co-op colony changes the social game than in another pile "
            "of buildings to unlock. Somebody has to keep the lights on while the rest of the team "
            "tries a completely unnecessary detour, and that feels like the beginning of a better "
            "story than anything the mission briefing is going to tell us."
        )
        self.search.execute.side_effect = [
            json.dumps({"ok": False, "error": {"code": "NO_RESULTS"}}),
            json.dumps({"ok": True, "results": [
                {"url": URL, "snippet": "An automation game with co-op.", "page_date": "2025-01-01"},
            ]}),
        ]
        self.responses(SEARCH, {**SEARCH, "query": "automation game cooperative colony"}, FETCH,
                       {**PROPOSE, "draft": draft}, APPROVED, FINISH)
        await self.worker().run_once(self.hints)
        self.assertEqual(self.reasons(), ["selected"])
        run = self.latest()
        self.assertEqual((run["searches"], run["fetches"], run["model_calls"]), (2, 1, 6))
        self.assertEqual(run["trace"]["events"][1]["results"][0]["page_date"], "2025-01-01")
        self.assertEqual(run["trace"]["events"][1]["results"][0]["snippet"], "An automation game with co-op.")
        self.assertEqual(run["trace"]["selected_result"], 1)
        self.assertEqual(self.search.execute.call_args.args[0], {
            "query": "automation game cooperative colony", "max_results": 5,
        })
        self.assertIn("sharp, laid-back", self.model.call_args.kwargs["input"][1]["content"])
        self.assertEqual(self.db.execute("SELECT draft FROM discovery_candidates").fetchone()[0],
                         f"{draft}\n<{URL}>")
        self.assertIsInstance(run["duration_ms"], int)

    async def test_context_windows_cover_history_and_eligible_channels_without_copying_text_to_trace(self):
        self.hints["1", "4"] = {"name": "other"}
        self.message(8, "excluded message", self.now - DAY, channel="7")
        self.message(9, "other guild message", self.now - DAY, guild="3")
        self.db.execute("BEGIN")
        for age in (2, 8, 35, 125, 500):
            for channel in ("2", "4"):
                for index in range(30):
                    self.message(f"{age}-{channel}-{index}", "Archive excerpt " * 20,
                                 self.now - age * DAY + index, channel=channel)
        self.db.execute("UPDATE messages SET author_id='4' WHERE message_id LIKE '%-4-29'")
        self.db.execute("COMMIT")
        await self.worker().run_once(self.hints)
        context = request_data(self.model.call_args.kwargs)["windows"]
        self.assertEqual(len(context), 10)
        for window in context:
            times = [message["at"] for message in window["messages"]]
            self.assertEqual(times, sorted(times))
        self.assertEqual({m["speaker"] for w in context for m in w["messages"]}, {1, 2})
        self.assertNotIn("excluded message", str(context))
        self.assertNotIn("other guild message", str(context))
        run = self.latest()
        self.assertGreater(run["trace"]["context"]["estimated_tokens"], 10_000)
        self.assertLess(run["trace"]["context"]["estimated_tokens"], 20_000)
        self.assertNotIn("Archive excerpt", json.dumps(run["trace"]))
        self.assertEqual(run["model_calls"], 1)
        self.search.execute.assert_not_awaited()

    async def test_continue_source_compare_candidates_and_keep_earlier_rejected_drafts(self):
        second = URL + "-other"
        self.results(URL, second)
        self.reader.execute.side_effect = [json.dumps(page) for page in (
            {"ok": True, "final_url": URL, "content": "Page introduction", "next_cursor": "cursor"},
            {"ok": True, "final_url": URL, "content": QUOTE, "next_cursor": None},
            {"ok": True, "final_url": second, "content": QUOTE},
        )]
        self.responses(SEARCH, FETCH, {**FETCH, "continuation": True},
                       {**PROPOSE, "draft": DRAFT}, {"approved": False, "reason": "routine_update",
                                                   "summary": "The change offers little to talk about."},
                       {**FETCH, "result": 2},
                       {**PROPOSE, "result": 2, "draft": "That co-op mechanic might actually settle the logistics debate."},
                       APPROVED, {**FINISH, "result": 2})
        await self.worker().run_once(self.hints)
        self.assertEqual(self.reasons(), ["routine_update", "selected"])
        self.assertEqual(self.reader.execute.call_args_list[1].args[0], {"url": URL, "cursor": "cursor"})
        self.assertEqual(self.latest()["trace"]["selected_result"], 2)
        with patch.dict("os.environ", {"DISCORD_SQLITE_PATH": self.path}):
            buffer = StringIO()
            with redirect_stdout(buffer):
                admin.discovery(Namespace(guild_id="1", limit=20, run_id=1, posts=True, json=True))
            rejected, selected = json.loads(buffer.getvalue())
            self.assertEqual(rejected["draft"], DRAFT)
            self.assertEqual(rejected["decision"], "routine_update")
            self.assertEqual(selected["decision"], "selected")
            buffer = StringIO()
            with redirect_stdout(buffer):
                admin.discovery(Namespace(guild_id=None, limit=20, run_id=1, posts=False, json=True))
            self.assertEqual(json.loads(buffer.getvalue())["runs"][0]["trace"]["selected_result"], 2)

    async def test_snippet_or_fabricated_evidence_cannot_support_selection(self):
        self.responses(SEARCH, {**PROPOSE, "draft": DRAFT}, FETCH,
                       {**PROPOSE, "draft": DRAFT, "quote": "This quote never appears on the page."},
                       FINISH, {"action": "finish"})
        await self.worker().run_once(self.hints)
        self.assertEqual(self.reasons(), ["missing_source_evidence"])
        run = self.latest()
        self.assertEqual(run["trace"]["events"][4]["decision"], "selection_not_approved")
        self.assertNotIn("selected_result", run["trace"])
        self.assertEqual(self.db.execute("SELECT draft FROM discovery_candidates").fetchone()[0], DRAFT)

    async def test_duplicate_archive_and_prior_canonical_urls(self):
        self.message(8, f"Already discussed {URL}?utm_source=chat", self.now - DAY, channel="4")
        self.hints["1", "4"] = {}
        self.responses(SEARCH, FETCH, {**PROPOSE, "draft": DRAFT}, {"action": "finish"})
        await self.worker().run_once(self.hints)
        self.assertEqual(self.reasons(), ["archived_url"])
        self.now += 6 * 3600
        del self.hints["1", "4"]
        self.results(URL + "?utm_source=provider")
        self.responses(SEARCH, FETCH, {"action": "finish"})
        with patch.dict("os.environ", {"DISCOVERY_INTERVAL_HOURS": "6"}):
            await self.worker().run_once(self.hints)
        self.assertEqual(self.latest()["trace"]["events"][1]["decision"], "candidate_cooldown")
        self.reader.execute.assert_awaited_once()

    async def test_transient_fetch_retries_after_cooldown_and_keeps_attempts(self):
        self.reader.execute.return_value = json.dumps({"ok": False, "error": {"code": "TIMEOUT"}})
        self.responses(SEARCH, FETCH, FETCH, {"action": "finish"})
        await self.worker().run_once(self.hints)
        first = self.latest()
        self.assertEqual(first["trace"]["events"][2]["decision"], "duplicate_url")
        self.reader.execute.assert_awaited_once()

        self.now += CANDIDATE_COOLDOWN
        self.source(URL)
        self.responses(SEARCH, FETCH, {**PROPOSE, "draft": DRAFT}, APPROVED, FINISH)
        await self.worker().run_once(self.hints)
        self.assertEqual(self.reasons(), ["timeout", "selected"])
        self.assertEqual(self.reader.execute.await_count, 2)

        self.now += 4 * CANDIDATE_COOLDOWN
        self.hints = {("1", "4"): {}}
        self.message(80, "Co-op building games", self.now - DAY, channel="4")
        self.results(URL + "?utm_source=provider")
        self.responses(SEARCH, FETCH, {"action": "finish"})
        await self.worker().run_once(self.hints)
        self.assertEqual(self.latest()["trace"]["events"][1]["decision"], "duplicate_url")
        self.assertEqual(self.reasons(), ["timeout", "selected"])
        self.assertEqual(self.reader.execute.await_count, 2)

    async def test_channel_rejection_can_be_reconsidered_in_another_channel(self):
        self.responses(SEARCH, FETCH, {**PROPOSE, "draft": DRAFT},
                       {"approved": False, "reason": "unrelated",
                        "summary": "This channel mostly talks about music."},
                       {"action": "finish"})
        await self.worker().run_once(self.hints)

        self.now += DEFAULT_INTERVAL
        self.hints["1", "4"] = {}
        self.message(80, "Co-op building games", self.now - DAY, channel="4")
        self.responses(SEARCH, FETCH, {**PROPOSE, "draft": DRAFT}, APPROVED, FINISH)
        await self.worker().run_once(self.hints)
        self.assertEqual(self.latest()["channel_id"], "4")
        self.assertEqual(self.reasons(), ["unrelated", "selected"])

    async def test_redirects_respect_permanent_and_within_run_deduplication(self):
        alias = URL + "-alias"
        self.results(alias, URL)
        self.responses(SEARCH, FETCH, {**FETCH, "result": 2},
                       {**PROPOSE, "draft": DRAFT}, APPROVED, FINISH)
        await self.worker().run_once(self.hints)
        self.assertEqual(self.latest()["trace"]["events"][2]["decision"], "duplicate_url")
        self.reader.execute.assert_awaited_once()

        self.now += CANDIDATE_COOLDOWN
        self.results(URL + "-new-alias")
        self.responses(SEARCH, FETCH, {"action": "finish"})
        await self.worker().run_once(self.hints)
        self.assertEqual(self.reasons(), ["selected", "duplicate_redirect"])
        self.assertEqual(self.reader.execute.await_count, 2)

    async def test_failed_continuation_is_not_repeated(self):
        self.reader.execute.side_effect = [
            json.dumps({"ok": True, "final_url": URL, "content": QUOTE, "next_cursor": "cursor"}),
            json.dumps({"ok": False, "error": {"code": "TIMEOUT"}}),
        ]
        continuation = {**FETCH, "continuation": True}
        self.responses(SEARCH, FETCH, continuation, continuation, {"action": "finish"})
        await self.worker().run_once(self.hints)
        self.assertEqual(self.latest()["trace"]["events"][3]["decision"], "duplicate_continuation")
        self.assertEqual(self.reader.execute.await_count, 2)

    async def test_final_model_call_is_reserved_when_late_proposal_would_use_it(self):
        second = URL + "-second"
        self.results(URL, second)
        self.reader.execute.side_effect = [
            json.dumps({"ok": True, "final_url": url, "content": QUOTE}) for url in (URL, second)
        ]
        self.responses(SEARCH, FETCH, {**PROPOSE, "draft": DRAFT}, APPROVED, {**FETCH, "result": 2},
                       *([{"action": "unknown"}] * 13),
                       {**PROPOSE, "result": 2, "draft": DRAFT + " Another opener."}, FINISH)
        await self.worker().run_once(self.hints)
        run = self.latest()
        self.assertEqual(run["model_calls"], LIMITS["model_calls"])
        self.assertEqual(run["trace"]["events"][-2]["decision"], "review_budget_exhausted")
        self.assertTrue(run["trace"]["events"][-1]["final_selection"])
        final_request = self.model.call_args.kwargs
        self.assertEqual(final_request["input"][1]["content"], FINAL_SELECTION)
        self.assertIn("The only available action is finish", final_request["input"][1]["content"])
        final_input = request_data(final_request)
        self.assertEqual(list(final_input["approved_candidates"]), ["1"])
        self.assertEqual(run["trace"]["selected_result"], 1)

    async def test_reserved_selection_can_choose_silence(self):
        self.responses(SEARCH, FETCH, {**PROPOSE, "draft": DRAFT}, APPROVED,
                       *([{"action": "unknown"}] * 15),
                       {"action": "finish", "result": None})
        await self.worker().run_once(self.hints)
        run = self.latest()
        self.assertEqual(run["model_calls"], LIMITS["model_calls"])
        self.assertEqual(run["outcome"], "complete")
        self.assertNotIn("selected_result", run["trace"])
        self.assertEqual(self.reasons(), ["approved"])

    async def test_reserved_selection_rejects_exploration_actions_and_unapproved_ids(self):
        for final_action, decision in (
            (SEARCH, "invalid_final_selection"),
            (FETCH, "invalid_final_selection"),
            ({**PROPOSE, "draft": DRAFT}, "invalid_final_selection"),
            ({"action": "finish", "result": 2}, "selection_not_approved"),
        ):
            with self.subTest(action=final_action["action"], result=final_action.get("result")):
                self.search.execute.reset_mock()
                self.reader.execute.reset_mock()
                self.responses(SEARCH, FETCH, {**PROPOSE, "draft": DRAFT}, APPROVED,
                               *([{"action": "unknown"}] * 15), final_action)
                await self.worker().run_once(self.hints)
                run = self.latest()
                self.assertEqual(run["model_calls"], LIMITS["model_calls"])
                self.assertEqual(run["outcome"], "budget_exhausted")
                self.assertTrue(run["trace"]["events"][-1]["final_selection"])
                self.assertEqual(run["trace"]["events"][-1]["decision"], decision)
                self.assertNotIn("selected_result", run["trace"])
                self.search.execute.assert_awaited_once()
                self.reader.execute.assert_awaited_once()
                self.now += CANDIDATE_COOLDOWN

    async def test_stable_prompt_prefix_and_cached_usage_are_visible_in_cli(self):
        requests = []
        actions = iter([
            (SEARCH, 0), (FETCH, 14), ({**PROPOSE, "draft": DRAFT}, 8),
            (APPROVED, 9), (FINISH, 0),
        ])

        def respond(request):
            requests.append(json.loads(request.content))
            action, cached = next(actions)
            return httpx.Response(200, json={
                "status": "completed",
                "output": [{
                    "type": "message", "role": "assistant", "content": [
                        {"type": "output_text", "text": json.dumps(action), "annotations": []},
                    ],
                }],
                "usage": {"input_tokens": 30, "output_tokens": 10, "total_tokens": 40,
                          "input_tokens_details": {"cached_tokens": cached},
                          "output_tokens_details": {"reasoning_tokens": 0}},
            })

        async with AsyncOpenAI(
            api_key="synthetic-key", max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        ) as client:
            worker = self.worker()
            worker.model = "gpt-6.1-terra"
            worker.client = client
            with patch.dict(LIMITS, model_calls=5):
                await worker.run_once(self.hints)

        self.assertEqual(len(requests), 5)
        first = requests[0]
        for request in requests:
            self.assertEqual(request["instructions"], first["instructions"])
            self.assertEqual(request["input"][0], first["input"][0])
            self.assertEqual(request["prompt_cache_options"], {"mode": "explicit"})
            self.assertEqual(request["model"], first["model"])
            self.assertEqual(request["text"], first["text"])
            self.assertFalse(request["store"])
        self.assertEqual(first["input"][0]["content"][0]["prompt_cache_breakpoint"], {"mode": "explicit"})
        self.assertNotEqual(first["input"][2], requests[1]["input"][2])
        self.assertEqual(requests[3]["input"][1], {"role": "developer", "content": REVIEW})
        self.assertNotIn("progress", request_data(requests[3]))
        self.assertEqual(requests[4]["input"][1], {"role": "developer", "content": FINAL_SELECTION})
        self.assertEqual(self.reasons(), ["selected"])
        with patch.dict("os.environ", {"DISCORD_SQLITE_PATH": self.path, "DISCOVERY_INTERVAL_HOURS": "6"}):
            buffer = StringIO()
            with redirect_stdout(buffer):
                admin.discovery(Namespace(guild_id=None, limit=20, run_id=1, posts=False, json=True))
        status = json.loads(buffer.getvalue())
        self.assertEqual(status["interval_seconds"], 21600)
        self.assertEqual(status["quiet_hours"], {
            "start": "22:00", "end": "08:00", "timezone": "America/Los_Angeles",
        })
        run = status["runs"][0]
        self.assertEqual((run["input_tokens"], run["cached_input_tokens"], run["output_tokens"]), (150, 31, 50))
        self.assertEqual((run["embedding_calls"], run["embedding_tokens"], run["model_calls"]), (0, 0, 5))

    async def test_review_gets_related_archive_and_prior_suggestions_for_paraphrases(self):
        previous = URL + "-previous"
        self.db.execute("INSERT INTO discovery_runs(guild_id, channel_id, started_at) VALUES ('1', '2', ?)",
                        (self.now - DEFAULT_INTERVAL,))
        self.db.execute(
            """INSERT INTO discovery_candidates(guild_id, url, run_id, reason, story, source_url)
               VALUES ('1', ?, 1, 'selected', 'Players can now cooperate in Lunar Colony.', ?)""",
            (previous, previous),
        )
        self.message(9, "We discussed Lunar Colony adding shared missions.", self.now - 500 * DAY)
        self.responses(SEARCH, FETCH, {**PROPOSE, "draft": DRAFT},
                       {"approved": False, "reason": "same_story",
                        "summary": "The shared missions already came up under another link."},
                       {"action": "finish"})
        await self.worker().run_once(self.hints)
        review = request_data(self.model.call_args_list[3].kwargs)
        self.assertEqual(review["prior_suggestions"], [["Players can now cooperate in Lunar Colony.", previous]])
        self.assertIn("We discussed Lunar Colony adding shared missions.", review["related_discussion"])
        self.assertEqual(self.reasons(), ["selected", "same_story"])

    async def test_search_and_model_budgets_bound_provider_loops(self):
        self.model.return_value = self.response(SEARCH)
        self.results(*(URL + f"-{n}" for n in range(8)))
        await self.worker().run_once(self.hints)
        run = self.latest()
        self.assertEqual(run["outcome"], "budget_exhausted")
        self.assertEqual(run["model_calls"], LIMITS["model_calls"] - 1)
        self.assertEqual(run["searches"], LIMITS["searches"])
        self.assertEqual(len(run["trace"]["events"][0]["results"]), 5)

    async def test_page_budget_includes_continuations(self):
        self.reader.execute.side_effect = [
            json.dumps({"ok": True, "final_url": URL, "content": QUOTE, "next_cursor": f"cursor-{index}"})
            for index in range(LIMITS["fetches"])
        ]
        self.responses(SEARCH, FETCH, *([{**FETCH, "continuation": True}] * 10), {"action": "finish"})
        await self.worker().run_once(self.hints)
        self.assertEqual(self.latest()["fetches"], LIMITS["fetches"])
        self.assertEqual(self.latest()["trace"]["events"][-2]["decision"], "fetch_budget_exhausted")

    async def test_provider_failures_keep_specific_diagnostics_and_draft(self):
        self.results(URL, URL + "-good")
        self.reader.execute.side_effect = [
            json.dumps({"ok": False, "error": {"code": "HTTP_ERROR", "http_status": 403,
                                                "message": "PRIVATE RESPONSE"}}),
            json.dumps({"ok": True, "final_url": URL + "-good", "content": QUOTE}),
        ]
        self.model.side_effect = [self.response(payload) for payload in
                                  (SEARCH, FETCH, {**FETCH, "result": 2},
                                   {**PROPOSE, "result": 2, "draft": DRAFT})]
        self.model.side_effect = [*self.model.side_effect, TimeoutError("PRIVATE ERROR")]
        with self.assertLogs(level="WARNING") as logs:
            await self.worker().run_once(self.hints)
        run = self.latest()
        self.assertEqual(run["outcome"], "provider_error")
        self.assertEqual(run["trace"]["events"][1]["error"], {"code": "HTTP_ERROR", "http_status": 403})
        self.assertEqual(run["trace"]["events"][3]["draft"], DRAFT)
        self.assertEqual(run["trace"]["events"][3]["decision"], "review_provider_error")
        self.assertNotIn("PRIVATE", json.dumps(run["trace"]) + "".join(logs.output))
        await self.worker().run_once(self.hints)
        self.assertEqual(self.model.await_count, 5)

    async def test_exploration_http_rejection_logs_safe_traceback_with_no_usage(self):
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
        self.assertEqual(request_data(request)["output_instruction"], "Return a JSON object.")
        self.assertEqual(request["max_output_tokens"], 1800)
        self.assertFalse(request["store"])
        self.assertNotIn("tools", request)
        self.assertNotIn("prompt_cache_options", request)
        self.assertNotIn("prompt_cache_breakpoint", request["input"][0]["content"][0])
        logged = "\n".join(logs.output)
        for expected in ("run=1", "stage=exploration", "BadRequestError", "HTTP 400",
                         "unsupported_parameter", "param=text.format", "Traceback", "in ask"):
            self.assertIn(expected, logged)
        for private in (private_marker, "synthetic-key", "base building", request["instructions"]):
            self.assertNotIn(private, logged)
        self.assert_exploration_failed((0, 0))

    async def test_exploration_timeout_omits_exception_and_chained_messages(self):
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
        self.assertIn("stage=exploration exception=TimeoutError", logged)
        self.assertIn("in timeout", logged)
        self.assertNotIn("private", logged)
        self.assert_exploration_failed((0, 0))

    async def test_exploration_response_failures_record_reported_usage(self):
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
                self.assert_exploration_failed((30, 10))
                self.now += DEFAULT_INTERVAL

    def assert_exploration_failed(self, tokens):
        self.assertEqual(self.db.execute(
            """SELECT outcome, model_calls, input_tokens, output_tokens, searches, fetches
               FROM discovery_runs ORDER BY id DESC LIMIT 1""",
        ).fetchone(), ("provider_error", 1, *tokens, 0, 0))
        self.assertEqual(self.reasons(), [])
        self.search.execute.assert_not_awaited()
        self.reader.execute.assert_not_awaited()

    async def test_historical_discussion_and_accepted_memory_can_bootstrap_exploration(self):
        self.db.execute("DELETE FROM messages")
        self.message(8, "Lunar Colony launch day", self.now - 80 * DAY)
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
        self.responses(SEARCH, {"action": "finish"})
        await self.worker().run_once(self.hints)
        context = request_data(self.model.call_args_list[0].kwargs)
        self.assertEqual(context["windows"][0]["messages"][0]["text"], "Lunar Colony launch day")
        self.assertIn("regularly plays", context["accepted_memories"][0])
        self.search.execute.assert_awaited_once()

    async def test_activity_during_finish_suppresses_selection(self):
        responses = iter([SEARCH, FETCH, {**PROPOSE, "draft": DRAFT}, APPROVED, FINISH])

        async def model(**kwargs):
            action = next(responses)
            if action == FINISH:
                self.message(9, "Conversation resumed", self.now)
            return self.response(action)

        self.model.side_effect = model
        await self.worker().run_once(self.hints)
        self.assertEqual(self.latest()["outcome"], "deferred_after_work")
        self.assertEqual(self.reasons(), ["approved"])

    async def test_private_query_format_rejected_before_provider(self):
        self.responses({**SEARCH, "query": "search for @private_handle"}, {"action": "finish"})
        await self.worker().run_once(self.hints)
        self.search.execute.assert_not_awaited()
        self.assertEqual(self.latest()["trace"]["events"][0]["decision"], "invalid_public_query")

    async def test_daily_slot_is_random_and_persists_across_restart(self):
        self.now = pacific_timestamp(8)
        self.random_slot.stop()
        with patch('discord_bot.storage.discovery_shadow.secrets.randbelow', return_value=3 * 3600) as draw:
            await self.worker().run_once(self.hints)
            self.assertEqual(self.db.execute("SELECT count(*) FROM discovery_runs").fetchone()[0], 0)
            self.assertEqual(self.db.execute(
                "SELECT scheduled_at FROM discovery_daily_schedule",
            ).fetchone()[0], int(pacific_timestamp(11)))
            self.database.close()
            self.database.open()
            self.now = pacific_timestamp(10, 59)
            await self.worker().run_once(self.hints)
            self.assertEqual(self.db.execute("SELECT count(*) FROM discovery_runs").fetchone()[0], 0)
            self.now = pacific_timestamp(11)
            await self.worker().run_once(self.hints)
            self.assertEqual(self.db.execute("SELECT count(*) FROM discovery_runs").fetchone()[0], 1)
            draw.assert_called_once()
        self.random_slot.start()

    async def test_delivery_includes_source_url_once(self):
        sender = AsyncMock()
        self.responses(SEARCH, FETCH, {**PROPOSE, "draft": DRAFT}, APPROVED, FINISH)
        worker = self.worker()
        worker.sender = sender
        await worker.run_once(self.hints)
        sender.assert_awaited_once()
        content = sender.await_args.args[1]
        self.assertEqual(content.count(URL), 1)
        self.assertEqual(content, f"{DRAFT}\n<{URL}>")

    async def test_overdue_overnight_run_reserves_once_at_opening_after_restart(self):
        self.db.execute("INSERT INTO discovery_runs(guild_id, channel_id, started_at) VALUES ('1', '2', ?)",
                        (pacific_timestamp(22) - 3 * DAY,))
        self.now = pacific_timestamp(8) - 1
        self.db.execute("DELETE FROM messages")
        self.message(50, "Archived discussion", self.now - DAY)
        await self.worker().run_once(self.hints)
        self.model.assert_not_awaited()
        self.assertEqual(self.latest()["id"], 1)
        self.database.close()
        self.database.open()
        self.now += 1
        for _ in range(3):
            await self.worker().run_once(self.hints)
        self.assertEqual(self.latest()["id"], 2)
        self.model.assert_awaited_once()

    async def test_custom_interval_controls_due_time(self):
        with patch.dict("os.environ", {"DISCOVERY_INTERVAL_HOURS": "3"}):
            await self.worker().run_once(self.hints)
            self.now += 3 * 3600 - 1
            await self.worker().run_once(self.hints)
            self.model.assert_awaited_once()
            self.now += 1
            await self.worker().run_once(self.hints)
        self.assertEqual(self.model.await_count, 2)

    async def test_quiet_hours_prevent_selection_before_and_after_final_request(self):
        for boundary_action, expected_calls in ((APPROVED, 4), (FINISH, 5)):
            with self.subTest(expected_calls=expected_calls):
                self.db.execute("DELETE FROM discovery_candidates")
                self.db.execute("DELETE FROM discovery_runs")
                self.now = pacific_timestamp(22) - 1
                actions = iter([SEARCH, FETCH, {**PROPOSE, "draft": DRAFT}, APPROVED, FINISH])

                async def respond(**kwargs):
                    action = next(actions)
                    if action is boundary_action:
                        self.now += 1
                    return self.response(action)

                self.model.reset_mock()
                self.model.side_effect = respond
                with patch.dict(LIMITS, model_calls=5):
                    await self.worker().run_once(self.hints)
                self.assertEqual(self.model.await_count, expected_calls)
                self.assertEqual(self.latest()["outcome"], "deferred_quiet_hours")
                self.assertNotIn("selected_url", self.latest()["trace"])
                self.assertEqual(self.reasons(), ["approved"])

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
        # Same-day calls remain blocked; a new Pacific day is eligible even
        # when fewer than 24 elapsed hours have passed.
        self.now = pacific_timestamp(21, 59)
        await self.worker().run_once(channels)
        self.assertEqual(self.db.execute("SELECT count(*) FROM discovery_runs").fetchone()[0], 1)
        self.now = pacific_timestamp(12) + DAY
        for _ in range(4):
            await self.worker().run_once(channels)
            self.now += DEFAULT_INTERVAL
        self.assertEqual(self.db.execute(
            "SELECT guild_id, channel_id, outcome FROM discovery_runs WHERE id>1 ORDER BY id",
        ).fetchall(), [
            ("3", "5", "weak_context"), ("3", "6", "weak_context"),
            ("1", "1", "weak_context"), ("3", "5", "weak_context"),
        ])
        self.search.execute.assert_not_awaited()
        self.reader.execute.assert_not_awaited()
        self.model.assert_not_awaited()

    async def test_guild_scope_keeps_context_and_deduplication_separate(self):
        self.message(9, "Second guild discussion", self.now - DAY, guild="3", channel="5")
        self.hints["3", "5"] = {}
        for expected_guild, excluded in (("1", "Second guild discussion"), ("3", "Lunar Colony base building session")):
            self.responses(SEARCH, FETCH, {**PROPOSE, "draft": DRAFT}, APPROVED, FINISH)
            await self.worker().run_once(self.hints)
            self.assertEqual(self.latest()["guild_id"], expected_guild)
            self.assertNotIn(excluded, json.dumps(self.model.call_args.kwargs["input"]))
            self.now += DEFAULT_INTERVAL
        self.assertEqual(self.reasons(), ["selected", "selected"])


class MigrationTests(TestCase):
    def test_discovery_migration_preserves_legacy_records(self):
        with TemporaryDirectory() as temporary:
            path = str(Path(temporary) / "legacy.sqlite")
            from discord_bot.storage import database
            with patch.object(database, "MIGRATIONS", MIGRATIONS[:-1]):
                legacy = Database(path).open()
                legacy.connection.execute(
                    "INSERT INTO discovery_runs(guild_id, channel_id, started_at) VALUES ('1', '2', 100)",
                )
                legacy.connection.execute(
                    """INSERT INTO discovery_candidates(guild_id, url, run_id, reason, draft)
                       VALUES ('1', ?, 1, 'selected', ?)""", (URL, DRAFT),
                )
                legacy.close()
            migrated = Database(path).open()
            self.addCleanup(migrated.close)
            self.assertEqual(migrated.connection.execute(
                "SELECT url, reason, draft, explanation FROM discovery_candidates",
            ).fetchone(), (URL, "selected", DRAFT, None))
            self.assertEqual(migrated.connection.execute(
                "SELECT started_at, trace, duration_ms, cached_input_tokens FROM discovery_runs",
            ).fetchone(), (100, None, None, 0))


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
        with patch.dict("os.environ", {"DISCOVERY_ENABLED": "true"}, clear=True), \
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
